# 竞品源码走读（ROADMAP iter1 交付物）

> 走读日期：2026-09-28 凌晨。方法：官方 README/文档站 + 源码定点取证——ccusage 抓取了 `rust/crates/ccusage-core/src/cost.rs` 与 `docs/guide/cost-modes.md` 的原文（raw.githubusercontent，当日实抓）；AgentMeasure 与 echo 为 README/文档级精读，**未逐行走读其源码，本文中相关结论如实降级为"自述级"**。星数为当日 GitHub 页面实抓。

## 一、四栏对照（源码/文档级证据）

| 方案 | 是否信任报数 | 是否有账本 | 是否有复算 | 价格表来源 |
|---|---|---|---|---|
| ccusage（18.8k★，活跃） | **信任**。`display` 模式直接用日志 `costUSD`；默认 `auto` "有预计算费用时直接使用 costUSD"；`calculate` 也只是把日志里的 token 数乘价格 | 无。只读本地日志，只读不写，无任何链式结构 | **无**。`cost.rs` 的 `calculate_cost_from_tokens` 直接吃 `UsageEntry.message.usage`（`TokenUsageRaw`），唯一防御是 `saturating_add` 防溢出——注释原话"corrupt line must not wrap the sum below the threshold"，防的是加法回绕，不是数字造假 | LiteLLM 数据库 + models.dev 目录 + 内置历史价格表；按事件时间戳 `pricing.find_at(model, ts)` 匹配当时价格 |
| AgentMeasure（218★） | 部分质疑。"证据与推论分离"，缺证据判 `UNPROVABLE`，"never silently zero" | 无哈希链。有 **AMS-1 结算声明**（SETTLEMENT.md 一页纸 + dispute-bundle JSON），宣称"同输入在任何机器重跑出同一声明" | **无逐条复算**。做的是一致性 conformance 规则（HC-01..06：重复记录、重试链、缓存核算、token stability），PASS/FAIL/UNPROVABLE 三态 | 不内嵌价格表；引用厂商公开单价（Zendesk $1.50-2.00/次等）做基准对照 |
| echo（546★，活跃） | 信任**自家代理**：请求过 `router.echo.merit.systems`，平台侧记账计费 | 平台侧记录，未描述任何开放审计机制 | 无 | 平台侧定价（含开发者加价 markup） |
| litellm cost tracking | 信任 | 无 | 无（报数 × 价格纯乘法） | `model_prices_and_context_window.json`（社区事实标准） |
| langfuse / Helicone | 信任 | 有记录无链 | 无 | 配置价 × 报数 |
| **tellan（本项目）** | **质疑**：四态裁决（OK / INFLATED / DEFLATED / INSUFFICIENT_DATA） | **哈希链 JSONL 账本**（CT 思路，`verify()` 定位首个坏 seq） | **包围盒复算**（非 OpenAI 模型诚实输出 [lo, hi]）+ 六类异常检测 | 内置 38 模型快照（逐条标注"快照估值，未逐条核验"）；溯源工具链 = iter5 |

## 二、ccusage 走读细节（对标重点）

**架构**：TypeScript monorepo（pnpm workspace）+ **Rust 重写进行中**（`rust/crates/ccusage-core` 等），Nix 打包，2,176 commits、issue 积压仅 2 个——工程与分发能力顶级。数据源覆盖 18 种 coding CLI 的本地日志。

**三种费用模式**（`docs/guide/cost-modes.md` 原文）：

| 模式 | token 数 | 价格 | 用途 |
|---|---|---|---|
| `auto`（默认） | 日志 | 日志 costUSD 优先，否则算 | 日常 |
| `calculate` | 日志 | LiteLLM + models.dev，按时间戳匹配 | 跨时期一致性比较 |
| `display` | — | 只显示日志已有 costUSD，缺失显示 $0.00 | 与实际账单核对（注意：是"对 Claude 的账"，不是独立裁决） |

**官方免责声明（原文）**："Costs are estimates and may not reflect actual billing"。另有：Web Search 等工具调用产生的 token 不计入；某些代理因"本地文件不含可靠 token 用量"整个数据源不被支持。

**做对了的（值得尊敬，部分值得抄）**：

