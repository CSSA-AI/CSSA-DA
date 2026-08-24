# CSSA-DA RAG / Serving 方向路线图

本文是**查询链路**方向的路线图:retriever → reranker → generator 这条链路的正确性、
可插拔性、可观测性,以及评估工具本身。

- 平台与部署见 [ROADMAP_platform.md](ROADMAP_platform.md)
- 数据与语料、ground truth dataset 见 [ROADMAP_data.md](ROADMAP_data.md)

设计细节见 [eval-dataset.md](../design/planned/eval-dataset.md)(数据集
怎么造)与 [eval-experiments.md](../design/planned/eval-experiments.md)
(实验矩阵与评估口径)。

**每一项属于哪个版本、什么时候做,见 [ROADMAP_versions.md](ROADMAP_versions.md)。**

---

## 这条线的产出是「能力」,不是「成绩」

这一点必须先说清楚,否则整条线看起来像是被数据线卡死了。

|  | 定义 | 被卡吗 |
|---|---|---|
| **能力** | 可插拔的架构、能跑的 eval harness、可观测的成本、正确的接口契约 | ❌ **现在就能做** |
| **成绩** | Recall@10 = 0.72、选定某个模型 | ✅ 必须等 ground truth |

**被 ground truth 卡住的是「调优」,不是「工程」。** 把 RAG 定义成「检索得准」,它
就死锁;定义成「链路正确、快、可插拔、可测量」,它现在有一大堆活,而且这些活决定了
数据线就绪之后**实验是跑四次还是重写三遍**。

> 更根本的一点:所有 RAG 系统里数据质量都压倒模型选择。你们的情况更极端 ——
> **知识库主体(小助手问答)根本还没进库**,现在库里是 2312 篇学生会宣传推文。
> 用户问「语言班什么时候截止」,换任何模型都答不了,因为答案不在里面。这条线做得
> 再好也补不上那个缺口,所以**不要把提升质量的指望放在这条线上**。

---

## 目录

