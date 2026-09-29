# REPORT — tellan（Tellan）夜间自动化迭代总结（2026-09-28 01:10 → 07:45）

> 执行方式：主会话完成 iter0（完整项目初版，构建 agent 产出 + 主会话验收），此后 3 轮自动化迭代（每小时一轮）+ 本收尾轮。
> 全程未 push 远程；所有提交在本地 `main`（v0.1.0-rc1 → 773ed39）。

## 一句话总结

**tellan（Tellan）v0.1.0-rc1 + 三个迭代完成**：LLM API 账单对账与计量审计标准件——哈希链防篡改账本、独立复算包围盒、三方对账裁决、六类异常检测、new-api/one-api 账目导入、tiktoken 精确模式族门禁；**137 项测试全绿，ruff 0 error**。生态位经竞品源码级走读确认：ccusage（18.8k★）的 `cost.rs` 直接信任日志报数，官方自述"费用是估算值"，裁决赛道无人占据。

## 每轮完成清单

| 轮次 | 时间 | 完成内容 | 测试 |
|---|---|---|---|
| iter0 | 01:10–01:45 | 完整项目：哈希链账本、HeuristicCounter 包围盒、三方对账四态裁决、六类异常检测、捕获代理（默认脱敏）、CLI 五命令、内置基准 | 111+1skip |
| iter1 | 02:40–03:00 | **竞品源码走读**：ccusage `cost.rs` 源码级确认信任报数（官方自述费用为估算、reasoning token 无计价）；AgentMeasure/echo 自述级；docs/competitors.md 四栏对照；追加 iter9（时间戳匹配价格）/iter10（对账声明工件） | 111+1skip |
| iter2 | 04:40–04:56 | **new-api/one-api 账目导入** `tellan import`：两家 Log struct 源码级字段表、JSONL/CSV 双格式、秒/毫秒/ISO 时间戳统一、缺 request_id 确定性合成、type==2 过滤、quota 折算；`Ledger.append` 加可选 ts（向后兼容）；docs/newapi.md 八条已知坑 | 130+1skip |
| iter3 | 06:40–06:54 | **tiktoken 族门禁**：覆盖清单数据化 + 负名单（kimi 等自有分词器强制拒绝，实测 cl100k 硬数 Kimi 偏差 3x）；`--strategy tiktoken` 不覆盖时降级 heuristic 并留痕；`tellan warmup` 预热命令；真实校准报告 benchmarks/calibration.md；**fixture 报数真值更正**（gpt-4o 的"厂商报数"原是 heuristic 编造值） | 137 |
| wrap-up | 07:40–07:45 | 双项目终验（pytest 退出码 0 / ruff 退出码 0）+ 本报告 | 137 |
| iter10 | 2026-09-28 日间 | **对账声明工件** `tellan statement`（OPEN_SOURCE_GROWTH_PLAN §5.5 主入口，先于 iter4 执行）：单页 Markdown+JSON——被质疑条目（报数 vs 复算盒并排 + record_hash）、异常清单、价格来源与缺价披露、复现命令块、`statement_sha256` 确定性（路径不参与哈希，换目录重跑同哈希）；链损坏/账本不存在拒绝出具；docs/statement_example.{md,json} + demo_ledger.jsonl（合成，复现命令实跑验证同哈希）；README 展示名 The Ledger of Vanishing Tokens + 方式五 | 150 |

## 关键数字（全部真实运行，出处见对应文档）

