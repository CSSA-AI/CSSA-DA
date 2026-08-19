# OpenAI 硬性支出上限（运维手册）

> 对应 [ROADMAP_platform.md](roadmap/ROADMAP_platform.md) 19.4「OpenAI 后台设硬性
> 支出上限」。这是控制台操作，代码管不到，必须由持有 OpenAI 账号管理权限
> （org Owner）的人手动完成，并在完成后勾掉 roadmap 里的复选框。

## 为什么必须设

限流（per-IP + 全局）只能**放慢**烧钱速度，不能封顶：

- 全局限流数的是**请求数**，不是 token 数——单个大请求的成本仍然远高于平均值
  （输入体积上限见 roadmap 19.5，是独立任务）
- 全局限流是进程内存计数：重启清零，将来多 worker 部署时有效额度会 ×N
- 任何代码层的防线都可能有漏洞；支出上限是 OpenAI 侧的兜底，**不管前面漏成
  什么样，当月最多花这么多**

## ⚠️ 最大的坑：只填金额不等于封顶

2026 年初 OpenAI 曾把硬性支出上限**静默降级为仅邮件预警**（只剩 alerts），
2026 年 7 月下旬才恢复。当前控制台里，**必须显式打开 "Enforce a hard limit"
开关**——只填金额不开开关，就只是预警线，不会拒绝请求。设完后务必目视确认
开关状态为 ON 并截图存档。

## 操作步骤

1. 登录 [platform.openai.com](https://platform.openai.com/)，切到本项目所用的
   organization（右上角头像 → 确认 org）
2. 建议为 CSSA-DA 使用**独立的 Project**（若还没有：Settings → Projects →
   Create project，并把后端用的 API key 换成该 project 的 key）——这样上限只
   约束本项目，不影响同 org 下其他用途
3. 进入 **Settings → Project → Limits → Spend**，点 **Edit spend limit**：
   - 填月度金额（见下节），**打开 "Enforce a hard limit" 开关**，保存
4. 再到 **Settings → Organization → Limits → Spend** 设一个更高的 org 级
   上限作为二道兜底（project 级与 org 级叠加生效，任一触顶即拒绝）
5. 在 **Spend alerts** 里设 50% 和 80% 两档告警，确认告警邮箱是有人看的邮箱
6. **实测一次**：鉴于「静默降级」的前科，用一个小额 scratch project（如上限
   $1）真实打到触顶，确认 API 返回 429 且错误码为 `*_spend_limit_exceeded`，
   再相信生产上限已生效

## 上限设多少

按最坏情况估算月成本，再留余量：

```
月成本上界 ≈ 单请求最大成本 × CHAT_GLOBAL_RATE_LIMIT(每天) × 31
```

内测阶段全局限流默认 `500/day`（gpt-4o-mini，正常单请求成本约 $0.0005–0.002，
典型月成本 $10 上下）。建议 **project 级 $20/月 + org 级 $50/月**：明显高于
正常月账单、又低到出事时亏得起，跑一个月后按实际用量回调。若要调大
`CHAT_GLOBAL_RATE_LIMIT`，先按上式重算并同步上调这里的金额。

⚠️ **上式里的「单请求最大成本」不是上面那个正常值。** 输入体积上限已随
CSS-6（`ae68a46c`）落地，因此上界现在可以精确算出：

```
system_prompt                113 字符
chat_history 上限     20 × 4,000 字符
message 上限              10,000 字符
检索上下文上限          5 × 2,000 字符   (rag-config.yaml generator.context)
──────────────────────────────────────
合计                    100,113 字符 ≈ 61,512 tokens
                        (中文 token/字符比 0.614，o200k_base 实测)
```

gpt-4o-mini 输入 $0.15/1M → **单请求最大成本 ≈ $0.0097**，是正常值的 5–19 倍。
代入上式：`$0.0097 × 500 × 31 ≈ $150/月`。

也就是说 **`500/day` 并不能把支出压在 $20 以内——project 级硬上限不是兜底，
它就是实际生效的那道闸**。持续按最大体积构造请求时，$20 约 **4 天**打满
（`20 ÷ ($0.0097 × 500) ≈ 4.1`），之后当月 `/chat` 全部返回 503。这是「封顶
优先于可用性」的有意取舍（见
[global-rate-limit.md](design/implemented/global-rate-limit.md) 的「已知取舍」），
50%/80% 告警正是为这个场景准备的——收到 50% 告警就该去查日志，而不是等打满。

## 触顶之后会发生什么

- OpenAI API 对后续请求返回 429，错误码为 `project_spend_limit_exceeded` /
  `organization_spend_limit_exceeded`（注意与预付费余额耗尽的
  `insufficient_quota` 是两回事，排障时先分清是哪个）
- SDK 抛 `RateLimitError`，后端把它映射为 `GenerationUnavailableError`，
  `/chat` 返回 `503` 和统一错误体（见
  [chatgpt_generator.py](../app/services/rag/generator/chatgpt_generator.py)
  的异常处理）——服务降级但不崩溃，检索仍可用
- usage 统计有约几十分钟延迟，触顶前后的少量请求可能漏过，上限金额不必精确
  到美分
- 恢复方式：等下月额度刷新，或管理员在控制台上调 spend limit

## 完成后核对

- [ ] Project 级 spend limit 已设置，**"Enforce a hard limit" 开关为 ON**，
      已截图存档（金额记录在团队内部渠道，不进仓库）
- [ ] Org 级 spend limit 已设置为二道兜底
- [ ] Spend alerts（50%/80%）已设置，告警邮箱是有人看的邮箱
- [ ] 已用 scratch project 实测过一次 `*_spend_limit_exceeded` 429
- [ ] 勾掉 [ROADMAP_platform.md](roadmap/ROADMAP_platform.md) 19.4 的对应复选框
