# CSSA-DA 未来部署计划

## 目标

将 CSSA-DA 部署到 AWS，并满足以下要求：

- 安全
- 可重复构建
- 可稳定扩容
- 可观测
- 可回滚

当前暂时假设微信清洗逻辑符合要求。微信清洗 golden tests 延后到首次 AWS
部署完成之后再处理。

数据库方向已确定：使用 **Amazon RDS for PostgreSQL + pgvector**，直接复用现有
schema、迁移和 `PGVectorRetriever` 代码，不引入专用向量数据库。

## 目标架构

API 请求链路：

```text
User
  |
  v
Application Load Balancer
  |
  v
Amazon ECS API Service
  |- FastAPI
  |- Retriever
  |- Reranker
  `- OpenAI API
       |
       v
Amazon RDS for PostgreSQL + pgvector
```

数据管线与 API 分开运行：

```text
Amazon ECS Pipeline Task
  |- Harvest
  |- Transform
  |- Validate
  |- Embed
  `- Import into RDS

Pipeline artifacts and reports
  |
  v
Amazon S3
```

外围服务：

```text
Amazon ECR         保存容器镜像
Secrets Manager    保存 API key 和数据库凭据
CloudWatch         保存日志、指标和告警
GitHub Actions     测试、构建、迁移和部署
AWS IAM OIDC       为 GitHub 提供短期 AWS 凭据
```

## 部署阻塞项

### 1. 保护付费的 `/chat` 接口（含结构化日志与可观测性基础）✅ 已完成

> **状态：已完成并验证（8 步全部落地）。** 设计与实现细节见
> [docs/design/chat-api-hardening.md](docs/design/chat-api-hardening.md)。
> 限流精细化（按用户维度）延后,见本文件第 16 项 /
> [issue #67](https://github.com/CSSA-AI/CSSA-DA/issues/67)。下面保留原始设计
> 记录以备回顾。

当前 `POST /chat` 没有鉴权和限流，`app/main.py` 里也没有注册任何 middleware
（无 CORS、无请求日志、无 rate limiting、无安全响应头、无兜底异常处理）。
只有 `RetrievalUnavailableError` / `GenerationUnavailableError` /
`GenerationTimeoutError` 三种已知错误有安全的公开响应，其他未预期的异常会
直接落到 Starlette 的默认行为，不会被结构化记录。

如果直接暴露到公网，任何人都可以触发：

- Embedding 计算
- Reranker 推理
- OpenAI API 调用
- AWS 计算资源消耗

#### 具体设计

**新增 `app/core/logging.py`**：仿照 `pipelines/shared/logging.py` 里的
`JsonLogFormatter`，但用 `request_id`（`ContextVar`）代替 `run_id`，单独实现
（不与 pipelines 共用，两者字段和上下文不同）。`configure_app_logging()` 把
JSON handler 挂到 `logging.getLogger("app")` 上，`propagate=False`。所有
`app.*` 下的 logger（包括 `app.services.rag.orchestrator`）自动继承，
无需改动 orchestrator 代码。

**新增 `app/core/middleware.py`**（纯 ASGI middleware，不用
`BaseHTTPMiddleware`，避免它的响应缓冲开销）：
- `RequestContextMiddleware`：读取/生成 `X-Request-ID`，绑定到 ContextVar，
  计时，请求结束时输出一条结构化 access log（method、path、status_code、
  duration_ms、request_id），并把 `X-Request-ID` 写回响应头。
- `SecurityHeadersMiddleware`：给所有响应加
  `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、
  `Referrer-Policy: no-referrer`、`Strict-Transport-Security`。

**CORS**：用 Starlette 自带的 `CORSMiddleware`，允许的 origin 来自新配置项
`ALLOWED_ORIGINS`（逗号分隔字符串，避免 pydantic-settings 对复杂类型要求
JSON 格式），并 `expose_headers=["X-Request-ID"]` 让前端能读到。

**Middleware 注册顺序**（`app/main.py`）：Starlette 里"最后
`add_middleware()` 的在最外层"，顺序反直觉，需要在代码里写注释说明：

```python
app.add_middleware(RequestContextMiddleware)   # 最先添加 -> 最内层
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins_list, ...)
```

**新增 `app/core/rate_limit.py`**：用 `slowapi`（内存态，单实例够用；本项目由
社团实际部署但不需要多 ECS 水平扩容，因此内存态限流是正确选择，Redis 分布式
限流彻底归入将来水平扩容再说）：

```python
limiter = Limiter(key_func=get_remote_address)

def chat_rate_limit() -> str:
    return settings.CHAT_RATE_LIMIT
