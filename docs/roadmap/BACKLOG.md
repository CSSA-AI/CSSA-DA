# 初始 Backlog —— Linear 导入清单

本文是三条 roadmap 的一个**视图**:把所有条目按「是否被阻塞」和优先级摊平,方便一次性
导入 Linear。

> ⚠️ **本文只在首次导入时是事实源。** 一旦 issue 进了 Linear,**状态以 Linear 为准**,
> 本文不再更新 —— 否则两边必然分叉。设计细节永远在
> [roadmap](.) 和 [design](../design/) 里,Linear issue 只放链接,不复制内容。

| 线 | 详细内容 |
|---|---|
| 平台与部署 | [ROADMAP_platform.md](ROADMAP_platform.md) |
| 数据与语料 | [ROADMAP_data.md](ROADMAP_data.md) |
| 查询链路与评估 | [ROADMAP_rag.md](ROADMAP_rag.md) |
| 版本边界 | [ROADMAP_versions.md](ROADMAP_versions.md) |

---

## 优先级口径

| 级别 | 含义 |
|---|---|
| **Urgent** | v1 必须,且有硬截止(契约变更 / 账单风险) |
| **High** | v1 必须 |
| **Medium** | 不在 v1,但现在做有回报、无阻塞 |
| **Low** | 无阻塞,可以等 |
| **Backlog(blocked)** | 有明确阻塞源,不放 Todo |

**blocked 的一律放 Backlog,不放 Todo** —— 这样 Todo 始终等于「现在真能领的活」,
自助领任务时不会领到干不了的。

---

## Urgent

| Title | Track | Size | 出处 |
|---|---|---|---|
| Add a BFF proxy endpoint in myCSSA (Django) | platform | 1d | Platform 19.7 —— 前端仓库是 Django + **public**，走 BFF 已定 |
| Fix doc_id chain and add `/v1/chat` prefix | rag | 1d | RAG 0.1 —— 契约变更,须赶在前端接入前 |
| Cap `/chat` input size (`chat_history` length + item count) | rag | 1h | RAG 0.8 / Platform 19.5 —— 并进上一条 |
| Set OpenAI hard spend cap + global rate limit | platform | 0.5d | Platform 19.4 —— 唯一兜住账单的东西 |
| Switch rate-limit key from IP to `X-User-Id` (fall back to IP when absent) | platform | 0.5d | 第 16 项 —— BFF 的必然要求 |
| Add `user_id` column to `chat_interactions` | rag | 0.5d | RAG 4.5 |

## High(v1)

| Title | Track | Size | 出处 |
|---|---|---|---|
| IaC skeleton: VPC / subnet / SG / ECR / IAM OIDC | platform | 1–2w | Phase 2 |
| Provision RDS PostgreSQL + pgvector | platform | 1w | 第 17 项 |
| ECS service + ALB + health check wiring | platform | 1w | 第 8 项 |
| Migration as a deployment gate (+ backward-compat rule) | platform | 3d | 第 11 / 11.1 项 |
| Outbound networking for OpenAI | platform | 2d | 第 12 项 |
| Resource baseline for ECS task sizing | platform | 3d | 第 14 项 |
| Re-scrape handbook (1589 subjects missing, only A–F covered) | data | 3d | Data 0.1 |
| Investigate 小助手 export path (confirm account type first) | data | 1–2w | Data 0.2 —— **blocks 整条数据线** |
| Decide WeChat article role in the KB: (a)/(b)/(c) | data | 决策 | Data 0.3 |
| Refusal-behaviour test suite (20 negative cases, zero fabrication) | rag | 3d | RAG 3.1 |
| `chat_interactions` table (6 columns) + BackgroundTasks write | rag | 3d | RAG 4.5 |
| Log retrieved doc_ids + scores in structured logs | rag | 1d | RAG 4.1 |
| Fix first-request cold penalty (~2.1s) | rag | 0.5d | RAG 0.6 |
| Raise retriever `top_k` off the current 5 | rag | 0.5d | RAG 0.3 |
| Swap reranker to an STS / sentence-pair model | rag | 3d | RAG 0.4 |

## Medium

| Title | Track | Size | 出处 |
|---|---|---|---|
| **Blind-authored eval queries — 15 per person** | data | 1–2h/人 | Data 2.2 —— 拆成 N 个子 issue,谁想做谁领 |
| Draft annotation guideline (0/1/2 + 时效性 + 跨源竞争) | data | 3d | Data 2.1 |
| Merge the two evaluators into one pure-function metrics module | rag | 2d | RAG 0.2 |
| Offline retrieval harness (numpy, fixtures, no DB) | rag | 1w | RAG 1.1 |
| Metrics + health indicators (per-source, judged fraction, bootstrap) | rag | 3d | RAG 1.2 |
| Eval report output with corpus sha256 + git sha | rag | 2d | RAG 1.3 |
| Add ruff + mypy config and a lint CI job | platform | 0.5d | Platform 4.2 —— 配置已写好可直接抄 |
| Start 群聊 privacy path (choose a/b/c, external comms) | data | 长周期 | Data 0.4 |

