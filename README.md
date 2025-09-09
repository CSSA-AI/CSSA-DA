### 环境安装
1. 使用anaconda作为环境管理方式
2. 打开terminal（打开 anaconda prompt 如果你是Windows用户）
3. Navigate到CSSA-DA文件夹
3. 运行conda env create -f environment.yaml
4. 运行conda activate cssa-ai来激活当前环境（或者直接在vscode中选择）
5. 后续更新环境运行conda env update -f environment.yaml --prune


### 项目注意：
1. 使用github作为代码传输方式，进行修改前先创建一个以自己名字命名的branch，创建新的file后进行修改，尽量不要修改已经在main里的文件，会导致conflict。完成当前任务后通过commit -> push -> pull request来合并入main。
2. 保持代码 clean 和 readable，不强制要求oop。


### Repo Layout:

rag-chatbot/
├─ apps/
│  ├─ api/                         # 后端 Web 服务（FastAPI/Flask）
│  │  ├─ src/
│  │  │  ├─ app/
│  │  │  │  ├─ main.py            # 入口（挂载路由、中间件）
│  │  │  │  ├─ routers/
│  │  │  │  │  ├─ chat.py         # /chat 流程编排入口（粘合代码就在这里）
│  │  │  │  │  ├─ health.py
│  │  │  │  ├─ deps.py            # 依赖注入（DB、向量库、缓存）
│  │  │  │  ├─ settings.py        # Pydantic 设置，读取 .env / configs/*
│  │  │  ├─ domain/
│  │  │  │  ├─ schemas.py         # Pydantic 模型（Message, Document, Hit, Answer...）
│  │  │  │  ├─ events.py          # 事件/日志结构（可用于审计）
│  │  │  └─ orchestrator/
│  │  │     └─ rag_orchestrator.py# 串联 retriever → reranker → generator
│  │  └─ tests/
│  │     ├─ unit/
│  │     └─ integration/
│  └─ web/                         # 前端（Next.js/React）
│     ├─ src/
│     │  ├─ pages/ or app/
│     │  ├─ components/
│     │  └─ lib/
│     └─ package.json
│
├─ packages/
│  ├─ rag_core/                    # 可复用的 RAG 核心（Python 包, src-layout）
│  │  ├─ src/rag_core/
│  │  │  ├─ retriever/
│  │  │  │  ├─ base.py            # 协议/接口：RetrieverProtocol
│  │  │  │  ├─ bm25.py
│  │  │  │  ├─ faiss_cosine.py
│  │  │  │  └─ qdrant.py
│  │  │  ├─ reranker/
│  │  │  │  ├─ base.py            # RerankerProtocol（cross-encoder 等）
│  │  │  │  └─ ms_marco_ce.py
│  │  │  ├─ generator/
│  │  │  │  ├─ base.py            # GeneratorProtocol（LLM 调用）
│  │  │  │  └─ openai_chat.py
│  │  │  ├─ pipeline/             # 离线流水线（chunk/embedding/index）
│  │  │  │  ├─ chunkers.py
│  │  │  │  ├─ embedder.py
│  │  │  │  ├─ indexer.py
│  │  │  │  └─ schemas.py         # 原始文档/切块/向量的通用 DTO
│  │  │  ├─ storage/              # 数据库/对象存储/缓存抽象
│  │  │  │  ├─ postgres.py
│  │  │  │  ├─ supabase.py
│  │  │  │  ├─ s3.py
│  │  │  │  └─ redis.py
│  │  │  ├─ eval/                 # 检索/重排/端到端评测
│  │  │  │  ├─ metrics.py         # Recall@k, MRR, nDCG, F1...
│  │  │  │  └─ runner.py
│  │  │  ├─ utils/                # 通用工具（日志、重试、并行、时间）
│  │  │  │─ tests/
│  │  │  └─ config/               # 默认配置（可被 apps 覆盖）
│  │  └─ pyproject.toml
│  └─ shared_types/               # 「共享类型」的单一事实源
│     ├─ openapi/                 # 由 API 导出的 OpenAPI（生成 TS 类型）
│     ├─ ts/                      # 生成的 TypeScript 类型（frontend 引用）
│     └─ py/                      # Pydantic/TypedDict（backend & pipelines 引用）
│
├─ services/
│  ├─ ingest/                      # 爬虫/Harvester（Trafilatura/Playwright/自定义）
│  │  ├─ jobs/
│  │  ├─ loaders/                 # HTML/PDF/API/自定义源
│  │  └─ cli.py                   # `python -m services.ingest ...`
│  ├─ indexer/                     # 触发切块→向量化→建索引（批处理/队列）
│  │  └─ cli.py
│  └─ worker/                      # 异步任务（Celery/RQ）
│
├─ data/                           # 数据分层（不入 Git 或用 DVC 管理）
│  ├─ raw/
│  ├─ interim/
│  ├─ processed/
│  └─ indexes/                     # FAISS/Qdrant dump
│
├─ configs/                        # 分环境配置（Hydra/纯 YAML 皆可）
│  ├─ base/
│  │  ├─ app.yaml                  # API 层参数（分页、限流、CORS）
│  │  ├─ rag.yaml                  # RAG 流水线参数（k, chunk_size, overlap...）
│  │  ├─ retriever.yaml            # 模型/索引路径/向量库连接
│  │  ├─ reranker.yaml
│  │  ├─ generator.yaml
│  │  └─ storage.yaml              # Postgres/Supabase/Redis/S3
│  ├─ dev/
│  └─ prod/
│
├─ infra/
│  ├─ docker/
│  │  ├─ api.Dockerfile
│  │  ├─ worker.Dockerfile
│  │  └─ web.Dockerfile
│  ├─ docker-compose.dev.yml       # 本地一键起（API+Web+DB+Qdrant/PG/Redis）
│  ├─ k8s/                         # 生产/预发部署（Deployment/Service/Ingress）
│  └─ terraform/                   # 云上基础设施（可选）
│
├─ scripts/                        # 开发者脚本（格式化、生成类型、导入数据）
│  ├─ gen_types.sh                 # OpenAPI → TS/Python 类型同步
│  ├─ seed_demo.sh                 # 演示数据
│  └─ precommit.sh
│
├─ notebooks/                      # 实验/可视化（EDA、评测、消融）
├─ tests/
│  ├─ e2e/                         # 端到端对话/检索回归测试
│  └─ load/                        # 简单压测脚本
├─ docs/                           # 架构图/ADR/运行手册/API 文档
├─ .env.example                    # 环境变量模板（见下）
├─ .pre-commit-config.yaml
├─ Makefile                        # 常用命令入口（make dev / make test / make index）
├─ README.md
└─ package.json / pyproject.toml   # 根级管理（前端/后端并存时都在 root）
