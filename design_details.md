# API 可观测性与安全加固 —— 设计说明

本文记录 `/chat` API 加固工作的设计细节、背后的取舍,以及为看懂这些代码所需的
基础知识。整体路线图见 [future_plan.md](future_plan.md) 第 1 项;本文覆盖已经
完成的步骤(Step 1–8,全部完成并验证)。

工作按"每步单独实现、单独验证、单独 review"的方式推进。本文兼作**学习参考**,
面向刚接触后端的读者:先给全局大图,再补基础知识,最后才逐步讲实现。凡是用到的
语言 / 框架机制,都在"基础知识"章节从头讲清,正文再引用。

---

## 目录

- [背景](#背景)
- [先看全局:一次请求的旅程](#先看全局一次请求的旅程)
- [基础知识](#基础知识)
  - [一、请求怎么进到我的代码里(Web 管道)](#一请求怎么进到我的代码里web-管道)
    - [技术栈全景:uvicorn / ASGI / Starlette / FastAPI](#技术栈全景uvicorn--asgi--starlette--fastapi)
    - [1. ASGI 三件套:scope / receive / send](#1-asgi-三件套scope--receive--send)
    - [2. 中间件的位置与洋葱结构](#2-中间件的位置与洋葱结构)
  - [二、怎么把发生的事记下来(日志)](#二怎么把发生的事记下来日志)
    - [3. Python logging 的三层结构](#3-python-logging-的三层结构)
    - [4. logger 的名字与父子继承](#4-logger-的名字与父子继承)
    - [5. LogRecord(record)是什么](#5-logrecordrecord-是什么)
  - [三、把"同一次请求"串起来(粘合剂)](#三把同一次请求串起来粘合剂)
    - [6. ContextVar 与 token](#6-contextvar-与-token)
  - [四、没接住的异常怎么变成安全响应](#四没接住的异常怎么变成安全响应)
    - [7. 框架按继承链(MRO)挑异常处理器](#7-框架按继承链mro挑异常处理器)
- [Step 1:结构化 JSON 日志基础](#step-1结构化-json-日志基础)
- [Step 2:RequestContextMiddleware](#step-2requestcontextmiddleware请求-id--access-log)
- [Step 3:SecurityHeadersMiddleware](#step-3securityheadersmiddleware安全响应头)
- [Step 4:CORS](#step-4cors跨源资源共享)
- [Step 5:/chat 限流(rate limiting)](#step-5chat-限流rate-limiting)
- [Step 6:兜底异常处理器](#step-6兜底异常处理器)
- [Step 7:让容器 stdout 只剩结构化日志](#step-7让容器-stdout-只剩结构化日志)
- [中间件注册顺序](#中间件注册顺序总览)
- [测试策略](#测试策略)
- [完成情况与后续](#完成情况与后续)

---

## 背景

在加固之前,[app/main.py](app/main.py) 没有注册任何 middleware:

- 没有结构化日志(`app.*` 的 logger 只是 `logging.getLogger(__name__)`,没有挂
  handler / formatter,日志无处可去)。
- 没有请求关联 ID,无法把"一次请求产生的多条日志"串起来。
- 没有 CORS、rate limiting、安全响应头。
- 只有三种已知的 `RAGServiceError` 子类有安全的公开错误响应,其他未预期的异常
  会直接落到 Starlette 默认行为,不会被结构化记录。

目标:在动 AWS 基础设施之前,先把 FastAPI 这一层做到"生产就绪"。结构化 JSON
日志打到 stdout,将来在 ECS 上会被 `awslogs` driver 直接采集到 CloudWatch,零
额外基础设施。

参照物:`pipelines/` 目录下的离线数据管线早已有一套结构化日志
([pipelines/shared/logging.py](pipelines/shared/logging.py)),用 `run_id` 串联
一次 pipeline run。API 侧刻意**不共用**这套代码,而是照它的模式另写一套用
`request_id` 串联一次请求 —— 两者是不同的 bounded context,字段和语义都不一样,
硬共享只会让两边耦合。

---

## 先看全局:一次请求的旅程

在钻进任何术语之前,先建立一张大图。用户在网页上问"怎么申请签证",到拿到回答,
请求在系统里是这样走一圈的(先不用管每个名词的细节,后面基础知识会逐个补):

```
用户浏览器
   │  发出 HTTP 请求
   ▼
uvicorn（网络服务器）           把网络字节翻译成 Python 能用的东西
   ▼
┌──────────────────────────────────────────────┐
│ CORSMiddleware（最外层）        ← Step 4：管“哪个网站的前端能调我” │
│  ┌────────────────────────────────────────┐  │
│  │ SecurityHeadersMiddleware      ← Step 3：给响应加安全头       │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │ RequestContextMiddleware  ← Step 2：发请求 ID、记访问日志 │
│  │  │  ┌────────────────────────────┐  │  │  │
│  │  │  │ FastAPI 路由（/chat 等）    │  │  │  │
│  │  │  │   → orchestrator            │  │  │  │
│  │  │  │   → retriever → generator   │  │  │  │
│  │  │  └────────────────────────────┘  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

关键直觉,记住这几点,后面就不会乱:

- **像洋葱,一层包一层**。请求从最外层往里穿,一直到最里面的业务代码(FastAPI
  路由 → RAG 管道);响应再从里往外一层层穿回去。
- **中间件是"必经的关卡"**,不是业务本身。每一层在请求进、出时顺手做一件横切的
  事(加个头、记条日志、检查一下),做完把请求递给下一层。
- **Step 2/3/4 做的三个中间件,就是往这张洋葱图里加的三层关卡**。本文后面每个
  Step,其实就是在讲"这一层关卡具体做什么、怎么做"。

基础知识就按这张图的两个方向来讲:先讲**请求怎么在这些层里流动**(Web 管道),
再讲**流动过程中怎么把事情记下来**(日志),最后讲**怎么让同一次请求的每条日志
都带上同一个 ID**(粘合剂)。

---

## 基础知识

这一章讲的都是 Python / ASGI 的通用机制,不是本项目特有的写法。看懂它们,后面
每一步都会变得直白。分四簇,由外到内、由整体到细节。

---

### 一、请求怎么进到我的代码里(Web 管道)

这一簇回答:用户在浏览器点一下,那串网络数据是怎么变成我 Python 代码里能处理的
东西的,又是怎么一层层穿过中间件的。

#### 技术栈全景:uvicorn / ASGI / Starlette / FastAPI

先认清这几个反复出现的名字是谁、谁建在谁之上,后面就不会晕。它们是**一摞**,
不是并列关系:

```
你的代码 (app/main.py：@app.post("/chat") ...)
   ↑ 建在
FastAPI        加：pydantic 数据校验、/docs 自动文档、Depends 依赖注入
   ↑ 建在
Starlette      提供：路由、Request/Response、middleware、异常处理
   ↑ 建在
ASGI 约定       server 和 app 对话的接口：scope / receive / send
   ↑ 跑在
uvicorn        网络服务器：把 TCP 字节 ↔ Python 对象
```

- **uvicorn** 是网络服务器,负责收发网络字节,按 ASGI 约定调用你的 app。
- **ASGI** 只是一套**接口约定**(下一节详讲),本身不是库。
- **Starlette** 是个轻量 web 框架,把"路由、请求/响应对象、middleware、异常
  处理"这些每个 web 项目都要写的脏活封装好。
- **FastAPI 建在 Starlette 之上**,只额外加了数据校验、自动文档、依赖注入等上层
  能力;**路由、middleware、异常处理这些底层机制直接用 Starlette 的**。

**为什么这对本文重要**:文中很多"框架默认行为"其实是 **Starlette 定的**,不是
FastAPI —— 比如[中间件注册顺序](#中间件注册顺序总览)的"后加在外层"规则、
[基础 7](#7-框架按继承链mro挑异常处理器)的"按 MRO 挑异常处理器"。FastAPI 只是把
这些转手暴露给你。理解"哪层负责什么",才知道该去哪层解决问题。

#### 1. ASGI 三件套:scope / receive / send

**它从哪来**:Python web 框架和 web 服务器本来是两拨人做的 —— 框架(Django、
Flask、FastAPI…)负责写业务,服务器(uvicorn、gunicorn…)负责收发网络。要让
"任一框架"能跑在"任一服务器"上,两边得先约好一套通用接口,否则每个框架都要为每个
服务器单独适配。早年的这套约定叫 **WSGI**,但它是**同步**的,扛不住"一个连接
挂很久"的场景(WebSocket、长轮询、大量并发 IO)。于是社区又定了一套**异步**版本
叫 **ASGI**(Asynchronous Server Gateway Interface)—— FastAPI / Starlette 就是
按 ASGI 写的,uvicorn 就是实现了 ASGI 的服务器。

三个角色:

```
用户浏览器  ──HTTP over TCP──►  uvicorn  ──scope/receive/send──►  你的 app
```

- **用户**发的是原始网络字节(遵循 HTTP 协议的一坨文本)。
- **uvicorn** 是"翻译官":一边听得懂网络字节,一边会说 Python。它把网络字节
  解析成 Python 能用的东西交给 app,再把 app 产出的东西翻译回网络字节发回去。
- **你的 app(含 middleware)** 只会说 Python,完全不碰网络。

用户发来的原始 HTTP 请求长这样(纯文本,分头 + 正文两部分):

```
POST /chat HTTP/1.1
Host: yourapi.com
Content-Type: application/json
X-API-Key: abc123
X-Request-ID: user-trace-42

{"message": "怎么申请签证"}
```

uvicorn 把它拆成三样交给 app:

- **`scope`** —— 一个字典,装请求的**头**部分:

  ```python
  scope = {
      "type": "http",       # http / websocket / lifespan（启动关闭事件）
      "method": "POST",
      "path": "/chat",
      "headers": [          # 注意：字节对的列表，不是字典；名字全小写
          (b"host", b"yourapi.com"),
          (b"content-type", b"application/json"),
          (b"x-api-key", b"abc123"),
          (b"x-request-id", b"user-trace-42"),
      ],
      "client": ("203.0.113.5", 54321),   # 客户端 IP + 端口
  }
  ```

  **关键**:`scope` 里**没有请求正文**。正文可能很大(上传大文件),不能一股脑
  塞进字典,所以要单独按需去拉 —— 这就引出 `receive`。这也解释了为什么我们的
  `_get_header` 要在 `scope["headers"]` 这个**字节对列表**里遍历查找,且用小写
  字节串 `b"x-request-id"` 比对(uvicorn 就是按这个格式放进去的)。

- **`receive`** —— 一个异步函数。`await receive()` 才按需拉取一趟请求正文
  (支持流式,`more_body: True` 表示"还有,再调一次")。我们的 middleware 用不上
  请求正文,把 `receive` 原样往下传;真正去 `await receive()` 的是 FastAPI,
  它拉出正文解析成 `ChatRequest` 对象。

- **`send`** —— 一个异步函数。`await send(message)` 把响应发出去。响应**分几趟
  发**:

  ```python
  await send({"type": "http.response.start", "status": 200, "headers": [...]})  # 状态+头
  await send({"type": "http.response.body", "body": b"..."})                     # 正文
  ```

**"ASGI" 这个词的含义现在可以揭开**:它就是"uvicorn 和你的 app 之间必须遵守的
接口约定" —— 约定 app 必须是一个**能接收 `(scope, receive, send)` 三个参数的
异步 callable**。我们的 middleware 类实现 `__call__(self, scope, receive, send)`,
签名长那样正是为了符合这个约定,好让 uvicorn / Starlette 能调用它。

**改响应头的唯一入手点**:响应是下游(FastAPI 路由)通过 `send` 一趟趟发出的,
不是一次性返回值。想改响应头,就得包一个"冒牌 send"(下面 Step 里的
`send_wrapper`)传给下游,在 `http.response.start` 那一趟消息经过时动手,其余趟
原样放行。这是 Step 2 / Step 3 两个 middleware 共用的核心手法。

**为什么用纯 ASGI middleware 而不是 `BaseHTTPMiddleware`**:后者会把下游响应在
另一个 task 里跑、攒成完整对象,有响应流式相关的开销和边界坑。我们只是加响应头 /
记日志这种轻量操作,纯 ASGI 形式(`__call__` + 包 `send`)更直接、更贴近底层、
更可控。

#### 2. 中间件的位置与洋葱结构

**它要解决什么**:有些事情是**每个请求都要做**的 —— 记 access log、加安全头、
鉴权、限流。如果写在每个路由函数里,几十个接口就要复制几十遍,还容易漏。更好的
办法是把这些"横切"逻辑抽出来,放在一个**所有请求都必经的位置**统一处理。这个
"必经位置"就是 middleware —— 一层套在真正业务外面的壳。ASGI 的 middleware 恰好
就是"包着下一层 app 的 app":它自己也是个 `(scope, receive, send)` callable,处理
完再调用被它包住的下一层。一层层套下去,就形成了[开头那张洋葱图](#先看全局一次请求的旅程)。

middleware 是**包在 API 路由外面的一层壳**,请求先进壳,壳再往里递给具体接口 ——
**不是**"接口先收到再回传给 middleware"。"往里递"就是代码里那一行
`await self.app(scope, receive, send_wrapper)` —— `self.app` 就是下一层。响应则沿
反方向一趟趟穿回来。

---

### 二、怎么把发生的事记下来(日志)

请求在上面那些层里流动时,我们想把关键节点记下来(谁来了、花了多久、出没出错)。
这一簇讲 Python 标准库 `logging` 的机制。

#### 3. Python logging 的三层结构

**它从哪来**:最朴素的记日志方式是到处 `print(...)`。但项目一大就会发现 `print`
管不了几件事:想按重要程度分级(调试信息 vs 严重错误)、想让日志同时进文件和
控制台、想统一给每条日志加上时间戳和来源、想上线时一键关掉调试输出 ——
`print` 全做不到。Python 标准库的 `logging` 模块就是为这些诉求设计的,它把"记
日志"这件事拆成三个各管一段的角色,于是每一段都能独立替换和配置。

三个容易混淆的概念,职责分明:

- **Logger** —— 你 `logging.getLogger(name)` 拿到的对象。负责"这条日志**记不
  记**"(按 level 过滤)。
- **Handler** —— 决定日志**写到哪儿**(stdout、文件、网络…)。本项目用
  `StreamHandler(sys.stdout)`。
- **Formatter** —— 决定日志**长什么样**(纯文本还是 JSON)。本项目用自定义的
  `AppJsonLogFormatter`。

一条日志的旅程:`logger.info(...)` → Logger 判断该不该记 → 交给挂在它身上的
Handler → Handler 用 Formatter 把日志变成最终字符串 → 写出去。

#### 4. logger 的名字与父子继承

**它要解决什么**:上一节说日志由 Logger 交给 Handler。但一个项目有几十个模块,
难道每个模块都要自己 `new` 一个 Logger、各自挂一遍 Handler?那配置会散得到处
都是。Python 的做法是:给 logger 起**有层级的名字**(用 `.` 分隔,像文件路径
一样),让子 logger 自动把日志"上交"给父 logger 去处理 —— 这样只在最顶上配一次
就够了。而这个"有层级的名字",约定俗成直接用模块自己的 `__name__`。

`__name__` 是**每个 Python 模块文件自动拥有的内置变量**,不需要你定义。当一个
`.py` 被当作模块 import 时,解释器把它的"点分路径"赋给这个变量:

- [app/main.py](app/main.py) 里 `__name__` == `"app.main"`
- [app/services/rag/orchestrator.py](app/services/rag/orchestrator.py) 里
  `__name__` == `"app.services.rag.orchestrator"`

(例外:一个文件被 `python xxx.py` 直接运行时,它的 `__name__` 是特殊值
`"__main__"`。但本项目的 `app/main.py` 是被 uvicorn **import** 的,所以是
`"app.main"`。)

**为什么这很重要**:Python logging 把 logger 名字里的 `.` 当作**父子分隔符**。
`"app.services.rag.orchestrator"` 是 `"app"` 的子孙。子 logger 默认会把日志
"冒泡"(propagate)给父 logger 处理。所以我们只要把 JSON handler 挂在 `"app"`
这**一个** logger 上,项目里所有 `app.*` 模块的日志都会自动流过来 —— 不用给每个
模块单独配置。这是 Step 1 能"零侵入"的根基。

#### 5. LogRecord(record)是什么

**它为什么存在**:Logger 决定"记",Formatter 决定"长什么样",但这两者之间得有个
东西**装着这条日志的原材料**在传递 —— 消息文本、级别、哪个模块发的、什么时间、
有没有异常。如果直接传一个字符串,Formatter 就没法灵活地"只取时间"或"额外加个
字段"了。所以 logging 把每条日志的全部信息打包成一个对象 `LogRecord`,在内部
流水线上传递,Formatter 拿到的就是这个对象,想取哪个字段取哪个。

每次你调用 `logger.info("hi %s", "world")`,logging 模块会**自动**造一个
`logging.LogRecord` 对象,把这次调用的所有信息打包进去:

```python
record.getMessage()          # -> "hi world"（自动做 % 格式化）
record.name                  # -> "app.main"（哪个 logger 发的）
record.levelname             # -> "INFO"
record.exc_info              # -> 异常信息（有异常时）
```

`Formatter.format(record)` 就是 logging 框架自动调用的 —— 每条日志都会经过它,
把这个 record 对象变成最终字符串。我们的 `AppJsonLogFormatter` 就是重写这个
`format` 方法,输出 JSON 而非纯文本。

**`extra={...}` 参数的原理**:`logger.info("msg", extra={"request_id": "x"})`
内部等价于给生成的 record 对象设一个属性 `record.request_id = "x"`。这就是为什么
formatter 里能用 `getattr(record, "request_id", None)` 把它读出来。Step 2 的
access log 用 `extra={"method": ..., "duration_ms": ...}` 传结构化字段,靠的正是
这个机制。

---

### 三、把"同一次请求"串起来(粘合剂)

上面两簇一个管"请求怎么流动"、一个管"怎么记日志"。还差最后一块:请求 A 在流动
过程中产生了好几条日志(中间件一条、路由一条、orchestrator 一条…),怎么让这几条
都自动带上**同一个 request_id**,好在排查时把它们串成一次请求?这就是 ContextVar
的用武之地 —— 它正是缝合"中间件设值"和"日志读值"的那根线,所以放在最后讲。

#### 6. ContextVar 与 token

**它要解决什么**:我们想让"当前这次请求的 request_id"在整条调用链里都能被读到 ——
从最外层的 middleware 一直到最深处的 orchestrator。有两个笨办法:一是把
`request_id` 当参数一层层往下传(所有函数签名都得改,侵入太狠);二是放一个普通
全局变量(但服务器同时处理多个请求,请求 A 和请求 B 会互相覆盖这个全局变量,
串味)。`contextvars` 是 Python 3.7 引入的标准库,专门解决这个矛盾:它提供一种
"看起来像全局变量、但每条执行流各有各的一份"的变量。asyncio 在切换并发任务时会
自动带着各自的上下文,所以天然做到请求间隔离。

`ContextVar` 就是它提供的这种"**和当前执行上下文绑定的全局变量**"。

它和普通全局变量的关键区别:在同一次请求的处理链路中(不管调用穿过多少层函数),
读它都拿到同一个值;但**不同并发请求之间彼此隔离**,互不覆盖。普通全局变量在
并发下会互相踩,`ContextVar` 不会 —— 这正是"给每个请求一个独立 request_id"需要
的特性。

**`set` 返回的 token**:

```python
token = cv.set("value")   # 设值，返回一个 token
cv.reset(token)           # 用 token 精确恢复到 set 之前那一刻的状态
```

`token` 是个"存档点",记住了 `set()` **之前**那一刻变量的值(如果之前从没设过,
记的是特殊值 `Token.MISSING`,不是 `None` —— 这个区分很重要)。`reset(token)`
就是"回到这个存档点"。

为什么不能简单地在收尾时 `cv.set(None)`?因为可能有**嵌套** set。实测:

```
cv.get() while nested        -> nested-value
cv.get() after inner reset   -> first-value   # 恢复到上一层的值，不是 None！
cv.get() after outer reset   -> None          # 恢复到最初始状态
```

如果内层用 `set(None)` 收尾,会把外层原本的值冲掉。用 `token` + `reset(token)`
才能精确恢复,嵌套多少层都不互相污染。

---

### 四、没接住的异常怎么变成安全响应

前三簇讲的是"正常路径"。但代码会抛异常——有些是我们预料到的(如
`RetrievalUnavailableError`),有些没预料到(如某处 `None.foo` 抛的
`AttributeError`)。这一簇讲框架**怎么决定用哪个处理器**去把一个异常变成 HTTP
响应,这是看懂 [Step 6 兜底处理器](#step-6兜底异常处理器)的前提。

#### 7. 框架按继承链(MRO)挑异常处理器

**它要解决什么**:你可以给不同异常注册不同的处理器
(`@app.exception_handler(SomeError)`),每个返回不同的响应。那么一个异常抛出时,
框架凭什么决定用哪个?答案是**按异常类的继承链**。

先看本项目异常的"家族树"(注意 `RAGServiceError` 继承自 `RuntimeError`,不是直接
继承 `Exception`):

```
Exception
└── RuntimeError
    ├── RAGServiceError                 （项目基类）
    │   ├── RetrievalUnavailableError
    │   ├── GenerationUnavailableError
    │   └── GenerationTimeoutError
    └── （其它 RuntimeError 子类，如手写的 RuntimeError("...")）
```

`RetrievalUnavailableError` **是一种** `RAGServiceError`,**也是一种**
`RuntimeError` 和 `Exception` —— 就像"哈士奇是一种狗,也是一种动物"。

**MRO(Method Resolution Order,方法解析顺序)** 就是"从一个类往上,到它所有祖先
的排队,从最具体到最泛"。`RetrievalUnavailableError` 的 MRO 是:

```
RetrievalUnavailableError → RAGServiceError → RuntimeError → Exception → ...
        (最近/最具体)                                          (最远/最泛)
```

**Starlette 就是拿抛出异常的 MRO 链,从最具体那头开始,逐个问"有没有人注册了处理
这个类的处理器",第一个匹配的就用它。** 由此得到三条结论,正是 Step 6 注释里那句话:

- **"按 MRO 挑"**:框架按继承链找处理器,不是随便找。
- **"具体处理器优先"**:抛 `RetrievalUnavailableError` 时,链上第一站就命中它专属
  的处理器(返回 503),根本走不到 `Exception`;只有抛一个**没有专属处理器**的异常
  (如裸 `RuntimeError`)时,才会一路退到 `Exception` 的兜底处理器。
- **"注册顺序无关"**:处理器谁先注册、谁后注册都不影响结果,因为框架比的是"在 MRO
  链上离异常多近",而不是"谁先登记"。距离由**类继承关系**决定,与代码顺序无关。

这条机制是 Step 6 能"加一个 `Exception` 兜底网、又不误伤已有具体处理器"的保证。

---

## Step 1:结构化 JSON 日志基础

**文件**:新增 [app/core/logging.py](app/core/logging.py);
[app/main.py](app/main.py) 顶部调用;
[app/core/config/settings.py](app/core/config/settings.py) 加 `LOG_LEVEL`;
[.env.example](.env.example) 补注释。

> 前置基础:[3. logging 三层](#3-python-logging-的三层结构)、
> [4. logger 名字与继承](#4-logger-的名字与父子继承)、
> [5. LogRecord](#5-logrecordrecord-是什么)、
> [6. ContextVar](#6-contextvar-与-token)。

### `AppJsonLogFormatter`

继承 `logging.Formatter`,把一条 `LogRecord` 转成 JSON 字符串,字段包括
`timestamp` / `level` / `logger` / `message`,以及 `request_id` 和一个结构化字段
白名单(`STRUCTURED_FIELDS`:`method`、`path`、`status_code`、`duration_ms`、
`error_code`),有异常时再加 `exception`。

`request_id` 的取值逻辑是"优先取手动传的,否则读 ContextVar":手动传指
`logger.info(..., extra={"request_id": "xxx"})`(见[基础 5](#5-logrecordrecord-是什么));
没手动传就退回读 `_request_id` 这个 **ContextVar** —— 这就是为什么深层代码(如
orchestrator)**一行都不用改**就能带上 request_id。

**为什么用白名单而不是把 `record.__dict__` 全塞进 JSON**:`LogRecord` 本身带
一堆内部字段(`pathname`、`lineno`、`thread`…),全丢进去噪音大,还可能塞进不可
JSON 序列化的对象导致报错。白名单让"系统到底记录哪些结构化字段"可控可查。

### `configure_app_logging(level)`

把 JSON handler 挂到 `logging.getLogger("app")` 上,`propagate = False`。

- **为什么挂在 `"app"`**:见[基础 4](#4-logger-的名字与父子继承) —— 所有
  `app.*` 模块都是 `"app"` 的子孙,日志自动冒泡上来,一处配置全局生效。
- **`propagate = False`**:防止 `"app"` 的日志继续往上冒泡到 root logger,被
  uvicorn 或别的库的 handler 重复打印一遍。
- **先清空已有 handler 再加**:函数可能被调用多次(`--reload`、测试反复起
  app)。不清空会累积 handler,同一条日志打印 N 遍。这里做成幂等。

### `bind_request_id(request_id)`

它是**给 `_request_id` 这个 ContextVar 临时赋值、并保证代码块结束后自动清干净**
的工具,配合 `with` 使用(实现是一个 `@contextmanager`)。要点:

- 用 `token` + `reset(token)` 精确恢复(见[基础 6](#6-contextvar-与-token)),
  嵌套调用不互相污染;`try/finally` 保证请求即使抛异常,request_id 也一定被清
  干净,不泄漏到下一个请求 / 下一个测试。
- `_request_id` 是模块内部变量,`bind_request_id` 是唯一对外的写入口,保证
  "设置"和"清理"永远配对 —— 别的模块不该直接操作那个 ContextVar。

Step 1 完成后整套日志管道是通的,但**还没有任何地方调用 `bind_request_id`**,
所以此时 request_id 恒为空 —— 这是预期的,Step 2 才真正填上。

---

## Step 2:RequestContextMiddleware(请求 ID + access log)

**文件**:[app/core/middleware.py](app/core/middleware.py) 新增类;
[app/main.py](app/main.py) 注册;
[tests/unit/test_api_middleware.py](tests/unit/test_api_middleware.py) 新增测试。

> 前置基础:[1. ASGI 三件套](#1-asgi-三件套scope--receive--send)、
> [2. 中间件的位置](#2-中间件的位置与洋葱结构)。

### 它做的四件事

1. **确定 request_id**:`_get_header(scope, b"x-request-id")` 在 `scope["headers"]`
   里找客户端有没有自带(上游网关 / 前端可以把自己的 trace ID 传下来,全链路对得
   上);没有就 `uuid.uuid4()` 生成。
2. **绑定到日志上下文**:`with bind_request_id(request_id):` 包住整个下游调用,
   于是路由、orchestrator、retriever 里的任何日志都自动带上同一个 request_id。
3. **写回响应头**:`send_wrapper` 在 `http.response.start` 那一趟往 headers 里
   追加 `X-Request-ID`,顺手抄下 `status_code`(留给 access log 用)。
4. **记一条 access log**:请求处理完后算出 `duration_ms`,打一条
   `"request completed"`,带 `method` / `path` / `status_code` / `duration_ms`
   —— 字段名正是 Step 1 在 `STRUCTURED_FIELDS` 预留的那几个。

改响应头走的是[基础 1](#1-asgi-三件套scope--receive--send) 讲过的"冒牌 send"
手法:在 `http.response.start` 那一趟消息经过时追加 `X-Request-ID`、顺手抄下
状态码,其余趟原样放行。access log 在 `with bind_request_id(...)` 块**内**打出,
以确保 request_id 尚未被清理时就完成记录。

`scope["type"] != "http"` 时直接放行:lifespan(启动 / 关闭)等事件也会经过
middleware,不加判断会把它们当请求处理而出错。

---

## Step 3:SecurityHeadersMiddleware(安全响应头)

**文件**:[app/core/middleware.py](app/core/middleware.py) 新增类 +
`SECURITY_HEADERS` 常量;[app/main.py](app/main.py) 注册;
[tests/unit/test_api_middleware.py](tests/unit/test_api_middleware.py) 新增测试。

结构与 `RequestContextMiddleware` 几乎相同 —— 同样判断 `http`、同样包
`send_wrapper`、同样在 `http.response.start` 那趟改 headers,只是塞进去的内容不同
(`headers.extend(SECURITY_HEADERS)`),且不需要 ContextVar、不掐表、不记日志。

### 四个安全头及其防御目标

| 响应头 | 值 | 防什么 |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | 禁止浏览器"猜"文件类型 |
| `X-Frame-Options` | `DENY` | 禁止任何网站用 `<iframe>` 嵌入本站 |
| `Referrer-Policy` | `no-referrer` | 跳出本站时不带来源网址 |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` | 只准用 HTTPS 访问本站(含子域名) |

**逐个讲清攻击场景**:

- **`X-Content-Type-Options: nosniff`** —— 每个响应用 `Content-Type` 声明自己是
  什么类型。老浏览器会"自作聪明"地偷看内容自己猜类型(MIME sniffing)。攻击场景:
  用户上传一个名为 `avatar.png`、内容其实是恶意 JS 的文件,服务器返回
  `Content-Type: image/png`,但浏览器猜"这像 JS",擅自当 JS 执行了。`nosniff` =
  "别猜,我说是啥就是啥",猜测行为被关掉。

- **`X-Frame-Options: DENY`** —— 防**点击劫持(clickjacking)**。攻击者做一个
  钓鱼页,用透明的 `<iframe>` 把你的银行"确认转账"页叠在一个"点击领 iPhone"按钮
  正上方,用户以为点 A 实际点到了透明的 B,钱就转走了。`DENY` = "任何网站都不许
  用 iframe 嵌我",这个透明叠加的把戏就搭不起来。

- **`Referrer-Policy: no-referrer`** —— 从 A 页跳到 B 页时,浏览器默认会带一个
  `Referer` 头告诉 B "访客从 A 来"。若 A 的网址本身含敏感信息(如
  `.../reset-password?token=SECRET`),这个 token 就顺着跳转泄露给第三方。
  `no-referrer` = "跳出去时一个字都别告诉对方我是谁"。

- **`Strict-Transport-Security`(HSTS)** —— 用户敲网址通常只打域名,浏览器第一次
  默认先试 `http://`(明文),给了中间人可乘之机(在公共 WiFi 上拦下明文请求、
  阻止升级到 HTTPS、偷看密码)。HSTS = "记住,`max-age` 秒内(这里两年)访问我
  一律直接用 HTTPS,连试都别试 HTTP",浏览器记住后会在本地就把 `http` 改成
  `https`,可被拦截的明文请求根本不发出。`includeSubDomains` = 所有子域名同样
  生效。**前提**:HSTS 只在 HTTPS 响应下被浏览器接受,本地 `http://localhost`
  开发时自然不生效,加了也无害。

对纯 JSON API 而言,`nosniff` 和 HSTS 最实在;`X-Frame-Options` /
`Referrer-Policy` 对 API 场景防御意义偏小,但**零成本、零副作用,且是安全审计的
标准项**,因此选择"无脑四个头全加",不按环境区分(避免过度设计)。

---

## Step 4:CORS(跨源资源共享)

**文件**:[app/core/config/settings.py](app/core/config/settings.py) 加
`ALLOWED_ORIGINS` + `allowed_origins_list` property;
[app/main.py](app/main.py) 注册 Starlette 自带的 `CORSMiddleware`;
[.env.example](.env.example) 补注释;
[tests/unit/test_api_middleware.py](tests/unit/test_api_middleware.py) 新增测试。

### CORS 到底是什么、防谁

CORS = Cross-Origin Resource Sharing。它是**浏览器**强加的一条安全规则,后端只是
配合它表态。

- **源(origin)** = 协议 + 域名 + 端口 三者的组合。`https://myapp.com` 和
  `http://localhost:3000` 是两个不同的源。
- **浏览器的默认规则(同源策略)**:网页里的 JS(`fetch` / `XMLHttpRequest`)
  默认**只能**请求和自己**同源**的后端。前端 `https://myapp.com` 的 JS 想调
  `https://api.myapp.com`,源不同,**浏览器自己在前端那边就把请求掐掉了**——
  不是后端拒绝。
- **它防什么**:防止你登录着银行时,另开的恶意标签页的 JS 偷用你的登录状态去调
  银行 API。
- **CORS 是"松绑机制"**:后端通过响应头明确说"我允许 `https://myapp.com` 的 JS
  来调我",浏览器看到这个表态才放行。

**为什么本项目需要它**:现在 API 只能用 Swagger / `curl` 调(它们不受同源策略
约束)。但"求职展示面"迟早要做前端页面(React 跑在 `localhost:3000` 或某部署
域名),那个前端的 JS 一 `fetch` 你的 API,源不同就被浏览器拦。这一步为未来的
前端 demo 铺路。

### 用 Starlette 自带的 `CORSMiddleware`

CORS 是极标准的需求,不自己写。配置(五个参数)如下:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    expose_headers=["X-Request-ID"],
)
```

**大前提**:这五个参数最终都是让 `CORSMiddleware` 往响应里加(或不加)几个
`Access-Control-*` 响应头,浏览器读这些头决定放行还是拦截。

| 参数 | 方向 | 一句话 | 我们的值 |
|---|---|---|---|
| `allow_origins` | 谁能调 | 哪些网站的前端 JS 有资格调我 | 白名单(配置读) |
| `allow_credentials` | 带不带 cookie | 跨源调我能否带用户凭证 | `False` |
| `allow_methods` | 什么动作 | 允许哪些 HTTP 动作 | `GET, POST, OPTIONS` |
| `allow_headers` | 请求头 | 前端**发**请求能带哪些头 | `Content-Type, X-API-Key` |
| `expose_headers` | 响应头 | 前端 JS 能**读**哪些响应头 | `X-Request-ID` |

**逐个讲清**:

- **`allow_origins`(控制 `Access-Control-Allow-Origin`)** —— 白名单。浏览器发
  请求时自动带 `Origin: https://myapp.com`,`CORSMiddleware` 拿它比对白名单:在
  名单里就回 `Access-Control-Allow-Origin: https://myapp.com`(浏览器放行),不在
  就不回这个头(浏览器拦下)。通配 `["*"]` 表示谁都能调,对有鉴权的 API 太松,
  用明确白名单。

- **`allow_credentials`(控制 `Access-Control-Allow-Credentials`)** —— 跨源请求
  默认不带 cookie,要带需前端显式开 `credentials: "include"` **且**后端这里
  `True`,两边都同意才带。我们鉴权靠 `X-API-Key` **请求头**,不用 cookie,故
  `False`。附带好处:CORS 规范规定 `allow_credentials=True` 时 `allow_origins`
  不能用 `["*"]`,`False` 就绕开了这个限制。

- **`allow_methods`(控制 `Access-Control-Allow-Methods`)** —— 允许的 HTTP 动作。
  盘点本项目:`GET`(`/health`、`/ready`、`/status`)、`POST`(`/chat`),加上预检
  要用的 `OPTIONS`,就这三个,不多给。

- **`allow_headers`(控制 `Access-Control-Allow-Headers`)** —— 允许前端**发**请求
  时带哪些(尤其自定义)**请求头**。必须含 `X-API-Key`(鉴权头),否则浏览器会
  拦掉请求,前端连鉴权头都递不过来,`/chat` 根本调不通;`Content-Type` 用于发
  JSON。

- **`expose_headers`(控制 `Access-Control-Expose-Headers`)** —— **最易忽略,且
  和前几步呼应**。跨源请求即便成功,前端 JS 默认也只能读几个标准响应头,任何
  **自定义响应头**默认读不到。我们 Step 2 加的 `X-Request-ID` 就属于自定义头,
  不在这里点名,前端 `response.headers.get("X-Request-ID")` 会拿到 `null`。放行
  后,前端能读到它 —— 比如报错时把这个 ID 展示给用户,用户报障时你拿它一搜服务器
  日志就能定位那次请求的完整链路。这是从 Step 1 一路铺来的"请求可追溯"能力延伸到
  了前端。

> 注意区分 `allow_headers`(管**请求**头,前端 → 后端)和 `expose_headers`(管
> **响应**头能否被前端 JS 读取,后端 → 前端)两个方向。

### 预检请求(preflight)

浏览器发跨源的"非简单请求"(如带自定义头 `X-API-Key` 的 POST)之前,会**先自动
发一个 `OPTIONS` 请求**问后端:"我等下想用 POST、带 X-API-Key 头调你,行不行?"
`CORSMiddleware` 自动回一个带 CORS 头的响应表态,浏览器得到许可才发真正的 POST。
这个探路的 `OPTIONS` 就叫预检,我们不用为它写路由。上面 `allow_methods` 里的
`OPTIONS` 就是给它的。

### `ALLOWED_ORIGINS` 存成字符串的理由

配置项存成**逗号分隔字符串**而非 `list[str]`:pydantic-settings 对 `list` 类型的环境
变量默认要求 JSON 格式(`.env` 里得写 `ALLOWED_ORIGINS='["a","b"]'`),和本文件
其它字段全是朴素字符串的风格不一致。用字符串 + 一个 `property` 拆分,更统一、
`.env` 写起来更顺手。默认值给两个常见本地前端端口(3000 = Next.js/CRA,
5173 = Vite),部署时用环境变量覆盖成真实前端域名。

---

## Step 5:/chat 限流(rate limiting)

**文件**:新增 [app/core/rate_limit.py](app/core/rate_limit.py);
[app/core/config/settings.py](app/core/config/settings.py) 加 `CHAT_RATE_LIMIT`;
[app/main.py](app/main.py) 注册 limiter、给 `/chat` 加限流、加 429 处理器;
[tests/conftest.py](tests/conftest.py) 加重置 fixture;依赖 `slowapi` 加到三处
依赖文件;[.env.example](.env.example) 补注释。

### 为什么只限 `/chat`

大多数接口是"廉价"的(`/health` 只返回一句话,被打一万次也不心疼)。但 `/chat`
每被调一次,背后是一次 embedding 计算 + 一次 reranker 推理 + **一次 OpenAI API
调用(真金白银,社团付费)**。这是一个"**每次调用都花钱**"的接口。一旦暴露到
公网,一个滥用脚本、一个前端死循环 bug,就能把社团的 OpenAI 账单刷爆。

**限流 = 给"同一客户端在一段时间内能调多少次"设上限**,超了直接返回 HTTP 429
(Too Many Requests),**在触发那三样昂贵操作之前就挡住**。

### 用 `slowapi`,按 IP,`10/minute`(方向 C:止血)

跟 CORS 一样,限流是标准需求,用成熟库 `slowapi`,不自己造。它在**内存**里维护
`{IP → 这分钟调了几次}` 的计数,超限就抛 `RateLimitExceeded`。

三个决定及取舍:

- **维度:按客户端 IP**(从 ASGI `scope` 里的 `client` 拿)。这是止血方案。
  **已知局限**:社团很多用户可能共用同一出口 IP(校园 WiFi / 宿舍 NAT),在服务器
  看来是同一个 IP,因此按 IP 限流会**多人共享一份额度**,可能误伤正常用户。精细化
  (按登录用户维度)延后,见 [future_plan.md](future_plan.md) 第 16 项 /
  [issue #67](https://github.com/CSSA-AI/CSSA-DA/issues/67)。
- **额度:`CHAT_RATE_LIMIT` 默认 `10/minute`**,存成字符串,部署时用环境变量按
  实际用量调,无需改代码。
- **存储:内存态,不接 Redis**。本项目由社团部署但**不需要多 ECS 水平扩容**,
  内存态因此是正确选择;Redis 分布式限流彻底归入"将来水平扩容再说"。

一个为测试着想的小设计:传给 slowapi 的限额是一个**函数**(每次请求现读
`settings.CHAT_RATE_LIMIT`),而非写死的字符串 —— 这样测试能临时把额度调到很低来
验证 429,不影响其它测试。

### 两个实现约束(值得记)

- **`/chat` 必须有一个名叫 `request` 的 `Request` 参数**。slowapi **按参数名
  `request` 去找**那个 HTTP 请求对象(它要读 IP),不是按类型。因此把原来的请求体
  参数改名为 `payload`,另加 `request: Request`。对外 JSON 格式不变。
- **429 响应要覆盖成统一安全格式**。slowapi 默认的 429 body 和我们其它错误长得
  不一样,加一个 `RateLimitExceeded` 处理器,让它也返回
  `{"error": {"code": "rate_limited", ...}}`,和 Step 2–4 的错误风格一致。

### 一个已知取舍(暂不处理)

鉴权失败(`require_internal_api_key` 拒绝)**不计入**限流次数,因为 slowapi 的检查
在接口函数内部、鉴权 dependency 之后才执行。要让"狂试错误 key"也被限流,得把限流
挪到鉴权之前,改动更大,不在本步。

---

## Step 6:兜底异常处理器

**文件**:[app/main.py](app/main.py) 加 `@app.exception_handler(Exception)`;
[tests/unit/test_api_middleware.py](tests/unit/test_api_middleware.py) 加测试。

> 前置基础:[7. 框架按继承链(MRO)挑异常处理器](#7-框架按继承链mro挑异常处理器)。

### 要解决什么

加固前只有三种**预料到的** `RAGServiceError` 子类(加 Step 5 的
`RateLimitExceeded`)有专属安全响应。**没预料到的**异常(数据库连接串写错抛出带
明文密码的异常、某处 `None.foo`、第三方库内部炸了)没有对应处理器,会穿透到
Starlette 最外层的默认兜底。两个后果:

- **不走我们的结构化日志**:这条错误不带 `request_id`、不以 JSON 格式记录,排查时
  对不上号。根因是 Starlette 是通用框架,**不认识我们在 Step 1 自定义的日志管道**。
- **响应格式不统一,且潜在泄露**:兜底返回的是 Starlette 的默认格式,不是我们的
  `{"error": {...}}`;若 `debug=True`(开发模式)甚至会把完整堆栈渲染给客户端。
  本项目默认没开 debug,但不该依赖"默认恰好安全"。

### 设计

加一个捕获 `Exception`(所有异常基类)的处理器当**兜底网**:用我们的 `logger` 记
完整异常 + 堆栈(`request_id` 由 formatter 自动带上),对客户端只返回无害的
`{"error": {"code": "internal_error", ...}}` + 500。这和已知错误的安全处理是同一
原则:**内部记全,对外说少**。

**为什么加了兜底不会误伤已有处理器**:见[基础 7](#7-框架按继承链mro挑异常处理器)
—— Starlette 按 MRO 挑处理器,具体类永远比 `Exception` 更近、优先命中,注册顺序
也无关。所以已知错误照走各自的处理器,只有"没人认领"的异常才落到这个兜底。

### 已知边界

新加的 **middleware 自身**如果抛异常,**绕不过**这个兜底 —— 因为异常处理器工作在
Starlette 的 `ExceptionMiddleware` 那层,而我们的两个 middleware 在它**外面**。
缓解办法是保持 middleware 代码尽量简单(它们本就很简单)。

---

## Step 7:让容器 stdout 只剩结构化日志

**文件**:[Dockerfile.cpu](Dockerfile.cpu)、[Dockerfile.gpu](Dockerfile.gpu) 的
uvicorn 启动命令加 `--no-access-log`。不改 Python 代码、不加测试。

### 要解决什么

uvicorn 作为服务器,**默认自己就给每个请求打一条纯文本访问日志**:

```
INFO:     203.0.113.5:54321 - "POST /chat HTTP/1.1" 200 OK
```

而 Step 2 我们已经**自己实现了一条结构化 JSON access log**(带 `request_id`、
`duration_ms`)。结果同一个请求 stdout 上有两条:uvicorn 的纯文本 + 我们的 JSON。
两个坏处:

- **格式不统一**:将来 ECS 上 `awslogs` driver 把 stdout 整个采到 CloudWatch,
  想用结构化查询(如"筛出 `duration_ms > 1000` 的请求")时,那些纯文本行是解析
  不了的噪音。
- **信息还更少**:uvicorn 那条没有 `request_id`、没有耗时,不如我们自己那条有用。

`--no-access-log` 关掉 uvicorn 的**访问日志**,让 stdout 只留我们的结构化 JSON。
注意:关的只是每请求的访问日志,**不影响** uvicorn 的启动日志(`Application
startup complete` 等,那些是想保留的)。

### 取舍

只加在 **Docker 启动命令**里,**不动**本地 `uvicorn --reload` 开发方式 —— 本地
肉眼扫那条纯文本访问日志反而方便,而"stdout 必须纯 JSON"只在生产 → CloudWatch
这条链路才重要。(另一种做法是做成可配置项开发生产统一,属于过度设计。)

### 验证

这步是启动参数、没有单元测试可加,靠**真跑容器**验证:`docker compose --profile
cpu up --build` 后,容器日志里 uvicorn 纯文本访问行 **0 条**、我们的 JSON access
log 正常、启动日志保留 —— 已实测通过(见[完成情况](#完成情况与后续) Step 7/8)。

---

## 中间件注册顺序(总览)

**Starlette 规则:最后 `add_middleware()` 的调用变成最外层**(请求最先经过,响应
最后经过)。当前:

```python
app.add_middleware(RequestContextMiddleware)    # 先加 → 内层
app.add_middleware(SecurityHeadersMiddleware)   # 中层
app.add_middleware(CORSMiddleware, ...)         # 最后加 → 最外层
```

最终层次(外 → 内):**CORS > SecurityHeaders > RequestContext**,正是
[开头那张洋葱图](#先看全局一次请求的旅程)的层次。

- **CORS 最外层**:预检 `OPTIONS` 应被尽早拦下直接回复,不该穿进内层走业务;且
  CORS 头要加在所有响应上(含错误响应)。
- **SecurityHeaders 靠外**:安全头应尽量靠外,连"请求还没进内层就出错"的错误
  响应也能带上安全头。

`main.py` 里对这条反直觉的规则写了注释,防止后续新增 middleware 时被悄悄打乱。

---

## 测试策略

按测试金字塔分两层,各司其职:**逻辑用带 mock 的单元/组件测试(免费、确定、快),
真实基础设施用集成测试,付费的 OpenAI 永远 mock**(见[测试金字塔:各层测什么](#测试金字塔各层测什么))。

### 单元/组件层:`tests/unit/test_api_middleware.py`

风格对齐既有的 [tests/unit/test_api.py](tests/unit/test_api.py)(`TestClient` +
`app.dependency_overrides`,orchestrator 整个换成 stub)。逐项覆盖各中间件与
处理器的行为:

- request_id 缺省时自动生成、客户端提供时原样回传、连续请求间不泄漏。
- access log 恰好一条,`method`/`path`/`status_code`/`duration_ms`/`request_id`
  齐全且与响应头一致。
- 深层(stub orchestrator 的 `run()` 内)日志的 request_id 与响应头一致 —— 证明
  ContextVar 穿透整个调用链,orchestrator 零改动。
- 安全头在成功响应(`/health`)与错误响应(`/chat` 触发 503)上都齐全。
- CORS 预检对允许的 origin 回 `Access-Control-Allow-Origin`,对未配置的 origin
  不回该头。
- 限额调低到 `2/minute` 后,第 3 次 `/chat` 返回 429 且是统一安全格式(不是
  slowapi 默认 body)。
- 抛裸 `RuntimeError`(带敏感串)时,兜底处理器返回安全 500 且异常原文不出现在
  响应里;已有的具体错误测试继续通过,反证兜底没误伤具体处理器。

### 集成层:`tests/integration/test_api_chat_integration.py`

单元层每个中间件是**孤立**测的;集成层验证它们在**真实完整 ASGI 栈**里**组合
正确**。这个测试走真 HTTP `/chat` → 真中间件栈 → **真 pgvector 检索**,只把付费的
OpenAI generator 和 embedding/reranker 模型换成 Fake(免费、确定,CI 也能跑;复用
了 `test_rag_pipeline.py` 的种数据 + Fake 模型模式)。覆盖:

- 带合法 key 的 `/chat` → 200,答案来自 fake generator 但 **sources 来自真实
  数据库检索** —— 证明 HTTP → 中间件 → DB → 响应整条链接线正确。
- **限流 429 仍带安全头 + `X-Request-ID`** —— 这是单元层(孤立测)覆盖不到的
  组合正确性:证明限流拒绝也会正确穿回外层中间件。全程 0 次真实 OpenAI 调用。

### 几个测试陷阱

- 不能直接用 pytest 的 `caplog`。因为 `configure_app_logging` 设了
  `propagate=False`,日志到不了 root logger,而 `caplog` 默认在 root 监听,会
  静默地什么都收不到。测试改为手动往 `"app"` logger 挂一个收集用的
  `logging.Handler`(见 `captured_app_logs` fixture)。
- slowapi limiter 是 `app` 级的共享状态,`TestClient` 又永远用同一个假客户端
  地址,不重置会让限流计数在测试间累积、互相影响。`tests/conftest.py` 加了一个
  autouse fixture 在每个测试前后 `limiter.reset()`。
- 测兜底 500 时要用 `TestClient(app, raise_server_exceptions=False)`,否则
  `TestClient` 默认会把服务器端异常**重新抛出**,拿不到处理器产生的 500 响应。

验证结果:`tests/unit` 162 passed;`tests/integration` 13 passed(需真实
Postgres + pgvector,本地用容器里的独立 `testdb` 跑,CI 用其专用 `testdb`)。

### 测试金字塔:各层测什么

一条铁律:**自动化测试永远不真调付费/不确定的外部服务(OpenAI 等)**,一律在接缝
处用 fake 替换(本项目靠 `Depends` 依赖注入 + `dependency_overrides` 做到)。各类
东西的规范归属:

| 要测的东西 | 放哪层 | 怎么测 |
|---|---|---|
| 限流 429、鉴权、错误映射、安全头、request_id | 单元/组件 | `TestClient` + stub orchestrator,不碰 OpenAI |
| 真 pgvector 检索、DB 迁移、导数据、HTTP 全栈接线 | 集成 | 真 Postgres,只 mock 掉付费的 OpenAI |
| 生成回答的质量、OpenAI 真实行为 | 不做自动化断言 | 人工/离线 eval,不进 CI |
| "整条链在真服务器上活着" | E2E 冒烟 | 起真容器打 `/health`,第三方仍 mock |

---

## 完成情况与后续

「保护 `/chat`」这项工作(future_plan 第 1 项)的 8 步**全部完成并验证**:

- Step 1–6:结构化日志、request_id 中间件、安全头、CORS、限流、兜底异常处理。
- Step 7:两个 Dockerfile 的 uvicorn 加 `--no-access-log`,stdout 只保留结构化
  JSON —— 已在真实容器里验证(纯文本访问行 0 条,JSON access log 正常)。
- Step 8:手动端到端验证 —— 对真实 `docker compose` 容器过了一遍 `/health`、
  `/ready`、安全头、`X-Request-ID`、CORS、`/chat` 鉴权;限流 429 由单元 + 集成
  测试覆盖。

后续步骤见 [future_plan.md](future_plan.md):模型交付可预测化(第 2 项)、
持久化存储(第 3 项)、容器加固(non-root、固定基础镜像、锁依赖、瘦身)、以及
AWS 基础设施与 CI/CD。限流的精细化(按用户维度)见 future_plan 第 16 项 /
[issue #67](https://github.com/CSSA-AI/CSSA-DA/issues/67)。
