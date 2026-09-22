# 首次语料导入:把「导进去了」变成可核对的事实 —— 设计说明

本文记录 [ROADMAP_platform](../../roadmap/ROADMAP_platform.md) 第 20 项(issue #105)的设计
和取舍:导入在那一刻记下 `CORPUS_SHA256`、按键和内容向数据库核对、写报告,对不上就失败;
把「跑迁移的身份」和「跑应用的身份」分开;以及让这两件事在 #111 搭好的 AWS 栈上真正接通的
Terraform 配置。

本文兼作**学习参考**,面向没配过 Postgres 权限、也没碰过这条导入管线的读者:先给全局大图,
再补基础知识,最后才逐步讲实现。照着敲的命令不在这里,在 [deployment.md](../../deployment.md)。

---

## 目录

- [背景](#背景)
- [先看全局:一份语料从文件到上线](#先看全局一份语料从文件到上线)
- [基础知识](#基础知识)
  - [一、「有数据」只能有一个定义](#一有数据只能有一个定义)
  - [二、checkpoint 说「完成」,说的是什么](#二checkpoint-说完成说的是什么)
  - [三、CORPUS_SHA256 是「什么」的 hash](#三corpus_sha256-是什么的-hash)
  - [四、数据库里的身份与权限](#四数据库里的身份与权限)
  - [五、为什么导入用迁移身份(粘合:二 × 四)](#五为什么导入用迁移身份粘合二--四)
- [实现步骤](#实现步骤)
  - [Step 1:行数的计法收敛到一处](#step-1行数的计法收敛到一处)
  - [Step 2:导入完按键和内容核对,再写报告](#step-2导入完按键和内容核对再写报告)
  - [Step 3:运行时角色脚本](#step-3运行时角色脚本)
  - [Step 4:在 #111 的栈上接通](#step-4在-111-的栈上接通)
  - [Step 5:用「像 RDS 的」Postgres 证明权限够、也证明权限不多](#step-5用像-rds-的postgres-证明权限够也证明权限不多)
- [上线](#上线)
- [测试策略](#测试策略)
- [已知取舍与未完成](#已知取舍与未完成)

---

## 背景

第 20 项要解决的是:**Phase 2 部署的是一个空库上的服务,而这个服务在空库上按设计拒绝
服务**。`/ready` 数不到当前模型的行就一直 503,ALB 永远不导流,ECS 反复重启 task ——
表象和网络配错一模一样。

操作层面这件事已经发生过一次:#111 在 AWS 上用 `ecs exec` 把 2312 行导进了生产 RDS,`/ready`
转 200,RDS 全程没有公网地址。但对照 #105 的完成标准,它留下了三个口子:

| 完成标准 | #111 之后的现状 | 缺什么 |
|---|---|---|
| `/ready` 的 `knowledge_base_rows` 与**本地导入报告**对得上 | 人眼看了一下是 2312 | 导入命令**根本不产出报告** |
| 跑迁移的凭据 ≠ 应用运行时的凭据 | 两者都是 RDS 主用户 `cssa_admin` | #111 自己在「三笔债」里记下了 |
| 本次语料的 `CORPUS_SHA256` 已记录并配进 task definition | 没记,也没配 | 从上线那天起,每一行 `chat_interactions` 的「哪份语料」坐标都是 null |

第三条最贵。`corpus_sha256` 是[四种版本坐标](../../../CONTRIBUTING.md#four-version-coordinates)
之一,它的全部价值在于半年后拿线上记录和离线评估做对照。**事后补算**容易和实际导入的那份
对不上 —— 文件被动过、被重新生成过、导入时用了 `--limit`。只有导入的那一刻,手里拿着的恰好
就是进了库的那批记录。

---

## 先看全局:一份语料从文件到上线

```text
      迁移身份(RDS 主用户,迁移任务里)                运行时身份(cssa_app,API 任务里)
      ────────────────────────────────                ─────────────────────────────────
每次部署,迁移任务:
① alembic upgrade head
     建表、改表、CREATE EXTENSION vector
② python -m ops.provision_runtime_role
     建 / 改 cssa_app,授权对齐清单,       ───────►  能:读 knowledge_base、pipeline_runs
     再验证它实际拥有的权限                            追加 chat_interactions
                                                    不能:DDL、写语料、读别人的问题
导入语料时,同一个任务定义起一次性任务:
③ 下载语料 → import-knowledge-base
     ├─ 校验 → 嵌入 → 分批写入(有 checkpoint)
     ├─ corpus_sha256 = 这批记录的指纹              ← 基础知识三
     ├─ 按键 + 内容逐条回库核对(跑了的、被 checkpoint 跳过的都核)  ← 二
     ├─ 数当前模型的行(与 /ready 同一条 SQL)       ← 一
     └─ 核对不上 → 失败;对上 → 日志里一行 command_completed(即报告)
④ 把 corpus_sha256 写进 infra/variables.tf,提交
⑤ terraform apply:API 以 cssa_app 连库、带上 CORPUS_SHA256   ← 四、五
⑥ /ready 的 knowledge_base_rows == 日志里的 knowledge_base_rows → 完成
```

左边一列是**部署时、由人发起、以迁移身份跑**的动作,右边是**长期运行、面向公网**的进程。
整份文档其实只在讲两件事:左边做完之后,怎么证明它真的做完了(③ 的核对、⑥ 的比对);以及
右边为什么不该拥有左边的任何能力(②、⑤)。

---

## 基础知识

### 一、「有数据」只能有一个定义

> 这一簇讲:`/ready`、导入报告和运维脚本为什么必须用同一条 SQL 数行。

`/ready` 判断「知识库有没有数据」时,数的不是「表里有几行」,而是**当前配置的嵌入模型和
revision 嵌出来的行**:

```sql
SELECT COUNT(*) FROM knowledge_base
WHERE embedding_model = %s
  AND embedding_revision IS NOT DISTINCT FROM %s;
```

所以有两种「空」:真的空表;以及表里满是**别的模型**嵌出来的向量。第二种读作空是对的 ——
不同模型的向量不在同一个空间里,维度都可能不同,拿来检索比没有更糟。

完成标准要求**拿导入报告的数去对 `/ready` 的数**。这只有在两边是同一个定义时才有意义。同一条
SQL 原来有三份:`/ready`、[ops/db_status.py](../../../ops/db_status.py) 的 `active_rows`、
以及导入报告。现在它只有一份,在 [app/services/knowledge_base.py](../../../app/services/knowledge_base.py)。

### 二、checkpoint 说「完成」,说的是什么

> 这一簇讲:为什么导入完不能相信自己的 checkpoint,而要逐条回头问数据库。

导入是分批的,每批提交一次,进度记在 checkpoint 文件里,中途失败重跑时从断点继续。
checkpoint 有一个**身份**,身份变了就从头来:

```json
{
  "dataset_fingerprint": "3f9c…",
  "model_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "model_revision": "…",
  "table_name": "knowledge_base",
  "target_id": "postgresql://localhost:15432/rag_vectordb",
  "batch_size": 100,
  "record_count": 2312
}
```

注意 `target_id` 只有**主机、端口、库名** —— 为了不把密码写进文件。于是 checkpoint 说
「completed」,严格的意思只是:**曾经有一次运行,在一个叫这个名字的地方跑完了**。它会以三种
方式说错:

1. **库被重建了。** #111 的栈是按「可以随时 destroy 再建」设计的。重建后的 RDS 地址、端口、
   库名都可能和原来一样,checkpoint 认得它,但里面一行都没有。
2. **两个库长得一样。** 走端口转发连一个库时,本地看到的是 `localhost:<端口>/rag_vectordb`。
   恰好和另一个库同端口同名,那个库的「completed」会让这次导入**直接跳过、什么都不写**。
3. **库里是另一个版本的语料。** 同样的文章,内容被清洗规则改过;或者规模相近的另一份语料。

三种情况下旧代码都退出 0,看起来一切正常。然后要么 `/ready` 503、task 反复重启;要么更糟
—— `/ready` 是绿的,但报出来的 `corpus_sha256` 指着一份库里并没有的语料,从此每一行记录都
带着一个**错的**坐标。

**所以导入完,每一条记录都要回库核对一遍**,不管这次是真的写了、还是被 checkpoint 跳过了:

> 这批记录的每一个 `(link, question_text)` 在表里都有一行,
> 内容和这条记录**逐字节相同**,且嵌入模型 / revision 是当前的。

只比「行数够不够」是不够的 —— 上面第 3 种情况里,行数完全一样。按键和内容比才能抓到它。
为什么比内容就够、不比 `source`、`tags` 这些:向量是从 `question_text` 和 `content`
算出来的([knowledge_base_text.py](../../../pipelines/embedding/knowledge_base_text.py)),键和
内容相同,检索看到的就是同一个东西。内容本身很大,所以比的是 md5:本地算记录内容的 md5,
库里用 `md5(content)`,只把键和 md5 传过去。

核对不上就**失败**,而不是悄悄替你 reset 重导。报错写明原因和补救(`--reset-checkpoint`,
完整管线是 `--reset-import-checkpoint`)。自动重导看着体贴,但它会让「checkpoint 和数据库对
不上」这件本该被看见的事消失。

核对通过时还有两个数值得看:

- `skipped_by_checkpoint` —— 这次是真跑了,还是被 checkpoint 跳过、只做了核对。跳过时
  `affected_count` 是**上一次**运行的数,不是这次的。
- `rows_outside_corpus` —— 表里同一模型、但不属于这份语料的行。loader 只做 upsert、从不删,
  所以更新语料时被删掉的文章会留在库里。它们不影响「这份语料完整」,但 `/ready` 会数它们、
  检索会返回它们,此时 `CORPUS_SHA256` 只描述了在线内容的一部分。所以报告和日志里单列、并打
  一条 warning,而不是让它失败。

还有一个边界:**空输入**(比如 `--limit 0`)的状态是 `empty`,`corpus_sha256` 为 null ——
「空列表的 hash」绝不能被当成一份语料的坐标配进部署。

### 三、CORPUS_SHA256 是「什么」的 hash

> 这一簇讲:「哪份语料」这个坐标到底对什么取指纹,以及为什么必须在导入时取。

最直觉的做法是对文件跑一次 `sha256sum`。它有两个问题:

- **`--limit` 之后它是错的。** 导了前 200 条,hash 却是整份文件的。
- **它对排版敏感。** 同一批记录换个缩进重新写一次文件,hash 就变了,可语料并没有变。

所以 `corpus_sha256` 取的是**实际导入的那批记录**的规范化 JSON(键排序、紧凑分隔符、UTF-8)
的 SHA-256。这恰好就是 checkpoint 身份里的 `dataset_fingerprint` —— 同一个函数
([`fingerprint_records`](../../../pipelines/shared/import_checkpoint.py)),同一个值。
「哪份语料」因此只有**一个定义**,而且它来自导入那一刻手里的数据。

> ⚠️ 这个指纹**对记录顺序敏感**。转换阶段把同一批记录换个顺序输出,会得到一个不同的
> `corpus_sha256`。这是有意接受的方向:把同一份语料误判成「不同」只是让一次比较变得保守;
> 反过来把不同的误判成「相同」,才会让半年后的对照悄悄失真。

**离线评估那边必须用同一个函数。** 评估报告和 `manifest.json` 里的 `corpus_sha256` 如果各自
对文件 `sha256sum`,线上和离线就是两把尺子。相关的地方都已加了指向这个函数的说明:
[CONTRIBUTING](../../../CONTRIBUTING.md#four-version-coordinates)、
[ROADMAP_rag](../../roadmap/ROADMAP_rag.md) 1.3、[ROADMAP_data](../../roadmap/ROADMAP_data.md) 1.5、
[eval-dataset.md](../planned/eval-dataset.md)。

### 四、数据库里的身份与权限

> 这一簇讲:Postgres 的「角色」「所有者」「授权」各是什么,迁移和应用分别需要什么,以及
> RDS 的主用户为什么不是超级用户、这带来了什么。

**角色(role)** 就是 Postgres 里的账号;能登录的角色就是通常说的「用户」。一个角色能对一张
表做什么,由三件事决定:

- **所有者(owner)**:建这张表的角色,能对表做任何事。
- **直接授权(GRANT … TO 角色)**:所有者把 `SELECT`、`INSERT` 等单项权限授给别的角色,
  甚至只授到某几列上。
- **间接得到的权限**:授给 `PUBLIC`(所有角色)的,以及通过「是另一个角色的成员」继承来的。

迁移和应用需要的东西完全不在一个量级:

| | 迁移 | 运行中的 API |
|---|---|---|
| `CREATE EXTENSION vector` | ✅ 要 —— 第一个迁移就有这句 | ❌ |
| 建表、改表、删表 | ✅ 要,而且是这些表的所有者 | ❌ |
| 读 `knowledge_base` | — | ✅ 检索、`/ready` 数行 |
| 读 `pipeline_runs` | — | ✅ `/status` 报最近一次管线运行 |
| 写 `chat_interactions` | — | ✅ 每个回答一行 |
| 写 `knowledge_base` | — | ❌ 见[五](#五为什么导入用迁移身份粘合二--四) |

API 是面向公网的进程。它用主用户连库,意味着任何一个能让它执行任意 SQL 的漏洞,都等于拿到
了整个库。**权限最小化不是为了防正常代码,是为了限定出事时的爆炸半径。**

几个具体的点:

**列级授权,以及 `ON CONFLICT` 的坑。** API 对 `chat_interactions` 只能 `INSERT`,读不回任何
人的问题。唯一例外是 `request_id` 这一列:写入语句是
`INSERT … ON CONFLICT (request_id) DO NOTHING`,Postgres 为了判断冲突,要求执行者对冲突列
有 `SELECT` 权限。只给 `INSERT` 的话**每一次写入都会被拒绝**,而且是静默的 —— 写入跑在响应
发出之后的后台任务里,失败只记日志。这个坑是集成测试抓出来的。

**RDS 的主用户不是超级用户。** 它有 `CREATEROLE`、`CREATEDB`,是 `rds_superuser` 的成员,
但不是 Postgres 意义上的 superuser。Postgres 16 对这种角色有一条很容易踩的规矩:建角色时可以
写 `NOSUPERUSER NOREPLICATION NOBYPASSRLS`,但 **`ALTER ROLE` 里连提都不能提这三个属性** ——
哪怕是关掉它们。所以脚本的「改」路径只碰 `LOGIN` 和密码;否则第一次部署能过,之后每一次都会
卡在迁移任务上。本地和 CI 都用真超级用户,发现不了这一点 —— 见 [Step 5](#step-5用像-rds-的postgres-证明权限够也证明权限不多)。

**声明式地收敛,而不是累加。** 授权是会累积的:今天授了、明天从清单里删了,库里那条授权还在。
所以脚本每次都「先收回,再按清单授予」,放在**同一个事务**里 —— 其他会话要么看到旧的完整
权限,要么看到新的完整权限。收回只做在迁移身份管得着的表上:对一张别人的、自己毫无权限的表
执行 `REVOKE` 是报错而不是空操作,会让整个脚本失败。

**验证的是「实际拥有」,不是「我授了什么」。** `REVOKE … FROM cssa_app` 只能收回自己授的;
授给 `PUBLIC` 的、别的授权人给的、通过成员关系继承的,都不受影响。所以收尾时脚本用
`has_table_privilege` / `has_column_privilege` 逐表逐列查 `cssa_app` 实际能做什么,和清单
逐项比对,多一项少一项都失败。授给 `PUBLIC` 的它**不替你收回**(那会影响所有角色),只报出
来。

**密码在客户端哈希。** `CREATE ROLE … PASSWORD '<明文>'` 会让明文出现在语句里,而语句可能
进服务器日志。脚本先在本地算出 SCRAM 校验值再发过去,服务器只见过哈希。

**轮换密码有一个窗口。** 一个角色只有一个密码,改了立刻生效;API 任务只在启动时读一次密钥。
所以「改密钥 → 跑迁移任务(改密码)→ 立刻强制重新部署 API」三步之间,新开的连接会失败。
步骤见 [deployment.md](../../deployment.md#轮换运行时数据库密码)。

### 五、为什么导入用迁移身份(粘合:二 × 四)

> 这一簇把前面两条线接起来:导入核对的是「写进去了没有」,权限决定的是「谁能写」。

运行时角色**不能写 `knowledge_base`**。那导入用谁?

用迁移身份。往库里写语料和改表结构是**同一类动作** —— 部署时发生、由人发起、次数很少、每一次
都该被记住。而 API 是一直在跑、面向公网的进程:一个被攻破的 API 如果能写语料,它能污染的不是
一次回答,而是**之后所有的回答**,而且没有任何报错。

具体做法是用迁移任务定义起一个一次性任务,把命令换成「下载语料 + 导入」。这带来三个后果,
都已处理:

- 导入不再跑在 API 容器里。#111 那次是 `ecs exec` 进 API 容器跑的,那时 API 还是主用户;
  现在 API 的角色写不了语料,而且把导入和 `/ready` 转绿绑在同一个容器里本来就别扭 —— 空库上
  ALB 会判它不健康、ECS 会回收它,正在导入的进程也跟着没了。
- 迁移任务里只有 `DB_*` 分件、没有 `DATABASE_URL`,所以管线 CLI 改为从 `Settings` 取连接串
  (#111 已经让 `Settings` 会从分件拼),和迁移、授权脚本走同一条规则。
- 任务的文件系统随任务消失,报告文件带不走。所以报告里的数字**同样写在日志最后一行
  `command_completed` 里**,那一行进 CloudWatch,就是能留下来的报告。

> Phase 3 管线变成定时任务之后,它该有**自己的**角色(能写 `knowledge_base` 和
> `pipeline_runs`,不能改表结构)。v1 只有两个身份,是因为 v1 的导入只有人手动跑。

---

## 实现步骤

### Step 1:行数的计法收敛到一处

> 前置知识:[一](#一有数据只能有一个定义)

[app/services/knowledge_base.py](../../../app/services/knowledge_base.py) 放两个函数:数当前
模型的行(`/ready`、[db_status.py](../../../ops/db_status.py) 和导入都用它),以及数「这份
语料里有几条原样在库里」(导入用)。两者的模型过滤条件放在一起,改一处就看得见另一处。

放在 `app/` 而不是 `pipelines/`:依赖方向是管线用应用的定义,而不是面向公网的应用去依赖
管线代码。

### Step 2:导入完按键和内容核对,再写报告

> 前置知识:[二](#二checkpoint-说完成说的是什么)、[三](#三corpus_sha256-是什么的-hash)

[import_knowledge_base.py](../../../pipelines/orchestration/import_knowledge_base.py) 的
`run_local_import` 无论真跑还是被 checkpoint 跳过,最后都走同一段收尾:

1. 另开一条短连接,数当前模型的行和这份语料原样在库的条数(表还不存在时,报「先跑迁移」);
2. 定状态:`completed` / `incomplete` / `empty`;
3. 写 `reports/pipelines/import_knowledge_base_<run_id>.json`;
4. `incomplete` 就抛 `KnowledgeBaseImportIncompleteError`,命令以非零退出;有语料外的行就
   打 warning。

报告长这样(CLI 最后一行日志里是同样的数字):

```json
{
  "run_id": "5b0e…",
  "stage": "import_knowledge_base",
  "status": "completed",
  "started_at": "2026-09-22T10:14:03+00:00",
  "finished_at": "2026-09-22T10:19:41+00:00",
  "input_key": "current/wechat_articles_processed.json",
  "limit": null,
  "skipped_by_checkpoint": false,
  "corpus_sha256": "3f9c…",
  "record_count": 2312,
  "unique_record_count": 2312,
  "affected_count": 0,
  "corpus_rows": 2312,
  "knowledge_base_rows": 2312,
  "rows_outside_corpus": 0,
  "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "embedding_revision": "…",
  "table_name": "knowledge_base",
  "target_id": "postgresql://cssa-da-prod-db.xxxx.ap-southeast-2.rds.amazonaws.com:5432/rag_vectordb"
}
```

`target_id` 故意不带凭据 —— 报告是会被人拷来拷去的文件。`run_id` 与命令本身的 `run_id` 相同
(完整管线 `run-wechat-pipeline` 也把自己的传进来,并把 `corpus_sha256`、行数和导入报告的位置
带进它自己的报告),所以报告和那次运行的全部日志能 join 起来。

### Step 3:运行时角色脚本

> 前置知识:[四](#四数据库里的身份与权限)、[五](#五为什么导入用迁移身份粘合二--四)

[ops/provision_runtime_role.py](../../../ops/provision_runtime_role.py),**以迁移身份**在迁移
之后运行(迁移任务每次部署都这么跑):

```bash
RUNTIME_DB_PASSWORD=… python -m ops.provision_runtime_role    # 角色名默认 cssa_app
```

按顺序:

1. **拒绝一看就错的情况**:要建的角色就是自己当前连着的身份;表还不存在(迁移没跑);同名
   角色已存在但带着 `SUPERUSER` / `CREATEROLE` / `CREATEDB` 等高权限属性 —— 那是别人的账号,
   不该被悄悄拿来当运行时角色。
2. **建或改角色**。建:显式 `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`;
   改:只动 `LOGIN` 和密码(RDS 的规矩,见[四](#四数据库里的身份与权限))。密码是本地算好的
   SCRAM 校验值。
3. **收敛授权**:`CONNECT` 这个库、`USAGE` public schema;对迁移身份管得着的每张表和序列
   收回全部权限;再按 `RUNTIME_TABLE_PRIVILEGES` 和 `RUNTIME_COLUMN_PRIVILEGES` 授予。
4. **验证实际拥有的**:属性、成员关系、能否建 schema / 建对象、拥有哪些对象,以及逐表逐列、
   逐序列的实际权限和清单比对。任何一项不符,整个事务回滚、报错,列出每一条。

第 4 步是这个脚本存在的意义本身:「运行时身份与迁移身份不同」这条完成标准,不是靠名字不同来
满足的,而是靠**运行时身份确实做不了迁移身份做的事**,并且每次部署都当场证明一次。

密码只从环境变量读,不接受命令行参数 —— 命令行参数会进 shell 历史和进程列表。

### Step 4:在 #111 的栈上接通

> 前置知识:[五](#五为什么导入用迁移身份粘合二--四)

改的都是 #111 的 Terraform 文件:

| 文件 | 改了什么 |
|---|---|
| [secrets.tf](../../../infra/secrets.tf) | 新增手填的 `cssa-da-prod-runtime-db-password` 密钥;执行角色能读它(和其他密钥一样按 ARN 授权) |
| [ecs_migrate.tf](../../../infra/ecs_migrate.tf) | 命令改为 `sh -c "alembic upgrade head && python -m ops.provision_runtime_role"`;注入 `RUNTIME_DB_USER` 和 `RUNTIME_DB_PASSWORD`;`depends_on` 读密钥的权限,所以 #111 流程里那条 `-target` 的 apply 会把权限一起带上 |
| [ecs.tf](../../../infra/ecs.tf) | API 的 `DB_USER` 改为 `cssa_app`(普通环境变量)、`DB_PASSWORD` 取自新密钥,**不再注入主用户密钥**;`CORPUS_SHA256` 来自变量,为 null 时整条不注入,指纹记为诚实的 null 而不是空字符串 |
| [variables.tf](../../../infra/variables.tf) | `runtime_db_user`(默认 `cssa_app`)和 `corpus_sha256`(默认 null,校验 64 位十六进制) |
| [outputs.tf](../../../infra/outputs.tf) | `rds_security_group_id`(核对「没有暴露过」用)、运行时角色名和密钥名 |

`corpus_sha256` 写成**变量的默认值、提交进仓库**,而不是每次 `apply` 时 `-var` 传:漏传一次,
新任务定义里这个变量就没了,指纹悄悄变回 null;而写进仓库,「语料什么时候换的、换成了哪份」
就有了 git 历史。

迁移命令用了 shell,和 #111 当初「不要 shell 包装」的取舍并不冲突:那条取舍防的是在 shell 里
手拼连接串、漏掉百分号编码。这里的 shell 只做 `&&`,两个步骤都自己从 `DB_*` 分件拼连接串。

### Step 5:用「像 RDS 的」Postgres 证明权限够、也证明权限不多

> 前置知识:[四](#四数据库里的身份与权限)

本地开发和 CI 都用超级用户连库,所以有两类问题在所有地方都跑得通、**只有生产会炸**:一条需要
某个权限的新代码路径;以及一条只有超级用户才能执行的授权语句(上面 `ALTER ROLE` 那个坑)。

[tests/integration/test_runtime_role.py](../../../tests/integration/test_runtime_role.py) 在
测试库里搭出生产的形状:一个**不是**超级用户、只有 `CREATEROLE` / `CREATEDB` 的「迁移身份」,
拥有一个临时库,由它跑迁移和授权脚本;超级用户只负责布景(预装 vector 扩展,像 RDS 那样)和
模拟有人手工改过权限。然后:

- 用运行时角色**驱动真实的 API 代码路径**:`check_readiness` 数到行、`PGVectorRetriever`
  检索到行、`/status` 读到最近一次运行、`record_chat_interaction` 真的写进了一行(这个函数从
  不抛异常,证据只能是那一行存在 —— `ON CONFLICT` 的坑就是这一条抓出来的);
- 参数化逐条证明它**做不了**迁移做的事(建表、改表、删表、建扩展、建 schema)、做不了导入
  做的事(写、改、删语料 —— 插入时显式给 id,确保拦住它的是表权限而不是序列权限)、也读不了
  别人的问题;
- 以非超级用户**连跑三次**授权脚本,确认收敛掉手工加的授权、密码真的换了。把 `ALTER ROLE`
  改回带那三个属性的写法,这条测试就会失败 —— 已经验证过;
- 授给 `PUBLIC` 的权限、角色拥有的表、继承来的成员关系都会被报出来;一张别人的表不会让脚本
  中止。

---

## 上线

照着敲的步骤在 [deployment.md](../../deployment.md):常规的每次部署(迁移任务现在顺带对齐授权)、
[导入或更新语料](../../deployment.md#导入或更新语料)、
[轮换密码](../../deployment.md#轮换运行时数据库密码)、
[核对数据库没有被暴露过](../../deployment.md#核对数据库没有被暴露过),以及只做一次的
[切换到运行时身份](../../deployment.md#一次性切换到运行时身份105)。

一次性切换的顺序,以及为什么是这个顺序:

1. **建密钥并写入值** —— 迁移任务要读它,ECS 起不了一个密钥没有值的任务。
2. **构建推送镜像**。
3. **跑迁移任务** —— 建出 `cssa_app`。先有角色,API 才能用它登录。
4. **以迁移身份导入语料,记下 `corpus_sha256`**。库里还是 #111 那份时用同一份文件:
   `affected_count` 为 0、`knowledge_base_rows` 等于 `unique_record_count`、
   `rows_outside_corpus` 为 0,三个数一起证明库里正是这份语料。库被重建过就是一次正常的首次
   导入。**这一步在 API 切换之前**:空库上的 API 过不了 `/ready`,部署熔断器会回滚它。
5. **把坐标写进 `variables.tf`,部署 API** —— 这次部署把 API 切到 `cssa_app`。
6. **核对五条完成标准,结果贴到 #105 上再关。**

---

## 测试策略

| 层 | 测什么 |
|---|---|
| 单元(导入) | 报告内容与返回值一致;`corpus_sha256` 等于实际导入记录的指纹、`--limit` 时只覆盖导入的那部分;传给核对的是每条记录的键和内容 md5,重复键以最后一条为准;checkpoint「已完成」而表是空的、或表里是规模相同的另一份语料 → 失败、报告为 `incomplete`、报错里两个命令的 flag 都有,`--reset-checkpoint` 之后真的重导;语料外的行被报出并打 warning;空输入不给出坐标;表不存在时提示先迁移;报告里没有密码 |
| 单元(CLI) | `command_completed` 那一行带齐 `corpus_sha256` 等全部字段、没有密码、`run_id` 与报告一致;没有 `--database-url` 时用 `Settings` 拼出的连接串 |
| 单元(脚本) | 短密码在连库之前就被拒;密码缺失、授权失败时的退出码;清单本身的两条策略:语料只读、交互日志只写 |
| 集成(导入) | 真 Postgres 上:别的模型的行不计入;报告的行数与 `/ready` 一致;语料外的行被报出;库里是旧版本内容(键相同、行数相同)时被抓出;重建后的库被抓出;中文内容下 Python 的 md5 与 Postgres 的 `md5()` 一致 |
| 集成(角色) | 见 [Step 5](#step-5用像-rds-的postgres-证明权限够也证明权限不多) |
| Terraform | `terraform fmt -check`、`terraform validate`;以及一次用 mock provider 的 `terraform test`(本地跑过,未提交):API 任务里 `DB_USER=cssa_app`、没有主用户密钥;`CORPUS_SHA256` 为 null 时不注入、有值时注入;非法值被变量校验拒绝;迁移任务的命令和注入正确 |

全部结果:单元 305 通过,集成 34 通过(本地 `docker compose --profile test` 的 pgvector pg16,
与 CI 同一镜像)。集成测试里的角色和临时库每次都不同名、结束时删除 —— 角色是整个集群的,不像
表那样随库清理。

---

## 已知取舍与未完成

- **生产上还没有执行。** 代码和配置都在这里,但 #105 的五条完成标准里有四条是「生产上是什么
  状态」,要按[上线](#上线)的步骤执行一遍才算数。
- **`CORPUS_SHA256` 是配出来的,不是从库里读的。** 有人重导了新语料却忘了改变量,之后每一行
  都会带着错的坐标。写进仓库 + 导入日志里醒目的一行降低了这个概率,但没有消除它。按构造就
  正确的形状是让导入把 hash 写进库里、API 从库里读 —— 真出现过一次漂移,就该换成那样。
- **指纹对记录顺序敏感。** 见[三](#三corpus_sha256-是什么的-hash)。
- **核对比的是键和内容,不比元数据。** `source`、`tags`、日期变了而内容没变,核对照样通过,但
  `corpus_sha256` 会不同。这些字段不影响检索,只影响展示。
- **内容 md5 假定数据库是 UTF8 编码。** RDS 和本地 pgvector 镜像默认都是。
- **本地 compose 的 API 仍用超级用户。** 所以「只有生产报 permission denied」这一类问题只靠
  `test_runtime_role.py` 兜,而它只覆盖它驱动过的代码路径。**加一条碰数据库的新代码路径,就在
  那里加一条。**
- **轮换密码有几十秒到几分钟的窗口。** 见[四](#四数据库里的身份与权限)。零停机需要两个登录
  角色轮流用、共享一个持有授权的组角色,现在不值得。
- **在 RDS 上删除 `cssa_app` 要多一步。** Postgres 16 里,建角色的一方只拿到这个角色的 ADMIN,
  没有它的权限,所以主用户不能直接 `DROP OWNED BY cssa_app`;得先把自己加进这个角色
  (`GRANT cssa_app TO cssa_admin`)再删。
- **运行时角色能建临时表。** Postgres 默认把 `TEMP` 授给 `PUBLIC`。临时表随会话消失,不影响
  持久的库结构,没有收回。
