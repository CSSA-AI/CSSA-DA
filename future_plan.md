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

### 1. 保护付费的 `/chat` 接口

当前 `POST /chat` 没有鉴权和限流。如果直接暴露到公网，任何人都可以触发：

- Embedding 计算
- Reranker 推理
- OpenAI API 调用
- AWS 计算资源消耗

需要完成：

- 确定并实现鉴权方案。
- 增加按客户端计算的 rate limiting。
- 保留请求大小限制。
- 增加 access log 和稳定的 `request_id`。
- 保持安全、稳定的公开错误响应。

验收条件：

- 匿名或无效客户端无法调用 `/chat`。
- 单个客户端无法超过规定的请求频率。
- 鉴权失败时不会执行 retrieval、reranking 或 OpenAI 调用。

### 2. 让模型交付过程可预测

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

## 高优先级容器工作

### 4. 使用 non-root 用户运行容器

当前两个 Dockerfile 都以 root 用户运行。

需要完成：

- 创建专用 application user。
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

### 9. 完善 readiness 语义

当前 `/ready` 会检查数据库和有效 knowledge-base rows，但不会证明：

- Embedding model 已加载
- Reranker 已加载
- RAG pipeline 已成功初始化

需要完成：

- 记录 RAG component 初始化状态。
- 保持 `/health` 轻量，并且不依赖外部服务。
- 只有 task 确实能够处理 `/chat` 时，`/ready` 才返回成功。

### 10. 清理初始化失败响应

运行期间的 RAG 错误已经使用安全的公开响应，但 dependency 初始化失败时，当前
HTTP 503 仍可能包含原始 exception 内容。

需要完成：

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

### 15. 改进结构化应用日志

应用已经将日志输出到 stdout 和 stderr，可以接入 CloudWatch。完整 tracing 可以延后，
但应先增加基础运维字段：

- `request_id`
- `duration_ms`
- `status_code`
- `error_code`
- `retrieval_count`
- `model_name`

LangChain/LangSmith tracing、metadata 和隐私策略继续延后到核心系统完成之后。

### 16. 确定生产 RDS 配置

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
- Runtime secret 通过环境变量读取。
- FastAPI lifespan 会在 shutdown 时关闭 PostgreSQL connection pool。
- Docker 使用 JSON-form `CMD`，Uvicorn 可以接收 termination signal。
- Database migration 可以通过 Alembic 独立运行。
- `/health`、`/ready` 和 `/status` 职责分离。
- Runtime database 和 OpenAI failure 已有安全的公开错误响应。
- 已有 unit test 和真实 pgvector integration test。

## 推荐交付顺序

### Phase 1：生产 API 容器

1. 确定并实现模型交付策略。
2. 固定模型 revision。
3. 创建最小化且锁定版本的 API runtime environment。
4. 固定基础镜像。
5. 使用 non-root runtime user。
6. 在本地构建并测量镜像。
7. 验证 startup、shutdown、health、readiness 和 first-request 行为。

### Phase 2：安全的 AWS API 基础设施

1. 使用 infrastructure as code 创建 VPC、subnet、security group、ECR、ECS、
   ALB、RDS、Secrets Manager、CloudWatch 和 IAM。
2. 在公开 `/chat` 前增加 authentication 和 rate limiting。
3. 配置 ECS 和 ALB health check。
4. 配置访问 OpenAI 所需的 outbound network。
5. 将 migration 作为部署关卡。
6. 部署 API 并运行 smoke test。

### Phase 3：生产 Pipeline

1. 增加 storage abstraction。
2. 使用 S3 保存 artifact、report 和 checkpoint。
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

首先决定模型如何进入 ECS。推荐的首版方案是：

```text
将固定 revision 的 embedding model 和 reranker model 放入 API 镜像。
```

在本地完成镜像构建，并测量以下指标之前，不应创建正式 AWS 基础设施：

- 镜像大小
- 启动时间
- 内存使用
- Shutdown 行为
- First-request latency
