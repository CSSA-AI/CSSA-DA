# 全站全局限流（CSS-10）：实现记录与不变量

> 状态：已实现。对应 [ROADMAP_platform.md](../../roadmap/ROADMAP_platform.md)
> 19.4「加全局限流」。OpenAI 侧的硬性支出上限（同一节第一项）见
> [docs/openai-spend-cap.md](../../openai-spend-cap.md)。

## 机制

在既有的同一个内存态 slowapi limiter 上，给 `/chat` 叠加第二个
`@limiter.limit` 装饰器：key_func 返回常量 `"global"`，全部客户端共享一个
计数桶（`CHAT_GLOBAL_RATE_LIMIT`，默认 `500/day`）。per-IP 层管「单个来源
别刷太快」，全局层管「全站总量封顶」——换 IP 绕得过前者，绕不过后者。

不引入 Redis（当前部署恒为 1 容器 × 1 uvicorn worker，内存计数就是真全局，
见 rate_limit.py 头注释的部署边界声明）；不新建第二个 Limiter 实例（否则
tests/conftest.py 的 autouse reset 会漏掉它）。

## 两条不变量（依赖 slowapi 未文档化行为，改动前必读）

以下语义在钉住版本 slowapi 0.1.10 + limits 5.8.0 的源码上核实过：

1. **两层限流都必须传 callable，不能传字符串字面量。**
   slowapi 把静态字符串限流永远排在所有 callable 限流之前评估，与装饰器
   书写顺序无关。若全局层退化成字符串，会被提前评估，被 per-IP 拦下的请求
   照样烧全局额度。

2. **装饰器顺序 load-bearing：per-IP 层必须是靠近函数的底部装饰器。**
   两层都是 callable 时按装饰器自下而上的注册顺序评估，且 slowapi 的
   hit 是「先扣再判、失败即断」。per-IP 在底部 → 先评估 → 它的 429 在触碰
   全局计数**之前**短路，单个狂刷的 IP 烧不掉全站额度。顺序反了，一个 IP
   用被拒绝的请求就能把全站打到熔断。回归哨兵：
   `test_per_ip_429s_do_not_burn_the_global_budget`。

   反向代价（可接受）：请求过了 per-IP 但被全局拦下时，该 IP 的分钟额度
   被白扣一次，不退款。

## 配套语义

- **fail-open 防护**：slowapi 对 callable 限额串的解析发生在每个请求时、
  包在 try/except 里，解析失败只记一条日志然后**跳过该层**（fail-open）。
  拼错限额串 = 静默裸奔。因此 `validate_rate_limit_config()` 在 lifespan
  启动期 fail-fast（含拒绝 `0/day` 这类解析合法但全站熔断的值），调用点
  必须在模型预载的 try/except **之外**。
- `"day"` 是 fixed-window：窗口从该 key 的首个请求起算 86,400 秒，不是
  自然日/UTC 对齐；进程重启计数清零。
- 429 响应体两层完全一致（统一安全错误体，不泄漏限额数值）；区分哪层
  触发看服务端 WARNING 日志（`"10 per 1 minute"` = per-IP 噪音，
  `"500 per 1 day"` = 全站额度耗尽，两种事态处置不同）。
- 生产调参：改 `CHAT_GLOBAL_RATE_LIMIT` 环境变量并重启容器。镜像内没有
  .env，该变量必须经 docker-compose 的 environment 块透传才能生效（已配）。
  调大前先按 [openai-spend-cap.md](../../openai-spend-cap.md) 的公式重算
  月成本，确认不顶穿 OpenAI 硬上限。

## 已知取舍

- 数请求数不数 token：单个大请求成本远高于均值，输入体积上限是 roadmap
  19.5 的独立任务，落地前本层的成本模型对恶意构造的大请求不成立。
- 全局额度可被恶意打满（全站 429 到窗口结束）：这是「封顶优先于可用性」
  的有意选择——被打满的损失上界是一天的限额成本，而不设全局层的损失上界
  是 OpenAI 账单。缓解手段是 per-IP 层先行拦截 + 日志告警人工介入。
- 鉴权失败（401）不计入任何限流层：沿用第 1 项的既有取舍
  （[chat-api-hardening.md](chat-api-hardening.md)），401 不触发 OpenAI
  调用，对成本封顶无害。
