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

改了 `settings.py` 的话这一步会慢很多——模型层会失效重传 600MB,这是已知的债
(见 aws-foundation.md「还没做的」)。

### 2. ⭐ 先改库:跑迁移任务

迁移任务做两件事,都以 RDS 主用户的身份:`alembic upgrade head`,然后
`python -m ops.provision_runtime_role`——把 API 连库用的那个低权限角色 `cssa_app`
的权限重新对齐到代码里的清单,并当场验证它做不了迁移能做的事。所以**新表的授权跟着建表
的那次迁移一起落地**,不需要另外记得。

> 前提:`cssa-da-prod-runtime-db-password` 这个密钥里**必须已经有值**。第一次用它之前的
> 做法见文末[「一次性:切换到运行时身份」](#一次性切换到运行时身份105)。

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

日志在这里(只看这一次任务的那条日志流):

```bash
aws logs tail /ecs/cssa-da-prod-migrate --region ap-southeast-2 --since 1h \
  --log-stream-name-prefix "ecs/migrate/${TASK##*/}"
```

> `exitCode` 是 `null` 而不是数字,通常意味着容器压根没起来(拉镜像失败、架构不对、
> 密钥取不到)。这种情况 `reason` 字段会说明原因。

成功时日志最后几行是授权脚本的输出:

```text
Runtime role cssa_app: updated
  knowledge_base: SELECT
  pipeline_runs: SELECT
  chat_interactions: INSERT
  chat_interactions (request_id): SELECT
```

如果是它报错(`error: role 'cssa_app' is not least-privilege: ...`),说明数据库里有人
手工给这个角色、或给 `PUBLIC` 加过权限。脚本**故意不替你收回**给 `PUBLIC` 的授权——那会
影响所有角色——报错里会列出是哪张表、哪项权限,查清来源、手工收回后重跑本步。

> 同样的报错也会出现在**往 `public` 里装了一个把视图开放给 `PUBLIC` 的扩展**之后(比如
> `pg_stat_statements`)。扩展请装进它自己的 schema(`CREATE EXTENSION ... SCHEMA ...`),
> 别装进 `public`;确实要放在 `public` 的,把它的对象加进脚本的清单,而不是绕过检查。

### 4. 上代码

```bash
terraform -chdir=infra apply -var="image_tag=$SHA"
```

这会注册新的 API 任务定义并滚动更新服务。部署有熔断器,新任务一直不健康会自动回滚。

```bash
SVC=$(terraform -chdir=infra output -raw ecs_service_name)
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SVC" --region ap-southeast-2
```

**`services-stable` 在回滚之后也会返回**——回滚到旧版本同样是「稳定」。所以要确认跑着的
是刚注册的那一版:

```bash
aws ecs describe-services --cluster "$CLUSTER" --services "$SVC" --region ap-southeast-2 \
  --query 'services[0].deployments[?status==`PRIMARY`].{taskDefinition:taskDefinition,rollout:rolloutState}'
```

`rollout` 要是 `COMPLETED`,`taskDefinition` 要等于 `terraform apply` 刚注册的那一版
(`terraform -chdir=infra state show aws_ecs_task_definition.api | grep arn` 能看到)。熔断器
回滚时 `rollout` 是 `FAILED`,`taskDefinition` 是旧的那一版。

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

**还有一条:API 要读写的新表,同一个提交里改授权清单。** API 连库用的是低权限角色
`cssa_app`,它只能碰
[ops/provision_runtime_role.py](../ops/provision_runtime_role.py) 里
`RUNTIME_TABLE_PRIVILEGES` / `RUNTIME_COLUMN_PRIVILEGES` 列出的东西。本地和 CI 都用超级
用户连库,所以漏了这一步**只有生产会报 permission denied**。在
[tests/integration/test_runtime_role.py](../tests/integration/test_runtime_role.py) 里给
新的代码路径加一条,CI 就能替你发现。

**反过来,从清单里删权限要分两次发版**——和删列一样。迁移任务用的是新镜像,它一跑就把
新清单之外的权限收回了,而此刻旧任务还在服务;回滚也不会重跑迁移任务,新清单会一直留着。
所以先发一版代码不再用它,下一版才从清单里删。

---

## 出问题了

**迁移失败(第 3 步 exitCode 非 0)** —— 服务没被碰过,线上是好的。看日志,修,重来。
Alembic 记录了自己跑到哪一版,重跑不会重复执行已经成功的那些。

**服务起不来(第 4 步卡住)** —— 熔断器会自动回滚到上一版任务定义。但**迁移已经执行了**,
所以旧代码现在跑在新表结构上——这就是上面那条硬规则存在的理由。

**要手动回滚** —— 用上一个 commit 的 sha 重新跑第 4 步。迁移不要回滚,让新结构留着。

---

## 导入或更新语料

语料导入**不在 API 容器里跑**:API 连库用的 `cssa_app` 写不了 `knowledge_base`,这是
故意的。导入以迁移身份跑,方法是用迁移任务定义起一个一次性任务,把命令换成「下载语料 +
导入」,并把 CPU / 内存调大(导入要加载嵌入模型,迁移任务的 512MB 装不下)。

下面沿用第 2 步的 `CLUSTER` / `FAMILY` / `SUBNETS` / `SG`,以及第 4、5 步的 `SVC` / `URL`。

**1. 准备一个一小时有效的语料下载链接。**容器里没有 AWS CLI 也没有权限读桶,预签名链接
把授权写在 URL 里。

- **换一份新语料**:转换步骤(`python -m pipelines transform-wechat`)的产物在
  `data/current/wechat_articles_processed.json`,把它传上去:

  ```bash
  BUCKET=$(terraform -chdir=infra output -raw data_bucket)
  aws s3 cp data/current/wechat_articles_processed.json \
    "s3://$BUCKET/current/wechat_articles_processed.json"
  ```

- **用桶里已经有的那一份**(比如给已经导入过的语料补坐标):**不要上传**——上传会覆盖它。
  先确认桶里现在那一版是你以为的那一版(桶开了版本控制):

  ```bash
  BUCKET=$(terraform -chdir=infra output -raw data_bucket)
  aws s3api list-object-versions --bucket "$BUCKET" \
    --prefix current/wechat_articles_processed.json \
    --query 'Versions[].{latest:IsLatest,modified:LastModified,size:Size}'
  ```

然后生成链接:

```bash
CORPUS_URL=$(aws s3 presign "s3://$BUCKET/current/wechat_articles_processed.json" \
  --expires-in 3600 --region ap-southeast-2)
```

**2. 起一次性任务。**链接通过环境变量传进去,不拼进命令字符串:

```bash
jq -n --arg url "$CORPUS_URL" '{
  cpu: "1024", memory: "4096",
  containerOverrides: [{
    name: "migrate",
    environment: [{name: "CORPUS_URL", value: $url}],
    command: ["sh", "-c",
      "mkdir -p data/current && python -c \"import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])\" \"$CORPUS_URL\" data/current/wechat_articles_processed.json && python -m pipelines import-knowledge-base --reset-checkpoint"]
  }]
}' > /tmp/import-overrides.json

TASK=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$FAMILY" \
  --launch-type FARGATE --region ap-southeast-2 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}" \
  --overrides file:///tmp/import-overrides.json \
  --query 'tasks[0].taskArn' --output text)

aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK" --region ap-southeast-2
```

`--reset-checkpoint`:容器每次都是新的,本来就没有 checkpoint;写上它是为了让这条命令的
含义不依赖这一点。`wait` 最多等 10 分钟,导入比这久就再敲一次 `wait`。导入会从 Hugging
Face 下载一次嵌入模型(走 NAT),这是故意的,原因见
[aws-foundation.md 第 14 步](design/implemented/aws-foundation.md)。

**3. 确认成功,读结果。**先看退出码,和第 3 步一样:

```bash
aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" --region ap-southeast-2 \
  --query 'tasks[0].containers[0].{exitCode:exitCode,reason:reason}'
```

`exitCode` 必须是 `0`。然后读这一次任务的日志——任务的文件系统随任务消失,**日志最后那一行
`command_completed` 带着导入报告的全部要点**:

```bash
aws logs tail /ecs/cssa-da-prod-migrate --region ap-southeast-2 --since 1h \
  --log-stream-name-prefix "ecs/migrate/${TASK##*/}" | grep '"command_completed"'
```

| 字段 | 应该是 |
|---|---|
| `status` | `completed` |
| `corpus_sha256` | 64 位十六进制。**这就是这份语料的坐标**,下一步要用 |
| `knowledge_base_rows` | 部署后 `/ready` 必须报同一个数 |
| `unique_record_count` / `corpus_rows` | 相等:这份语料的每一条都原样在库里 |
| `rows_outside_corpus` | 通常是 0。大于 0 表示库里还有不属于这份语料、但同一模型嵌入的行(比如更新语料时被删掉的文章),`/ready` 会数它们、检索也会返回它们 |
| `affected_count` | 这次改动了几行;库里已经是同一份语料时是 0 |
| `limit` | 不应出现(出现说明只导了前 N 条) |
| `model_name` / `model_revision` / `target_id` | 用的是哪个模型、连的是哪个库 |

退出码非 0 时日志里会写明原因;`KnowledgeBaseImportIncompleteError` 表示**导完之后库里并没有
这份语料**,按报错里的提示处理。**把这一行存下来**,下一步要贴进 PR——日志组只保留 90 天。

**4. 把坐标配给 API,同一次坐下来做完。**导入完成的那一刻起,API 服务的已经是新语料,但它的
`CORPUS_SHA256` 还是旧值,直到这一步部署完。所以别隔天。

把 `corpus_sha256` 写进 [infra/variables.tf](../infra/variables.tf) 里 `corpus_sha256` 的
`default`,在分支上提交、开 PR,把上一步那一行日志贴进 PR 描述。然后**立刻**部署——不用重新
构建镜像:`infra/` 不进镜像,代码没变,沿用正在跑的那个 tag:

```bash
RUNNING=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SVC" \
  --region ap-southeast-2 --query 'services[0].taskDefinition' --output text)
TAG=$(aws ecs describe-task-definition --task-definition "$RUNNING" --region ap-southeast-2 \
  --query 'taskDefinition.containerDefinitions[0].image' --output text)
terraform -chdir=infra apply -var="image_tag=${TAG##*:}"
```

再做第 4 步末尾的回滚检查。不要用 `-var corpus_sha256=...` 临时传:漏传一次,新任务定义里
这个变量就没了,每一行 `chat_interactions` 的「哪份语料」又悄悄变回 null。也**不要自己对文件
算 hash**——这个值的意义就在于它来自真正把数据导进去的那一次运行。

**5. 核对。**

```bash
curl -s "$URL/ready" | jq '{status, knowledge_base_rows}'
```

`knowledge_base_rows` 必须等于第 3 步日志里的数。

---

## 轮换运行时数据库密码

Postgres 一个角色只有一个密码,改了立刻生效;而 API 任务只在**启动时**从 Secrets Manager
读一次密码。所以顺序必须是:

1. 往密钥里写新值(做法见 [infra/secrets.tf](../infra/secrets.tf) 顶部注释)。
2. 跑一次迁移任务:只要第 2 步里的 `aws ecs run-task` 和 `wait`,再加第 3 步的检查——任务
   定义没变,**不需要**那条 targeted `terraform apply`。它把 `cssa_app` 的密码改成新值。
3. **马上**让 API 重新起任务读新密码,并确认滚动完成:

   ```bash
   aws ecs update-service --cluster "$CLUSTER" --service "$SVC" --force-new-deployment \
     --region ap-southeast-2
   aws ecs wait services-stable --cluster "$CLUSTER" --services "$SVC" --region ap-southeast-2
   ```

第 2 步和第 3 步之间,旧任务已有的连接还能用,但**新开的连接会认证失败**:`/ready` 会报
503,那段时间里的 `chat_interactions` 写入会失败(只记日志)。所以两步之间不要停。

---

## 核对:数据库没有被暴露过

#105 的完成标准之一是「RDS 全程没有公网地址,也没有为导入加进 SG、事后忘了删的规则」。
看 Terraform 文件不够——在控制台手工加的规则既不在文件里,也不会出现在 `terraform plan`
的差异里。要看**线上实际的状态**,以及**这段时间里发生过什么**:

```bash
RDS_SG=$(terraform -chdir=infra output -raw rds_security_group_id)
DB_ID=$(aws rds describe-db-instances --region ap-southeast-2 \
  --query 'DBInstances[0].DBInstanceIdentifier' --output text)

# 1. 现在没有公网地址
aws rds describe-db-instances --region ap-southeast-2 \
  --query 'DBInstances[].{id:DBInstanceIdentifier,public:PubliclyAccessible}'

# 2. 现在只有一条入站规则:来源是 ECS 任务的安全组,端口 5432
aws ec2 describe-security-group-rules --region ap-southeast-2 \
  --filters Name=group-id,Values="$RDS_SG" \
  --query 'SecurityGroupRules[?IsEgress==`false`].{port:FromPort,fromGroup:ReferencedGroupInfo.GroupId,cidr4:CidrIpv4,cidr6:CidrIpv6,prefixList:PrefixListId}'

# 3. 过去 90 天里,谁动过这个安全组和这个数据库实例(CloudTrail 只保留 90 天)
for RESOURCE in "$RDS_SG" "$DB_ID"; do
  aws cloudtrail lookup-events --region ap-southeast-2 \
    --lookup-attributes AttributeKey=ResourceName,AttributeValue="$RESOURCE" \
    --query 'Events[?ReadOnly==`false`].{time:EventTime,event:EventName,user:Username}'
done
```

期望:

- 第 1 条:`public` 是 `false`。
- 第 2 条:只有一条,`fromGroup` 等于 `terraform -chdir=infra output -raw ecs_tasks_security_group_id`,
  没有任何 `cidr4` / `cidr6` / `prefixList`。
- 第 3 条:安全组上只有 Terraform 建栈时的 `CreateSecurityGroup` / `AuthorizeSecurityGroupIngress`
  (每次重建一组),**没有**导入期间的 `AuthorizeSecurityGroupIngress` / `ModifySecurityGroupRules`;
  实例上没有 `ModifyDBInstance`(除了建栈时的)。拿不准某一条是什么,看它的明细——把 query 换成
  `Events[].CloudTrailEvent`,里面的 `requestParameters` 写着改了什么(`ModifyDBInstance` 的
  `publiclyAccessible`、入站规则的来源 CIDR)。

---

## 一次性:切换到运行时身份(#105)

在此之前,API 和迁移都用 RDS 主用户连库。下面这些只做一次,之后就是上面的常规流程。
**顺序不能换**:先有角色,API 才能用它登录;先把语料的坐标记下来,API 才能带着它上线。

**1. 建好密码密钥并写入值。**密钥得先存在才能写值:

```bash
terraform -chdir=infra apply -target=aws_secretsmanager_secret.runtime_db_password
openssl rand -base64 36 | tr -d '\n' > /tmp/p
aws secretsmanager put-secret-value --region ap-southeast-2 \
  --secret-id "$(terraform -chdir=infra output -raw runtime_db_password_secret_name)" \
  --secret-string file:///tmp/p
rm /tmp/p
```

**2. 构建并推送镜像**(第 0、1 步)。

**3. 跑迁移任务**(第 2、3 步)。日志里应该是 `Runtime role cssa_app: created`。targeted
apply 会顺带把「执行角色能读新密钥」那条权限一起建好——迁移任务定义依赖它。

**4. 导入语料并记下坐标**(上面「导入或更新语料」的第 1–3 步)。先看库里现在有什么:

```bash
curl -s "$URL/ready" | jq '{status, knowledge_base_rows}'
```

- **2312,且 `ready`**(还是 #111 导入的那一份):**用桶里已有的那一版,不要上传**,先按第 1
  步确认它的修改时间是 #111 导入的那天(2026-09-17)。期望 `affected_count` 为 0、
  `knowledge_base_rows` 等于 `unique_record_count`、`rows_outside_corpus` 为 0——这三个数一起
  证明库里正是这份语料,此时的 `corpus_sha256` 就是它的坐标。`affected_count` 不是 0,说明桶里
  这份和库里原来的内容有出入;现在库里已经是桶里这份了,`corpus_sha256` 对它依然成立,把这件事
  记在 #105 上。
- **0,或者不是 `ready`**(栈被重建过):就是一次正常的首次导入,用「换一份新语料」那条路。

**5. 配上坐标并部署 API。**和「导入或更新语料」第 4 步一样提交 `variables.tf`、开 PR,但这次
部署用第 2 步构建的镜像:`terraform -chdir=infra apply -var="image_tag=$SHA"`。这次部署会把
API 切到 `cssa_app`。**这个 PR 同时在 [ROADMAP_versions.md](roadmap/ROADMAP_versions.md) 和
[ROADMAP_platform.md](roadmap/ROADMAP_platform.md) 里勾掉第 20 项**,并把第 4 步那一行日志和
下面第 6 步的输出贴进描述——这样 roadmap 的勾和它的证据落在同一个 PR 里。

**6. 核对完成标准:**

```bash
# API 跑着的是刚注册的那一版(不是被熔断器回滚后的旧版)
aws ecs describe-services --cluster "$CLUSTER" --services "$SVC" --region ap-southeast-2 \
  --query 'services[0].deployments[?status==`PRIMARY`].{taskDefinition:taskDefinition,rollout:rolloutState}'

# 就看那一版:API 用 cssa_app 和运行时密钥,有 CORPUS_SHA256
RUNNING=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SVC" \
  --region ap-southeast-2 --query 'services[0].taskDefinition' --output text)
aws ecs describe-task-definition --task-definition "$RUNNING" --region ap-southeast-2 \
  --query 'taskDefinition.containerDefinitions[0].{env:environment[?name==`DB_USER`||name==`CORPUS_SHA256`],secrets:secrets[].{name:name,from:valueFrom}}'

# 迁移任务仍然用主用户
aws ecs describe-task-definition --task-definition "$FAMILY" --region ap-southeast-2 \
  --query 'taskDefinition.containerDefinitions[0].secrets[].{name:name,from:valueFrom}'

curl -s "$URL/ready" | jq '{status, knowledge_base_rows}'
```

期望:`rollout` 是 `COMPLETED`;API 那一版有 `DB_USER=cssa_app` 和 `CORPUS_SHA256`,`secrets` 里
没有 `DB_USER`,`DB_PASSWORD` 的 `from` 是运行时密码密钥;迁移任务的 `DB_USER` / `DB_PASSWORD`
的 `from` 是 RDS 主用户密钥(`terraform -chdir=infra output -raw db_secret_arn`);`/ready` 是
`ready`,行数等于第 4 步日志。再做一遍上面的[「核对:数据库没有被暴露过」](#核对数据库没有被暴露过)。

---

## 从零重建之后

栈 destroy 之后再 apply(#111 的设计允许这么做),数据库是空的,`cssa_app` 也不存在,API 起
不来是正常的。按这个顺序把它带回来:

1. 按 [aws-foundation.md「演练:destroy 与重建」](design/implemented/aws-foundation.md#演练destroy-与重建)
   建出栈、推镜像。
2. **三个**应用密钥都要有值:OpenAI、chat key、运行时数据库密码(还在 7 天恢复期内的,用
   `aws secretsmanager restore-secret` 捞回来,连值都不用重灌)。
3. 跑迁移任务(第 2、3 步)——建表,建出 `cssa_app`。
4. 导入语料(「导入或更新语料」第 1–3 步)。用的是同一份文件的话,日志里的 `corpus_sha256`
   应该等于 `variables.tf` 里已经提交的值;不一样就按第 4 步提交新值。
5. 让 API 重新起任务,并确认滚动完成、`/ready` 转绿:

   ```bash
   aws ecs update-service --cluster "$CLUSTER" --service "$SVC" --force-new-deployment \
     --region ap-southeast-2
   aws ecs wait services-stable --cluster "$CLUSTER" --services "$SVC" --region ap-southeast-2
   curl -s "$URL/ready" | jq '{status, knowledge_base_rows}'
   ```

---

## 相关文档

- [aws-foundation.md](design/implemented/aws-foundation.md) —— 这些东西是什么、为什么这么建
- [CONTRIBUTING.md](../CONTRIBUTING.md) —— 提交、分支和 review 约定