```

**限流维度：先按客户端 IP，`CHAT_RATE_LIMIT` 默认 `10/minute`（方向 C，保命型
止血）。** 这是一个够用的止血方案，能挡住最主要的威胁——脚本狂刷 / 前端死循环
把社团的 OpenAI 账单刷爆。精细化（按登录用户 ID 等）延后到前端和用户体系确定
之后再做（见"中优先级工作 / 精细化限流"）。

传入**函数**而不是字符串常量给 `@limiter.limit(...)`，这样每次请求都会重新
读取 `settings.CHAT_RATE_LIMIT`，方便测试时 monkeypatch 出一个很低的限额。
`/chat` 需要一个真正的 `Request` 参数才能配合 slowapi，把现有的
`request: ChatRequest` 改名成 `payload: ChatRequest` 并加
`http_request: Request`（JSON 请求体格式不变，只是内部参数名变化）。
`RateLimitExceeded` 的响应体要覆盖成跟其他错误一致的安全格式：
`{"error": {"code": "rate_limited", "message": "..."}}`，429。

**兜底异常处理**（`app/main.py`）：加
`@app.exception_handler(Exception)`，把完整异常和 `request_id` 记到结构化
日志，对外只返回 `{"error": {"code": "internal_error", ...}}`，500。
Starlette 按异常类型的 MRO 找 handler，已有的具体异常类型 handler 会继续
优先匹配，不需要调整注册顺序。

**依赖**：`slowapi` 需要同时加到 `requirements-ci.txt`、
`environment_cpu.yml`、`environment_gpu.yml`（这三处分别管 CI 和真实构建的
依赖，缺一个就会导致 CI 和生产环境不一致）。

**顺带清理**：`Dockerfile.cpu` / `Dockerfile.gpu` 的 uvicorn 启动命令加
`--no-access-log`，避免 stdout 里同时出现 uvicorn 自带的纯文本访问日志和
我们的结构化 JSON 日志，保持 stdout 干净（为将来接 CloudWatch 铺路）。

#### 分步实施清单（每一步单独提交、单独验证，再进入下一步）

1. `app/core/logging.py` + `configure_app_logging()` 接入 `app/main.py`，
   确认现有测试全部通过（先不加中间件，只验证结构化日志本身能跑起来）。
2. `RequestContextMiddleware`（request_id + access log），配套测试：无
   header 时自动生成、有 header 时原样回传、深层日志（orchestrator 里的
   log）也能带上同一个 request_id。
3. `SecurityHeadersMiddleware`，配套测试：成功和失败响应都带上四个头。
4. `CORSMiddleware` + `ALLOWED_ORIGINS` 配置项，配套测试：允许的 origin
   preflight 通过，未配置的 origin 不返回 `Access-Control-Allow-Origin`。
5. `app/core/rate_limit.py` + `/chat` 参数改名 + `CHAT_RATE_LIMIT` 配置项，
   配套测试：超过限额返回安全格式的 429；`tests/conftest.py` 加 autouse
   fixture 在每个测试前后 reset limiter 状态（`TestClient` 请求永远用同一个
   客户端地址，不 reset 会导致测试之间互相影响）。
6. 兜底 `Exception` handler，配套测试：未预期的 `RuntimeError` 返回安全的
   500 body，异常原文不出现在响应里（对照现有
   `test_chat_returns_safe_service_errors` 的写法）。
7. `--no-access-log` 加到两个 Dockerfile，本地跑一次 `docker compose`
   确认镜像仍然正常启动、`/health` healthcheck 仍然通过。
8. 手动验证：`uvicorn app.main:app --reload`，检查 `/health`、`/chat`
   （带合法 `CHAT_API_KEY`）返回里有 `X-Request-ID` 和安全响应头，stdout
   每次请求有一条 JSON 日志，连续打 `/chat` 超过限额能看到 429。

#### 已知取舍（暂不处理）

- **限流按 IP 是止血,非最终方案。** 社团用户很多人可能共用同一出口 IP（校园
  WiFi / 宿舍 NAT），对服务器看起来是同一个 IP，因此"每 IP 每分钟 10 次"在
  校园网下是**多人共享一份额度**，可能误伤正常用户。当前接受这个不完美——它
  仍能挡住主要威胁（脚本狂刷）。精细化按用户维度的限流延后（见下方"精细化
  限流"）。
- 鉴权失败（`require_internal_api_key` 拒绝）不计入 rate limit 次数，因为
  slowapi 的检查在 endpoint 函数内部、鉴权 dependency 之后才执行。要修的话
  需要把限流挪到鉴权之前，改动更大，本阶段不做。
- 新加的 middleware 本身如果抛异常，会绕过兜底 handler（它们在 Starlette
  的 `ExceptionMiddleware` 外层）。保持这部分代码尽量简单、覆盖测试即可。
- 分布式 rate limiting（Redis 等）、Prometheus `/metrics`、OpenTelemetry
  tracing 都不在本阶段范围内，等真正需要多实例水平扩容或更细粒度的指标时
  再评估。

验收条件：

- 匿名或无效客户端无法调用 `/chat`。
- 单个客户端无法超过规定的请求频率。
- 鉴权失败时不会执行 retrieval、reranking 或 OpenAI 调用。
- 每次请求都有一条结构化 JSON access log，带 `request_id`。
- 未预期异常不会把内部细节泄露给客户端。

### 2. 让模型交付过程可预测 ✅ 已完成（CPU；GPU 待补齐）

> **状态：CPU 侧已完成。** `ops/download_models.py` 在可缓存镜像层下载两个
> 模型，revision 固定在 `app/core/config/rag-config.yaml`，`Dockerfile.cpu`
> 设置 `MODEL_DIR`，`app/main.py` lifespan 在接流量前调用
> `model_registry.preload_models()`，`ModelRegistry` 用 `local_files_only`
> 加载本地模型。**遗留：`Dockerfile.gpu` 尚未下载模型、未设 `MODEL_DIR`，
> 需与 CPU 侧对齐（见第 4/5 项的 GPU 补齐）。** 下面保留原始设计记录。

当前 embedding model 和 reranker 在第一次 `/chat` 请求时才加载。这会导致
`/health` 已经返回成功，但 RAG pipeline 实际上还不能稳定提供服务。

推荐的首版方案：

- 在 Docker build 阶段下载两个模型。
- 固定两个模型的 revision。
- 在 task 接收流量前完成模型加载。
- 确保第一个用户请求不会下载模型文件。

后续可以评估的替代方案：

- 在应用启动阶段预加载模型。
- 使用 Amazon EFS 保存共享 model cache。

验收条件：

- 新 ECS task 无需下载模型即可处理 `/chat`。
- 可以从源码配置准确复现模型版本。
- 必需模型不可用时，readiness 不会返回成功。

### 3. 使用持久化存储代替本地 pipeline 文件

当前 pipeline 依赖 `./data` 和 Docker bind mount。Fargate task 的本地存储是
临时存储，不能作为长期事实来源。

计划映射：

```text
data/raw          -> s3://<bucket>/raw
data/processed    -> s3://<bucket>/processed
data/current      -> s3://<bucket>/current
data/checkpoints  -> s3://<bucket>/checkpoints
data/reports      -> s3://<bucket>/reports
```

需要完成：

- 为 pipeline stage 定义统一的 storage interface。
- 保留本地 filesystem 实现供开发环境使用。
- 增加 AWS 环境使用的 S3 实现。
- 保留 checkpoint、report 和 current artifact 的现有语义。

验收条件：

- Pipeline task 被替换后不会丢失持久状态。
- 失败的 task 可以通过 S3 checkpoint 恢复。
- API 部署不依赖本地 `data` 目录。

#### 具体设计（storage abstraction）

**统一接口（key 寻址的对象存储，对 S3 友好）** —— 新增 `pipelines/shared/storage/`：

- `base.py`：`Storage` Protocol，动作为 `write(key, data: bytes)` / `read(key) -> bytes`
  / `exists(key)` / `list(prefix)` / `delete(key)` / `delete_prefix(prefix)`；配套
  `StorageNotFoundError`。key 是 `/` 分隔的**逻辑名字**（如
  `reports/pipelines/x.json`），不是文件系统路径，各后端自行把 key 映射到自己的布局。
- `local.py`：`LocalStorage(base_dir)`，把 key 映射到 `base_dir/key`，内部保留
  「临时文件 + 原子 `replace`」，**磁盘布局与抽象前完全一致**（现有集成测试无感）。
- `S3Storage`（后续，见 Phase 3）：PUT 天然原子，`list` = list_objects，
  `delete_prefix` = 按前缀删除。上层 stage 代码**零改动**即可切换。

**需要迁移的咽喉点**（现在直接碰文件系统、且都用「临时文件 + 原子 replace」的地方）。
按「存储位置由谁决定」分两类，决定它们的迁移时机：

- **A 类 —— 根来自 `data_dir`（干净，可独立迁移）**：位置纯由 `data_dir` 推出，
  没有任意 input，逻辑 key 一目了然。
  1. `pipelines/shared/reports.py` `write_json_report` —— reports
  2. `pipelines/ingestion/wechat/storage/local.py` `JsonFileCheckpointStore`
     —— wechat harvest checkpoint（构造点 `harvest_wechat.py`，路径由 `data_dir` 推出）
  3. `pipelines/ingestion/wechat/storage/local.py` `JsonChunkArticleSink`
     —— wechat 批次落盘 + current（同上）
- **B 类 —— 根来自「任意 input」（与入口串联绑定，第 5 步一起做）**：位置跟随用户可
  传任意值的 `--input` / `--checkpoint-file`，没有第 5 步的入口串联就得不到干净 key。
  4. `pipelines/shared/json_records.py` `load/write_json_records` —— raw / processed
  5. `pipelines/shared/import_checkpoint.py` `JsonImportCheckpointStore`
     —— import checkpoint（路径 = `checkpoint_file or import_checkpoint_file_for(input_file)`）

**入口串联与寻址决策（关键）**：

- 在 pipeline 入口（`pipelines/cli.py` / `run_local_*`）**只创建一次** `Storage`
  （本地 → `LocalStorage`，云 → `S3Storage`），连同逻辑 key 一路传给各 stage；
  stage 代码不再自己构造 storage、不再处理裸 `Path`。做完这步，本地 ↔ S3
  只需改入口一行。
- **决策：采用「方案②」—— artifact 一律用「存储根下的逻辑 key」寻址，不再支持
  CLI 传入任意绝对路径。**
  - 理由：S3 没有「绝对路径」概念，只有「桶 + key」；「任意本地路径」这个能力
    本就只对本地成立，对 S3 天生不成立。
  - 收益：本地与云写法一致；强制所有数据住在 `data/` 根（或 S3 桶）内，养成好习惯；
    去掉「任意路径」后门分支，代码更简单。
  - 影响：`--input` 等参数从「文件路径」改为「根下逻辑 key」（例如
    `current/wechat_articles_processed.json`）；需要调试外部文件时，先放进 `data/`
    根再引用。
  - **B 类**（`json_records`、`JsonImportCheckpointStore`）的迁移**与本步绑定**：入口把
    storage + 逻辑 key 传下来后，它们一并改为 `(storage, key)` 签名，**不单独提前做**
    （提前做只能得到光秃秃的文件名 key，对 S3 无意义，且第 5 步还要重做）。

#### 分步实施清单（每步单独提交、单独验证）

1. ✅ **已完成并提交**：接口 + `LocalStorage` + 单测（纯新增，零风险）。
2. ✅ **已完成**：迁移 reports —— `write_json_report(storage, key, payload)`；唯一调用方
   `wechat_pipeline` 用 `LocalStorage(data_dir)` + `report_file.relative_to(data_dir)`，
   输出字节与落盘位置均不变。
3. ✅ **已完成**：迁移 wechat harvest checkpoint（A 类，`JsonFileCheckpointStore`）——
   构造函数改收 `(storage, key)`，唯一构造点 `harvest_wechat.py` 用
   key `checkpoints/wechat_scraper_state.json`。
4. ✅ **已完成**：迁移 wechat article sink（A 类，`JsonChunkArticleSink`）——逻辑更重
   （写批次 / list / 合并 / 拷到 current / 删临时目录），用到
   `write`+`list`+`read`+`delete_prefix`；`ArticleOutput.location` 改为逻辑 key。
5. ✅ **已完成**：**入口串联**（`cli.py` 只建一次 storage、往下传）：一并迁移 **B 类**
   （`json_records` 与 `JsonImportCheckpointStore`）；`--input` / `--checkpoint-file` 改为
   逻辑 key（落实方案②）；删掉 `import_checkpoint_file_for` 与 transform legacy 回退。
6. `S3Storage` 实现（等真正上 AWS 时做，见 Phase 3），上层不改。

不在本阶段范围：`S3Storage` 实现、AWS 相关配置（留到 Phase 3）。

## 高优先级容器工作

### 4. 使用 non-root 用户运行容器 ✅ 已完成（CPU；GPU 待补齐）

> **状态：CPU 侧已完成。** `Dockerfile.cpu` 创建 system 用户 `appuser`
> 并以 `USER appuser` 运行。**遗留：`Dockerfile.gpu` 仍以 root 运行，
> 需补上同样的 non-root 用户。** `readonlyRootFilesystem` 留到 Phase 2 写
> ECS task definition 时评估。

当前 GPU Dockerfile 仍以 root 用户运行。

需要完成：

- 创建专用 application user。（CPU 已完成，GPU 待补齐）
- 只授予该用户所需应用目录和 cache 目录的访问权限。
- 在 ECS task definition 中评估启用 `readonlyRootFilesystem`。

### 5. 固定基础镜像

`Dockerfile.cpu` 当前使用：

```dockerfile
FROM continuumio/miniconda3:latest
```

需要完成：

- 将 CPU 基础镜像固定到经过审核的版本或 digest。
- 开始 GPU 部署时，将 GPU 基础镜像固定到经过审核的 digest。
- 建立受控的基础镜像更新流程。

### 6. 锁定 runtime 依赖

当前 Conda environment 文件包含大量未固定版本的依赖，不同时间构建可能得到
不同的运行环境。

需要完成：

- 为每种 runtime 定义唯一的直接依赖来源。
- 生成可重复的 lock file。
- 根据需要拆分 CPU、GPU、pipeline、test 和 development 依赖。
- 明确列出直接 runtime 依赖，避免依靠 transitive dependency 安装。

### 7. 缩小 API 镜像

CPU environment 包含多项 API runtime 不需要的工具，例如：

- Jupyter
- IPython
- pytest
- mypy
- matplotlib
- 部分开发和编译工具

需要完成：

- 创建最小化的 API runtime environment。
- 适当使用 multi-stage Docker build。
- 从最终镜像中移除 compiler 和开发工具。
- 清理 apt、Conda 和 pip cache。
- 测量压缩和解压后的镜像大小。

### 5+6+7 合并实施：生产 API 镜像的锁定与瘦身

> **决策（2026-07-27）**：第 5（固定基础镜像）、第 6（锁定依赖）、第 7（缩小
> 镜像）本质是同一件事，合并实施。

**总方向 —— 按团队分工拆两套环境，互不拖累：**

- **数据科学家（DS）线**：继续用 `environment_cpu.yml`（conda + notebook），
  jupyter / matplotlib / nltk / gensim 都留着，供 DS 微调模型用。**它不再是
  生产镜像的来源，永远不进部署产物**，因此不必强锁、不必瘦身。交接点：DS 在
  notebook 产出模型 / LoRA adapter，工程师侧只负责加载已训好的模型。
- **工程师线（生产 API 运行时）**：迁到纯 pip 工具链 + slim 基础镜像，严格锁定、
  精简、可复现。这是部署到 ECS 的镜像。

**工程师线内部再分「生产 / dev」两层**（按"用户请求跑不跑得到"划分）：

- 生产运行时：`/chat` 真正依赖的包（fastapi、uvicorn、torch(CPU)、
  sentence-transformers、peft、langchain-*、sqlalchemy、asyncpg、pgvector …）。
- dev / 测试：在生产之上叠加 `pytest`、`httpx`、`mypy`——只在开发和 CI 用，
  **不进生产镜像**。

**锁定工具（2026-07-27 定）：`uv`。** 直接依赖写进 `pyproject.toml`
（`[project].dependencies` = 生产，dev group = 测试工具），`uv lock` 生成单一
`uv.lock`（含 transitive）。本地 / CI `uv sync`，生产镜像 `uv sync --no-dev`。
基础镜像 `python:3.11-slim` 固定到 digest（落实第 5 项）。`torch` 走 CPU wheel
的 index。DS 的 conda 环境不受影响。

#### 分步实施清单（每步单独提交、单独验证，再进入下一步）

1. ✅ **建 `pyproject.toml` + `uv.lock`（纯新增，不动 CI / Dockerfile）**：已完成。
   `[project].dependencies` = 共享核心运行时；`[dependency-groups]` 分
   `api` / `pipeline` / `dev`（虚拟项目 `package = false`，故用 groups 而非
   optional-dependencies）；torch 走 `pytorch-cpu` index（锁到 `2.12.1+cpu`）；
   ML 栈钉到 `.venv` 验证过的版本。用纯粹由 `uv.lock` 构建的隔离环境跑
   `pytest tests/unit`：**186 passed**（与 `.venv` 基线一致，无回归）。
2. ✅ **切 CI 到 uv**：已完成。`unit-test.yml` 与 `integration-test.yml` 改用
   `astral-sh/setup-uv@v6`（`enable-cache`）+ `uv sync --locked`（锁文件过期即
   CI 失败）+ `uv run pytest`；删除 `requirements-ci.txt`。本地按 CI 确切命令验证：
   `uv sync --locked` / `uv run python ops/check_config.py` / `uv run pytest
   tests/unit` → **186 passed**（集成测试需 postgres 服务，未在本地跑，命令形式与
   单测一致）。apt 系统依赖步骤暂保留。
3. ✅ **重写为 slim 多阶段镜像，并拆成 `Dockerfile.api` + `Dockerfile.pipeline`
   （决策 2026-07-27：合并 cpu/gpu → 再按 api/pipeline 拆两个部署镜像）**：已完成。
   两者同一 `python:3.11-slim`（固定 digest `db3ff2…`）+ 三阶段构建（builder：uv
   装对应 group + 下模型；final：只搬 venv+models+代码、non-root、无 uv/编译器）。
   - `Dockerfile.api`：`--group api`，下 **embedding + reranker** 两模型，`uvicorn`
     常驻 + HTTP healthcheck。
   - `Dockerfile.pipeline`：`--group pipeline`，**只下 embedding**（管线不 rerank；
     `ops/download_models.py` 新增 `--models` 选择，配套单测），无端口 / 无
     healthcheck，`ENTRYPOINT python -m pipelines`。
   删除 `Dockerfile.cpu` / `Dockerfile.gpu` / 中间的单一 `Dockerfile`；
   `docker-compose.yml`（api/migrate 用 `Dockerfile.api`、pipeline 用
   `Dockerfile.pipeline`、删 `api-gpu`、镜像名 `cssa-da-api` / `cssa-da-pipeline`）、
   `docker-check.yml`（build 两镜像各自冒烟）、README、设计文档同步。
   本地 `docker build` 两镜像均成功，冒烟全绿：pipeline `--help` ✅、
   `check_config --profile all` ✅、API 启动 + 模型本地加载（无联网下载）+
   `/health` → `{"status":"ok"}` ✅。**确认 `python-multipart` 无需。**
   单测 **188 passed**（含新增 `--models` 测试）。
   **体积：API 3.35GB / Pipeline 3.06GB**（pipeline 省掉 reranker 模型 + api 库
   约 290MB；torch 754MB + embedding 477MB 为硬成本；相比 conda 全家桶 5–8GB
   大幅瘦身）。落实第 5/6/7 项。
4. ✅ **`environment_cpu.yml` / `environment_gpu.yml` 重定位为 DS notebook 环境**：
   已完成。两个 yml 加英文注释 + 头部声明「DS 交互/微调用，非部署产物；部署走
   `Dockerfile.api` / `Dockerfile.pipeline` + `uv.lock`」；依赖全部保留、**版本不锁**
   （决策 2026-07-27：DS 环境保持放养便于实验）。README 说明同步更新。两个 yml
   都保留（GPU 版供 DS 在显卡机上微调）。
   **延后待办**：真要做可复现微调 / golden test 时，用 `conda-lock` 给 DS 环境上锁，
   并把 ML 核心（torch / transformers / sentence-transformers / peft）对齐 `uv.lock`
   的固定版本，保证 DS 训出的 adapter 能在生产镜像加载。
5. ✅ **本地测量（不依赖 DB 的部分）**：已完成。镜像大小 API 3.35GB / Pipeline
   3.06GB；**冷启动 → `/health` 可用 ~7s**（含 torch + 两模型预加载，阻塞启动，
   故首个请求不再等模型）；**idle 内存 ~950 MiB**、idle CPU ~0.1%。
   → Phase 2 选 Fargate size 参考：内存至少 1GB，建议 2GB 留请求峰值余量。
   **延后到 Phase 2（需真实 Postgres + 有数据的 knowledge_base）**：`/ready`、
   first-request `/chat` 端到端 latency、peak 内存 —— 连同负载测试一起做。

> **注（2026-07-27）**：原第 5 步「`Dockerfile.gpu` 对齐」已作废——决定合并为
> 单一部署镜像、删除 GPU Dockerfile（DS 的 GPU 训练走 conda notebook，GPU
> serving 属 Phase 5 延后项，届时按需另建）。原「本地构建并测量」顺延为第 5 步。

原始条目（第 5/6/7 项）保留在下方以备回顾。

### 8. 在 ECS 中明确配置 health check

Dockerfile 已经包含 health check，但 ECS task definition 仍需要明确配置 container
health check。ALB target group health check 需要单独配置。

推荐语义：

```text
ECS container health check  -> /health
ALB target health check      -> /ready
```

在使用 `/ready` 作为 ALB health check 前，需要先完成模型 readiness。

需要完成：

- 在 ECS task definition 中配置 container health check。
- 为模型加载设置足够的 start period。
- 配置 ALB target group health check。
- 验证 readiness 失败时，新 task 不会接收流量。

### 9. 完善 readiness 语义 ✅ 已完成

> **状态：已完成。** `app/services/rag/model_registry.py` 用
> `ModelRegistryStatus` 记录 embedding / reranker 的加载状态；
> `app/services/readiness.py` 的 `check_readiness` 在数据库和 knowledge-base
> rows 之外，还检查 `model_registry.status().is_ready`，未 ready 时 `/ready`
> 返回 503。`/health` 仍是轻量的静态 `{"status":"ok"}`，不依赖外部服务。

`/ready` 现在会检查数据库、有效 knowledge-base rows，并证明：

- Embedding model 已加载
- Reranker 已加载
- RAG pipeline 已成功初始化

已完成：

- 记录 RAG component 初始化状态。
- 保持 `/health` 轻量，并且不依赖外部服务。
- 只有 task 确实能够处理 `/chat` 时，`/ready` 才返回成功。

### 10. 清理初始化失败响应 ✅ 已完成

> **状态：已完成。** `app/main.py` 的兜底 `@app.exception_handler(Exception)`
> 把原始异常记入结构化日志，对外只返回安全的
> `{"error": {"code": "internal_error", ...}}`（500）。`/ready` 只回
> `readiness.to_dict()` 里 curated 的 `reason` 字符串（如
> "Database is unavailable"），不含数据库 URL、内部路径或 provider 细节；
> lifespan 里模型 preload 失败也只记日志，由 `/ready` 拦住流量。

已完成：

- 对外返回稳定的初始化错误。
- 在内部日志中保存原始 exception。
- 不向客户端返回数据库 URL、内部路径或 provider 细节。

### 11. 定义 migration 部署关卡

Docker Compose 会在 migration 完成后启动 API，但 ECS 不会继承 Compose 的依赖关系。

要求的部署顺序：

```text
Build and push image
  |
  v
