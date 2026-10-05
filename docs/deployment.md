# 部署清单

把一个 commit 发到生产。照着做,不要跳步。

> **这份文档迟早会消失。** 它现在是一份人照着敲的清单,而清单的问题是「人可以跳过
> 任何一步」。Phase 4 上了 CI 之后,下面这些会变成流水线里的几格,那时这份文档就只
> 剩「为什么是这个顺序」还有用。在那之前,**它就是唯一的关卡**,所以第 2 步不能省。

---

## 需要什么

- `aws` CLI,凭据配好(`aws sts get-caller-identity` 能出你的身份)
- `terraform`、`docker`、`jq`
- 在 Apple Silicon 上构建。镜像是 ARM64 的,x86 机器构建出来的镜像**在 Fargate 上起不来**

下面所有可变的值都从 `terraform output` 取,不要抄硬编码的 ID——重建一次就全变了。

---

## 顺序为什么是这个

一次发版要发生两件事:**数据库改结构**,和**新代码上线**。顺序只有一个是对的:

```
先改库,再上代码    ✅  旧代码不碰新列,照常跑
先上代码,再改库    ❌  新代码去查一个还不存在的列,当场 500
```

所以第 2 步必须在第 4 步之前,而且**第 2 步失败就不要做第 4 步**。这就是「关卡」的全部
含义。

---

## 步骤

### 0. 确认你在要发布的那个 commit 上

```bash
git status --short          # 应该是空的
git log --oneline -1
SHA=$(git rev-parse --short=8 HEAD)
echo "要发布: $SHA"
```

工作区不干净就停下。镜像 tag 是 commit,如果本地有未提交的改动,tag 就在说谎——而
`GIT_SHA` 会被写进每一条 `chat_interactions` 记录,那是将来排查问题的依据。

### 1. 构建并推送镜像

```bash
ECR=$(terraform -chdir=infra output -raw ecr_repository_url)

aws ecr get-login-password --region ap-southeast-2 \
  | docker login --username AWS --password-stdin "${ECR%%/*}"

docker build -f Dockerfile.api -t "$ECR:$SHA" .
docker push "$ECR:$SHA"
```

ECR 仓库是 `IMMUTABLE` 的:**同一个 tag 不能推第二次**。如果要重推同一个 commit(比如
上次构建坏了),得先把旧镜像删掉。

改了 `app/core/config/rag-config.yaml` 里的模型选择,这一步会慢很多——600MB 的模型层
失效、重新下载、全量重传。**只有换模型时才该这样**;改别的代码(包括 `settings.py`)
用的是缓存层,推送只传变化的那几 MB。

### 2. ⭐ 先改库:跑迁移任务

```bash
CLUSTER=$(terraform -chdir=infra output -raw ecs_cluster_name)
FAMILY=$(terraform -chdir=infra output -raw ecs_migrate_task_family)
SUBNETS=$(terraform -chdir=infra output -json private_subnet_ids | jq -r 'join(",")')
SG=$(terraform -chdir=infra output -raw ecs_tasks_security_group_id)
```

迁移任务的镜像版本也是 Terraform 管的,所以先只更新它、**不要碰服务**:

```bash
terraform -chdir=infra apply \
  -target=aws_ecs_task_definition.migrate \
  -var="image_tag=$SHA"
```

然后跑:

```bash
TASK=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$FAMILY" \
  --launch-type FARGATE --region ap-southeast-2 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' --output text)

aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK" --region ap-southeast-2
```

### 3. ⭐ 确认它成功了,否则到此为止

```bash
aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" --region ap-southeast-2 \
  --query 'tasks[0].containers[0].{exitCode:exitCode,reason:reason}'
```

**`exitCode` 必须是 `0`。** 不是 0 就停下,不要做第 4 步——此刻服务还没被碰过,线上跑的
仍然是好的旧版本,你有时间慢慢查。

成功长这样(2026-09-22 实测,当时无待执行的迁移):

```
{ "exitCode": 0, "reason": null }
```

从 `run-task` 到任务停止约一到两分钟,**其中大部分时间在拉 982MB 的镜像**,不是在跑
迁移。`aws ecs wait` 期间终端没有任何输出,那是正常的。

日志在这里:

```bash
aws logs tail /ecs/cssa-da-prod-migrate --region ap-southeast-2 --since 10m
```

没有待执行的迁移时,日志只有 alembic 的两行连接信息——**看着像什么都没发生,那就是对的**。
有迁移要跑时,每一条会打出 `Running upgrade <from> -> <to>`。

> `exitCode` 是 `null` 而不是数字,通常意味着容器压根没起来(拉镜像失败、架构不对、
> 密钥取不到)。这种情况 `reason` 字段会说明原因。

### 4. 上代码

```bash
terraform -chdir=infra apply -var="image_tag=$SHA"
```

这会注册新的 API 任务定义并滚动更新服务。部署有熔断器,新任务一直不健康会自动回滚。

```bash
aws ecs wait services-stable --cluster "$CLUSTER" \
  --services "$(terraform -chdir=infra output -raw ecs_service_name)" \
  --region ap-southeast-2
```

### 5. 验证

```bash
URL=$(terraform -chdir=infra output -raw alb_url)
curl -s "$URL/ready" | jq .
```

`status` 要是 `ready`。负载均衡器的健康检查看的就是这个接口,所以它不绿,流量根本不会
进来。

---

## 写迁移时的硬规则

> **每个迁移执行之后,上一版代码必须仍然能正常工作。**

**关卡保证不了这条。** 因为滚动更新不是一瞬间的:新容器起来了、旧容器还没退,这几分钟
里**新旧代码同时在跑**,而数据库已经是新结构了。这是每一次正常部署的常态,不是意外。

而且回滚只换镜像,**不会撤销迁移**。出事了你能在 30 秒内退回旧代码,但表结构退不回去。

实践上:

| 改动 | 行不行 |
|---|---|
| 加一列(可空,或有默认值) | ✅ |
| 加一张表 | ✅ |
| 加索引 | ✅ |
| 删列、改列名、改类型 | ❌ **不能一步到位** |

要删一列得**分两次发版**:先发一版代码不再读写它,等它上线稳定了,下一版才真的 `DROP`。

这条没法自动检查,只能靠 review 时有人问一句:**「这个迁移下去之后,旧代码还活得了吗?」**

---

## 出问题了

**迁移失败(第 3 步 exitCode 非 0)** —— 服务没被碰过,线上是好的。看日志,修,重来。
Alembic 记录了自己跑到哪一版,重跑不会重复执行已经成功的那些。

**服务起不来(第 4 步卡住)** —— 熔断器会自动回滚到上一版任务定义。但**迁移已经执行了**,
所以旧代码现在跑在新表结构上——这就是上面那条硬规则存在的理由。

**要手动回滚** —— 用上一个 commit 的 sha 重新跑第 4 步。迁移不要回滚,让新结构留着。

---

## 相关文档

- [aws-foundation.md](design/implemented/aws-foundation.md) —— 这些东西是什么、为什么这么建
- [CONTRIBUTING.md](../CONTRIBUTING.md) —— 提交、分支和 review 约定
