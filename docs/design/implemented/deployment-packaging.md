# 部署打包:依赖锁定与容器镜像 —— 设计说明

本文记录「把项目打包成可部署产物」这项工作的设计细节、背后的取舍,以及为看懂
这些配置所需的基础知识。整体路线图见 [ROADMAP_platform.md](../../roadmap/ROADMAP_platform.md)
第 5 / 6 / 7 项(并涉及第 2、4 项),本文是它们的详细展开。

工作按「每步单独实现、单独验证、单独 review」的方式推进(与
[chat-api-hardening.md](./chat-api-hardening.md)、
[storage-abstraction.md](./storage-abstraction.md) 同一套节奏)。本文兼作
**学习参考**,面向没接触过依赖管理 / Docker 的读者:先给全局大图,再补基础知识,
最后才逐步讲实现。凡是用到的概念,都在「基础知识」章节从头讲清,正文再引用。

---

## 目录

- [背景](#背景)
- [先看全局:从代码到「能到处跑的盒子」](#先看全局从代码到能到处跑的盒子)
- [基础知识](#基础知识)
  - [一、可复现的两层:声明 vs 锁定](#一可复现的两层声明-vs-锁定)
  - [二、按角色切分依赖:group 与虚拟项目](#二按角色切分依赖group-与虚拟项目)
  - [三、一个镜像是怎么造出来的](#三一个镜像是怎么造出来的)
  - [四、torch 为什么特殊(粘合:依赖 × 镜像大小)](#四torch-为什么特殊粘合依赖--镜像大小)
- [实现步骤](#实现步骤)
  - [Step 1:pyproject.toml + uv.lock](#step-1pyprojecttoml--uvlock)
  - [Step 2:CI 切换到 uv](#step-2ci-切换到-uv)
  - [Step 3:slim 多阶段镜像,拆 api / pipeline](#step-3slim-多阶段镜像拆-api--pipeline)
  - [Step 4:conda yml 定位为 DS 环境](#step-4conda-yml-定位为-ds-环境)
  - [Step 5:本地构建与测量](#step-5本地构建与测量)
- [两条线、三份声明:全景对照](#两条线三份声明全景对照)
- [测试与验证策略](#测试与验证策略)
- [完成情况与后续](#完成情况与后续)

---

## 背景

Phase 1 的目标是把 CSSA-DA 变成**可安全、可复现、可稳定部署**到 AWS 的东西。
这需要先解决打包层面的三个毛病:

1. **依赖会漂移,不可复现。** 同一个依赖(`fastapi`、`torch`…)在三个地方各写
   一遍——生产用的 `environment_cpu.yml`(conda)、GPU 用的
   `environment_gpu.yml`、CI 用的 `requirements-ci.txt`(pip),而且**几乎都不锁
   版本**。今天构建和下个月构建,装到的版本可能不同;CI 测过的版本,和生产装的
   也可能不是同一个。「在我机器上能跑」不等于「到服务器能跑」。

2. **镜像巨大、混入无关工具。** 生产镜像以 `continuumio/miniconda3:latest`
   为底(科学计算全家桶),还顺手装了 `jupyter`、`matplotlib`、`ipython`、
   `pytest`、`mypy`——这些**只有数据科学家写 notebook 才用,API 服务根本用不到**,
   却全打进了要部署的镜像,体积达数 GB。

3. **数据科学家(DS)与工程师(Eng)两条线搅在一起。** DS 的 notebook 微调工作
   和工程师的部署工作,本该是不同的环境,却共用一份依赖清单,互相拖累。

本文记录如何用一套现代工具链(`uv` + `pyproject.toml` + 多阶段 Docker)把这三点
一并解决,产出**锁定、精简、按角色分离**的部署产物。

> **一个先讲清的边界**:DS 那条线**不需要 Docker**。他们在自己机器上开 Jupyter
> 交互式干活,一个 conda `yml` 足矣。Docker 的价值在于「让一套环境在你控制不了的
> 服务器上原样跑起来」——那是**部署**的需求,只属于工程师这条线。所以本文的
> Docker 部分自始至终只服务于工程师的部署线;DS 的 `yml` 单独定位([Step 4](#step-4conda-yml-定位为-ds-环境))。

---

## 先看全局:从代码到「能到处跑的盒子」

一张图先把整条打包链路摆出来。后面每个 Step 都能在这张图上找到位置。

```text
        ┌─────────────────────────── 工程师部署线 ───────────────────────────┐
        │                                                                     │
  pyproject.toml            uv.lock                    容器镜像               │
  (人写:我要哪些   ──lock──▶ (机器生成:每个包的  ──build──▶  ┌────────────────┐  │
   直接依赖,分            确切版本+hash,94 个)              │ Dockerfile.api │  │
   api/pipeline/dev)         │                              │  slim+多阶段    │──┼─▶ ECS
        │                    │                              │  api 组+双模型  │  │  常驻服务
        │              本地 .venv / CI                       └────────────────┘  │
        │              (uv sync,同一份锁)                   ┌────────────────┐  │
        │                                                   │Dockerfile.     │  │
        │                                                   │  pipeline      │──┼─▶ ECS
        │                                                   │  pipeline 组   │  │  定时任务
        │                                                   │  +embedding    │  │
        │                                                   └────────────────┘  │
        └─────────────────────────────────────────────────────────────────────┘

        ┌─────────────────────────── 数据科学线 ─────────────────────────────┐
        │  environment_cpu.yml / environment_gpu.yml (conda)                  │
        │      └─ conda env create → Jupyter 里微调模型 → 产出模型/LoRA adapter │  ← 交接点
        │         不进 Docker、不部署                                          │
        └─────────────────────────────────────────────────────────────────────┘
```

用大白话走一遍这条链路:

1. **人只维护一份「购物清单」** `pyproject.toml`——写清楚"我直接要哪些库",并按
   **用途**分成 `api` / `pipeline` / `dev` 三组。→ [基础二](#二按角色切分依赖group-与虚拟项目)、[Step 1](#step-1pyprojecttoml--uvlock)
2. **机器把清单算成一张「精确到条码的小票」** `uv.lock`——把每个包(含被顺带拖进来
   的 94 个)钉到确切版本 + 校验码。这就是「可复现」的载体。→ [基础一](#一可复现的两层声明-vs-锁定)
3. **本地和 CI 都照这张小票装环境**(`uv sync`),于是三处装到的东西**一模一样**。
   → [Step 2](#step-2ci-切换到-uv)
4. **构建镜像**:用「多阶段」技巧,在一个临时「工作间」里装好依赖、下载模型,再把
   **成品**搬进一个干净的 slim 小盒子;临时工具一律不带。→ [基础三](#三一个镜像是怎么造出来的)、[Step 3](#step-3slim-多阶段镜像拆-api--pipeline)
5. **产出两个镜像**:`Dockerfile.api`(常驻 API 服务)和 `Dockerfile.pipeline`
   (定时数据管线任务),各装各的依赖组、各下各需要的模型。→ [Step 3](#step-3slim-多阶段镜像拆-api--pipeline)
6. **DS 那条线平行存在**,用 conda `yml` + notebook,与 Docker 无关;它产出的
   模型/adapter 由工程师镜像加载,这是两条线唯一的交接点。→ [Step 4](#step-4conda-yml-定位为-ds-环境)

---

## 基础知识

### 一、可复现的两层:声明 vs 锁定

> **这一簇讲什么**:为什么要用**两个**文件,而不是一个,来保证「每次装到的东西
> 一模一样」。

**naïve 做法为什么不行。** 最直觉的做法是写一份 `requirements.txt`,里面写
`fastapi`、`torch`……然后 `pip install`。问题在于:这份清单只说了"我要 fastapi",
没说"要哪个版本"。今天装到 `fastapi 0.115`,下个月官方发了新版,同一份清单装到
`0.120`——行为可能变了。而且你写的 `fastapi` 背后会**自动拖进来**几十个它依赖的库
(叫 **transitive / 传递依赖**),这些你根本没写、也没锁,漂移更失控。

**解法:分成「声明」和「锁定」两层。**

- **声明(`pyproject.toml`)** —— 人写、人读的**直接依赖**清单,可以松(只写
  `fastapi`,不写版本)。它回答"我**想要**什么"。
- **锁定(`uv.lock`)** —— 由工具从声明**解析生成**的完整清单,把**每一个**包
  (直接的 + 全部 transitive,本项目 94 个)钉到**确切版本 + 内容校验码(hash)**。
  它回答"实际会装**哪些、哪个版本**"。**人不手改它**,改依赖永远改 `pyproject.toml`
  再重新 lock。

打个比方:`pyproject.toml` 是**购物清单**("买牛奶、鸡蛋"),`uv.lock` 是**精确到
条码批次的小票**("XX 牌全脂牛奶 1L 批次 123…")——照小票买,下次买到的是一模一样
的东西。

**`pyproject.toml` 是什么。** 它不是某个工具的私有格式,而是 Python 官方标准
(PEP 518/621),`pip`、`uv`、`pytest`、`mypy` 都能读它。一个文件里同时放:项目
元数据、依赖、以及各工具的配置(`[tool.xxx]`)。

**为什么必须两个文件都进 git。** 只有声明(松)→ 不可复现;只有锁(全是版本号)→
人看不懂哪些是"我真要的"、哪些是"被拖进来的"。两个一起:人读声明知道意图,机器读
锁保证一致。**`uv.lock` 是「可复现」这个目标的载体,必须提交。**

**工具选型的取舍(uv vs pip-tools)。** 两者都能"声明 → 锁定":
- `pip-tools`:老牌,输出普通 `requirements.txt`,任何 pip 环境可用。缺点:慢。
- **`uv`(本项目选用)**:Rust 写的,快 10–100×,一个 `uv.lock` 覆盖所有依赖组,
  且 CI/镜像里能一站式 `sync`。缺点:较新、要学。
- 因为 DS 那条线继续用 conda、**不碰这个工具**,"团队门槛"不成立;工程师这条线
  选了更现代的 `uv`。两者产出的锁都能达到可复现,选择不影响架构。

### 二、按角色切分依赖:group 与虚拟项目

> **这一簇讲什么**:同一份 `pyproject.toml` 里,怎么把依赖按"谁用、干什么"分开,
> 让 API 镜像不背 pipeline 的库、生产不背测试工具。

**两个维度的切分,别混。** 项目里有两个正交的"分开":

| 维度 | 分的是什么 | 靠什么实现 |
|---|---|---|
| **DS vs 工程师** | 谁用、干什么(notebook 微调 vs 部署) | conda `yml` ↔ `pyproject.toml`(两套文件) |
| **api / pipeline / dev** | 工程师内部:装哪些依赖 | `pyproject.toml` 里的 **dependency group** |

工程师内部又按"用户请求跑不跑得到"分层:

- **生产运行时**:`/chat` 真正依赖的(fastapi、torch…);会进生产镜像。
- **dev / 测试**:`pytest`、`httpx`、`mypy`——只在开发/CI 用,**不进生产镜像**。
  意义不在省体积(它们才几十 MB),而在**安全面**(生产不带测试执行器/类型检查器)
  和**卫生**(要审计 CVE 的依赖更少)。且几乎白送——多写一行就分好了。

**dependency group 是什么(为什么不是 extras)。** 有两种"可选依赖组"的机制:

- `[project.optional-dependencies]`(**extras**):是**可安装分发包**的特性,靠
  `pip install 包名[extra]` 触发(如 `uvicorn[standard]`)。前提是**这个项目本身
  得能被 `pip install`**。
- `[dependency-groups]`(**PEP 735,本项目用的**):是**开发/环境**的可选依赖组,
  靠 `uv sync --group 名字` 装,与打包无关。

本仓库有 `app/` 和 `pipelines/` **两个平级顶层包**,不是一个可 `pip install` 的库,
部署时是「拷源码直接跑」。所以在 `pyproject.toml` 里声明它是**虚拟项目**
(`[tool.uv] package = false`)——uv 只帮它管依赖、不去构建/安装项目本身。而 uv 规定
**虚拟项目不能用 extras、只能用 group**。于是选 group。效果一致:api / pipeline 各自
选装。

本项目的分组形状(示意):

```toml
[project]
dependencies = [ "torch==2.12.1", "sentence-transformers==5.6.0", "peft==0.19.1",
                 "psycopg2-binary", "sqlalchemy", "alembic", "pydantic",
                 "pydantic-settings", "pyyaml", "langchain-core", "openai", ... ]  # 共享核心

[dependency-groups]
api      = [ "fastapi", "uvicorn[standard]", "slowapi" ]     # 常驻 API
pipeline = [ "requests" ]                                    # 数据管线(爬取)
dev      = [ "pytest", "httpx", "numpy", "mypy",
             { include-group = "api" }, { include-group = "pipeline" } ]  # 测试:含前两组
```

- **共享核心**(`[project].dependencies`):API 和 pipeline **都要**的(torch/模型、
  数据库、config)。
- **`dev` 用 `include-group` 把 api+pipeline 都包进来**:于是一句 `uv sync`(dev 是
  默认组)就装齐整个测试环境;镜像里则 `uv sync --no-default-groups --group api`
  只装该角色要的。

**「不装用不到的直接依赖」是原则。** 迁移时用全仓 grep 核实"代码真 import 了才留",
删掉了声明了但从未 import 的 `asyncpg`、`pgvector`(python 包)、`tiktoken`、
`rank-bm25`、`langchain-openai/community`、`python-multipart`,并补上漏掉的
`pyyaml`(`settings.py` 真在用)。

### 三、一个镜像是怎么造出来的

> **这一簇讲什么**:Docker 镜像是什么、多阶段/固定 digest/non-root 各解决什么问题。

**镜像是什么。** 一个 Docker **镜像**可以理解成「一个自带精简 Linux + Python + 你的
代码 + 依赖的盒饭」。它在你电脑、同事电脑、AWS 上打开都**一模一样**。`docker build`
就是按一张**食谱**(`Dockerfile`)把这个盒饭做出来,食谱一行一行写"先放什么、再装
什么"。

**多阶段构建(multi-stage):一个文件、两道工序、只留成品。** naïve 做法是在一个
镜像里又装编译工具、又装 uv、又装依赖——这些"脚手架"会**全部留在最终镜像里**,又大
又多余。多阶段的解法(打比方):

> 你在一个**乱厨房**里和面、烤制(用一堆工具、满地面粉);做完只把**成品点心**装进
> 一个**干净小盒子**给客人,工具面粉统统不带。

具体是**同一个 Dockerfile 里写多个 `FROM` 段**:第一段 `builder` 装 uv、装依赖、
下模型(比较重);最后一段只 `COPY --from=builder` 把**成品**(装好的
`.venv` + 模型 + 代码)搬进干净的 slim 基础镜像。**只有最后一段变成最终镜像**,
builder 段 build 完即弃。于是最终镜像**无 uv、无编译器、无 dev 工具**。

**固定基础镜像 digest:防"脚下的地基悄悄变了"。** 食谱第一行是"以某镜像为底"。
若写 `python:3.11-slim`(只有 tag),官方哪天更新了这个 tag,你的构建就悄悄换了地基。
所以钉到**内容指纹**:`python:3.11-slim@sha256:db3ff2…`——`@sha256:` 后面那串是该
镜像层的唯一哈希,只要它不变,地基永远是同一个。uv 二进制也同样按 digest 钉死
(`ghcr.io/astral-sh/uv:0.11.32@sha256:df4c…`)。更新地基成了**有意识的动作**,而非
隐式发生。

**non-root 用户:最小权限。** 默认容器里进程以 root 跑;一旦被攻破,攻击者就是容器内
root。解法是建一个专用普通用户 `appuser`,用 `USER appuser` 运行,并 `COPY --chown`
把文件归它所有。攻击面更小。

**模型预先烤入(item 2)。** 把固定 revision 的模型在 build 阶段就下载进
`/models`(`MODEL_DIR`),运行时 `local_files_only` 从本地加载。好处:**第一个用户
请求不必干等模型下载**。代价:镜像更大(模型是硬成本)。因为加载在 FastAPI
lifespan 里、**阻塞启动**,所以「`/health` 能应答」就意味着"模型已就绪、可服务"。

### 四、torch 为什么特殊(粘合:依赖 × 镜像大小)

> **这一簇讲什么**:把「依赖锁定」和「镜像大小」两件事连起来——镜像里最大的一块
> `torch` 是怎么来的、怎么锁对、怎么别让它把镜像撑爆。

**torch 不是一个版本,而是好几种「构建」。** 大多数包只有一种版本;`torch` 针对不同
硬件后端编译出多个二进制,版本号都叫 `2.x`,内容却天差地别:

| 构建变体 | 打包了什么 | 解压后大小 |
|---|---|---|
| CPU-only | 只有 CPU 内核 | ~200 MB |
| CUDA 11.8/12.x | CPU 内核 + **整套 NVIDIA GPU 库**(cuDNN/cuBLAS…) | ~2.5–3 GB |

**默认会踩的坑。** `pip/uv install torch` 从 PyPI 默认往往拿到 **CUDA 变体**。在
**没有 GPU 的生产 CPU 镜像**里,这意味着凭空背上 ~2.5GB 永远不会执行的 NVIDIA 库——
和"缩小镜像"背道而驰。

**解法:声明式地指向 PyTorch 的 CPU index。** CPU-only 变体在 PyTorch 官方独立 index
(`download.pytorch.org/whl/cpu`)。在 `pyproject.toml` 里声明(而非散在构建命令里):

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true          # 只有被点名的包才从这个 index 拿,别的包不受影响

[tool.uv.sources]
torch = { index = "pytorch-cpu" }   # 明确:torch 走 CPU index
```

**为什么这必须在生成锁文件那步就配好。** `uv.lock` 会把每个包解析到"确切 wheel +
hash"。如果生成锁时没配 index,锁进去的就是 CUDA 变体——之后镜像照锁文件装,拿到的
还是 2.5GB 的错版本。所以 index 配置和锁必须**同时**落地。做完可见锁到
`torch==2.12.1+cpu`(`+cpu` 后缀即证据),下载仅 ~117MB。

**ML 栈为什么钉死版本。** Hugging Face 生态(`transformers`/`sentence-transformers`/
`peft`)迭代快、常有破坏性变更。本项目把这几个**钉到代码验证过的版本**(`torch
2.12.1` / `sentence-transformers 5.6.0` / `peft 0.19.1`,并约束 transitive 的
`transformers 5.12.1`),避免未来 re-lock 悄悄滑到未测过的新版。这是可复现在 ML 侧的
具体落实。

---

## 实现步骤

每步单独提交、单独验证。下面每步先点出它依赖哪些基础知识。

### Step 1:pyproject.toml + uv.lock

> 先备知识:[基础一(声明 vs 锁定)](#一可复现的两层声明-vs-锁定)、
> [基础二(group / 虚拟项目)](#二按角色切分依赖group-与虚拟项目)、
> [基础四(torch CPU)](#四torch-为什么特殊粘合依赖--镜像大小)。

新增 [pyproject.toml](../../../pyproject.toml) + [uv.lock](../../../uv.lock)。声明共享核心 +
`api`/`pipeline`/`dev` 三组;`package = false`(虚拟项目);torch 走 CPU index;ML 栈
钉版本;`requires-python = ">=3.11,<3.12"`(与本地 .venv 3.11.9、CI 3.11 一致)。
`ops/download_models.py` 后续新增 `--models` 选择(见 Step 3)。此步**纯新增,不动
CI / Dockerfile**,零风险。锁定 94 个包。

### Step 2:CI 切换到 uv

> 先备知识:[基础一](#一可复现的两层声明-vs-锁定)。

[unit-test.yml](../../../.github/workflows/unit-test.yml) 与
[integration-test.yml](../../../.github/workflows/integration-test.yml) 改用
`astral-sh/setup-uv@v6`(开缓存)+ `uv sync --locked` + `uv run pytest`;删除
`requirements-ci.txt`。

- **`--locked` 是关键守卫**:它断言 `uv.lock` 与 `pyproject.toml` 一致,**不一致就
  让 CI 失败**——谁改了声明却忘了重新 lock,会被当场挡下。这把"可复现"钉进了 CI。
- **`uv run` vs 直接 `pytest`**:CI 是全新机器、没有"已激活的环境";`uv run` 明确
  在 `uv sync` 出来的环境里执行,不依赖任何"激活"状态。(程序无法改父 shell 的
  `PATH`,所以 uv 不靠"激活"而是"我来当爹、给子进程直接设好环境"。)

### Step 3:slim 多阶段镜像,拆 api / pipeline

> 先备知识:[基础三(镜像/多阶段/digest/non-root/模型烤入)](#三一个镜像是怎么造出来的)、
> [基础二(group)](#二按角色切分依赖group-与虚拟项目)。

把 conda 版 `Dockerfile.cpu`/`Dockerfile.gpu` 替换为两个 slim、多阶段、uv 锁定的
镜像,同一 `python:3.11-slim@sha256:db3ff2…` 固定 digest 起步:

- [Dockerfile.api](../../../Dockerfile.api):`--group api`,下 **embedding + reranker**
  两模型,`uvicorn` 常驻 + HTTP healthcheck。
- [Dockerfile.pipeline](../../../Dockerfile.pipeline):`--group pipeline`,**只下
  embedding**(管线在 import 时给文档算 embedding;reranking 是查询期的 API 才需要),
  无端口/无 healthcheck(批处理任务),`ENTRYPOINT python -m pipelines`。

**为什么拆两个(而不是一个三用)。** 目标架构里 API 是**常驻服务**、按流量扩容;
pipeline 是**定时/一次性任务**、跑完就退——两者需要不同的扩容策略、权限、发布节奏。
基础二分好的 group 正是为此埋的伏笔:拆分只是各自 Dockerfile 里 `uv sync` 换个
`--group`。**拆分的价值在运营隔离,不在体积**——两个镜像仍都得背 torch + embedding
模型(硬成本);pipeline 只是额外省掉 reranker 模型(~130MB)和几个 API 库。

**`download_models.py --models` 选择。** 为让 pipeline 镜像真省掉 reranker,给下载
脚本加了 `--models` 选择(默认下全部,保持既有测试绿),pipeline 只传 `embedding`。

配套同步:[docker-compose.yml](../../../docker-compose.yml)(api/migrate 用
`Dockerfile.api`、pipeline 用 `Dockerfile.pipeline`、删 `api-gpu` 服务、镜像名
`cssa-da-api`/`cssa-da-pipeline`)、
[docker-check.yml](../../../.github/workflows/docker-check.yml)(build 两镜像各自冒烟)、
README、本设计文档。

> **一个决策记录(2026-07-27)**:原本有 CPU/GPU 两个 Dockerfile。因 DS 的 GPU 训练
> 走 conda notebook、GPU **serving** 属 Phase 5 延后项,决定**合并为单一部署镜像、
> 删除 GPU Dockerfile**;随后再按 api/pipeline 拆成两个。GPU serving 到 Phase 5 真
> 需要时按需另建。

### Step 4:conda yml 定位为 DS 环境

> 先备知识:[背景里的「两条线」边界](#背景)、[基础二](#二按角色切分依赖group-与虚拟项目)。

[environment_cpu.yml](../../../environment_cpu.yml) /
[environment_gpu.yml](../../../environment_gpu.yml) 加英文注释 + 头部声明:**它们是 DS
的 notebook 环境(交互/微调用),不是部署产物;部署走 `Dockerfile.*` + `uv.lock`**。
依赖全部保留、**版本刻意不锁**(DS 需要实验灵活性);两个 yml 都留(GPU 版供 DS 在
显卡机上微调)。

**要不要锁 DS 环境?** 现在不锁——它不上生产,漂移不影响线上。**延后待办**:真要做
可复现微调 / golden test 时,用 `conda-lock` 给 DS 环境上锁,并把 ML 核心
(torch/transformers/sentence-transformers/peft)**对齐 `uv.lock` 的固定版本**,保证
"DS 训出的 adapter 能在生产镜像加载"(两条线的交接点靠这个版本对齐守住)。

### Step 5:本地构建与测量

> 先备知识:[基础三(模型烤入 → 启动语义)](#三一个镜像是怎么造出来的)。

本地 `docker build` 两镜像均成功,冒烟全绿(pipeline `--help`、
`check_config --profile all`、API 启动 + 模型本地加载 + `/health`)。测得(不依赖 DB
的部分):

| 指标 | 结果 |
|---|---|
| 镜像大小 | API **3.35GB** / Pipeline **3.06GB** |
| 大头 | torch 754MB + 模型(API 605MB / Pipeline 477MB)为硬成本 |
| 冷启动 → `/health` 可用 | **~7 秒**(含 torch + 模型预加载,阻塞启动) |
| Idle 内存 / CPU | **~950 MiB** / ~0.1% |

→ 指导 Phase 2 选 Fargate size:内存至少 1GB,建议 **2GB** 留请求峰值余量。
依赖 DB 的指标(`/ready`、`/chat` 端到端 latency、peak 内存)延后到 Phase 2 连同负载
测试做。

---

## 两条线、三份声明:全景对照

| | 生产运行时(镜像内) | dev / 测试 | DS notebook |
|---|---|---|---|
| 声明在哪 | `pyproject.toml` `[project]` + `api`/`pipeline` group | 同上 + `dev` group | `environment_*.yml` |
| 锁定 | `uv.lock`(严格) | `uv.lock` | 不锁(刻意) |
| 装法 | 镜像 `uv sync --no-default-groups --group api`(或 `pipeline`) | 本地/CI `uv sync` | `conda env create` |
| 含 jupyter/matplotlib? | 否 | 否 | 是 |
| 含 pytest/mypy? | 否 | 是 | 是 |
| 是部署产物? | 是 | 否 | 否 |

---

## 测试与验证策略

- **单元测试**:`188 passed`(含新增的 `download_models --models` 选择测试)。
- **锁一致性守卫**:CI 的 `uv sync --locked` 保证锁文件永远跟 `pyproject.toml` 同步。
- **镜像冒烟**:`docker-check.yml` 构建两镜像并各自冒烟——pipeline `--help`、
  API `/health`、`check_config`。本地已全部真跑通过。
- **用「与锁一致的隔离环境」验证,而非污染本地 .venv**:验证 Step 1/2 时,用
  `UV_PROJECT_ENVIRONMENT` 指向一个全新环境跑 `uv sync` + 测试,得到"纯粹由
  `uv.lock` 构建"的环境,验证最诚实,也不打断本地 .venv。
- **一个真实教训(Windows MAX_PATH)**:首次把隔离环境放在很深的临时目录下,
  `transformers` 扫自己的 `models/` 目录时报 `FileNotFoundError`——根因是 Windows
  260 字符路径上限,**不是依赖版本问题**(一度误判)。换到短路径后即全绿。教训:
  Windows 上深路径 + 大依赖树容易踩 MAX_PATH,验证环境放浅一点。

---

## 完成情况与后续

**已完成(Phase 1)**:依赖锁定(第 6 项)、镜像瘦身(第 7 项)、固定基础镜像
(第 5 项)、模型交付(第 2 项)、non-root(第 4 项);CI 切 uv、DS 环境定位、
本地构建与测量。

**明确延后**:

- **`S3Storage`**(存储抽象第 6 步)→ Phase 3 真上 AWS 时,上层 stage 代码零改动。
  见 [storage-abstraction.md](./storage-abstraction.md)。
- **DB 相关测量**(`/ready`、`/chat` latency、peak 内存)→ Phase 2 连同负载测试。
- **DS 环境上锁 + ML 核心对齐**(`conda-lock`)→ 真做 golden test / 可复现微调时。
- **GPU serving 镜像** → Phase 5 真需要 GPU 推理时按需另建(现 CPU 足够)。
- **ECS 层面**(container/ALB health check、migration 部署关卡、outbound network、
  Fargate size、生产 RDS)→ Phase 2,见 [ROADMAP_platform.md](../../roadmap/ROADMAP_platform.md)
  第 8、11、12、17 项。
