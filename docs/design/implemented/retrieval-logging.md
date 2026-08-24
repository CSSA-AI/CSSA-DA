# 检索日志 —— 设计说明

RAG 链路的 retrieve / rerank 两段各记一条结构化日志,记 `doc_id` + 分数 + 排名,
**不记任何用户内容**。对应 issue CSS-15,设计依据
[ROADMAP_rag.md Phase 4.1](../../roadmap/ROADMAP_rag.md)。

本文只讲这一层。它依赖的 JSON 日志基础设施(formatter、`request_id` 中间件、
`STRUCTURED_FIELDS` 白名单)在
[chat-api-hardening.md](chat-api-hardening.md) 里已经讲过,本文直接引用。

---

## 目录

- [背景](#背景)
- [大图:一条查询在日志里留下什么](#大图一条查询在日志里留下什么)
- [基础知识](#基础知识)
  - [一、为什么用户内容不能进日志](#一为什么用户内容不能进日志)
  - [二、join key:把两个存储面缝起来](#二join-key把两个存储面缝起来)
- [字段契约](#字段契约)
- [实现:为什么埋在 adapter 层](#实现为什么埋在-adapter-层)
- [怎么用它排障](#怎么用它排障)
- [测试策略](#测试策略)
- [已知边界](#已知边界)

---

## 背景

改之前,整条 RAG 链路只有两行日志:

```python
logger.info("Starting RAG pipeline for query: %s", query)
...
logger.info("Generated response successfully.")
```

**检索回了什么,一个字都没记。** 线上出现一个坏回答,能拿到的只有 query 和
「成功了」。而检索 / 重排 / 生成三段的失败长得完全一样 —— 「召回就没捞到」和
「捞到了但被 reranker 排下去了」是两种完全不同的修法,不分段就区分不了。线上问题
往往重现不了,所以「重现一遍看看」不是可行的排障路径。

同时,第一行把 **query 原文**拼进了日志 message。上 ECS 之后这会自动进 CloudWatch。

所以这次改动是两件事,一件加一件减:

- **加**:retrieve / rerank 各记一条结构化日志,含 `doc_id` / `score` / `rank`
- **减**:把 `Starting RAG pipeline` 那行里的 query 去掉

---

## 大图:一条查询在日志里留下什么

```
POST /v1/chat  {"message": "how do I apply for oshc"}
     │
     ├─ RequestContextMiddleware ── 生成 request_id,绑进 ContextVar
     │
     │   ┌─────────────── RAG 链路 ───────────────┐
     ├──▶│ orchestrator.run()                     │──▶ 日志① "Starting RAG pipeline"
     │   │   │                                    │        (无 query)
     │   │   ├─ retrieve  ──────────────────────  │──▶ 日志② stage=retrieve
     │   │   │                                    │        results=[{doc_id,score,rank}...]
     │   │   ├─ rerank    ──────────────────────  │──▶ 日志③ stage=rerank
     │   │   │                                    │        results=[{doc_id,score,rank}...]
     │   │   └─ generate  ──────────────────────  │──▶ 日志④ "Generated response successfully."
     │   └────────────────────────────────────────┘
     │
     └─ 中间件出口 ──────────────────────────────────▶ 日志⑤ access log
                                                          method/path/status_code/duration_ms
     ▼
响应头 X-Request-ID: e25acbd1-...
```

**五条日志带同一个 `request_id`,且和响应头里的值相同。** 这是整个设计的支点 ——
日志里没有 query、没有正文、没有答案,能把这条链路认回某一次具体对话的,只有它。

真实输出(测试环境实测,顺序即发生顺序):

```json
{"level":"INFO","message":"Starting RAG pipeline","request_id":"e25acbd1-..."}
{"level":"INFO","message":"Retrieved candidates","request_id":"e25acbd1-...","stage":"retrieve",
 "results":[{"doc_id":"wx_a","score":0.9,"rank":1},{"doc_id":"wx_b","score":0.8,"rank":2}]}
{"level":"INFO","message":"Reranked candidates","request_id":"e25acbd1-...","stage":"rerank",
 "results":[{"doc_id":"wx_b","score":0.95,"rank":1}]}
{"level":"INFO","message":"Generated response successfully.","request_id":"e25acbd1-..."}
{"level":"INFO","message":"request completed","request_id":"e25acbd1-...",
 "method":"POST","path":"/v1/chat","status_code":200,"duration_ms":2584.0}
```

对照日志②和③就能看出 reranker 干了什么:`wx_b` 从第 2 名升到第 1 名,`wx_a` 被截掉。
**这是「记两条而不是一条」的全部理由** —— 只记最终结果,你只知道 generator 拿到了
什么,不知道它是怎么变成这样的。

---

## 基础知识

> 前置基础:[logging 三层结构](chat-api-hardening.md#3-python-logging-的三层结构)、
> [LogRecord 是什么](chat-api-hardening.md#5-logrecordrecord是什么)、
> [ContextVar 与 token](chat-api-hardening.md#6-contextvar-与-token)、
> [`AppJsonLogFormatter`](chat-api-hardening.md#appjsonlogformatter)。

### 一、为什么用户内容不能进日志

**这个 cluster 回答:明明日志里放 query 排障更方便,为什么偏不。**

最自然的写法就是把 query 放进去 —— 出问题时一眼看到用户问了什么。原先那行
`"Starting RAG pipeline for query: %s"` 正是这个思路,当初的动机是用 CloudWatch
Insights 挖真实 query 分布。

问题不在于「日志不安全」,而在于**同一份用户内容会落在两个地方**。项目规划里
`chat_interactions` 表(CSS-17)本来就要存 query 和 answer。两边都写的后果:

| | CloudWatch 日志 | `chat_interactions` 表 |
|---|---|---|
| 保留期 | 按 log group 配置,另一套 | 我们自己定 |
| 访问控制 | 有 AWS 控制台权限的人 | 有库权限的人 |
| 能不能 SQL 查 | ❌ 按扫描量计费的全文检索 | ✅ |
| 能不能 join `knowledge_base` | ❌ | ✅ |
| 拿到用户反馈后能不能 UPDATE 回同一行 | ❌ | ✅ |

**Postgres 在每一项上都更合适。** 所以分工是:**日志负责排障,表负责分析。**

而且这不只是「哪个更方便」的问题。ROADMAP 里「只记 id 不记正文,零隐私成本」这句
承诺,**只有在日志里真的没有正文时才成立**。小助手接的是新生求助(签证被拒、挂科、
经济困难),多一个可搜索的副本就多一个暴露面。

**取舍**:放弃了「用日志挖 query 分布」这个能力。可接受,因为 `chat_interactions`
会把这个能力以更好的形式还回来。代价是在它落地之前(CSS-17),query 分布暂时无处可查。

### 二、join key:把两个存储面缝起来

**这个 cluster 回答:内容和链路分开存了,怎么再拼回去。**

既然 query 在 Postgres、检索链路在 CloudWatch,就需要一个两边都有的值把它们对上。
这就是 `request_id`:

- 它**已经**在响应头 `X-Request-ID` 里(中间件加的)
- 它**已经**是 `chat_interactions` 的主键(CSS-17 的设计)
- 它由 `bind_request_id` 绑进 ContextVar,formatter 自动读出来 —— **所以链路深处的
  orchestrator 和 adapter 一行都不用改**就带上了它

排障路径因此变成两步:**先在日志里按 `request_id` 拿到检索链路,再回库拿 query 和
answer。** 需要看文档正文?`doc_id` 直接去 `knowledge_base` 查。

这也解释了一个容易被忽略的点:**`request_id` 断了,这批日志就整体失效。** 不是
少一个字段,是从「能定位到某次对话」退化成「一堆匿名的 doc_id」。所以它值得被测试
单独守住(见[测试策略](#测试策略))。

---

## 字段契约

两条日志形状完全相同,靠 `stage` 区分:

| 字段 | 类型 | 说明 |
|---|---|---|
| `stage` | `"retrieve"` \| `"rerank"` | 哪一段产生的 |
| `results` | array | 该段的输出,**数组顺序即该段的排序结果** |
| `results[].doc_id` | str | 文档 id,取自 `SearchResult.article.id`。微信文章为 `wx_<slug>`,由 [doc_id.py](../../../app/services/rag/doc_id.py) 从 `link` 派生(CSS-7);无法识别的链接形状走 `kb_<hash>` 兜底 |
| `results[].score` | float | 该段自己的分数 —— 两段的分数**不可比**(见下) |
| `results[].rank` | int \| null | 该段内的排名,1-based |

三个契约细节:

**1. 两段的 `score` 语义不同,不要跨段比较。** retrieve 的分数是向量距离取负
([pg_retriever.py](../../../app/services/rag/retriever/pg_retriever.py)),
rerank 的是 cross-encoder 的输出
([cross_encoder_reranker.py](../../../app/services/rag/reranker/cross_encoder_reranker.py))。
同一篇文档两段分数不一样是正常的,上面样例里 `wx_b` 从 0.8 变 0.95 就是这样。

**2. `rank` 是各段内部重新编号的,都从 1 开始。** reranker 在截断后会重排一遍
`rank`,所以它不是「原始检索名次」。**要看顺序变化,对照两条日志的 `doc_id` 序列,
不要看 `rank` 数值。**

**3. 空结果会记成 `"results": []`,不会被省略。** formatter 的白名单过滤条件是
`is not None`,空数组是 falsy 但不是 `None`。这是有意的 —— 「检索一条都没返回」
恰恰是最需要在日志里看见的情况。

**新增字段要同步改白名单。** `AppJsonLogFormatter` 只输出
[`STRUCTURED_FIELDS`](../../../app/core/logging.py) 里列出的字段,不在白名单里的
`extra` 会被静默丢弃 —— 不报错,只是字段消失。`stage` 和 `results` 就是为此加进去的。

> ⚠️ `extra` 里不能用 `message` / `args` / `name` 这类 `LogRecord` 已占用的 key,
> 会直接抛 `KeyError`。这也是字段叫 `stage` 而不是 `name` 的原因。

---

## 实现:为什么埋在 adapter 层

日志点在
[langchain_adapter.py](../../../app/services/rag/adapters/langchain_adapter.py) 的两个
runnable 里,每段跑完立刻记一条。

**为什么不在 orchestrator 里统一记**:链路是
`retrieve | rerank | generate` 的 LCEL 组合,`invoke()` 返回的最终 state 里
`search_results` **已经被 rerank 覆盖了** —— orchestrator 拿不到 retrieve 阶段的
原始输出。要在那一层记两段,就得把链路拆开跑,等于放弃 LCEL 组合。

**代价**:观测逻辑绑在了 adapter 这个「LangChain 翻译层」上。ROADMAP 4.2 讨论过
adapter 是一个「期权」—— 哪天真换掉 LangChain,这两条日志要跟着搬。

**替代方案**:LangChain callback handler。更「正统」,但同样绑 LangChain,而且要
理解 callback 的生命周期才能读懂日志从哪来。当前写法直白得多,在链路只有三段的
规模下,这个直白更值钱。

**顺带**:`stream()` 复用同一套 runnable,所以流式路径自动也有日志,不需要单独埋点。

---

## 怎么用它排障

**追一次具体请求**(已知 `request_id`,例如从用户报错截图的响应头里拿到):

```
fields @timestamp, message, stage, results, status_code, duration_ms
| filter request_id = "e25acbd1-643a-4b7b-80f7-457c5070c3ca"
| sort @timestamp asc
```

拿到的就是上面「大图」里那五行。对照日志②③判断是召回问题还是重排问题,再拿
`request_id` 回 `chat_interactions` 取 query 和 answer,拿 `doc_id` 回
`knowledge_base` 取正文。

**找「什么都没召回」的请求**:

```
fields @timestamp, request_id
| filter stage = "retrieve" and isempty(results)
```

> CloudWatch Insights 会把嵌套 JSON 数组扁平化成 `results.0.doc_id` 这样的字段名。
> 按具体某篇文档筛选时需要注意这一点,上线后建议实测一次再固化查询语句。

---

## 测试策略

分两层,因为这套日志的正确性有两种完全不同的失效方式。

**单元层 —— 记了什么**
([test_langchain_adapter.py](../../../tests/unit/test_langchain_adapter.py)、
[test_orchestrator.py](../../../tests/unit/test_orchestrator.py),5 个测试):
断言 `doc_id` / `score` / `rank` 的值和顺序符合预期,且 payload 里不含 query。
rerank 那个测试特意让 dummy 返回和检索**不同的顺序**,以证明日志反映的是该段自己的
输出顺序。

**请求层 —— 串没串起来**
([test_retrieval_logging.py](../../../tests/unit/test_retrieval_logging.py),3 个测试):
起一次真实的 `/v1/chat`(真 orchestrator + 假三件套),断言
① 两条 stage 日志都在且内容正确,
② **五条日志的 `request_id` 彼此相同、且等于响应头的值**,
③ 格式化后的整份输出不含 query 原文 / 文档正文 / 生成的回答。

**为什么第二层非要有**:单元测试断言的是 `LogRecord` 的属性,`request_id` 却是
中间件绑进 ContextVar、formatter 在**格式化时**读出来的。链路一旦断了 —— 比如
`/v1/chat` 改成 `async def` 把 pipeline 丢进 executor、或者 `bind_request_id` 挪了
位置 —— 日志照记不误,只是**悄悄不再可 join**,单元测试一个都不会红。

这三个测试用变异测试验证过确实能抓到回归:把 query 加回 orchestrator、让中间件不再
bind、从白名单里删掉 `results`,三种改法各自只挂掉对应的那一个测试。

请求层的测试断言的是**格式化后的 JSON 字符串**而不是 `LogRecord` 属性,所以顺带
覆盖了 formatter 和白名单本身。

---

## 已知边界

**1. `chat_interactions` 还不存在(CSS-17)。** 在它落地之前,`request_id` 只能把日志
内部串起来,回查 query / answer 的那一半还接不上。**这段时间 query 分布无处可查** ——
这是[基础知识一](#一为什么用户内容不能进日志)里那个取舍的现金代价。

**2. Phase 4 其余部分未做。** 分阶段延迟(retrieve / rerank / generate 各自的
p50 / p95)、token 计数与成本都还没有,见
[ROADMAP_rag.md Phase 4.1](../../roadmap/ROADMAP_rag.md)。当前只有整个请求的
`duration_ms`(access log 里)。
