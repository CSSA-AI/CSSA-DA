# CSSA-DA 平台方向路线图

本文是**平台与部署**方向的路线图：容器化、AWS 基础设施、CI/CD、可观测性、安全。

另外两条线：

- 数据与语料、ground truth dataset → **[ROADMAP_data.md](ROADMAP_data.md)**
- 查询链路与评估工具 → **[ROADMAP_rag.md](ROADMAP_rag.md)**

三条线并行推进，与本线的耦合点见第 18 项。

**每一项属于哪个版本、什么时候做,见 [ROADMAP_versions.md](ROADMAP_versions.md)。**

---

## 部署目标


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

> ⏰ **2026-08-09 补充**：本项设计时**还没有前端**，`CHAT_API_KEY` 的定位是
> 「internal test clients 用的共享 key」（见 `deps.py` docstring），限流按 IP 也
> 明确标注为「保命型止血」。前端出现后，这两个前提都变了 —— 见
> [第 19 项](#19-前端接入的安全边界2026-08-09-新增v1-阻塞项)。
>
> **状态：已完成并验证（8 步全部落地）。** 设计与实现细节见
> [docs/design/chat-api-hardening.md](../design/implemented/chat-api-hardening.md)。
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

### 2. 让模型交付过程可预测 ✅ 已完成

> **状态：已完成。** `ops/download_models.py`（含 `--models` 选择）在可缓存镜像
> 层下载模型，revision 固定在 `app/core/config/rag-config.yaml`，`Dockerfile.api`
> / `Dockerfile.pipeline` 设置 `MODEL_DIR`，`app/main.py` lifespan 在接流量前
> 调用 `model_registry.preload_models()`，`ModelRegistry` 用 `local_files_only`
> 加载本地模型。实测冷启动 ~7s 内模型加载完毕，首个请求无需联网下载。
> （GPU Dockerfile 已删除，不再有 GPU 侧待补齐。）下面保留原始设计记录。

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

### 3. 使用持久化存储代替本地 pipeline 文件 ✅ 存储抽象已完成（S3 留 Phase 3）

> **状态：接口 + `LocalStorage` + 各咽喉点迁移 + 入口串联已完成**（见下方分步
> 实施清单步骤 1–5 全部 ✅）。**`S3Storage` 实现留到 Phase 3**（真正上 AWS 时，
> 上层 stage 代码零改动，仅入口换后端）。

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

### 4. 使用 non-root 用户运行容器 ✅ 已完成

> **状态：已完成。** `Dockerfile.api` 与 `Dockerfile.pipeline` 都创建 system
> 用户 `appuser` 并以 `USER appuser` 运行，`COPY --chown=appuser` 交付
> venv/models/代码。（GPU Dockerfile 已删除。）`readonlyRootFilesystem` 留到
> Phase 2 写 ECS task definition 时评估。

已完成：

- 创建专用 application user（`appuser`，两个镜像均是）。
- 只授予该用户所需应用目录和 cache 目录的访问权限。
- 在 ECS task definition 中评估启用 `readonlyRootFilesystem`（留 Phase 2）。

### 5. 固定基础镜像 ✅ 已完成

> **状态：已完成。** `Dockerfile.api` / `Dockerfile.pipeline` 均以
> `python:3.11-slim@sha256:db3ff2…` 固定 digest 起步，uv 二进制也按 digest 钉死
> （`ghcr.io/astral-sh/uv:0.11.32@sha256:df4c…`）。详见「### 5+6+7 合并实施」。
> 下面保留原始条目。

`Dockerfile.cpu`（历史）当前使用：

```dockerfile
FROM continuumio/miniconda3:latest
```

需要完成：

- 将 CPU 基础镜像固定到经过审核的版本或 digest。
- 开始 GPU 部署时，将 GPU 基础镜像固定到经过审核的 digest。
- 建立受控的基础镜像更新流程。

### 6. 锁定 runtime 依赖 ✅ 已完成

> **状态：已完成。** `pyproject.toml` 声明直接依赖（`api`/`pipeline`/`dev`
> group），`uv.lock` 锁定全部 transitive；本地 / CI / 生产镜像统一走这份锁。
> ML 核心钉到验证过的版本，torch 走 CPU index。详见「### 5+6+7 合并实施」。
> 下面保留原始条目。

（历史）当前 Conda environment 文件包含大量未固定版本的依赖，不同时间构建可能得到
不同的运行环境。

需要完成：

- 为每种 runtime 定义唯一的直接依赖来源。
- 生成可重复的 lock file。
- 根据需要拆分 CPU、GPU、pipeline、test 和 development 依赖。
- 明确列出直接 runtime 依赖，避免依靠 transitive dependency 安装。

### 7. 缩小 API 镜像 ✅ 已完成

> **状态：已完成。** 换 slim 基础镜像 + 多阶段构建（final 阶段无 uv/编译器/dev
> 工具）+ 拆 API/Pipeline 双镜像。jupyter/matplotlib/pytest/mypy 等均不进生产。
> 实测 API 3.35GB / Pipeline 3.06GB（torch + 模型为硬成本；相比 conda 全家桶
> 5–8GB 大幅瘦身）。详见「### 5+6+7 合并实施」。下面保留原始条目。

（历史）CPU environment 包含多项 API runtime 不需要的工具，例如：

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
> 镜像）本质是同一件事，合并实施。设计与实现细节、基础知识见
> [docs/design/deployment-packaging.md](../design/implemented/deployment-packaging.md)。

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

#### 11.1 硬规则：每个 migration 必须向后兼容上一版代码

**代码能秒回滚，数据库不能。**

```
出问题 → 重新部署上一个镜像 → 30 秒回到旧代码  ✅
      → 但 migration 已经执行，表结构已经改了   ❌
```

回滚只换镜像，**不会撤销 migration**。所以：

> **每个 migration 执行之后，上一版代码必须仍能正常工作。**

不满足这条，回滚就成了「代码退回去了但数据库回不去」，服务反而更坏。

**安全的改动**（可以单次部署）：

- 加表 —— 旧代码不认识它，无影响
- 加**可空**列，或带默认值的列
- 加索引

**危险的改动**（必须拆成两次部署）：

| 想做的事 | 部署 1 | 部署 2 |
|---|---|---|
| 删列 | 发一版代码，不再读写该列（列仍在） | 确认稳定后，migration 删列 |
| 改列类型 | 加新列、双写、代码读新列 | 删旧列 |
| 加非空列 | 先加可空列 + 回填 | 再加 NOT NULL 约束 |
| 重命名列 | 等价于「加新列 + 删旧列」，同上 | |

中间任何一步回滚，代码和数据库都对得上。

**这条约束比部署自动化本身更重要** —— 自动化只是让部署更快，而这条决定了出事时
救不救得回来。

> 落到眼前的例子：`chat_interactions` 建表（[ROADMAP_rag.md](ROADMAP_rag.md)
> Phase 4.5）是**加表**，安全，单次部署即可；后续那些 `feedback` / `user_id` /
> `token_usage` 扩展列都是**可空加列**，同样安全。这是当初把它们设计成 nullable
> 的另一个理由。

### 12. 设计 outbound networking

Private ECS task 必须能够访问 OpenAI。

> **已确认（2026-08-03）：运行时不需要 Hugging Face 出网。** 两个镜像在
> `docker run --network none` 下都能完整加载模型（api 6.27s / pipeline 6.60s，
> 两模型均 `ready`）。模型在构建期由 `ops/download_models.py` 烤入 `/models`，
> 运行时经 `MODEL_DIR` 走 `local_files_only=True` 的本地分支
> （`app/services/rag/model_registry.py`）。
>
> 导入日志里那条 `You are sending unauthenticated requests to the HF Hub` 是
> `huggingface_hub` 初始化时无条件打印的提示，**不代表发生了网络请求**。

因此出站需求收敛为一份确定清单：

| Task | 需要的出站连接 | 不需要 |
|---|---|---|
| API | OpenAI API | Hugging Face |
| Pipeline（harvest 阶段） | 微信 API | Hugging Face |
| Pipeline（transform / embed / import） | 仅 RDS（VPC 内） | 任何公网 |

这让出网可以按目的地白名单收紧，而不是「开个 NAT 放行全部」；也意味着
transform/embed/import 可以放在完全不出网的子网里。

需要完成：

- 将 API task 放在 private subnet。
- 提供受控的 outbound internet access（按上表最小化）。
- Inbound 只允许来自 ALB security group。
- RDS 只允许来自 ECS task security group。
- ⚠️ 把 `MODEL_DIR` 当作 task definition 的必填项校验。它一旦缺失，
  `model_registry` 会**静默回退**到连 Hugging Face 下载（见
  `_load_embedding_model` 的 else 分支），在 private subnet 里表现为启动卡死到
  超时且日志难以定位。更彻底的做法是直接删掉该回退分支——生产镜像永远自带模型。

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

> ⏰ **2026-08-10：本项已升级为 v1 必做。** 原文写的是「等**前端和用户体系确定后**
> 再做」—— 前端已确认是 Django + 已有登录，且[第 19.7 项](#197--已确认走-bff2026-08-10)
> 已选定走 BFF。BFF 之后所有请求都从同一个 IP 发出，`get_remote_address` 失去区分度，
> 全体用户会挤在一份 `10/minute` 里。
>
> **实现要点**：`key_func` 改读 `X-User-Id`；**该 header 缺失时回退到 IP**，否则在
> BFF 上线之前所有请求会挤进同一个桶，比现状更糟。不需要验证 header 真伪 —— 只有
> 持 `CHAT_API_KEY` 的 BFF 能进门，这是标准的 trusted proxy 做法。

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

### 18. 检索质量评估与模型选型 → 已拆分到另外两条线

这一项的完整内容已拆走，本文只保留与平台线的耦合点：

- **语料建设、ground truth dataset、数据源接入** → [ROADMAP_data.md](ROADMAP_data.md)
- **查询链路、评估工具、架构实验** → [ROADMAP_rag.md](ROADMAP_rag.md)

**两条线并行推进**：数据线 Phase 0–4 全程不碰数据库，平台线的大头（网络、IAM、
ECR、Secrets、迁移编排）与模型选型完全无关，不需要等待。真正需要对齐的只有下面
七项：

| # | 耦合点 | 平台侧要做什么 | 必须在何时收敛 |
|---|---|---|---|
| 1 | **`doc_id` 链路修复** | `pg_retriever` 补 `SELECT id` 并传到 `SearchResult`。这**改变 `/chat` 响应体**——当前每次响应都在吐一个随机 UUID（`Article.id` 是 `default_factory=uuid4`），是公开契约变更 | ⏰ **上线、前端接入之前**。趁没有真实客户端，改起来零成本 |
| 2 | **向量维度** | `VECTOR(384)` 写死。若选型结论是 1024 维模型，需 ALTER + 全库重嵌入重导 | ⏰ **建 RDS 前**。现在 DB 是一次性容器，迁移=删了重来；上生产后要变成停机窗口+回滚方案，成本差一个数量级 |
| 3 | **模型文件大小** | 模型烤入镜像。若换成 bge-m3 + bge-reranker-v2-m3（约各 2.2GB），镜像从 3.35GB 冲到 ~7GB，**Phase 1 的验收基线（冷启动 7.5s / idle 944MiB）全部要重测**，并可能推翻第 4.1 项的「烤入镜像」方案 | ⏰ **写 ECS task definition 前** |
| 4 | **`top_k`** | 现 retriever `top_k=5`、reranker `top_k=3`，评估要求 deep pool（50）。5→50 让每请求 CPU 差 10 倍 | ⏰ **第 13/14 项（worker/扩容策略、资源基线）定稿前** |
| 5 | **PII 脱敏 stage** | 小助手 1:1 问答是求助场景的私密对话，含真名/微信号/学号/手机号。**脱敏 + 个人化内容筛选必须是 pipeline 的一个 stage，在入库之前执行** —— 放到下游就等于原始 PII 已经进了 Postgres 和 S3 | Phase 3 生产 Pipeline 设计时 |
| 6 | **`held_out_for_eval` 排除** | eval 划走的对话不能回流进语料。标记落在源头，**由 ingest 阶段强制排除** —— 否则下次重跑管线会静默污染 eval set，且**没有任何报错** | 同上 |
| 7 | **query 不进日志 + log group 保留期** | 改口径（2026-08-10）：`orchestrator.py` 那句 `"Starting RAG pipeline for query: %s"` **去掉 query**；日志只记 `request_id` + `doc_id` + `score` + `rank`，query / answer 落 [ROADMAP_rag.md](ROADMAP_rag.md) Phase 4.5 的 `chat_interactions`，`request_id` 作 join key。原方案「改成 `extra={"query": ...}` 给 CloudWatch Insights 挖」在 4.5 落地后已被取代 —— Postgres 能 SQL 查、能 join `knowledge_base`、带 `config` 指纹、反馈可回填，而两边都写会让同一份用户内容有两套保留期、两个访问控制面。仍需设定 log group 保留期限（当前无限期）。**已确认可用于分析，将在隐私声明中告知** | 与第 15 项一并做 |

> **一个可选的降级方案**：若不希望本线受任何阻塞，可先只做 **reranker 的替换** ——
> 它不动 schema、不动向量维度、不需要重嵌入，只是换镜像里的模型文件。而当前
> `cross-encoder/ms-marco-MiniLM-L12-v2` 不只是英文模型的问题，**任务类型也是错的**
> （ms-marco 训练的是 query→段落，而本系统主任务是问题↔问题匹配），大概率是投入
> 产出比最高的单点改动。详见 [ROADMAP_data.md](ROADMAP_data.md) Phase 3。


### 19. 前端接入的安全边界（2026-08-09 新增，v1 阻塞项）

前端团队已存在（网页 + 已有登录系统），这触发了第 1 项当初显式挂起的决定
（见[第 16 项](#16-精细化限流按用户维度)：「等**前端和用户体系确定后**再做」）。

#### 19.1 先分清两把钥匙

系统里有两把 key，容易混：

```
浏览器 ──带 CHAT_API_KEY──► CSSA-DA 后端 ──带 OPENAI_API_KEY──► OpenAI
         ↑ 第一道门                        ↑ 第二道门
   「你有资格调我的 /chat 吗」        ✅ 只在服务器上，从不外泄
```

| 钥匙 | 谁持有 | 状态 |
|---|---|---|
| `OPENAI_API_KEY` | 只有 CSSA-DA 后端 | ✅ 安全，一直都安全 |
| `CHAT_API_KEY` | **谁调 `/chat` 谁得带** | ⚠️ 见下 |

`require_internal_api_key` 检查的是**第二把**。**OpenAI 密钥一步都没泄漏，但「花这笔
钱的权限」会随前端代码公开** —— 卡锁在保险箱里，但门禁卡人手一张。

#### 19.2 为什么登录不能替代

登录管的是「谁能进网页」，不管「网页里有什么」。用户一旦登录成功，网页代码连同内嵌
的 key 已经在他的电脑上，登录不会阻止他按 F12。

三条现实泄漏路径，按概率排序：

1. **前端仓库公开 → key 进 git 历史**（最现实；GitHub 上有专门扫密钥的爬虫，且删掉
   也没用，历史还在）
2. **用户无意泄漏** —— 截 Network 面板的图发群里问「为什么报错」
3. 内测用户里有人写脚本绕过网页直接调

> 诚实评估：有登录 + 纯内测 + 用户是熟人，**实际泄漏概率确实低**。对内测阶段这个
> 风险水平可能已经可以接受 —— 前提是损失封顶（19.4）且前端仓库不公开。

#### 19.3 两条路径（✅ 已选定 BFF，见 19.7）

| 方案 | 成本 | 风险 |
|---|---|---|
| **接受 key 公开** | 零 | key 会泄漏，靠 19.4 封顶损失 |
| **BFF（前端服务端持有 key）** | 前端约二十行 | key 永不离开服务器 |

**有登录恰恰说明 BFF 的基础已经有了** —— 登录必须在服务端验证，所以前端团队已经有
一台服务器。BFF 不是新建系统，是在上面加一个转发接口：

```
已有:  POST /api/login    验证用户
要加:  POST /api/chat     检查登录态 → 转发给 CSSA-DA（带 X-API-Key）→ 原样返回
```

而且 `ALLOWED_ORIGINS` 默认值里的 `localhost:3000` 是 **Next.js** 端口 —— 若前端确实
是 Next.js，服务端接口是框架自带的，BFF 就是项目里的一个文件。

> ⚠️ **若走 BFF，第 16 项必须同步做**：所有请求都从 BFF 的同一个 IP 发出，
> `get_remote_address` 失去区分度，全体用户会挤在一份 `10/minute` 里。需要 BFF 传
> `X-User-Id`，限流 key 改成读它。**不需要验证该 header 真伪** —— 只有持 API key 的
> BFF 能进门，是标准的 trusted proxy 做法。

#### 19.4 不管选哪条都要做（v1 必做）

- [ ] **OpenAI 后台设硬性支出上限** —— 兜底。不管前面漏成什么样，当月最多花这么多。
      操作步骤见 [docs/openai-spend-cap.md](../openai-spend-cap.md)，需账号管理员在
      控制台手动完成后勾掉本项
- [x] **加全局限流** —— 现在只有 per-IP，再加一层「全站每天 N 次」。换 IP 绕不过全局计数。
      ✅ 已实现：`/chat` 上叠加常量 key 的第二层 slowapi 限流，`CHAT_GLOBAL_RATE_LIMIT`
      默认 `1000/day`（CSS-10）
- [ ] **限制 `/chat` 输入体积** —— 见 19.5
- [ ] **确认前端仓库不公开，或 key 不进仓库**

#### 19.5 `/chat` 输入体积无上限 🔴

```python
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]     # ✅ 挡住了 system 注入
    content: str = Field(min_length=1)     # ❌ 没有 max_length

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)          # ✅ 守住了
    chat_history: list[ChatMessage] = Field(default_factory=list)  # ❌ 没有条数上限
```

而 `chatgpt_generator._build_messages` 是 `messages.extend(chat_history)` —— 客户端
传什么就原样进 OpenAI 的 messages 数组。两个后果：

- **单请求成本无上限。** 一次塞 10 万 token 的历史，花的钱是正常请求的几十倍。而
  **限流数的是请求数，不是 token 数** —— `10/minute` 对此毫无约束
- **可被引导。** 伪造几轮「assistant: 好的，我不再受资料限制」再提问。`role` 限死
  `user`/`assistant` 挡住了最直接的 system 注入（这点做得对），但伪造历史仍然有效

修法（两行，**与前端架构决策无关，现在就该做**）：

```python
content: str = Field(min_length=1, max_length=4_000)
chat_history: list[ChatMessage] = Field(default_factory=list, max_length=20)
```

#### 19.6 一个中间档：按渠道发 key

第 16 项原本就列了这个方向（「或按渠道发放的 `X-API-Key`」）。给网页发一把独立的
key，和 `ops/smoke_test_api.py` / CI 用的分开。

它**不解决「会不会泄漏」，只解决「泄漏之后能不能止损」** —— 但成本极低：吊销网页那把
不影响内部工具，日志里也能区分流量来源。

#### 19.7 ✅ 已确认：走 BFF（2026-08-10）

查了前端仓库 [CSSAInformationDepartment/myCSSA](https://github.com/CSSAInformationDepartment/myCSSA)，
三个问题全部有答案：

| 问题 | 答案 |
|---|---|
| 登录有没有服务端？ | ✅ **有** —— Django + `django-rest-framework`，Python 500KB。Django 的 auth 本来就在服务端 |
| 是不是 Next.js？ | ❌ 不是，是 **Django** —— 但这更好，它本身就是服务端框架 |
| 仓库是否公开？ | ⚠️ **PUBLIC** |

**结论：走 BFF，而且几乎没有成本。** Django 已经是服务端，BFF 不是「新建一个服务」，
就是加一个 view：

```python
@login_required
def chat_proxy(request):
    # 内测阶段：再加一个 allowlist 检查
    resp = requests.post(
        f"{CSSA_DA_URL}/v1/chat",
        json=json.loads(request.body),
        headers={
            "X-API-Key": settings.CSSA_DA_API_KEY,   # 只存在于服务器
            "X-User-Id": str(request.user.id),        # 给限流和记录用
        },
        timeout=35,
    )
    return JsonResponse(resp.json(), status=resp.status_code)
```

`@login_required` 顺带解决内测资格（再加一个 allowlist 即可，CSSA-DA 侧零改动）。
团队有 DRF 经验，这套写法熟悉。

**仓库 public 让这个选择更没有悬念**：key 一旦进前端代码，就会永久留在公开仓库的
git 历史里 —— 删掉文件也没用。

##### 由此确定的三件事

1. **接口契约**（由 CSSA-DA 定，前端照做）：
   - 调 `POST /v1/chat`（含版本前缀）
   - 带 `X-API-Key`，值从 Django settings / 环境变量读，**绝不进前端模板或 JS**
   - 带 `X-User-Id`，用作限流维度与 `chat_interactions` 的记录维度
   - `X-Request-ID` 响应头**透传回浏览器**并保存（反馈与排障要靠它）
   - 错误响应原样透传（401 / 429 / 503 / 504 都有安全格式的 body）
2. **[第 16 项](#16-精细化限流按用户维度)从「延后」升级为 v1 必做** —— BFF 之后所有
   请求都来自同一个 IP，`get_remote_address` 失去区分度。
   ⚠️ 实现时 `X-User-Id` 缺失要**回退到 IP**，否则在 BFF 上线之前所有请求会挤进同
   一个桶，比现状更糟。
3. **`chat_interactions` 加 `user_id` 列** —— 见
   [ROADMAP_rag.md](ROADMAP_rag.md) Phase 4.5。内测期最有价值的是能追到具体的人去问
   「这个回答哪里不好」。

##### CORS 可以收了

走 BFF 之后浏览器只调自己的服务器（同源），`ALLOWED_ORIGINS` 只需保留本地开发用的
`localhost` 条目。

---

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
7. ✅ 在本地构建并测量镜像（API 3.35GB / Pipeline 3.06GB；冷启动→`/health` ~7.5s；
   idle 内存 ~944 MiB）。
8. ✅ 验证 startup、shutdown、health、readiness 和 first-request 行为
   （2026-08-03 本地实测，见下方「Phase 1 收尾验证记录」）。

> **Phase 1 已全部完成。** 原先「剩余聚焦」列出的第 5/6/7 项均已落地；其中提到的
> `Dockerfile.gpu` 已不存在——GPU 路线在打包阶段废弃，torch 固定为 CPU wheel，
> 现在只有 `Dockerfile.api` 和 `Dockerfile.pipeline`。

#### Phase 1 收尾验证记录（2026-08-03，本地 Docker Desktop / Windows）

验证环境：`cssa-da-api:latest` + `cssa-da-pipeline:latest` 本地重建，pgvector
容器，`knowledge_base` 导入 200 行。

| 指标 | 实测 | 结论 |
|---|---|---|
| 冷启动 → `/health` | 7.49s / 7.57s（两次） | 与既有记录一致 |
| Idle 内存 | 943.9 MiB | 与既有记录一致 |
| `/health` 延迟 | warm ~2ms（首次 16ms） | 适合 ECS container health check |
| `/ready` 延迟 | 稳定 ~10ms | 适合 ALB target health check |
| `/ready` not-ready | 503，`reason` 为 curated 文案，无内部细节 | 第 9/10 项在真实 DB 上复验通过 |
| `/ready` ready | 200，`knowledge_base_rows: 200` | — |
| `/chat` 首请求 | 4662ms | ⚠️ 见下方「first-request 冷惩罚」 |
| `/chat` 稳态 | 均值 2584ms（2386–2882） | 由 OpenAI 生成耗时主导 |
| SIGTERM（空闲） | 1.67s 退出，exit code 0 | 远低于 ECS 默认 30s stopTimeout |
| SIGTERM（有在途请求） | 3.01s 退出，exit 0，在途 `/chat` 完整返回 200 | 滚动发布不丢请求 |
| 关闭后 PG 后端连接 | 1 → 0 | lifespan 确实关闭了连接池 |
| 离线加载（`--network none`） | api 6.27s / pipeline 6.60s，两模型 ready | 运行时不需要任何公网 |
| 单元测试 | 188 passed | — |

补充验证：`/chat` 与 `/status` 在缺 key / 错 key 时均返回 401；安全响应头
（`X-Request-ID`、`nosniff`、`X-Frame-Options: DENY`、`no-referrer`、HSTS）齐全；
uvicorn 关闭日志四步完整（`Shutting down` → `Waiting for application shutdown` →
`Application shutdown complete` → `Finished server process`）。

**first-request 冷惩罚（待修）**：首个 `/chat` 比稳态慢约 **2.1 秒**。原因不是模型
加载（模型已在 lifespan 预加载），而是 `app/api/deps.py` 的
`_build_rag_orchestrator` 用 `lru_cache` 懒构建——第一个请求才创建 PG 连接池和三个
组件。在 ECS 上这意味着：新 task 通过 `/ready` 后 ALB 立即导流，**第一个真实用户
承担这 2.1 秒**，而 `/ready` 此时已宣称 ready。

建议修法：在 lifespan 的模型预加载之后同步构建一次 orchestrator，把这段成本移到启动
期（冷启动约 7.5s → 9.6s，仍远低于 `Dockerfile.api` 中 healthcheck 的 60s
`start-period`）。这样 `/ready` 的语义才真正等于「能以全速服务」。

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

#### CI 与 CD 分别指什么

| 缩写 | 全称 | 含义 |
|---|---|---|
| **CI** | Continuous **Integration** | 每次改动自动跑测试，保证能合进主干 |
| **CD** | Continuous **Delivery** | 通过测试的代码**随时可上线**，但由人决定何时 |
| **CD** | Continuous **Deployment** | 通过测试的代码**自动上线**，无人参与 |

**本项目选 Continuous Delivery，不选 Deployment**，即部署由 **tag 触发**而非
push 到 `main` 触发。理由：

- OpenAI 花的是真钱，一个 bug 自动上线可能直接烧账单
- 没有 on-call，半夜自动部署挂了没人知道
- 社团项目没有「必须几分钟内上线」的需求

Continuous Deployment 适合一天发几十次、有完整告警与自动回滚的团队 —— 我们不需要
那个速度，却要付它的可靠性代价。

**这个选择的直接含义**：`main` 可以自由累积提交而不影响生产；只有打 tag 才部署。
因此**不需要 `develop` / `prod` 这类长期环境分支** —— 「什么在生产」由 tag 和
镜像 tag 回答，不由分支回答。分支模型见
[CONTRIBUTING.md](../../CONTRIBUTING.md#branching-model)。

```
push / PR ──► CI：单测 + 集成测试 + docker 构建检查        ← 已经有了
                      │
                  merge 到 main
                      │
                  打 tag v0.1.1
                      │
        ┌──────────── CD ────────────┐
        │ 1. 构建镜像，tag = git sha   │
        │ 2. 推到 ECR                 │
        │ 3. 跑 Alembic migration     │  ← 第 11 项部署关卡
        │ 4. 更新 ECS service（滚动）  │
        │ 5. 等健康检查通过            │
        │ 6. 跑 smoke test            │
        │ 7. 失败 → 回滚上一个镜像     │
        └─────────────────────────────┘
```

#### 清单

| # | 事项 | 属于 |
|---|---|---|
| 1 | GitHub Actions 使用 AWS IAM OIDC | CD 前提 |
| 2 | Pull request 运行 unit test 和 pgvector integration test | **CI ✅ 已有** |
| 3 | 构建镜像并使用 immutable tag 推送到 ECR | CD |
| 4 | 部署 service 前运行 migration（见[第 11 项](#11-定义-migration-部署关卡)） | CD |
| 5 | 增加 deployment rollback 和部署后 smoke test | CD |
| 6 | 增加 dashboard、alarm、request log 和 capacity metric | 运维 |
| 7 | 代码质量工具链（见 [4.2](#42-代码质量工具链当前缺口)） | CI |
| 8 | 发布自动化：校验 Conventional Commits、生成 CHANGELOG、自动打 tag（见 [CONTRIBUTING.md](../../CONTRIBUTING.md#versioning-and-releases)） | CD |

**现状：CI 已经有了，缺的全是 CD。**

#### 4.2 代码质量工具链（当前缺口）

现状：**CI 里没有任何 linter 或 formatter**；`mypy` 在 `dev` 依赖组里，但既没有
配置文件也不在 CI 里跑。风格与类型问题只能靠人 review 时肉眼发现。

**先说清楚期望值。** 回看目前发现的所有真问题 —— doc_id 链路断裂、两个 evaluator
口径不一致、`precision_at_k` 除错、随机负例、handbook 抓取中断、`chat_history` 无
上限、API key 会泄漏 —— **全部是语义问题，lint 一个都抓不到**。所以这一项是**便宜
的保险，不是提升质量的手段**，不要排在测试前面。

仍然值得做的两个理由：

1. **`ruff check` 不只是格式化**，`F821`（未定义名字）、`F401`（未使用 import）、
   `B006`（可变默认参数）这些能抓真 bug —— 而且恰好对上 LLM 辅助开发的典型失误：
   用一个不存在的函数、留下改到一半的死代码。
2. **review 注意力是瓶颈**。凡是机器能挡的就不该占用人的注意力，人应该盯「这个设计
   对不对」，而不是「这里少了个 import」。

##### 配置

`pyproject.toml`：

```toml
[tool.ruff]
target-version = "py311"
line-length = 88          # 现有代码 p99 就是 88，几乎不动到现有行
extend-exclude = ["migrations/versions", "scripts", "cssa-ci"]

[tool.ruff.lint]
# 只选“能抓 bug”的，不开那 800 条风格规则
select = [
    "E4", "E7", "E9",  # pycodestyle：真错误，不含 line-too-long
    "F",               # pyflakes：未定义名字、未使用 import ← 核心价值
    "B",               # bugbear：可变默认参数等
    "I",               # isort：import 排序
    "UP",              # pyupgrade：py311 现代写法
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]        # 重新导出，不算未使用
"tests/**" = ["B011"]

[tool.ruff.lint.flake8-bugbear]
# ⚠️ 没有这段，B008 会把 FastAPI 依赖注入全部误报
extend-immutable-calls = [
    "fastapi.Depends", "fastapi.Security", "fastapi.Query",
    "fastapi.Body", "fastapi.Header", "fastapi.Path",
]

[tool.mypy]
python_version = "3.11"
files = ["app", "pipelines"]
ignore_missing_imports = true   # sentence_transformers / peft / slowapi 无 stub
warn_unused_ignores = true
warn_redundant_casts = true
# 先不开：disallow_untyped_defs / strict
```

> **`flake8-bugbear` 那段是关键。** B008 规则是「不要在参数默认值里调用函数」，而
> FastAPI 的依赖注入正是这么写的（`app/api/deps.py` 的 `Security(...)`、
> `app/main.py` 的 `Depends(...)`，共 5 处）。不配这段，第一次跑就是一屏假报警，
> 然后 ruff 就会被整体关掉。
>
> **mypy 别一上来开 strict** —— 会产生几百个错误然后被忽略，等于没配。先跑绿，
> 再逐模块收紧。

`dev` 依赖组加 `"ruff"`。

##### CI：`.github/workflows/lint.yml`

```yaml
name: lint
on:
  pull_request:
    branches: [main]
  push:
    branches: [main, "feature/**", "dev/**", "chore/**", "fix/**"]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy
```

push 的分支列表**必须和 `unit-test.yml` 保持一致**，否则又会出现「某个前缀不跑
CI」那类不一致（见 [CONTRIBUTING.md](../../CONTRIBUTING.md#branching-model)）。

##### 落地顺序：分两步，别一次做完

**第一步 —— 只上 `ruff check`。** 改动很小（就是修出来的那些真问题），价值立刻兑现：

```bash
uv add --dev ruff
uv run ruff check .            # 先看有多少
uv run ruff check --fix .      # 能自动修的先修
```

**第二步 —— 再上 `ruff format`。** 这一步会重排全仓库（引号、空行、trailing
comma），diff 很大。单独一个 commit，并配 blame 忽略：

```bash
uv run ruff format .
git commit -am "style: apply ruff format across the repo"
git rev-parse HEAD >> .git-blame-ignore-revs
git config blame.ignoreRevsFile .git-blame-ignore-revs   # 每人配一次
```

**这样 `git blame` 会跳过那个纯格式化 commit**，不会所有行都指向它。GitHub 也认
`.git-blame-ignore-revs` 这个文件。

##### 时机

**在有大批新代码之前做。** RAG 线 Phase 1/2（评估工具、可插拔架构）会新增不少
文件，先立规则比事后统一格式便宜得多 —— 后者会产生一个巨大的、和功能无关的 diff，
既淹没 review 又污染 `git blame`。

因此本项在 [ROADMAP_versions.md](ROADMAP_versions.md) 里标为 **v2 建议提前**，
而不是跟着 Phase 4 走到 v4。

### Phase 5：延后处理的改进

1. 增加 LangChain/LangSmith tracing，并定义 metadata 隐私规则。
2. 修改微信清洗行为前增加 golden tests。
3. 只有 CPU 测试数据证明有必要时，才评估 GPU inference。
4. 模型交付方式：达到下方阈值前，一律保持「烤入镜像」。

#### 4.1 模型交付方式：现状、阈值与备选（2026-08-03 实测）

**现状构成**（`cssa-da-api:latest`，3.35GB）：

| 内容 | 大小 |
|---|---|
| `.venv` 依赖 | 1.5 GB（其中 torch 单独 754 MB） |
| `/models` 两个模型 | 605 MB（embedding 477 MB + reranker 129 MB） |
| 应用代码 | 5.5 MB |

**模型只占镜像 18%，地板由 torch 决定**：即使把模型全部移出镜像，镜像仍在 2.7GB
量级。因此「模型撑爆镜像」要到相当大的规模才成立。

**为什么镜像大小在 Fargate 上仍需盯住**：Fargate **不跨 task 缓存镜像**，每启动一个
新 task 都要从 ECR 完整拉取。镜像大小直接乘进冷启动、扩容速度、滚动发布每一批和
ECR 传输量。（ECS on EC2 会在实例上缓存镜像，只有节点上第一个 task 付这个代价——
所以「换 EC2 launch type」本身也是一个备选。）

**触发阈值**（替代原先含糊的「不再可行」）：

- `/models` < 2 GB → 保持烤入，不讨论。
- 2–5 GB → 实测一次 ECR 拉取耗时，对照扩容 SLO 再定。
- \> 5 GB，或任何自托管 LLM → 改用下方备选，或转 ECS on EC2 吃镜像缓存。

参考体量：embedding / reranker 换 large 级（bge-m3、multilingual-e5-large 一类）后
`/models` 约 4.6 GB，镜像约 7 GB；自托管 7B 模型 fp16 约 14 GB，届时烤入方案失效。
注意生成走 OpenAI API，除非改为自托管 LLM，否则只有 embedding / reranker 会增长。

**⚠️ S3 在 Fargate 上无法挂载。** S3 是对象存储而非文件系统；`s3fs` /
`Mountpoint for S3` 依赖 FUSE，而 Fargate 不提供 `/dev/fuse` 也不给 `SYS_ADMIN`。
ECS task definition 支持的卷类型里没有 S3。因此备选只有两条：

| | 烤入镜像（现状） | EFS 挂载 | S3 + 启动时下载 |
|---|---|---|---|
| 镜像大小 | 大 | 小 | 小 |
| 模型加载速度 | 本地盘，最快 | NFS，明显慢（模型是几百个小文件，每次冷启动重付） | 下载后本地盘，最快 |
| 启动耗时 | 拉镜像（含模型） | 无下载，但读文件走网络 | 拉镜像 + 下载模型 |
| 换模型 | 重建 + 重新部署 | 传 EFS 即可 | 传 S3 + 重启 task |
| 常驻成本 | 无 | 有：按 GB/月 + 吞吐量，每 AZ 一个 mount target | 近乎为零 |
| 运维复杂度 | 最低 | 最高 | 中 |
| 版本可追溯 | 最好：镜像 tag = 代码 + 模型版本 | 差：EFS 内容可被随时改动，故障难复现 | 中：可用带版本的 S3 前缀 |

**若将来必须拆分，倾向 S3 + 启动时下载而非 EFS**：EFS 的小文件读性能对模型加载不
友好且每次冷启动重付；EFS 是常驻成本 + 常驻运维；而烤入方案「镜像 tag 即模型版本」
这一可追溯性很有价值，EFS 会打破它，S3 用带版本前缀能保住大部分。

**关键：三种方案都不需要改代码。** `MODEL_DIR` 只是一个文件系统路径，指向
`/models`、`/mnt/efs/models` 还是 `/tmp/models`，`model_registry` 的
`local_files_only=True` 分支一字不改，差别全在 task definition 和启动脚本里。因此
这个决定可以推迟到模型真的变大、有实测数据时再做。

## 当前最需要决定的问题

第 1 项（保护 `/chat`、结构化日志）已完成。模型进入 ECS 的首版方案也已确定并落地：

```text
将固定 revision 的 embedding model 和 reranker model 放入 API 镜像。
```

**「创建正式 AWS 基础设施」的前置门槛已全部满足**（2026-08-03 本地实测，明细见
Phase 1 的「收尾验证记录」）：

| 门槛指标 | 状态 |
|---|---|
| 镜像大小 | ✅ API 3.35GB / Pipeline 3.06GB |
| 启动时间 | ✅ 冷启动 → `/health` 7.5s |
| 内存使用 | ✅ idle 943.9 MiB |
| Shutdown 行为 | ✅ 1.67s 优雅退出（exit 0）；在途请求完整排空 |
| First-request latency | ✅ 已测：首个 `/chat` 4662ms，稳态 2584ms |

因此 Phase 2（AWS 基础设施）现在可以开工。进入 Phase 2 前建议先修掉 Phase 1 记录
中的 **first-request 冷惩罚**（在 lifespan 预热 orchestrator），否则 `/ready` 通过
后仍有约 2.1 秒的首请求代价，会干扰后续负载测试的基线。

**与 Phase 2 并线的第二条线**：第 18 项（检索质量评估与模型选型）现在开工，它对
Phase 2 的依赖已被设计为零（评估 harness 直接读语料快照，不连 DB）。但其中 4 个
耦合点必须在指定时机收敛，最紧的一个是 `Article.id` 修复 —— 它改变 `/chat` 响应
体，**必须在 Phase 2 上线、前端接入之前完成**。详见第 18 项。

下一批需要决定的问题落在 Phase 2 自身：

- 第 8 项：ECS container health check 与 ALB target group health check 的具体配置
  （语义已定：`/health` 给 ECS，`/ready` 给 ALB；模型 readiness 已完成，前置条件
  满足）。
- 第 11 项：migration 作为部署关卡的编排方式（Compose 的 `depends_on` 在 ECS 不
  继承）。
- 第 12 项：出网设计（出站清单已收敛，见该项表格）。
