# Pipeline 存储抽象 —— 设计说明

本文记录 pipeline「存储抽象（storage abstraction）」工作的设计细节、背后的取舍,
以及为看懂这些代码所需的基础知识。整体路线图见
[future_plan.md](../../future_plan.md) 第 3 项;本文是它的详细展开。

工作按「每步单独实现、单独验证、单独 review」的方式推进(与
[chat-api-hardening.md](./chat-api-hardening.md) 同一套节奏)。本文兼作**学习参考**,
面向刚接触数据管线的读者:先给全局大图,再补基础知识,最后才逐步讲实现。凡是用到的
概念,都在「基础知识」章节从头讲清,正文再引用。

---

## 目录

- [背景](#背景)
- [先看全局:数据的旅程与「中间人」](#先看全局数据的旅程与中间人)
- [基础知识](#基础知识)
  - [一、pipeline 的数据住在哪(data/ 布局)](#一pipeline-的数据住在哪data-布局)
  - [二、为什么「路径」不够,要「key」](#二为什么路径不够要key)
  - [三、Storage 接口与后端](#三storage-接口与后端)
  - [四、把两者粘起来:入口串联与逻辑 key 寻址(粘合剂)](#四把两者粘起来入口串联与逻辑-key-寻址粘合剂)
- [迁移步骤](#迁移步骤)
  - [Step 1:接口 + LocalStorage(已完成)](#step-1接口--localstorage已完成)
  - [Step 2:迁移 reports(已完成)](#step-2迁移-reports已完成)
  - [Step 3:迁移 wechat harvest checkpoint(已完成)](#step-3迁移-wechat-harvest-checkpoint已完成)
  - [Step 4:迁移 article sink(待做)](#step-4迁移-article-sink待做)
  - [Step 5:入口串联 + B 类咽喉点(待做)](#step-5入口串联--b-类咽喉点待做)
  - [Step 6:S3Storage(待做,Phase 3)](#step-6s3storage待做phase-3)
- [迁移顺序原则:A 类先、B 类后](#迁移顺序原则a-类先b-类后)
- [测试策略](#测试策略)
- [尚未完成](#尚未完成)

---

## 背景

pipeline 目前把每一步的产物写成文件,存在项目的 `data/` 目录里(抓取的原始文章、
清洗后的记录、断点续跑的存档、运行报告)。这在开发者自己的电脑上没问题。

问题出在部署目标:pipeline 要作为 **Amazon ECS Fargate task** 运行,而 Fargate 的
本地磁盘是**临时存储**——task 一结束就被清空。用大白话说,那台机器像一间**钟点房**:
退房时房间里的东西全部清零,下一个 task 是全新的空房间。于是:

- 抓来的文章、清洗结果、报告 —— task 重启后全丢。
- 「断了能接着跑」的存档(checkpoint)在钟点房模式下形同虚设,每次都得从头来。

所以 pipeline **不能再依赖本地磁盘做长期事实来源**,得改成写到一个**永久的外部仓库**
——亚马逊的 **Amazon S3**(可理解为「云上的对象存储 / 无限大网盘」)。

如果代码里到处写死「存到本地 `data/` 目录」,那上云时每个 stage 都要改。本工作的目标
就是**把「存哪、怎么存」抽象成一个可替换的接口**,让:

- 本地开发 → 用「本地文件系统」实现;
- 上云 → 换成「S3」实现;
- **上层 pipeline 代码一行都不用动**。

数据库方向已定为 RDS for PostgreSQL,不在本文范围;本文只讲 pipeline **文件产物**的
存储抽象。

---

## 先看全局:数据的旅程与「中间人」

pipeline 是一条 ETL 流水线:抓 → 洗 → 校 → 灌。**各段之间不是用内存传递数据,而是
用文件交接**——上一段的输出文件,就是下一段的输入文件:

```text
微信 API
   │  ① 抓取(harvest)
   ▼
data/raw/          原始快照(不可变)
   │  ② 清洗(transform)
   ▼
data/processed/    加工结果
   │  (定稿一份)
   ▼
data/current/      给下一段用的稳定输入
   │  ③ 校验 → ④ 向量化 → ⑤ 灌库(import,校验内联其中)
   ▼
Postgres knowledge_base 表

旁路:data/checkpoints/(断点续跑存档) · data/reports/(运行报告)
```

这些 `data/…` 文件就是流水线的**胶水**。存储抽象要做的,就是在「读写这些文件的代码」
和「文件真正落在哪」之间,插一个**中间人(storage)**:

```text
          pipeline stage 代码
                  │  只会喊:存 / 取 / 在不在 / 列出 / 删
                  ▼
          ┌───────────────┐
          │   Storage      │   ← 一份「插头规格」,大家都照这个规格
          │  (接口/Protocol)│
          └───────────────┘
             ╱          ╲
   LocalStorage          S3Storage(待做)
   (落到 data/)          (落到 S3 桶)
```

关键在于:不管背后是本地磁盘还是 S3,中间人对外的**动作名字和用法完全一样**;变的只是
中间人内部怎么实现。做完全部迁移后,「本地 ↔ S3」只需在**入口**换一个中间人,其余代码
无感知。

后面的基础知识,分四簇讲清这张图的每一块:数据住在哪(一)、为什么用 key 而不是路径
(二)、中间人接口长什么样(三)、以及怎么把中间人从入口一路发下去(四,粘合剂)。

---

## 基础知识

### 一、pipeline 的数据住在哪(data/ 布局)

> 这一簇是地基:先知道「有哪些产物、各住哪」,后面「怎么抽象存储」才有对象。

pipeline 的本地产物遵循一套**能干净映射到对象存储**的布局(见
[pipelines/README.md](../../pipelines/README.md) 与
[pipelines/shared/paths.py](../../pipelines/shared/paths.py)):

```text
data/
  raw/          不可变的源快照
  processed/    转换后的中间产物
  current/      给下一段消费的稳定输入
  checkpoints/  可续跑的本地状态(存档)
  reports/      运行报告 / 审计摘要
```

它天然对应未来的云路径:`data/raw/…` → `s3://<bucket>/raw/…`,以此类推。这套「本地目录
= 未来 S3 前缀」的对应关系,正是存储抽象设计的出发点。

**checkpoint(存档)存什么?** 它不存文章正文,只存「进行到哪 + 少量防错校验」,纯为
断点续跑。例如 wechat 抓取存档
([HarvestState](../../pipelines/ingestion/wechat/models.py)):

```json
{
  "begin": 120,
  "total_saved": 120,
  "valid_count": 98,
  "seen_links": ["url1", "url2"]
}
```

`begin` 让抓取从第 120 篇接着跑,`seen_links` 防重复抓。理解「产物 = 段间胶水、checkpoint
= 续跑状态」,就能理解为什么这些东西必须落到**永久**存储。

### 二、为什么「路径」不够,要「key」

> 这一簇解释接口最核心的设计选择:用「名字(key)」而不是「文件路径」寻址。

最直觉的做法是让存储接口收一个文件路径(`Path`)。但它对 S3 天生不成立:

- **本地文件系统**按「路径」寻址:有目录、有 `..`、能原子 rename、能 `glob`。
- **S3 没有「路径 / 目录」这些概念**:它是「一个桶(bucket)+ 桶内的 **key**」。你没法
  对 S3 说「存到 `/Users/devin/桌面/x.json`」——这句话对云仓库毫无意义。

所以接口改用 **key**——一个 `/` 分隔的**逻辑名字**,而不是文件系统路径:

```text
key = "reports/pipelines/wechat_pipeline_<run_id>.json"
       └────────── 逻辑名字,与「本地 or 云」无关 ──────────┘
```

各后端再把同一个 key 映射到自己的布局:本地拼成 `data/<key>`,S3 拼成
`s3://<bucket>/<key>`。key 寻址让接口保持中立,是「上 S3 时上层零改动」的前提。

**「找不到」怎么表达?** 接口定义了一个 `StorageNotFoundError`(读一个不存在的 key
时抛出),让「缺失」有一个与后端无关的统一语义,而不是本地漏 `FileNotFoundError`、S3
漏另一种异常。

**取舍**:也可以直接用现成库(如 `fsspec` / `smart_open`)一把抹平本地与 S3。这里选择
**手写一个极小接口**(见下),因为动作只有 6 个、零额外依赖、行为完全可控;代价是 S3
后端要自己写一小段(Step 6)。对一个仅需「读写整份 JSON + 列目录 + 删」的管线,这个
取舍偏向简单和可控。

### 三、Storage 接口与后端

> 这一簇是中间人本体:一份接口规格 + 一个本地实现(S3 实现留到 Step 6)。

**接口(规格)** —— [pipelines/shared/storage/base.py](../../pipelines/shared/storage/base.py)
定义 `Storage` Protocol,动作如下(key 是字符串,内容是字节):

| 动作 | 含义 | 取代了原来的 |
|---|---|---|
| `write(key, data)` | 原子写入(实现内部保证) | 临时文件 + `replace` |
| `read(key)` | 读出字节;缺失抛 `StorageNotFoundError` | `open(...).read` |
| `exists(key)` | 在不在 | `Path.exists` |
| `list(prefix)` | 列出某前缀下所有 key(排序) | `glob` |
| `delete(key)` | 删(缺失不报错) | `unlink` |
| `delete_prefix(prefix)` | 按前缀整片删 | `rmtree` |

这层里**没有任何「磁盘 / 目录 / S3」字眼**——干净、中立,这正是插头规格该有的样子。
`Protocol` 意为「规格」:只规定必须会这几个动作,不规定怎么实现。

**本地后端** —— [pipelines/shared/storage/local.py](../../pipelines/shared/storage/local.py)
的 `LocalStorage(base_dir)`:

- 把 key 映射到 `base_dir/key`。以 `base_dir=data/` 为例,key
  `reports/pipelines/x.json` 就落在 `data/reports/pipelines/x.json`——**与抽象前的磁盘
  布局逐字节一致**,现有集成测试察觉不到变化。
- `write` 内部仍用「临时文件 + 原子 `replace`」,保证崩溃在写一半时不会留下损坏产物;
  `list` / `delete_prefix` 会忽略 `.tmp` 临时文件。
- 所有「建目录、临时文件、改名、glob、rmtree」这些脏活,**被收拢进这一个盒子**,咽喉点
  代码不再重复它们。

**S3 后端(待做)**:同样这 6 个动作,内部改成 S3 的 PUT/GET/list_objects/delete。PUT
天然原子(不需要临时文件把戏),`delete_prefix` 用「按前缀批量删」。上层零改动即可切换。

### 四、把两者粘起来:入口串联与逻辑 key 寻址(粘合剂)

> 这一簇把前面几簇接上:中间人从哪来、怎么发到各 stage,以及由此定下的寻址规则。

有了接口和本地实现,还差一步:**谁来创建中间人、怎么传给各 stage**。终极形态是——在
pipeline 的**入口**(`pipelines/cli.py` / `run_local_*`)**只创建一次** `Storage`
(本地→`LocalStorage`,云→`S3Storage`),连同逻辑 key 一路传给 harvest / transform /
import 各段;stage 代码不再自己构造 storage、不再处理裸 `Path`。做完这步,本地 ↔ S3
只需改**入口一行**。

由此定下一个寻址决策(记作**方案②**):

> **artifact 一律用「存储根下的逻辑 key」寻址,不再支持 CLI 传入任意绝对路径。**

- **理由**:S3 没有「绝对路径」概念;「任意本地路径」这个能力本就只对本地成立。
- **收益**:本地与云写法一致;强制所有数据住在 `data/` 根(或 S3 桶)内,养成好习惯;
  去掉「任意路径」后门分支,代码更简单。
- **影响**:`--input` 等参数从「文件路径」改为「根下逻辑 key」(如
  `current/wechat_articles_processed.json`);需要调试外部文件时,先放进 `data/` 根再
  引用。
- **权衡**:牺牲了「随手指一个桌面文件喂给管线」的自由;但这个自由充其量省一次复制,
  且对 S3 无意义,不值得为它保留一条本地专属分支。

这条粘合剂决定了**哪些咽喉点能先迁、哪些要等入口串联**——见下面的
[A 类先、B 类后](#迁移顺序原则a-类先b-类后)。

---

## 迁移步骤

咽喉点(现在直接碰文件系统的地方)逐个迁移,**每步单独提交、单独验证**。当前全套件
共 **178 个单元测试**,每步都要求全绿。

### Step 1:接口 + LocalStorage(已完成)

> 前置基础:[三、Storage 接口与后端](#三storage-接口与后端)。

纯新增,零风险:落地 `Storage` 接口、`StorageNotFoundError`、`LocalStorage`,配 14 个
单测([tests/unit/test_storage.py](../../tests/unit/test_storage.py))覆盖读写往返、嵌套
建目录、key→磁盘映射、原子写不留 `.tmp`、`list` 排序与忽略 `.tmp`、`delete` /
`delete_prefix`。此步不碰任何现有代码。

### Step 2:迁移 reports(已完成)

> 前置基础:[一、data/ 布局](#一pipeline-的数据住在哪data-布局)、
> [三、Storage 接口](#三storage-接口与后端)。

最小咽喉点试水:[write_json_report](../../pipelines/shared/reports.py) 改为
`(storage, key, payload)`——只把报告序列化成字节交给中间人,不再自己碰磁盘。唯一调用方
[wechat_pipeline](../../pipelines/orchestration/wechat_pipeline.py) 用
`LocalStorage(data_dir)` + `report_file.relative_to(data_dir)` 推出 key,**输出字节与
落盘位置均不变**。配 [test_reports.py](../../tests/unit/test_reports.py) 3 个测试(含
「JSON + 末尾换行」的格式锁定)。

> 这是中间人第一次真正接进 pipeline——最小、最独立的一处,证明整条链路可通。

### Step 3:迁移 wechat harvest checkpoint(已完成)

> 前置基础:[一(checkpoint 存什么)](#一pipeline-的数据住在哪data-布局)、
> [三、Storage 接口](#三storage-接口与后端)。

[JsonFileCheckpointStore](../../pipelines/ingestion/wechat/storage/local.py) 的构造函数从
收 `state_file: Path` 改为 `(storage, key)`;`load` / `save` / `clear` 改用
`storage.exists / read / write / delete`。唯一构造点
[harvest_wechat](../../pipelines/orchestration/harvest_wechat.py) 用
`LocalStorage(data_dir)` + key `checkpoints/wechat_scraper_state.json`。字节与位置不变;
同步更新了直接测试它的 round-trip 用例。

### Step 4:迁移 article sink(待做)

> 前置基础:[三、Storage 接口(全部 6 个动作)](#三storage-接口与后端)。

[JsonChunkArticleSink](../../pipelines/ingestion/wechat/storage/local.py) 负责「抓取时
分批落盘 + 最后合并定稿」,是 A 类里最重的一个,几乎用到接口的全部动作:`write_batch`
→ `write`;`finalize` 里 `glob` → `list`(仍需按批次号数字排序)、读各批 → `read`、写
final 与 current → `write`、`rmtree` 临时目录 → `delete_prefix`。构造函数从 3 个 `Path`
改为 `storage` + 3 个 key。

一个设计点:`finalize` 返回的 `ArticleOutput.location`(现为绝对磁盘路径)将改为**逻辑
key**——与方案②一致、本地云通用(它是信息性字段,只进报告和日志,不参与控制流)。

### Step 5:入口串联 + B 类咽喉点(待做)

> 前置基础:[四、入口串联与逻辑 key 寻址](#四把两者粘起来入口串联与逻辑-key-寻址粘合剂)。

在 `cli.py` / `run_local_*` 创建 storage、按逻辑 key 往下传;**一并迁移 B 类**——
[json_records](../../pipelines/shared/json_records.py) 与
[JsonImportCheckpointStore](../../pipelines/shared/import_checkpoint.py);`--input` 等
参数改为逻辑 key(落实方案②)。B 类必须放在这一步,原因见下节。

### Step 6:S3Storage(待做,Phase 3)

> 前置基础:[三(S3 后端)](#三storage-接口与后端)。

等真正上 AWS 时,新增 `S3Storage` 类(同一套 6 个动作,内部走 S3),入口把
`LocalStorage` 换成 `S3Storage` 即可,上层 stage 代码不改。属 future_plan 的 Phase 3。

---

## 迁移顺序原则:A 类先、B 类后

咽喉点按「**存储位置由谁决定**」分两类,这决定了它们的迁移时机:

- **A 类 —— 根来自 `data_dir`(干净,可独立迁移)**:位置纯由 `data_dir` 推出,逻辑 key
  一目了然。包括 reports、wechat harvest checkpoint、article sink。→ Step 2/3/4。
- **B 类 —— 根来自「任意 input」(与入口串联绑定)**:位置跟随用户可传任意值的
  `--input` / `--checkpoint-file`。没有 Step 5 的入口串联,就得不到干净的逻辑 key——
  硬提前迁只能得到「光秃秃文件名」当 key,对 S3 无意义,且之后还要重做。包括
  `json_records`、import checkpoint。→ 必须放到 Step 5。

一句话:**能从 `data_dir` 干净推出 key 的先迁;跟随任意路径的,等入口把 storage + key
串起来再一起迁。**

---

## 测试策略

- **每步跑全套件**:每迁一个咽喉点,`pytest tests/unit -q`(与 CI 同命令)必须全绿,
  再进下一步。出问题时范围极小,一眼定位是哪一步。
- **行为字节级不变**:迁移不改变产物内容与落盘位置。序列化保持原样(reports 尾部带
  `\n`,checkpoint / records / sink 不带),`LocalStorage` 把 key 映射回原物理位置,现有
  集成测试无感。
- **接口层独立测试**:`test_storage.py` 用 `tmp_path` 直接测 `LocalStorage` 的每个动作,
  与业务解耦。
- **纯标准库**:`LocalStorage` 只用 `pathlib` / `shutil`,可在最小环境下独立验证。

---

## 尚未完成

- **S3Storage 实现**与 AWS 相关配置 —— 留到 future_plan 的 Phase 3。
- **Step 4/5** —— article sink 迁移、入口串联 + B 类迁移 + `--input` 改逻辑 key。
- 一个已知的小取舍:失败分支「先写报告 → 再写 DB 记录 → 抛出」,若 DB 写入本身抛错,会
  出现「有报告但无 DB 行」的部分追踪。影响很小,暂不处理。