- 内置基准（11 个合成 fixture，`benchmarks/results.md`）：诚实报数 **100% 落包围盒**；故意操纵 case（报数膨胀 2x、content:null 计费、中转截断）**裁决与异常全部命中**；单条对账 ~0.3ms（纯 CPU）
- 盒宽校准（`benchmarks/calibration.md`，tiktoken 0.14.0 实测）：gpt-4o 输入比率 1.39x / 输出 0.92x、gpt-4o-mini 0.87x / 0.98x——设计盒 [0.5, 1.6] 全覆盖；国产模型族 9 条诚实列「无法校准」
- 竞品证据（`docs/competitors.md`）：ccusage `calculate_cost_from_tokens` 直接采用日志 usage、价格查不到静默返回 0.0、reasoning token 在算费源码中完全不存在；AgentMeasure 审计 124 个用量工具发现 45+ 计费 bug（行业级证据）
- 中转生态切口：`tellan import` 一行命令接入 new-api（48,972★）+ one-api（37,026★，已停更）账目导出——ccusage 的 18 个数据源里没有这一条

## 夜间抓到的真 bug / 事故（评审与测试当场修复，全部留痕）

1. **fixture 报数造假被 tiktoken 戳穿**（iter3 最有价值发现）：gpt-4o 的"厂商风格报数 110/20"实为构建时按 heuristic 点估计填写的合成值，tiktoken 实测 107/12 → honest fixture 测试失败是对的；已改真值，usage 来源披露转 iter13
2. kimi-k2 曾被权重族并入 openai_legacy → 精确模式负名单修复（cl100k 硬数偏差 3x）
3. Ledger.append 无 ts 参数 → 历史账目导入会丢失原始时间戳 → 向后兼容扩展
4. 校准脚本口径错误（手工抽 content 漏 tool_calls 文本）→ 与实现共用 message_text
5. 两次门禁事故诚实存档：iter2 一次带红提交（命令链管道写法失误 + Windows 套接字抖动偶发，已改为直读 pytest 退出码 + `_post` 传输层重试）；iter3 全套 160s 回归（文档级限速首次真生效，bench mock 需显式零间隔预算）——均已在 WORKLOG 记录

## 诚实未完成项

1. **iter4、iter5~iter8 及评审追加条目（iter9、iter11~iter13）未执行**：偏差排行榜生成器、价格库溯源、代理加固、红队轮、发布工程、时间戳匹配价格、真实站点校准、捕获测试根因加固、usage 来源披露（iter10 对账声明已于 2026-09-28 日间完成，见上表；协议下一项回到 iter4）。
2. **零真实数据验证**：全部基准是合成 fixture；未对真实厂商/中转站出网采数（设计立场：内置基准不构成对任何真实厂商的指控）。
3. 价格快照 38 条未联网逐条核对（逐条标注"快照估值，发布前需人工核对"）。
4. tiktoken 未随包安装时的路径依赖 `pytest.importorskip`；CI 离线需按 docs/tiktoken.md 方案预热。
5. 账本无签名：防事后篡改不防根信任伪造（HMAC/外部锚定设计选项在 iter7 红队轮）。

## 给你的下一步建议（按优先级）

1. **注册 GitHub 仓库并 push**：`cd tellan && git remote add origin <url> && git push -u origin main`。README 的三方对账图 + docs/statement_example.md（一页对账声明示例，可直接当首发截图/贴文素材）+ docs/competitors.md 的 ccusage 源码级对照是现成的首发内容。
2. **发布渠道**：Show HN（钩子：ccusage 18.8k★ 但全行业在信任厂商报数）；V2EX/掘金中文场（钩子：new-api/one-api 站长与用户的对账工具，`tellan import` 是唯一能吃中转账本的入口）；把 docs/competitors.md 改写成《我们读了 ccusage 的算费源码》一文。
3. **跑一遍真实数据**：用你自己的 API key 走 `tellan proxy` 一晚 + 导出你常用中转站的账目 `tellan import`——真实偏差数据是 iter4 排行榜的第一批弹药，也是 README 最有说服力的截图。
4. **价格快照人工核对**：按 iter5 的 runbook 先核对热门 10 个模型（deepseek-chat/gpt-4o/glm-4.6/kimi-k2 优先）。
5. PyPI 发布需要你的 token（包名 `tellan` 已验证未注册，01:12 查询 404）。
