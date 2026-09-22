# 首次语料导入:把「导进去了」变成可核对的事实 —— 设计说明

本文记录 [ROADMAP_platform](../../roadmap/ROADMAP_platform.md) 第 20 项(issue #105)
**代码侧**的设计和取舍:导入在那一刻记下 `CORPUS_SHA256`、向数据库要行数、写报告、
对不上就失败;以及一个把「跑迁移的身份」和「跑应用的身份」分开的脚本。

本文兼作**学习参考**,面向没配过 Postgres 权限、也没碰过这条导入管线的读者:先给全局
大图,再补基础知识,最后才逐步讲实现。

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
  - [Step 2:导入完先核对,再写报告](#step-2导入完先核对再写报告)
  - [Step 3:运行时角色脚本](#step-3运行时角色脚本)
  - [Step 4:用真 Postgres 证明权限够、也证明权限不多](#step-4用真-postgres-证明权限够也证明权限不多)
- [上线步骤](#上线步骤)
- [测试策略](#测试策略)
- [已知取舍与未完成](#已知取舍与未完成)

---

## 背景

第 20 项要解决的是:**Phase 2 部署的是一个空库上的服务,而这个服务在空库上按设计拒绝
服务**。`/ready` 数不到当前模型的行就一直 503,ALB 永远不导流,ECS 反复重启 task ——
表象和网络配错一模一样。

操作层面这件事已经发生了:#111 在 AWS 上用 `ecs exec` 把 2312 行导进了生产 RDS,`/ready`
转 200,RDS 全程没有公网地址。但对照 #105 的完成标准,它留下了三个口子:

| 完成标准 | 现状 | 缺什么 |
|---|---|---|
| `/ready` 的 `knowledge_base_rows` 与**本地导入报告**对得上 | 人眼看了一下是 2312 | 导入命令**根本不产出报告** |
| 跑迁移的凭据 ≠ 应用运行时的凭据 | 两者都是 RDS 主用户 `cssa_admin` | #111 自己在「三笔债」里记下了 |
| 本次语料的 `CORPUS_SHA256` 已记录并配进 task definition | 没记,也没配 | 从上线那天起,每一行 `chat_interactions` 的「哪份语料」坐标都是 null |

第三条最贵。`corpus_sha256` 是[四种版本坐标](../../../CONTRIBUTING.md#four-version-coordinates)
之一,它的全部价值在于半年后拿线上记录和离线评估做对照。**事后补算**容易和实际导入的
那份对不上 —— 文件被动过、被重新生成过、导入时用了 `--limit`。只有导入的那一刻,手里拿
着的恰好就是进了库的那批记录。

本文的改动都在代码侧:导入命令、一个新脚本、测试。**真正在生产上执行**依赖 #111 的
`infra/`(还没合入 main),步骤见[上线步骤](#上线步骤)。

---

## 先看全局:一份语料从文件到上线

```text
            迁移身份(RDS 主用户)                     运行时身份(cssa_app)
            ────────────────────                     ────────────────────
① alembic upgrade head
     建表、CREATE EXTENSION vector
② python -m ops.provision_runtime_role
     建 / 改 cssa_app,只给最小权限 ─────────────►  能:读 knowledge_base、pipeline_runs
                                                      追加 chat_interactions
                                                   不能:DDL、写语料、读别人的问题
③ python -m pipelines import-knowledge-base
     ├─ 校验 → 嵌入 → 分批写入(有 checkpoint)
     ├─ corpus_sha256 = 这批记录的指纹             ← 基础知识三
     ├─ 问数据库:当前模型有几行?(与 /ready 同一条 SQL)  ← 一
     ├─ 行数 < 唯一键数 → 失败,提示 --reset-checkpoint  ← 二
     └─ 写 reports/pipelines/import_knowledge_base_<run_id>.json
④ 把报告里的 corpus_sha256 配进 API 的 CORPUS_SHA256
⑤ 部署 API,以 cssa_app 连库                        ← 四、五
⑥ /ready 的 knowledge_base_rows == 报告里的 knowledge_base_rows → 完成
```

左边一列是**部署时、由人发起**的动作,右边是**长期运行、面向公网**的进程。整份文档其实只在
讲两件事:左边做完之后,怎么证明它真的做完了(①–④ 的核对);以及右边为什么不该拥有左边
的任何能力(②、⑤)。

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

完成标准要求**拿导入报告的数去对 `/ready` 的数**。这只有在两边是同一个定义时才有意义:
如果报告数的是「表里所有行」而 `/ready` 数的是「当前模型的行」,两者在换模型的那天会
自然地对不上,于是真正的问题(导了一半)会被当成噪音,反过来也可能掩盖问题。

同一条 SQL 原来有**三份**:`/ready`、[ops/db_status.py](../../../ops/db_status.py) 的
`active_rows`、以及这次要加的导入报告。现在它只有一份,见
[app/services/knowledge_base.py](../../../app/services/knowledge_base.py)。

### 二、checkpoint 说「完成」,说的是什么

> 这一簇讲:为什么导入完不能相信自己的 checkpoint,而要回头问数据库。

导入是分批的,每批提交一次,进度记在 checkpoint 文件里,中途失败重跑时从断点继续。
checkpoint 有一个**身份**,身份变了就从头来:

```json
{
  "dataset_fingerprint": "3f9c…",   // 这批记录的指纹
  "model_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "model_revision": "…",
  "table_name": "knowledge_base",
  "target_id": "postgresql://localhost:15432/rag_vectordb",
  "batch_size": 100,
  "record_count": 2312
}
```

注意 `target_id` 只有**主机、端口、库名** —— 为了不把密码写进文件。于是 checkpoint 说
「completed」,严格的意思只是:**曾经有一次运行,在一个叫这个名字的地方跑完了**。它有两种
典型的方式说错:

1. **库被重建了。** #111 的栈是按「白天建、晚上 destroy」设计的。重建后的 RDS 地址、端口、
   库名都可能和原来一样,checkpoint 认得它,但里面一行都没有。
2. **两个库长得一样。** 走端口转发连生产库时,本地看到的是 `localhost:<端口>/rag_vectordb`。
   如果恰好和本机开发库同端口同名,开发库的「completed」会让生产导入**直接跳过、什么都
   不写**,而命令报成功。

两种情况下命令都退出 0,报告里的 `affected_count` 还是上一次的数字,看起来一切正常。然后
`/ready` 503、task 反复重启 —— 又回到了第 20 项想省掉的那一天排查。

**所以导入完要问数据库本身。** 判据是:

> 当前模型的行数 ≥ 这批记录里 `(link, question_text)` 的**唯一键数**

为什么是唯一键数而不是记录数:表的唯一索引就是 `(link, question_text)`,键相同的记录落到
同一行上,记录数会比行数多。为什么是 ≥
而不是 ==:表里可能还有另一份用同一模型嵌入的语料,那些行是合法的多出来的。一次完整的导入
之后,这批的每一个键都必然有一行带着当前模型 —— upsert 在模型不同时会覆盖 —— 所以「少于」
就是确凿的「缺了」。

不满足就**失败**,而不是悄悄替你 reset 重导。报错里写明原因和补救(`--reset-checkpoint`),
报告以 `status: "incomplete"` 照样写出来。自动重导看着体贴,但它会让「checkpoint 和数据库
对不上」这件本该被看见的事消失。

### 三、CORPUS_SHA256 是「什么」的 hash

> 这一簇讲:「哪份语料」这个坐标到底对什么取指纹,以及为什么必须在导入时取。

最直觉的做法是对文件跑一次 `sha256sum`。它有两个问题:

- **`--limit` 之后它是错的。** 导了前 200 条,hash 却是整份文件的 —— 这个坐标指向一份库里
  并没有的语料。
- **它对排版敏感、对内容不敏感的地方不对。** 同一批记录换个缩进重新写一次文件,hash 就变了,
  可语料并没有变。

所以 `corpus_sha256` 取的是**实际导入的那批记录**的规范化 JSON(键排序、紧凑分隔符、UTF-8)
的 SHA-256。这恰好就是 checkpoint 身份里的 `dataset_fingerprint` —— 同一个函数
([`fingerprint_records`](../../../pipelines/shared/import_checkpoint.py)),同一个值。
「哪份语料」因此只有**一个定义**,而且它来自导入的那一刻手里的数据,不来自事后的某个文件。

> ⚠️ 这个指纹**对记录顺序敏感**。转换阶段如果把同一批记录换了个顺序输出,会得到一个不同
> 的 `corpus_sha256`。这是有意接受的方向:把同一份语料误判成「不同」,只是让一次比较变得
> 保守;反过来把不同的误判成「相同」,才会让半年后的对照悄悄失真。

**离线评估那边必须用同一个函数。** [ROADMAP_rag](../../roadmap/ROADMAP_rag.md) 1.3 的评估
报告、[ROADMAP_data](../../roadmap/ROADMAP_data.md) Phase 1.5 的 `manifest.json` 都要带
`corpus_sha256`;它们如果各自对文件 `sha256sum`,线上和离线就是两把尺子,这个坐标存在的
意义就没了。

### 四、数据库里的身份与权限

> 这一簇讲:Postgres 的「角色」「所有者」「授权」各是什么,以及迁移和应用分别需要什么。

**角色(role)** 就是 Postgres 里的账号;能登录的角色就是通常说的「用户」。一个角色能对
一张表做什么,由两件事决定:

- **所有者(owner)**:建这张表的角色。所有者能对表做任何事,包括 `ALTER`、`DROP`,以及
  把权限授给别人。
- **授权(GRANT)**:所有者可以把 `SELECT`、`INSERT` 等**单项**权限授给别的角色,甚至只授
  到某几列上。

迁移和应用需要的东西完全不在一个量级:

| | 迁移 | 运行中的 API |
|---|---|---|
| `CREATE EXTENSION vector` | ✅ 要 —— 第一个迁移就有这句,普通角色建不了扩展 | ❌ |
| 建表、改表、删表 | ✅ 要,而且是这些表的所有者 | ❌ |
| 读 `knowledge_base` | — | ✅ 检索、`/ready` 数行 |
| 读 `pipeline_runs` | — | ✅ `/status` 报最近一次管线运行 |
| 写 `chat_interactions` | — | ✅ 每个回答一行 |
| 写 `knowledge_base` | — | ❌ 见[五](#五为什么导入用迁移身份粘合二--四) |

API 是面向公网的进程。它用主用户连库,意味着任何一个能让它执行任意 SQL 的漏洞,都等于拿到
了整个库:能删表、能改语料、能读出所有人问过的问题。**权限最小化不是为了防正常代码,是为了
限定出事时的爆炸半径。**

几个具体的点:

**列级授权。** API 对 `chat_interactions` 只能 `INSERT`,不能 `SELECT` —— 它能写入用户的
问题和回答,但读不回任何人的。这样即使 API 进程被攻破,交互日志也拖不走。唯一的例外是
`request_id` 这一列,见下一条。

**`ON CONFLICT` 要读它的冲突列。** 写入语句是
`INSERT … ON CONFLICT (request_id) DO NOTHING`。Postgres 为了判断「冲突了没有」,要求执行者
对冲突目标的列有 `SELECT` 权限 —— 只给 `INSERT` 的话,**每一次写入都会被拒绝**。更糟的是这个
拒绝是**静默的**:写入跑在响应发出之后的后台任务里,失败只记一条日志,用户和 `/ready` 都
看不出任何异常,而 `chat_interactions` 一行都不会有。这个坑是
[Step 4](#step-4用真-postgres-证明权限够也证明权限不多) 的集成测试抓出来的,修法是只把
`request_id` 这一列的 `SELECT` 授给它。

**声明式地收敛,而不是累加。** 授权是会累积的:今天授了、明天从清单里删了,库里那条授权
还在。所以脚本每次都是「先 `REVOKE ALL`,再按清单 `GRANT`」,而且放在**同一个事务**里 ——
其他会话要么看到旧的完整权限,要么看到新的完整权限,看不到中间那个什么都没有的瞬间。代码
里的那份清单因此**就是**权限的全集。

**密码在客户端哈希。** `CREATE ROLE … PASSWORD '<明文>'` 会让明文出现在语句里,而语句可能
进服务器日志、进 `pg_stat_statements`。脚本改为先在本地算出 SCRAM 校验值再发过去,服务器
只见过哈希。

### 五、为什么导入用迁移身份(粘合:二 × 四)

> 这一簇把前面两条线接起来:导入核对的是「写进去了没有」,权限决定的是「谁能写」。

运行时角色**不能写 `knowledge_base`**。那导入用谁?

用迁移身份。理由是:往库里写语料和改表结构是**同一类动作** —— 部署时发生、由人发起、次数
很少、每一次都该被记住。而 API 是一直在跑、面向公网的进程。一个被攻破的 API 如果能写语料,
它能污染的不是一次回答,而是**之后所有的回答**,而且没有任何报错。

这也是为什么上面的核对(二)要问数据库而不是问 checkpoint:导入跑在一个和服务完全不同的
身份、往往也是不同的机器上,「导完了」和「服务看得见」之间没有任何天然的联系,只有同一条
SQL 数出同一个数,才把两边接上。

> Phase 3 管线变成定时任务之后,它该有**自己的**角色(能写 `knowledge_base` 和
> `pipeline_runs`,不能改表结构)。v1 只有两个身份,是因为 v1 的导入只有人手动跑。

---

## 实现步骤

### Step 1:行数的计法收敛到一处

> 前置知识:[一](#一有数据只能有一个定义)

新建 [app/services/knowledge_base.py](../../../app/services/knowledge_base.py),只放一个函数:
给一个游标,数当前模型 / revision 的行。`/ready`
([readiness.py](../../../app/services/readiness.py))、运维脚本
([db_status.py](../../../ops/db_status.py))和导入都调它。

放在 `app/` 而不是 `pipelines/`:依赖方向是管线用应用的定义(管线本来就读
`app.core.config`),而不是面向公网的应用去依赖管线代码。

### Step 2:导入完先核对,再写报告

> 前置知识:[二](#二checkpoint-说完成说的是什么)、[三](#三corpus_sha256-是什么的-hash)

[import_knowledge_base.py](../../../pipelines/orchestration/import_knowledge_base.py) 的
`run_local_import` 原来在 checkpoint 显示「已完成」时直接返回。现在无论是真的跑了、还是被
checkpoint 跳过,最后都会走同一段收尾:

1. 另开一条短连接,用 Step 1 的函数数行 —— 包括 checkpoint 跳过的那条路径,那正是最需要
   核对的一条;
2. 算唯一键数,比较;
3. 写 `reports/pipelines/import_knowledge_base_<run_id>.json`(不满足时 `status` 为
   `incomplete`);
4. 不满足就抛 `KnowledgeBaseImportIncompleteError`,命令以非零退出。

报告长这样:

```json
{
  "run_id": "5b0e…",
  "stage": "import_knowledge_base",
  "status": "completed",
  "input_key": "current/wechat_articles_processed.json",
  "corpus_sha256": "3f9c…",
  "record_count": 2312,
  "unique_record_count": 2312,
  "affected_count": 0,
  "knowledge_base_rows": 2312,
  "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "embedding_revision": "…",
  "table_name": "knowledge_base",
  "target_id": "postgresql://localhost:15432/rag_vectordb"
}
```

`target_id` 故意不带凭据 —— 报告是会被人拷来拷去的文件。同样三个数字(`corpus_sha256`、
`knowledge_base_rows`、`report_key`)也写在命令最后一行 `command_completed` 的 JSON 日志里:
在 `ecs exec` 这类容器里跑时,容器文件系统是临时的,**终端上的那行日志才是能带走的东西**。

`run_id` 与命令本身的 `run_id` 相同(完整管线 `run-wechat-pipeline` 也把自己的传进来),所以
报告和那次运行的全部日志能 join 起来。

### Step 3:运行时角色脚本

> 前置知识:[四](#四数据库里的身份与权限)、[五](#五为什么导入用迁移身份粘合二--四)

[ops/provision_runtime_role.py](../../../ops/provision_runtime_role.py),**以迁移身份**在迁移
之后运行:

```bash
RUNTIME_DB_PASSWORD=… python -m ops.provision_runtime_role    # 角色名默认 cssa_app
```

它做的事按顺序:

1. **拒绝几种一看就错的情况**:要建的角色就是自己当前连着的身份;表还不存在(迁移没跑);
   同名角色已存在但带着 `SUPERUSER` / `CREATEROLE` / `CREATEDB` 等高权限属性 —— 那是别人
   的账号,不该被悄悄拿来当运行时角色。
2. **建或改角色**,显式 `NOSUPERUSER NOCREATEDB NOCREATEROLE …`,密码是本地算好的 SCRAM
   校验值。重跑就是改密码,所以轮换密码 = 换一个值再跑一次。
3. **收敛授权**:`CONNECT` 这个库、`USAGE` public schema;对 schema 里所有表和序列
   `REVOKE ALL`;再按 `RUNTIME_TABLE_PRIVILEGES` 逐表授权。
4. **反过来验证它做不到什么**:不能在 schema 里建对象、不能建 schema、不拥有任何关系、不是
   任何其他角色的成员(否则会继承那个角色的权限)。任何一条不满足就整个事务回滚、报错。

第 4 步是这个脚本存在的意义本身:「运行时身份与迁移身份不同」这条完成标准,不是靠名字不同
来满足的,而是靠**运行时身份确实做不了迁移身份做的事**,并且每次运行都当场证明一次。

密码只从环境变量读,不接受命令行参数 —— 命令行参数会进 shell 历史和进程列表。

### Step 4:用真 Postgres 证明权限够、也证明权限不多

> 前置知识:[四](#四数据库里的身份与权限)

本地开发和 CI 都用超级用户连库,所以一条需要某个权限的新代码路径,在所有地方都能跑,**只有
生产会报 permission denied**。[tests/integration/test_runtime_role.py](../../../tests/integration/test_runtime_role.py)
按生产的方式建出角色,然后**用它去驱动真实的 API 代码路径**:

- `check_readiness` 能数到行、报 ready;
- `PGVectorRetriever.search` 能检索到行;
- `get_pipeline_metadata_status` 能读到最近一次运行;
- `record_chat_interaction` 真的写进了一行 —— 这个函数从不抛异常,所以证据只能是那一行存在。
  [四](#四数据库里的身份与权限) 里的 `ON CONFLICT` 坑就是这一条抓出来的。

反方向同样重要:用参数化测试逐条证明它**做不了**迁移做的事(建表、改表、删表、建扩展)、
做不了导入做的事(写、删语料)、也读不了别人的问题。

---

## 上线步骤

> ⚠️ 这一节依赖 #111 的 `infra/`,在它合入之前无法执行。Terraform 的具体改动(新密钥、两个
> 任务定义的接线)随 #111 合入后单独提交;这里写清楚形状和顺序,**顺序是关键**。

**1. 先给已经在库里的那份语料补上坐标。** #111 导入时没有记 hash。补法不是对文件
`sha256sum`,而是**用同一份文件再跑一次导入**,照 #111 的方式在 API 容器里跑 —— 必须趁
API 还连着主用户的时候做,第 4 步之后它就写不了语料了。容器里的 checkpoint 早就没了,所以
它会真的跑一遍。upsert 对内容相同的行什么都不做,于是报告里 `affected_count` 为 0、
`knowledge_base_rows` 等于 `unique_record_count`,**这两个数本身就证明了库里正是这份语料**,
此时的 `corpus_sha256` 就是它名副其实的坐标。

**2. 准备运行时密码。** 本地生成,放进一个手填的 Secrets Manager 密钥(与 #111 对 OpenAI
key 的做法一致,值不经过 Terraform state)。

**3. 让迁移任务同时完成授权。** 迁移任务定义额外注入 `RUNTIME_DB_PASSWORD`,命令改为:

```sh
alembic upgrade head && python -m ops.provision_runtime_role
```

这样每次部署,新表的授权跟着建表的迁移一起落地(前提是同一个提交里改了
`RUNTIME_TABLE_PRIVILEGES`)。脚本是幂等的,每次部署跑一遍无害。

**4. 先跑迁移任务,再切 API。** API 任务定义改为 `DB_USER=cssa_app`、`DB_PASSWORD` 取自
新密钥,同时加上 `CORPUS_SHA256`。**顺序反了**,新 task 会拿着一个库里还不存在的账号去连,
起不来,熔断器回滚 —— 表象又是「连不上库」。

`CORPUS_SHA256` 建议写成 Terraform 变量的默认值提交进仓库,而不是每次 `apply` 时 `-var`
传入:漏传一次,新任务定义里这个变量就没了,fingerprint 悄悄变回 null;而写进仓库,「语料
什么时候换的、换成了哪份」就有了 git 历史。

**5. 核对完成标准:**

```bash
curl -s "$URL/ready" | jq .knowledge_base_rows    # == 报告里的 knowledge_base_rows
aws rds describe-db-instances --query 'DBInstances[].PubliclyAccessible'   # [false]
```

对照 #111 的 `infra/security_groups.tf`,确认没有为导入加过规则;两个任务定义里的
`DB_USER` 不同。

**之后的每一次导入**都以迁移身份跑:用迁移任务定义起一个一次性任务,覆盖命令,并把
cpu / memory 调大 —— 导入要加载嵌入模型,迁移任务那 512MB 装不下。

---

## 测试策略

| 层 | 测什么 |
|---|---|
| 单元(导入) | 报告内容与 `ImportResult` 一致;`corpus_sha256` 等于实际导入记录的指纹、`--limit` 时只覆盖导入的那部分;重复键只期望一行;checkpoint「已完成」而表是空的 → 抛错、报告为 `incomplete`、`--reset-checkpoint` 之后真的重导;报告里没有密码 |
| 单元(脚本) | 短密码在连库之前就被拒;密码缺失、授权失败时的退出码;清单本身的两条策略:语料只读、交互日志只写 |
| 集成(真 Postgres) | 运行时角色走通所有 API 代码路径;参数化证明它做不了七类事;重跑收敛掉手工加的授权并轮换密码;拒绝复用高权限角色、拒绝继承其他角色、拒绝给自己授权;导入报告的行数与 `/ready` 一致,重建后的库被抓出来 |

全部结果:单元 277 通过,集成 29 通过(本地 `docker compose --profile test` 的 pgvector
pg16,与 CI 同一镜像)。集成测试里的角色名每个测试都不同、结束时删除 —— 角色是整个集群的,
不像表那样随库清理。

---

## 已知取舍与未完成

- **Terraform 接线不在本 PR。** 新密钥、迁移任务的命令与注入、API 任务的 `DB_USER` /
  `DB_PASSWORD` / `CORPUS_SHA256` 都改在 #111 的文件里,等它合入后单独提交。在那之前本 PR 的
  代码可以用,但生产上两个身份仍然是同一个。
- **`CORPUS_SHA256` 是手配的环境变量,可能和库里实际的语料漂移。** 有人重导了一份新语料却忘了
  更新变量,之后每一行记录都会带着一个**错的**坐标 —— 比 null 更糟。另一个形状是让导入把
  hash 写进库里、API 从库里读,那样它是按构造正确的。本次按 issue 的设计走环境变量,用「写进
  仓库」来降低漂移概率;真出现过一次漂移,就该换成从库里读。
- **指纹对记录顺序敏感。** 见[三](#三corpus_sha256-是什么的-hash)。
- **本地 compose 的 API 仍用超级用户。** 所以「只有生产报 permission denied」这一类问题只靠
  `test_runtime_role.py` 兜,而它只覆盖它驱动过的代码路径。**加一条碰数据库的新代码路径,就
  在那里加一条。** 让 compose 也按生产的两身份跑是更彻底的做法,但会改变每个人的本地环境,
  没有在这次一起做。
- **核对用的是 ≥ 而不是逐键比对。** 表里如果还有另一份同模型的语料,多出来的行可能掩盖少掉
  的行。v1 库里只有一份语料,两者等价;多源语料进库之后值得改成按键核对。
- **运行时角色能建临时表。** Postgres 默认把 `TEMP` 授给 `PUBLIC`。临时表随会话消失,不影响
  持久的库结构,没有收回。