- [大图](#大图)
- [Phase 0:修掉已知缺陷](#phase-0修掉已知缺陷)
- [Phase 1:评估工具](#phase-1评估工具)
- [Phase 2:可插拔的检索方案](#phase-2可插拔的检索方案)
- [Phase 3:生成器行为测试](#phase-3生成器行为测试)
- [Phase 4:可观测性与成本](#phase-4可观测性与成本)
- [Phase 4.5:交互记录](#phase-45交互记录)
- [Phase 5:跑实验、出结论](#phase-5跑实验出结论)
- [Phase 6:上线与持续调优](#phase-6上线与持续调优)
- [与其他两条线的耦合](#与其他两条线的耦合)
- [当前状态速览](#当前状态速览)

---

## 大图

```
Phase 0  修掉已知缺陷        doc_id 链路 / 指标模块合并 / top_k 结构性问题
   │
Phase 1  评估工具            指标纯函数 / 离线 harness / judged fraction / bootstrap
   │
Phase 2  可插拔检索方案      让 A/B/C 之间切换是改配置,不是改代码   ← 最高价值
   │
Phase 3  生成器行为测试      拒答 / 引用格式 / 截断 / 注入防护
   │
Phase 4  可观测性与成本      分阶段延迟 / token / 检索结果落日志 / LangSmith 取舍
   │
Phase 4.5 交互记录           chat_interactions 表 —— 数据线的输血管
   │
   ══════ 以上全部不依赖 ground truth ══════
   │
Phase 5  跑实验、出结论      ⛔ 卡 ROADMAP_data Phase 2
   │
Phase 6  上线与持续调优
```

---

## Phase 0:修掉已知缺陷

**目标**:把现在就知道是错的东西改掉。全部不需要任何数据支撑。

### 0.1 doc_id 链路是断的 ✅

> **已修复**(CSS-7 / [PR #74](https://github.com/CSSA-AI/CSSA-DA/pull/74))。
> 实现与下面的原计划有一处偏离:`knowledge_base` 表里**没有**稳定 id 列可 `SELECT`,
> 所以改为由 [doc_id.py](../../app/services/rag/doc_id.py) 从 `link` **派生**
> —— 微信文章取 `wx_<slug>`,无法识别的链接形状走确定性 hash 兜底并记 warning。
> 效果与验收标准一致:同一 query 两次请求返回同样的 id。
> 下面是当初的问题描述,保留备查。

[pg_retriever.py](../../app/services/rag/retriever/pg_retriever.py) 的 SQL 没有
`SELECT id`,构造 `Article` 时也没传 id;而 [article.py](../../app/schemas/article.py) 的
`id` 是 `default_factory=lambda: str(uuid.uuid4())` —— **每次检索都是全新随机 UUID**。

后果有两个:

- `app/services/rag/eval/*.py` 里所有基于 `r.article.id` 的命中判断永远不成立,
  **现有指标恒为 0**
- [main.py](../../app/main.py) 的 `ChatResponse.sources` 会把整个 `Article`(含那个随机
  UUID)序列化返回 —— **当前每次 `/chat` 响应都在吐一个无意义的随机 id**

- **交付**:SQL 带 `id`,一路传到 `SearchResult`;ID 规则与数据集 `doc_id` 一致
- **验收**:同一 query 两次请求返回同样的 id,且能在语料里查到
- ⏰ **这是公开契约变更,必须赶在平台线上线、前端接入之前** —— 趁现在没有真实客户端,
  改起来零成本

#### 顺带做掉:API 路径加版本前缀

`/chat` → **`/v1/chat`**。理由和上面是同一个:一旦有了消费者(前端团队),响应
schema 的变更就是破坏性的,而**现在还没有任何消费者,是引入版本前缀成本最低的
窗口**。

有了它,以后再遇到 doc_id 这类变更时,可以让 `/v1` 与 `/v2` **并行跑一段**,前端
从容迁移,而不是约时间一起发版。

**两件事绑在同一个 PR 里做** —— 它们是同一个窗口期,分开做等于把前端惊动两次。
发布与版本规范见 [CONTRIBUTING.md](../../CONTRIBUTING.md#5-版本与发布)。

### 0.2 合并两个 evaluator

`RetrieverEvaluator` 和 `RerankerEvaluator` **重复实现了同一套指标**,而且 nDCG 的
gain 写法还不一致(一个用 `rel`,一个用 `2^rel - 1`)。不同口径的数字没法横向比,
而横向比正是评估的全部意义。

顺带的 bug 和缺失:

- `precision_at_k` 除的是 `self.k`,而不是 `min(k, len(results))`
- 缺 **MRR** 和 **hit-rate** —— 本项目多数 query 只有少量相关文档,MRR 比 nDCG 敏感

- **交付**:一个「输入 ranked `doc_id` list + qrels,输出指标 dict」的**纯函数模块**,
  retriever / reranker 共用
- **验收**:单测覆盖边界情况(空结果、结果少于 k、无相关文档、全命中)

### 0.3 `top_k` 的结构性问题

`rag-config.yaml` 现在是 retriever `top_k=5` → reranker `top_k=3`。
**reranker 在 5 个候选里排序基本没有意义** —— 它的价值在于从几十个候选里挑出对的。

这不是「调参」,是结构性错配,不需要 ground truth 就能判断。具体设多少要等
Recall@k 曲线(Phase 5),但现在就该调大到一个合理量级。

- ⚠️ 会显著改变每请求 CPU,与 [ROADMAP_platform](ROADMAP_platform.md) 第 13/14 项
  (worker/扩容策略、资源基线)耦合

### 0.4 reranker 的任务类型是错的

`cross-encoder/ms-marco-MiniLM-L12-v2` 不只是英文模型的问题 —— **ms-marco 训练的是
「query → 长文档段落」,是单一任务类型的模型**。就算换成中文版,单一任务类型这件事
本身就不够。

原理上明确、风险可控,**可以先换,标记为「待 Phase 5 验证」**,不用等尺子。

- ✅ **已决定进 v1**(2026-08-09)—— 理由:平台线是长杆,不做完也上不了线,所以换
  模型的时间成本是免费的
- ⚠️ 别当成已验证的结论 —— 换了之后仍需在 Phase 5 补一个正式对比

#### 选型判据已修订(2026-08-11)

> **原判据**:「本系统主任务是问题 ↔ 问题匹配,要找 **STS / 句对分类型**的
> cross-encoder。」
>
> **这条判据在语料变异构之后不再成立。** 见
> [ROADMAP_data](ROADMAP_data.md#一个必须先说清楚的前提):问答类和文档类会长期
> 并存。而在 [Phase 2.2](#22-三种方案的接口) 的 C 结构下,**cross-encoder 是唯一
> 让两种模态可比的部件** —— 选一个纯 STS 模型等于优化了正在离开的那个世界,并且
> 会亲手把合池重排那个点做坏。

**新判据:在句对和段落两种任务上都不塌。**

- 候选要同时看 `(问题, 问题)` 和 `(问题, 段落)` 两种输入下的表现,**不能只看一种**
- 验证时**两种模态各测一组**,分别记录,不要合成一个平均分 —— 平均分会把「一种
  很好、一种崩了」和「两种都中等」显示成同一个数
- 多语言仍是硬要求(用户提问是中文)
- 体积仍是硬约束:模型进镜像,`/models` 现在 605MB,large 级会冲到 GB 量级,
  Phase 1 的验收基线全部要重测

**换掉 ms-marco 这个动作没有变**,变的是拿什么标准挑替代品。

### 0.5 训练数据用的是随机负例

[qa_dataset.py](../../app/services/rag/reranker/qa_dataset.py) 用
`random.choice(all_answers)` 造负例。随机抽的负例和 query 大概率毫无关系,模型只要
学会「这俩沾边吗」就能把 loss 降下去。但线上 reranker 面对的是 top-50,**这 50 条
全都跟 query 沾边**。这样训出来的模型在真实任务上基本没有增益。

难负例必须从检索器里挖(见 [ROADMAP_data](ROADMAP_data.md) Phase 2.5)。**在训练
数据就绪之前,这个训练脚本不要跑** —— 跑了也是白跑。

### 0.6 first-request 冷惩罚

首个 `/chat` 比稳态慢约 **2.1 秒**。原因不是模型加载(已在 lifespan 预加载),而是
[deps.py](../../app/api/deps.py) 的 `_build_rag_orchestrator` 用 `lru_cache` 懒构建 ——
第一个请求才创建 PG 连接池和三个组件。

在 ECS 上这意味着:新 task 通过 `/ready` 后 ALB 立即导流,**第一个真实用户承担这
2.1 秒**,而 `/ready` 此时已宣称 ready。

- **修法**:在 lifespan 的模型预加载之后同步构建一次 orchestrator
- **验收**:首请求与稳态延迟差 < 200ms;冷启动仍远低于 healthcheck 的 60s
  `start-period`
- 📌 平台线 Phase 2 开工前建议先修,否则会干扰负载测试基线

### 0.7 `stream()` 绕过了链,且另建了一条

[orchestrator.py:55-66](../../app/services/rag/orchestrator.py#L55-L66):

```python
def stream(self, inputs):
    state = (
        LangChainRAGAdapter.retriever_runnable(self.retriever)
        | LangChainRAGAdapter.reranker_runnable(self.reranker)
    ).invoke(inputs)                            # ← 每次调用现建一条新链
    yield from self.generator.stream_text(...)  # ← 完全在链外
```

三个问题:

- **`run()` 用 `self._chain`,`stream()` 用临时拼的另一条链** —— 两条代码路径,改
  一条忘另一条就会静默漂移
- 每次调用重建 runnable(小浪费)
- 任何挂在链上的观测(计时、tracing)对 streaming 请求都会**缺掉生成那一段**

这说明抽象在漏:LCEL 表达不了「前两步同步、第三步流式」,所以只能绕过去。

- **交付**:两条路径共用同一个已构建的链前缀;或者干脆不用 LCEL 表达 streaming
- **验收**:`run()` 与 `stream()` 走同一份 retrieve+rerank 代码

### 0.8 `/chat` 输入体积无上限 🔴

`ChatRequest.chat_history` 既不限单条长度也不限条数,而
`chatgpt_generator._build_messages` 是 `messages.extend(chat_history)` —— 客户端传
什么就原样进 OpenAI 的 messages 数组。**单请求成本无上限**(限流数的是请求数不是
token 数),且可以靠伪造对话历史引导模型。

修法两行,**与前端架构决策无关,现在就该做**。详见
[ROADMAP_platform](ROADMAP_platform.md) 第 19.5 项。

---

## Phase 1:评估工具

**目标**:把 harness 写完并跑通,数据一到就能按下开始。

**前置**:Phase 0.2 ✅ | **不依赖 ground truth** —— 用假数据 fixture 开发和测试

### 1.1 离线检索 harness

语料约 1.7 万篇,而且现有迁移里**没有建 ivfflat / hnsw 索引** —— pgvector 就是精确
全表扫描,所以**用 numpy 在内存里做精确检索与线上行为等价**。

这不是妥协,是刻意选择:harness 不连 Postgres,就不需要为实验做维度迁移或建第二
张表,这条线也就**完全不阻塞平台线**。

- **交付**:`load_dataset()` + 三路召回(dense / dense / BM25)+ 结果落盘
- **验收**:同一配置两次运行结果完全一致(固定随机种子)

### 1.2 指标与健康度

在 0.2 的纯函数模块之上补齐评估口径:

- **分源指标** —— wechat / handbook / assistant_qa 各自的 Recall@k、nDCG@10、MRR@10。
  聚合数字会把不同源上相反的表现平均成无意义的数
- **judged fraction** —— top-k 里被标注过的比例。**< 80% 说明踩到 pool 盲区,该配置
  的数字不可用**
- **配对显著性** —— per-query 配对比较 + bootstrap 置信区间。150 条 query 上几个点
  的差距很可能是噪声
- **同簇去重** —— `top_k` 里同簇的多篇只算一次命中,否则一个簇刷满 top-5 会让
  recall 虚高

- **验收**:能对着假数据产出一份完整报告,含上述全部字段

### 1.3 报告与留痕

- **交付**:每次运行输出 JSON + Markdown 报告到 `data/reports/eval/`,记录配置、
  **语料 sha256**、git sha
- **验收**:任何一份历史报告都能凭 sha256 判断是否可与新结果比较

---

## Phase 2:可插拔的检索方案

**目标**:让架构 A / B / C 之间切换是**改配置**,不是改代码。

**这是本条线现在能做的最高价值的事。** Phase 5 便不便宜,完全取决于这一步做得怎么样
—— 是「跑四次实验」还是「重写三遍」。

### 2.1 一个容易被忽略的耦合

文档侧和查询侧的文本构造**必须成对定义**,但现在它们分散在两个包里:

| 侧 | 位置 | 现在做什么 |
|---|---|---|
| 文档侧 | [knowledge_base_text.py](../../pipelines/embedding/knowledge_base_text.py) | `build_embedding_text = question + "\n\n" + content` |
| 查询侧 | [pg_retriever.py](../../app/services/rag/retriever/pg_retriever.py) | `_encode_query` 直接编码原始 query |

换架构要同时改这两处,而且必须保持一致 —— 改一边不改另一边,是那种**不会报错、
只会让指标莫名其妙变差**的 bug。

所以可插拔的单元不是「模型」,而是**「检索方案」对象:它同时拥有文档侧和查询侧的
文本构造 + 模型 + 是否加 instruction 前缀**。

> ⚠️ 具体的坑:**bge 系列默认是非对称检索模型**,官方文档明确说对称任务不要加
> query instruction 前缀。架构 A 要加、B 不要加 —— 这个开关必须属于「方案」,
> 不能散落在调用点。

### 2.2 三种方案的接口

| 方案 | 文档侧编码什么 | 查询侧 | 索引 |
|---|---|---|---|
| **A** 都当文档 | 全文 | 原始 query + instruction | 单 |
| **B** doc2query | 生成的问题 | 原始 query,无 instruction | 单 |
| **C** 双索引 | 分别按 A/B | 同上 | 双,**合池后联合重排**(见 2.2.1) |

- **交付**:`RetrievalStrategy` 抽象 + 三个实现 + 由 `eval-matrix.yaml` 选择
- **验收 1**:新增一种**方案**不需要改 orchestrator,只加一个类 + 一段配置
- **验收 2**(2026-08-11 新增):新增一个**数据源**不需要改任何代码 —— 只是多一批
  行、多一个 `source` 值、指标表里多一行。见 [2.2.2](#222-源会越来越多索引不能跟着源走)

#### 2.2.1 C 的「合并」必须写死:合池 + 联合重排

原先这一格只写了「cross-encoder 合并」,太含糊 —— 它有两种读法,一种致命:

```
❌  两个索引各出 top-k → 按 bi-encoder 分数排序合并 → 再重排
✅  两个索引各出 top-k → 合成一个候选池 → cross-encoder 对全池联合打分
```

**第一种是坏的,因为分数在两个空间里根本不可比。** 对称模型给 question↔question
打的分**系统性**高于 question→passage,哪怕后者才是更好的答案。按分数合并,QA 行
会稳定压过文档行 —— 而这不是质量差异,是**模态偏置**。它不会报错,只会让文档源
看起来「效果不好」。

第二种绕开了整个问题:cross-encoder 看的是**真实文本对**,输出的是同一个空间里的
分数。**这是全链路里唯一不需要标定就能跨模态比较的地方。**

> ⚠️ **由此产生的硬要求**:C 结构下 cross-encoder 是唯一让两种模态可比的部件,
> 它必须同时吃得下 `(问题, 问题)` 和 `(问题, 段落)`。选一个纯 STS 模型会亲手把
> 这个合并点做坏 —— 见 [0.4](#04-reranker-的任务类型是错的) 的选型判据。

#### 2.2.2 源会越来越多,索引不能跟着源走

**索引按模态建,不按源建。** 模态只有两个且固定,源会持续增长:

```
模态（2 个，固定）        源（N 个，持续增长）
  qa   ←  小助手问答 / 论坛帖子 / CSSA FAQ / …
  doc  ←  handbook / 墨大官网 / Home Affairs / ATO / …
```

于是加第 N+1 个源的成本是:判断模态 → 写进 corpus(doc 多一步切块)→ 指标表多
一行。**不新建索引、不重嵌入、不重调 `top_k`、不改 orchestrator。**

如果让索引跟着源走,每加一个源都要重新决定它和别的源怎么合并 —— 那是一个随源数
平方增长的问题。
- 🔒 **实验期间不要改 `rag-config.yaml`** 里钉住的模型与 revision —— 平台线的镜像
  构建和 `ops/download_models.py` 依赖它稳定。候选写进独立的 `eval-matrix.yaml`

### 2.3 让 harness 与生产共用方案代码

否则你评估的东西和你部署的东西不是一回事。共用的是**文本构造 + 模型选择 +
instruction 开关**;索引层不共用(harness 用 numpy,生产用 pgvector),这是刻意的。

- **验收**:同一个 `RetrievalStrategy` 实例,既能被 harness 调用,也能被
  `PGVectorRetriever` 调用

---

## Phase 3:生成器行为测试

**目标**:验证生成器的**行为契约**。

**不依赖检索 qrels** —— 只需要几十条手工构造的 `(query, 给定上下文, 期望行为)`,
比检索 gold set 便宜一个数量级。

### 3.1 拒答行为 🔴 当前完全没有测试

`rag-config.yaml` 的 system prompt 明确要求「如果资料中没有答案,请说明资料不足,
不要编造」。**这条行为现在一个测试都没有,而它是 RAG 最容易出事的地方。**

- **做法**:给一批**不含答案**的上下文,看它编不编。上下文手工构造、直接喂给
  generator,**不经过检索** —— 测的是生成器的行为契约,不受当前检索质量影响
- **验收**:20 条负样本上,零编造

#### 它是发布关卡,不是 CI 测试(2026-08-10 定)

真跑要调 OpenAI。**钱不是问题** —— 20 条 × gpt-4o-mini 一次全跑是一美分量级。
真正的代价是**非确定性**:flaky test 最终都会被人加 `skip`。所以要限定跑的时机。

它守的不是「模型今天会不会幻觉」,而是**一类具体的改动**:改 system prompt(比如
手滑删掉「不要编造」,或加了 [3.3](#33-一个必须避开的陷阱-) 那句「可以推测」)、
换 generator 模型或版本、改 `context.max_items` / `max_chars_per_item`、换 reranker
导致喂进去的上下文形状变了。这类破坏**不微妙** —— 20 条里会挂一片而不是挂一条,
所以 20 条这个样本量够用。

- 独立 marker,`pytest tests/unit` 与每次 push 的 CI **都不跑**
- 碰 prompt / generator 模型 / context 配置的 PR **必须跑**,结果贴 PR
- 打 tag 发布前跑一次
- 用生产的 `temperature: 0.3`,不为了稳定改成 0 —— 测的就是线上行为
- **判据两条都要**:出现拒答表述 **且** 未出现上下文里不存在的具体事实。只判前
  半句是纸糊的,模型可以先说「资料不足」再编一段

诚实的边界:跑过一次 20/20 **不等于证明幻觉率为 0**,只证明这一版没有明显破坏这条
行为。别拿它当质量指标用。

### 3.2 其他契约

- **引用格式** —— prompt 要求「如资料包含来源和链接,请尽量引用」,需要可验证的判据
- **上下文截断** —— `max_items: 5` / `max_chars_per_item: 2000`,验证截断不会把答案
  切掉
- **prompt 注入** —— 检索到的内容里若含指令性文本,不能被当成指令执行。**这是 RAG
  特有的攻击面**:攻击者只要让一段文字进语料就行
- **语言与语气** —— 中文回答、不跑偏

### 3.3 一个必须避开的陷阱 ⚠️

**不要现在写「为了补偿检索质量」的 prompt。**

现在检索差,你可能想加一句「如果资料看起来不太相关,尝试从中推测」。它现在确实
有用 —— 但等检索修好后,这句会变成**主动的伤害**,让模型在资料明明够好时还去瞎推测。

> **可以现在做**:输出契约类(拒答、格式、语气、结构、注入防护)—— 只取决于 prompt
> 和上下文的**形状**
> **必须等**:任何调节「资料不够好时怎么办」的措辞 —— 它取决于检索的**质量**,
> 而那正是要换掉的东西

---

## Phase 4:可观测性与成本

**目标**:上线前就能回答「慢在哪、花了多少钱、检索回了什么」。

### 4.1 要采什么

- **分阶段延迟** —— retrieve / rerank / generate 各自的 p50 / p95。实测稳态 `/chat`
  均值 2584ms,主要由 OpenAI 生成耗时主导,但需要分解到段才能优化
- **token 计数与成本** —— 直接从 OpenAI 响应的 `response.usage` 取,三行代码,
  **不需要任何框架**
- **检索结果** —— ✅ **已实现**(CSS-15):retrieve / rerank 各记一条结构化日志,
  含 `doc_id` + 分数 + `rank`。两条形状相同,所以 rerank 前后的顺序变化能直接对照。
  只记 id 不记正文,零隐私成本。字段契约与查询方式见
  [retrieval-logging.md](../design/implemented/retrieval-logging.md)
- **reranker 的候选数敏感度** —— cross-encoder 给 50 个候选打分的延迟是硬上线约束,
  直接决定 `top_k` 上限
- **query 不进日志**(2026-08-10 修订,✅ 已实现于 CSS-15)——
  [orchestrator.py](../../app/services/rag/orchestrator.py) 的
  `"Starting RAG pipeline for query: %s"` 已去掉 query(而不是改成
  `extra={"query": ...}`)。当初的决策理由保留在下面备查。

  原先的写法是为了用 CloudWatch Insights 挖真实 query。但 [Phase 4.5](#phase-45交互记录)
  的 `chat_interactions` 落地之后,**Postgres 才是更好的挖掘面**:能 SQL 查、能 join
  `knowledge_base`、带 `config` 指纹、反馈到了能 UPDATE 回同一行、保留期由我们自己定。
  日志则要按扫描量计费,且没有前四项。

  两边都写 query = 同一份用户内容落在两个地方、两套保留期、两个访问控制面 —— 而本节
  「只记 id 不记正文,零隐私成本」这句话只有在日志里真的没有正文时才成立。

  **分工**:日志记 `request_id` + `doc_id` + `score` + `rank`,负责排障;
  `chat_interactions` 记 query / answer,负责分析。`request_id` 是两边的 join key,
  它已经在响应头里,也已经是 `chat_interactions` 的主键。

### 4.2 关于 LangChain / LangSmith

**现状**:[orchestrator.py](../../app/services/rag/orchestrator.py) 里的链**是真的 LCEL 链**
—— 三个 `RunnableLambda` 用 `|` 组合,`invoke()` 走 LangChain 运行时。而且
**`langsmith` 包已经在生产镜像里**(`langchain-core` 1.5.1 是 api group 依赖,传递
依赖了 `langsmith` 和 `langchain-protocol`)。开 tracing 只需要几个环境变量。

**但对本项目,LangSmith 只能兑现一半价值:**

| 能力 | 对我们 |
|---|---|
| Trace 调试(看到检索回了什么、prompt 长什么样) | ✅ **最实际的收益** |
| 反馈 → 数据集curation | ✅ 但要等有真实用户 |
| Prompt 版本管理 | ⚠️ 会让生产行为脱离 git,不建议 |
| **token / 成本追踪** | ❌ **拿不到** —— generator 直接用 OpenAI SDK 而非 `ChatOpenAI`,LangSmith 只看到一个返回字符串的普通函数 |
| **检索模型选型** | ❌ 它的 evaluator 是 LLM-as-judge 那一路,没有 Recall@50 / nDCG / judged fraction 这套 IR 指标;标注界面也是 run 级反馈,不适合 (query, doc) 对的分级判定 |

**一句话:LangSmith 是个不错的调试器,但不是我们缺的那把尺子。** Phase 1/2/5 那些活
该自己写还得自己写。

#### 决定:开发环境开,生产默认不开

- **开发 / 本地**:用测试数据开 tracing,拿它的调试价值(收益最大、风险最小)
- **生产**:走 4.1 的方案 —— 自己的计时 + 结构化 JSON 日志 → CloudWatch,数据不出
  自己的账户

**若将来要在生产开,采用「只 trace 结构、不 trace 内容」**:

- 保留:每步耗时、检索回的 `doc_id` + 分数、rerank 前后顺序变化、错误
- 掩掉:query 原文、文档正文、生成的回答

这几乎不损失调试能力(看到 doc_id 和分数就能判断检索对不对,要看正文自己去库里查),
同时把暴露面降到接近零。另外 dev / prod 分成两个 project,并设置保留期。

#### 隐私:两个常见误解

- ❌「反正发给 OpenAI 也被拿去训练了」—— **OpenAI API 默认不用客户数据训练模型**
  (与 ChatGPT 消费版是两套政策),数据保留约 30 天用于滥用监控后删除。所以开
  LangSmith 不是「再泄一次」,是第一次。
- 真正的差别不在厂商,在两点:**① 保留期** —— OpenAI 约 30 天删,LangSmith trace
  持久保存(那是产品的意义);**② 可浏览性** —— OpenAI 那边团队谁都看不到,
  LangSmith 是可搜索的网页界面,**项目里任何有登录权限的人都能翻**。小助手接的是
  新生求助(签证被拒、挂科、经济困难),开了全量 trace 等于给这些内容建了一个社团
  内部可搜索的存档。风险不在第三方,在自己的访问控制。

> 📌 **若决定在生产开**:已定的隐私声明措辞是「用于分析」,需要补上第三方平台这一
> 项,否则声明与实际做法对不上。见 [ROADMAP_platform](ROADMAP_platform.md) Phase 5
> 第 1 项「定义 metadata 隐私规则」。

#### adapter 值不值:买的是期权

三个 `RunnableLambda` 做的事等价于顺序调用三个函数,而 `stream()`
(见 [0.7](#07-stream-绕过了链且另建了一条))已经证明这层抽象表达不了真实需求。

**它的实际价值是期权** —— 将来想开 LangSmith 时几个环境变量就行;代价是三个传递
依赖进了辛苦瘦身过的镜像。这笔交易可以接受,但要清楚**买的是期权而不是功能**。
如果确定生产不会用 LangSmith,去掉这层能让链路更直白,`stream()` 的双路径问题也
自然消失。

---

## Phase 4.5:交互记录

**目标**:让上线之后产生的真实问答**不白白流走**。

**这是数据线的输血管**。[ROADMAP_data](ROADMAP_data.md) 整条线最难的就是「真实
query 从哪来」—— 闭卷编写、按簇抽取、担心合成数据泄漏,全都是因为没有真实流量。
`/chat` 一上线就开始产生真实 query。

> **一个不对称**:反馈、看板、隐式信号全是加法,哪天想做就做;但**没记下来的
> query 是找不回来的**。所以记录本身要早,分析可以晚。

### v1 最小版本:6 列

```sql
CREATE TABLE chat_interactions (
    request_id  TEXT PRIMARY KEY,        -- 已有的 X-Request-ID
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    query       TEXT NOT NULL,
    answer      TEXT,
    retrieved   JSONB,                   -- [{doc_id, score, rank}]
    config      JSONB                    -- 配置指纹,见下
);
```

- 用 FastAPI 的 **`BackgroundTasks` 写入**,响应发出后再写,不给 `/chat` 加延迟。
  写失败只记日志,绝不抛出去影响用户。
  ⚠️ **失败那条日志要带完整 payload(含 query)** —— 这是 query 唯一被允许进日志的
  地方。正常路径下 query 只进 Postgres(见 [4.1](#41-要采什么)),但 DB 抖动的那几
  分钟如果连日志也不记,这批 query 就是真的找不回来了
- 存 **Postgres 而不是只靠日志**:反馈是后到的、要 UPDATE 回同一行;要和
  `knowledge_base` join;量很小(社团级每天几百条);`pipeline_runs` 表已是同样性质
  的先例

### `config` 指纹别省 —— 最容易漏、漏了最贵

```json
{
  "embedding_model": "...", "embedding_revision": "...",
  "reranker_model": "...", "reranker_revision": "...",
  "generator_model": "gpt-4o-mini",
  "top_k": 5, "rerank_top_k": 3,
  "prompt_version": "...",
  "corpus_sha256": "...",
  "git_sha": "..."
}
```

五行代码的事,但**没有它,半年后你分不清哪条记录是换 reranker 之前还是之后产生
的**,整批数据的比较价值就没了。

`corpus_sha256` 把线上日志和离线评估数据集**统一到同一把尺子上**。

### 依赖

⚠️ **`retrieved` 这一列的价值依赖 [0.1](#01-doc_id-链路是断的-) 修好** —— 否则记下
来的是一堆随机 UUID。两件事绑在一起做。

### 后续扩展(全部是 nullable 加列,零风险)

> 「nullable 加列」不只是省事 —— 它满足
> [ROADMAP_platform](ROADMAP_platform.md#111-硬规则每个-migration-必须向后兼容上一版代码)
> 第 11.1 项的硬规则:**migration 执行后上一版代码必须仍能工作**。加表和加可空列
> 都安全,单次部署即可;删列 / 改类型 / 加 NOT NULL 则必须拆成两次部署。

| 何时加 | 加什么 |
|---|---|
| 有前端了 | `POST /feedback` + `feedback` / `feedback_at` / `feedback_note` 列。钩子已经现成 —— `X-Request-ID` 已在响应头且对前端暴露 |
| **走 BFF 的话** | `user_id` 列 —— 内测期最有价值的是**能追到具体的人去问「这个回答哪里不好」**,比任何自动化信号都准。取决于 [ROADMAP_platform](ROADMAP_platform.md) 第 19 项的架构决策 |
| 想看多轮行为 | `ChatRequest` 加 `session_id` + `turn_index`。可捕捉**最强的隐式负反馈**:同一会话里换个说法又问一遍 = 上一轮失败了 |
| 开始关心账单 | `token_usage`(在此之前 OpenAI 后台够看) |
| 要做飞轮 | `refused` —— 是否触发了「资料不足」,即知识库缺口的直接信号 |
| 想复盘 reranker | `retrieved` 里同时记 rerank **前后**两个阶段 |

> **关于契约变更的截止**:`session_id` 是**请求体新增可选字段,后加完全向后兼容**,
> 老客户端不传即可 —— 它**没有**硬截止。**上线前必须完成的契约变更只有
> [0.1](#01-doc_id-链路是断的-) 一条**,因为它改的是响应体里已有字段的语义。

### 数据后面喂给谁

| 数据 | 去向 |
|---|---|
| 真实 query | eval set 的 `origin: human_log`;也是验证「闭卷编写可不可信」的对照组 |
| `refused` 的 query | 知识库缺口清单 → 让小助手回答 → 变成新 KB 条目(飞轮) |
| 点踩 + `retrieved` | 检索失败案例;补进 pool 重标 |
| 检索到但被点踩的文档 | 训练用的难负例 |
| `config` + 指标 | 线上表现与离线 eval 的一致性校验 |

### ⛔ 一条红线

**不要把系统自己生成的回答写回知识库。**

小助手的回答可以入库 —— 那是**真人**的新信息。但系统生成的答案是从语料里推出来的,
写回去等于自我引用:不增加信息,只增加一层改写过的重复内容;而且一旦某次答错就被
固化进语料,以后不断被检索出来强化。这是 RAG 的一个已知坍缩模式。

`chat_interactions` 是**分析用的,不是语料源**。要用它改进知识库,路径是
「发现缺口 → **人**来回答 → 人的答案入库」,中间必须有人。

---

## Phase 5:跑实验、出结论

⛔ **前置:[ROADMAP_data](ROADMAP_data.md) Phase 2 完成(gold set 就绪)**

这是唯一被数据线卡住的 phase。

```
5.1  baseline(当前线上配置)              ← 必须有,否则后面的数没有参照系
5.2  doc2query pilot(200 篇,按源分层)
5.3  2×2 网格:A1 / A2 / B1 / B2          ← 离线,一格几分钟
5.4  看分源结果 → 决定要不要做 C
5.5  reranker 单独一轮(固定候选池,只比提升量 Δ)
5.6  用 Recall@k 曲线定 top_k
```

**5.3 为什么是网格不是一条线**:直接跳到 B 会同时改架构和模型,赢了也不知道是哪个
带来的。纵向比得到架构的贡献,横向比得到模型的贡献。

**5.4 的 C 是条件分支**:B 若全面领先就直接用 B;只有「B 在问答对上赢、A 在
handbook 上赢」才需要 C。

- **验收**:胜出配置相对 baseline 的提升**经过 bootstrap 检验显著**,且 judged
  fraction ≥ 80%

---

## Phase 6:上线与持续调优

- **落 schema** —— 维度迁移 / 建表 / 镜像重测。这是与平台线的收敛点,
  见 [ROADMAP_data](ROADMAP_data.md) Phase 5
- **线上抽样比对** —— 线上结果与离线 eval 是否一致。不一致说明 harness 与生产有偏差
- **prompt 精调** —— 这时候才轮到「资料不够好时怎么办」那类措辞
- **reranker PEFT / LoRA** —— 训练数据来自 [ROADMAP_data](ROADMAP_data.md) Phase 2.5
  的真实难负例

---

## 与其他两条线的耦合

| # | 事项 | 本线 | 对方 |
|---|---|---|---|
| 1 | `doc_id` 链路 | [0.1](#01-doc_id-链路是断的-) | 改 `/chat` 响应体 → **平台上线前** |
| 2 | first-request 冷惩罚 | [0.6](#06-first-request-冷惩罚) | 平台 Phase 2 开工前 |
| 3 | `top_k` 调大 | [0.3](#03-top_k-的结构性问题) / [5.6](#phase-5跑实验出结论) | 平台第 13/14 项资源基线 |
| 4 | 模型选型结论 | [Phase 5](#phase-5跑实验出结论) | 平台的向量维度 / 镜像大小 / ECS 规格 |
| 5 | gold set | [Phase 5](#phase-5跑实验出结论) ⛔ | **数据线 Phase 2** |
| 6 | 训练用难负例 | [0.5](#05-训练数据用的是随机负例) / [Phase 6](#phase-6上线与持续调优) | 数据线 Phase 2.5 |
| 7 | query 结构化日志 | [Phase 4](#phase-4可观测性与成本) | 数据线 Phase 6 挖掘日志 |
| 8 | `chat_interactions` 表 | [Phase 4.5](#phase-45交互记录) | 需一条 Alembic 迁移(平台线);产出喂给数据线 Phase 6 |
| 9 | LangSmith 隐私规则 | [Phase 4.2](#42-关于-langchain--langsmith) | 平台线 Phase 5 第 1 项 |

**三条线的依赖不对称**:

```
Platform  ←  无外部依赖,自己能跑完
Data      ←  外部依赖最多(导出途径、隐私授权、跨部门对接)  ← 关键路径
RAG       ←  Data(仅 Phase 5 起)
```

**数据线既是关键路径,又是唯一要等别人的那条**,应该最早启动、推得最狠。

---

## 当前状态速览

| Phase | 依赖 ground truth | 状态 |
|---|---|---|
| **0.1** doc_id 链路 + `/v1/chat` | ❌ | ✅ 已完成 —— doc_id (CSS-7 #74)、`/v1/chat` (#73) |
| **0.2** 合并 evaluator | ❌ | 🔴 未开始 |
| **0.3** `top_k` 结构性 | ❌ | 🔴 未开始 |
| **0.4** 换 reranker | ❌ | 🔴 未开始 —— **✅ 已定进 v1**(待 Phase 5 验证) |
| **0.5** 随机负例 | ❌ | 🟡 训练脚本暂不要跑 |
| **0.6** 冷惩罚 | ❌ | 🔴 未开始 |
| **0.7** `stream()` 双路径 | ❌ | 🔴 未开始 |
| **0.8** 输入体积无上限 | ❌ | 🔴 未开始 —— **v1 必做**,两行 |
| **Phase 1** 评估工具 | ❌ | ⬜ 未开始 |
| **Phase 2** 可插拔方案 | ❌ | ⬜ 未开始 —— **价值最高** |
| **Phase 3** 生成器行为 | ❌ | ⬜ 未开始 |
| **Phase 4** 可观测性 | ❌ | 🟡 部分完成 —— 检索日志已落(CSS-15);分阶段延迟、token / 成本未做 |
| **Phase 4.5** 交互记录 | ❌ | ⬜ 未开始 —— **上线即开始产生真实 query** |
| **Phase 5** 跑实验 | ✅ | ⛔ 卡数据线 Phase 2 |
| **Phase 6** 上线调优 | ✅ | ⬜ 未开始 |

**Phase 0–4 全部不依赖 ground truth**,现在就能做。

---

## 一句话提醒比例

这几份文档产出了大量设计。对一个学生社团项目,**要小心别把 eval 建设本身做成了项目**。

最小可信版本不大:小助手数据进库 + 80–100 条 gold query + 跑一轮对比,**两周量级**。
文档里那些完整形态(bootstrap 置信区间、kappa 双标、pool_miss 补标)是「做对」的
样子,但时间紧就**先跑通一遍粗糙的、再逐步加严**。

判断标准很简单:**如果一个环节不影响「A 和 B 哪个好」的结论,就可以先跳过。**
