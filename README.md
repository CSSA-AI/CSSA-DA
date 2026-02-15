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

### Github使用规范：
1. 本项目采用github进行version control
2. branch命名规则：

    a. feature/... → 新功能 (feature/retriever/devin)

    b. bugfix/... → bug修复 (bugfix/null-pointer/devin)

    c. hotfix/... → 紧急热补丁 (hotfix/security-patch/devin)

    d. release/... → 准备更新 (release/v2.1.0/devin)

    e. chore/... → 整理，config等非功能性实现 (chore/update-policy/devin)

3. 对于持续时间较长的branch，强烈建议频繁 

### Repo Layout:

```plaintext
rag-chatbot-backend/
├── .github/                        # [DevOps] CI/CD 流水线
│   └── workflows/
│       ├── test.yml                # 自动测试 (Pytest)
│       └── lint.yml                # 代码规范检查 (Ruff/Black)
│
├── app/                            # [核心代码库]
│   ├── __init__.py
│   │
│   ├── api/                        # [C组 - Platform Squad] 接口层
│   │   ├── __init__.py
│   │   ├── deps.py                 # 依赖注入 (提供 DB Session, User, RAG Pipeline)
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── chat.py         # WebSocket/SSE 聊天接口 (调用 RAG Pipeline)
│   │       │   ├── wechat.py       # 微信生态接口 (Token 验证, 消息解密)
│   │       │   └── admin.py        # 内部管理接口 (手动触发爬虫等)
│   │       └── router.py           # 路由汇总
│   │
│   ├── core/                       # [C组] 基础设施层
│   │   ├── config.py               # 环境变量配置 (Pydantic Settings)
│   │   ├── database.py             # 数据库连接 (Async Engine)
│   │   ├── security.py             # JWT / OAuth2 工具
│   │   └── logger.py               # 全局日志配置
│   │
│   ├── models/                     # [全员] 数据库模型 (SQLAlchemy)
│   │   ├── base.py
│   │   ├── article.py              # Article 和 ArticleChunk (向量字段在这里)
│   │   └── chat_log.py             # 聊天记录表
│   │
│   ├── schemas/                    # [全员] 数据交互契约 (Pydantic)
│   │   ├── article.py              # 定义爬虫数据的结构
│   │   ├── chat.py                 # 定义前端 Request/Response 结构
│   │   └── common.py               # 通用结构 (分页等)
│   │
│   ├── services/                   # [核心业务逻辑]
│   │   ├── __init__.py
│   │   │
│   │   ├── ingestion/              # [A组 - Data Squad] 数据管道
│   │   │   ├── crawler.py          # 爬虫逻辑
│   │   │   ├── cleaner.py          # 数据清洗
│   │   │   ├── splitter.py         # 文本切片
│   │   │   └── manager.py          # 入库总控 (Ingestion Manager)
│   │   │
│   │   └── rag/                    # [B组 - AI Squad] RAG 引擎
│   │       ├── interfaces.py       # [关键] 定义 Retriever/Reranker/Generator 的抽象基类
│   │       ├── pipeline.py         # [关键] RAG Orchestrator (把组件拼起来)
│   │       ├── components/         # 具体实现类
│   │       │   ├── retriever.py    # PostgresRetriever
│   │       │   ├── reranker.py     # CohereReranker / BgeReranker
│   │       │   └── generator.py    # OpenAI / Claude Generator
│   │       └── utils.py            # AI 专用工具 (Token计算, Prompt构建)
│   │
│   └── main.py                     # FastAPI 启动入口
│
├── alembic/                        # [C组] 数据库迁移脚本
│   └── versions/
├── alembic.ini
│
├── data/                           # 本地开发数据 (不提交到 Git)
│   └── prompts/                    # [B组] Prompt 模板 (.txt / .yaml)
│       ├── system_prompt.txt
│       └── user_prompt_template.txt
│
├── scripts/                        # [A组] 离线任务脚本
│   ├── run_ingestion.py            # 手动跑爬虫
│   └── seed_db.py                  # 初始化数据库
│
├── tests/                          # [全员] 测试用例
│   ├── unit/                       # 单元测试 (Mock DB)
│   └── integration/                # 集成测试 (真实 DB)
│
├── .env.example                    # 环境变量模板
├── .gitignore
├── docker-compose.yml              # 本地开发环境 (Postgres + App)
├── Dockerfile                      # 生产环境镜像构建
├── Makefile                        # 常用命令封装 (make run, make test)
└── pyproject.toml / requirements.txt
```