1. **时间戳匹配价格**（`find_at(model, timestamp)`）：为 DeepSeek 这类分时段调价设计，旧日志按当时价格重算——我们的 prices.json 目前是"一口价快照"，重审历史账本会用今天的价格审昨天的账（已转为 iter9）。
2. **模型别名链式回退**（`resolve_model_name` + 多候选遍历，全部落空才报缺失）：比我们的单层别名归一化更强韧。
3. **缓存 token 细分计价**：5m/1h 两档（1h 乘 `CACHE_CREATE_1H_INPUT_MULTIPLIER = 2.0`），无细分时回退扁平费率——比我们"cached 一档"更贴 Anthropic 真实计费。
4. **长上下文阶梯计价**（`long_context_threshold` / `tiered_cost`）：我们完全没有。
5. **分发工程**：18 源接入 + Nix/Rust 双轨 + 文档站——涨到 18.8k★ 的直接原因，值得 iter8 发布工程参照。

**反面教材（不许抄）**：价格查不到**静默返回 0.0**（`calculate_cost_from_tokens` 一律 `0.0` 不报错，仅旁路 `missing_pricing_model_*` 报告）——对账工具最忌讳"算不出就当免费"；tellan 对应行为是 `PRICE_MISSING` 异常 + `INSUFFICIENT_DATA` 降级。

**对我们生态位最重要的发现**：`cost.rs` 全文**没有 reasoning token 的任何处理**——这家最大的用量统计工具对 2025 年以来最大的计量变量（不可见推理消耗）视而不见；且官方承认费用"may not reflect actual billing"。统计赛道它赢，**裁决赛道无人做**，源码级确认成立。

## 三、AgentMeasure（自述级，未走读源码）

- **定位差异**：它是"Agent 会话度量 + 计量一致性 conformance"，面向 Codex/Claude Code 会话日志的审计语义，不是 API 账单逐条对账。与我们相邻但不同赛道。
- **可尊敬的纪律**："never silently zero"、证据/推论分离、实验预注册（假设先哈希）、同输入重跑同声明——与我们的 INSUFFICIENT_DATA 诚实降级同源。
- **AMS-1 结算声明**：一页纸（双向两行、无法结算的移除项、第三方复现块）+ dispute-bundle JSON。这是"可发给对方客服的审计产物"的好形态，我们只有 markdown 报告（已转为 iter10）。
- **生态证据（对 GAP_PROOF 的加持）**：它自述审计了 110-124 个 usage 工具、发现 45+ 个已验证计费 bug、19 个修复合入上游——**"用量数字普遍不可靠"已是被第三方实测过的行业事实**。
- **付费意愿证据**：商业层 $990 一次性对账 / $490 月起，开源层永久免费——说明这个方向有真实预算。
- **边界**：0 watching、218★、无准确率 SLA、Utility/Value 层仍草案——它没占住"逐条对账 + 防篡改"位置。

## 四、echo（自述级）

代理式计量（"user pays"SDK，开发者加价分成）：请求过它的 router，**计量方=收费方=受益方**。这把结构性问题摆上了台面：**谁做计量，谁就想让报数为真**——litellm/网关/中转站/echo 全在这个利益结构里，独立审计没有动机去质疑自己经手的数字。tellan 的立场（离线、脱敏、质疑报数）恰好站在这个结构的对面。它没有审计/对账概念，不构成竞争。

## 五、结论

1. **生态位源码级确认**：四个维度（质疑报数 / 防篡改账本 / 独立复算 / 异常裁决）没有任何一个现有工具占全；最大的统计工具 ccusage 官方自认费用是估算。
2. **吸收两条**（已转 ROADMAP iter9/iter10）：时间戳匹配价格；一页纸对账声明工件。
3. **反面教材一条**：静默 0.0——已由 PRICE_MISSING/INSUFFICIENT_DATA 覆盖，写进文档当立场。
4. **风险更新**：ccusage 若加"验证模式"是最现实的威胁（渠道+工程力碾压）；对冲 = 中文中转生态切口（它 18 个源里没有 new-api/one-api）+ 代理捕获（它是日志只读，我们做不了它的赛道，它也还没做我们的）。

## 六、证据清单

- ccusage 仓库与 README：https://github.com/ccusage/ccusage （18.8k★，2,176 commits，2026-09-28 实抓）
- ccusage 费用模式文档：https://raw.githubusercontent.com/ccusage/ccusage/main/docs/guide/cost-modes.md （2026-09-28 实抓）
- ccusage 算费核心源码：https://raw.githubusercontent.com/ccusage/ccusage/main/rust/crates/ccusage-core/src/cost.rs （2026-09-28 实抓）
- AgentMeasure：https://github.com/roy-tong/AgentMeasure （218★，2026-09-28 实抓，README 级）
- echo：https://github.com/Merit-Systems/echo （546★，2026-09-28 实抓，README 级）