Run one-off ECS migration task
  |
  v
Wait for successful completion
  |
  v
Deploy or update the ECS API service
  |
  v
Wait for healthy targets
```

验收条件：

- Migration 失败会停止部署。
- 每个 release 只运行一个受控的 migration task。
- CloudWatch 中可以查看 migration log。

### 12. 设计 outbound networking

Private ECS task 必须能够访问 OpenAI。如果模型没有放进镜像或 EFS，它还需要访问
Hugging Face。

需要完成：

- 将 API task 放在 private subnet。
- 提供受控的 outbound internet access。
- Inbound 只允许来自 ALB security group。
- RDS 只允许来自 ECS task security group。

## 中优先级工作

### 13. 确定 worker 和扩容策略

API 当前运行一个 Uvicorn worker。由于每个 worker 可能单独加载模型并创建数据库
连接池，一个 worker 不一定是错误选择。

修改 worker 数量前需要测量：

- 模型加载后的 idle memory
- 单请求 peak memory
- 单请求 CPU utilization
- Retrieval、reranking 和 generation latency
- 并发请求行为
- Cold-start duration

根据数据决定使用：

```text
较少 ECS tasks × 多个 workers
```

还是：

```text
较多 ECS tasks × 单个 worker
```

### 14. 建立资源基线

选择 Fargate task size 前需要记录：

- 压缩镜像大小
- 解压镜像大小
- 模型 artifact 大小
- 启动时间
- Idle memory
- Peak memory
- CPU saturation point
- 可接受 latency 下的 requests per second

### 15. 补充业务级可观测性字段

基础的结构化日志、`request_id`、access log 已经在第 1 项里完成。这里延后的
是更细粒度的业务字段，等 RAG pipeline 有实际打点需求时再加：

- `retrieval_count`（检索到的候选数）
- `model_name` / `model_revision`（当前生效的 embedding/reranker 版本）
- `error_code`（已在错误响应里有，日志里补充记录）

LangChain/LangSmith tracing、metadata 和隐私策略继续延后到核心系统完成之后。

### 16. 精细化限流（按用户维度）

第 1 项已经上了**按 IP、`10/minute` 的止血型限流**（方向 C）。它够挡住脚本
狂刷，但按 IP 计数在校园 WiFi / 宿舍 NAT 下会**多人共享一份额度**，可能误伤
正常用户。等前端和用户体系确定后再做精细化：

- 确定限流维度：登录用户 ID、会话 token，或按渠道发放的 `X-API-Key`。
- 可能需要把限流检查挪到鉴权**之前 / 同层**，以便对"狂试错误 key"也计数
  （当前鉴权失败不计入限流，见第 1 项已知取舍）。
- 若届时已做多实例水平扩容，改用 Redis 等共享存储做分布式限流（当前单实例
  内存态足够，不需要）。
- 可考虑分层限额：正常用户宽松额度 + 全局兜底额度保护 OpenAI 账单。

在此之前,`CHAT_RATE_LIMIT` 可直接通过环境变量按实际用量调整,无需改代码。

### 17. 确定生产 RDS 配置

连接数预算计算方式：

```text
ECS task count
  x Uvicorn workers per task
  x retriever pool_max_size
  + pipeline, migration, and operations connections