## Low

| Title | Track | Size | 出处 |
|---|---|---|---|
| Unify `run()` / `stream()` code paths in orchestrator | rag | 2d | RAG 0.7 |
| Generator contract tests: citation format, truncation, prompt injection | rag | 3d | RAG 3.2 |
| Implement `S3Storage` | platform | 3d | Phase 3 |
| Per-stage latency + token/cost instrumentation | rag | 2d | RAG 4.1 |

---

## Backlog(blocked)

### A 类:活是明确的,只等一个输入 → 正常开 issue,设 blocked-by

| Title | Track | Blocked by |
|---|---|---|
| Run A/B/C architecture experiment matrix | rag | gold set |
| Decide `top_k` from the Recall@k curve | rag | ↑ |
| Vector dimension migration + full re-embed | data | 选型结论 |
| Mine hard negatives and retrain reranker (LoRA) | rag | 训练数据 |
| Cross-validate `authored_blind` vs `human_log` rankings | data | 真实流量 |

### B 类:活的形态取决于阻塞的结果 → 只开占位 issue,别拆细

| Title | Track | Blocked by | 为什么不拆 |
|---|---|---|---|
| Corpus build pipeline (QA 提取 / 脱敏 / 聚簇 / 冻结) | data | 导出结论 | 提取管线怎么写完全取决于聊天记录长什么样 |
| Gold set construction (pooling / 标注 / 打包) | data | 语料冻结 | 规模取决于「≥2 条簇」有多少 |
| Pluggable retrieval strategy (A/B/C 接口) | rag | 设计未定 | 现在拆会写出错的抽象 |
| 群聊 ingestion + 话题窗口切分 | data | 隐私路径 | 隐私路径选 a/b/c 决定能拿到什么 |

拆细了会在阻塞期间过期 —— 等真开工时设计已经变了,还得重写。**占位 issue 的作用是
「让人知道这件事存在、以及它在等什么」,不是排期。**

---

## 依赖关系

只有三条真依赖,其余全独立:

```
doc_id 链路        ──►  chat_interactions      （retrieved 列需要稳定 id）
IaC 骨架           ──►  ECS + ALB
harness (1.1)      ──►  指标 (1.2)
```

把 blocked 也摆上看板之后,**杠杆最高的几件事会自己浮出来**:

```
小助手导出调研        → blocks 4（整条数据线）
doc_id 链路           → blocks 1，且有硬截止
```

> 「问前端那三个问题」原本 blocks 3 条，**2026-08-10 已解决** —— 查仓库即得答案：
> myCSSA 是 Django + DRF 且仓库 public，因此走 BFF。那三条已从 Blocked 移入 Urgent/High。

---

## Linear 结构建议

三个正交的轴，互不重叠：

| 维度 | 用什么 | 回答 |
|---|---|---|
| **Project** | v1 / v2 / v3 / v4 | 这件事**属于哪个版本** |
| **Label（Stream）** | Platform / RAG / Data | 这件事**属于哪条线** |
| **Status** | Todo / Blocked / … | 这件事**现在能不能干** |

关键是后两个的区分：**「属于 v3」和「现在能不能做」是两回事** —— 例如闭卷编写 query
交付的是 v3 的 gold set，但现在就该开工，所以 Project = v3、Status = Todo。

```
Project:  v1 — 能跑（内测）        ← Urgent + High
          v2 — 能用（小助手进库）   ← 语料建设、S3、lint、评估工具（提前做）
          v3 — 能信（选型完成）     ← 闭卷 query、标注 guideline、gold set、实验矩阵
          v4 — 能活（运营化）       ← 群聊、CI/CD、反馈闭环、PEFT

Label:    Platform / RAG / Data（Stream 组，workspace 里已存在）
Status:   Blocked / Todo / In Progress / In Review / Done
Relation: 用 Linear 原生的 blocked-by，别写在描述里
Cycle:    2 周
```

**每个 issue 的 DoD 直接引用 [ROADMAP_versions.md](ROADMAP_versions.md) 的退出标准**,
不要在 Linear 里重写。

---

## 会议节奏(12 人)

12 人各讲各的 = 两小时,且大部分内容与大部分人无关。建议:

| 时长 | 内容 |
|---|---|
| 30 min | 核心组讲(两周任务讲设计、一周任务讲结果) |
| 10 min | 并行组组长各 3 min |
| 20 min | 决策:前端架构、微信定位、下一版范围 |

**每次会最多 5 个讲解位,其余走书面。讲解位按「谁完成了实质工作」轮转,不按人头。**

**会 1**:讲设计 = IaC / RDS / chat_interactions;讲结果 = doc_id / 拒答 / handbook /
成本封顶;决策 = 前端架构、微信定位。

**会 2**:讲结果 = 部署跑通 / chat_interactions / 小助手结论;v1 上线 + 打 tag
`v0.1.0`;定 v2 范围。
