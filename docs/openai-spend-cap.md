# OpenAI 硬性支出上限（运维手册）

> 对应 [ROADMAP_platform.md](roadmap/ROADMAP_platform.md) 19.4「OpenAI 后台设硬性
> 支出上限」。这是控制台操作，代码管不到，必须由持有 OpenAI 账号管理权限的人手动
> 完成，并在完成后勾掉 roadmap 里的复选框。

## 为什么必须设

限流（per-IP + 全局）只能**放慢**烧钱速度，不能封顶：

- 全局限流数的是**请求数**，不是 token 数——单个大请求的成本仍然远高于平均值
  （输入体积上限见 roadmap 19.5，是独立任务）
- 任何代码层的防线都可能有漏洞；支出上限是 OpenAI 侧的兜底，**不管前面漏成
  什么样，当月最多花这么多**

## 操作步骤

1. 登录 [platform.openai.com](https://platform.openai.com/)，切到本项目所用的
   organization（右上角头像 → 确认 org）
2. 进入 **Settings → Organization → Limits**（或直接访问
   [platform.openai.com/settings/organization/limits](https://platform.openai.com/settings/organization/limits)）
3. 在 **Usage limits** 里设置：
   - **Budget limit（硬上限）**：当月用量达到该金额后 API 请求直接被拒绝
   - **Notification threshold（告警线）**：建议设为硬上限的 50%–80%，达到时
     OpenAI 会给账号邮箱发邮件，留出反应时间
4. 若项目使用了 OpenAI 的 **Projects** 功能，可在 **Settings → Project →
   Limits** 里再给单个 project 设更细的月度预算，与 org 级上限叠加生效

## 上限设多少

按最坏情况估算月成本，再留余量：

```
月成本上界 ≈ 单请求最大成本 × CHAT_GLOBAL_RATE_LIMIT(每天) × 31
```

内测阶段全局限流默认 `1000/day`，正常单请求成本远低于 $0.01；建议先设一个
**明显高于正常月账单、又低到出事时亏得起**的整数（例如正常月账单的 3–5 倍），
跑一个月后按实际用量回调。

## 触顶之后会发生什么

- OpenAI API 对后续请求返回 `429 insufficient_quota`，SDK 抛 `RateLimitError`
- 后端把它映射为 `GenerationUnavailableError`，`/chat` 返回 `503` 和统一错误体
  （见 [chatgpt_generator.py](../app/services/rag/generator/chatgpt_generator.py)
  的异常处理）——服务降级但不崩溃，检索仍可用
- 恢复方式：等下月额度刷新，或管理员在控制台上调 Budget limit

## 完成后核对

- [ ] Budget limit 已设置并截图存档（金额多少记录在团队内部渠道，不进仓库）
- [ ] Notification threshold 已设置，告警邮箱是有人看的邮箱
- [ ] 勾掉 [ROADMAP_platform.md](roadmap/ROADMAP_platform.md) 19.4 的对应复选框