```

还需要确定：

- 支持的 PostgreSQL 和 pgvector 版本
- TLS 要求，例如 `sslmode=require`
- Connection timeout
- Private subnet
- Security group
- Backup retention
- Multi-AZ 要求
- Maintenance 和 upgrade policy

## 当前已经具备的部署基础

以下部分已经适合继续向 AWS 推进：

- `.env`、virtual environment、cache、tests、notebook 和大部分本地数据已从
  Docker build context 排除。
- 没有发现 tracked `.env` 或 private key。
- Runtime secret 通过环境变量读取（ECS 可以直接用 Secrets Manager 注入同名
  环境变量，代码不需要改动）。
- FastAPI lifespan 会在 shutdown 时关闭 PostgreSQL connection pool。
- Docker 使用 JSON-form `CMD`，Uvicorn 可以接收 termination signal。
- Database migration 可以通过 Alembic 独立运行。
- `/health`、`/ready` 和 `/status` 职责分离。
- Runtime database 和 OpenAI failure 已有安全的公开错误响应。
- 已有 unit test 和真实 pgvector integration test。

## 推荐交付顺序

### Phase 1：生产 API 容器与可观测性/安全基础

1. ✅ 完成第 1 项"保护付费的 `/chat` 接口"的分步实施清单（结构化日志、
   request_id、CORS、安全响应头、rate limiting、兜底异常处理）。
2. ✅ 确定并实现模型交付策略（模型烤入单一 `Dockerfile`，启动本地加载无联网）。
3. ✅ 固定模型 revision。
4. ✅ 创建最小化且锁定版本的 API runtime environment（`pyproject.toml` + `uv.lock`，
   `api`/`pipeline` group，slim 多阶段镜像；依赖锁定 + 镜像瘦身已落地）。
5. ✅ 固定基础镜像（`python:3.11-slim` 钉 digest）。
6. ✅ 使用 non-root runtime user（`appuser`）。
7. ✅ 在本地构建并测量镜像（API 3.35GB / Pipeline 3.06GB；冷启动→`/health` ~7s；
   idle 内存 ~950 MiB）。
8. ◻ 验证 startup、shutdown、health、readiness 和 first-request 行为（`/health` +
   模型本地加载 + 启动耗时已验；`/ready`（需 DB）、shutdown、first-request
   latency 延后至 Phase 2 连同负载测试）。

> **Phase 1 剩余聚焦**：第 6 项（依赖锁定）+ 第 7 项（镜像瘦身）+ 第 5 项
> （固定基础镜像）+ 把第 2/4/5 项在 `Dockerfile.gpu` 侧对齐，然后本地构建并
> 测量镜像大小 / 启动时间 / 内存 / first-request latency。

### Phase 2：安全的 AWS API 基础设施

1. 使用 infrastructure as code 创建 VPC、subnet、security group、ECR、ECS、
   ALB、RDS、Secrets Manager、CloudWatch 和 IAM。
2. 配置 ECS 和 ALB health check。
3. 配置访问 OpenAI 所需的 outbound network。
4. 将 migration 作为部署关卡。
5. 部署 API 并运行 smoke test。

### Phase 3：生产 Pipeline

1. Storage abstraction 已在第 3 项提前落地（接口 + `LocalStorage` + 逐咽喉点迁移
   + 入口串联，见「### 3」的分步实施清单）；本阶段只需补 `S3Storage` 实现。
2. 使用 S3 保存 artifact、report 和 checkpoint（入口把 `LocalStorage` 换成
   `S3Storage`，上层 stage 代码不改）。
3. 将 pipeline stage 作为一次性或定时 ECS task 运行。
4. 增加 pipeline alarm 和失败恢复流程。

### Phase 4：CI/CD 和运维

1. GitHub Actions 使用 AWS IAM OIDC。
2. Pull request 运行 unit test 和 pgvector integration test。
3. 构建镜像并使用 immutable tag 推送到 ECR。
4. 部署 service 前运行 migration。
5. 增加 deployment rollback 和部署后 smoke test。
6. 增加 dashboard、alarm、request log 和 capacity metric。

### Phase 5：延后处理的改进

1. 增加 LangChain/LangSmith tracing，并定义 metadata 隐私规则。
2. 修改微信清洗行为前增加 golden tests。
3. 只有 CPU 测试数据证明有必要时，才评估 GPU inference。
4. 只有模型放入镜像不再可行时，才评估 EFS model cache。

## 当前最需要决定的问题

第 1 项（保护 `/chat`、结构化日志）是当前正在按分步清单推进的工作，一步
一步做、每步单独验证。

其次是模型如何进入 ECS。推荐的首版方案是：

```text
将固定 revision 的 embedding model 和 reranker model 放入 API 镜像。
```

在本地完成镜像构建，并测量以下指标之前，不应创建正式 AWS 基础设施：

- 镜像大小
- 启动时间
- 内存使用
- Shutdown 行为
- First-request latency
