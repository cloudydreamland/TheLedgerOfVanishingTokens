# ROADMAP — 夜间自动化迭代驱动表

> 规则：自动迭代每一轮从上到下找第一个未勾选条目，完整做完（代码+测试+文档）再勾选。
> 每条目设计为一轮（≤45 分钟）可完成。做完更新 WORKLOG.md 并提交。
> 每轮固定动作：① 选条目实现；② **对抗评审**（以资深开发者/项目经理/老板三视角挑刺，可上网核查竞品与用户抱怨，结论写入 WORKLOG 的"评审记录"）；③ 有效批评转化为新条目追加到本表末尾；④ 全量 pytest + ruff 必须绿；⑤ 提交。

## 迭代条目

- [x] **iter1 — 竞品源码走读（2026-09-28 夜间完成）**：精读 ccusage 与 AgentMeasure 的核心源码（账单解析、价格表、聚合口径），可选补充 echo 等同类小工具；写 `docs/competitors.md`：各家"是否信任报数 / 是否有账本 / 是否有复算 / 价格表来源"四栏对照，如实记录它们做对了什么；README"与现有方案的关系"表格据此更新为源码级结论。→ 完成：ccusage 走读到 `cost.rs` 源码级（信任报数、无复算、reasoning token 无处理、官方自述费用为估算、时间戳匹配价格/别名链/缓存细分/长上下文阶梯 four 项可吸收设计、静默 0.0 反面教材）；AgentMeasure/echo 自述级精读（如实标注未走读源码）；docs/competitors.md + README 表更新；评审追加 iter9（时间戳匹配价格）/iter10（对账声明工件）。
- [x] **iter2 — new-api/one-api 账目导出适配器（2026-09-28 夜间完成）**：实现 `tellan.adapters.newapi`：把中转站的账目导出（JSON/CSV）映射为 tellan 账本记录（列映射表 + 字段文档），处理常见脏数据（缺 request_id、usage 为字符串、时间戳格式不一）；配 fixture 测试；写 `docs/newapi.md` 说明导出路径与已知坑。
- [x] **iter3 — tiktoken 精确模式覆盖面与 CI 策略（2026-09-28 夜间完成）**：盘点精确模式可覆盖的模型清单（含第三方 OpenAI 兼容端点），`--strategy tiktoken` 对非 OpenAI 模型给出明确行为（降级 or 报错，二选一并文档化）；设计 encoding 缓存预热方案（离线 CI 不下载）；为盒宽校准写一个最小脚本（用 tiktoken 对内置 fixture 实测各真盒宽，输出建议倍率，写进 benchmarks）。
- [ ] **iter4 — 计量偏差排行榜生成器**：`tellan rank`：从多本账本聚合各模型/各 provider 的偏差统计（均值、P95、落盒率），生成周报 markdown 工件（可直接发布的内容形态）；内置匿名化样例数据；明确"数据从哪来、如何脱敏"的说明，不编造真实厂商数字。
- [ ] **iter5 — 价格库溯源与刷新工具链**：`tellan prices` 子命令族：list/check/diff；每条价格补 `source_url` 字段约定；写刷新 runbook（人工核对流程，明确"脚本抓取仅作候选，人工确认才入库"）；对快照做"过期提醒"（as_of 超过 N 天在审计输出中提示）。
- [ ] **iter6 — 代理加固**：CaptureProxy 补重试（幂等安全时）、上游 TLS 校验开关、连接/读超时参数化、大响应（>10MB）与流式背压处理、并发压测（线程池 50 并发不丢账本记录）；账本并发追加跨进程安全性评估（当前锁是进程内的，如实写结论）。
- [ ] **iter7 — 红队评审轮**：以安全工程师视角审计：账本伪造（攻击者能否重构整条链？——能，本地账本无签名，如实文档化"防篡改防的是事后抵赖，不是根信任伪造"，并给出 HMAC/外部锚定的设计选项）、代理绕过（直连上游绕过捕获的检测建议）、日志注入（messages 里的控制字符/超长行）、--no-redact 的误用警告。
- [ ] **iter8 — 发布工程**：launch_checklist（V2EX/掘金/知乎/imjtz 文案要点：以"Gemini 计费事故你还查不出"为钩子）；PyPI 发布检查单；README_EN.md 完整版；`python -m build` 出 sdist/wheel 验证；tag v0.1.0。

### iter1 评审追加（2026-09-28 夜间，竞品源码走读产出）

- [ ] **iter9 — 时间戳匹配价格**：借鉴 ccusage `pricing.find_at(model, timestamp)`（其为 DeepSeek 分段调价设计）：`prices.json` 条目支持可选 `effective` 生效区间，audit/report 按账本记录 ts 匹配当时价格——重审旧账不再用今天的价格审昨天的账；fixture 测试覆盖"调价前后两笔同模型记录"；任何时段都查不到价格时走 `PRICE_MISSING`，不学 ccusage 的静默 0.0；文档写明与 litellm/models.dev 字段的兼容约定。
- [x] **iter10 — 对账声明工件（settlement statement）（2026-09-28 日间完成）**：借鉴 AgentMeasure AMS-1"一页纸可申诉产物"：`tellan statement LEDGER` 生成单页 Markdown + JSON（被质疑条目、厂商报数 vs 本地复算并排、异常清单、**复现命令块**），第三方拿账本 + 同版本脚本重跑应得同一结论（做成确定性测试）；这是"可发给中转站客服"的交付形态，也是可传播内容。→ 完成：`statement.py` + CLI 子命令（链损坏/账本不存在拒绝出具，exit 2）；`statement_sha256` 覆盖版本+账本哈希+参数+汇总+质疑清单，路径与复现命令不参与哈希（换目录重跑同哈希，测试锁死）；缺价显式披露"未计入合计"；演示工件 docs/statement_example.{md,json} + docs/demo_ledger.jsonl 由 tools/make_demo_statement.py 确定性生成，声明内复现命令已实跑验证同哈希；+13 测试（全量 150 passed / ruff 0）。注：本条先于 iter4 执行，依据 OPEN_SOURCE_GROWTH_PLAN §5.5（声明为主入口）；iter4 仍是协议下一项。

### iter2 评审追加（2026-09-28 夜间，适配器实现轮）

- [ ] **iter11 — 真实站点导出校准**：当前适配器只在两家 main 分支 Log struct（2026-09-28 实抓）与合成 fixture 上验证过，**未接触真实站点导出**。征集 ≥2 个真实部署（不同版本/不同 DB 后端）的脱敏导出样本，统计适配器贴合率（识别/跳过/字段命中率）写进 benchmarks；docs/newapi.md 的"已知坑"逐条用真实样本证实或证伪。在此之前，文档中所有"已验证"表述均指源码级+fixture 级。

- [ ] **iter12 — 捕获测试加固**：`test_capture.py` 在 Windows 上出现过一次 `ConnectionAbortedError` 套接字中断竞态（2026-09-28 夜间，重跑即绿）：排查测试 teardown 顺序与 server 端 keep-alive/关闭时序，加重试或隔离端口（bind 0），目标：连跑 20 遍全绿；顺带给 CI 加 pytest 重跑策略的评估结论（加或不加都写明理由）。

### iter3 评审追加（2026-09-28 夜间，tiktoken 轮）

- [ ] **iter13 — fixture 报数来源披露（usage provenance）**：gpt-4o fixture 的"厂商风格报数"被 tiktoken 实测戳穿为合成值（构建时无真值可依）。给 FIXTURES 增加 `usage_source` 字段（"tiktoken 实测" / "heuristic 合成" / "厂商文档示例"），bench 报告逐条披露该字段；规则：有真值必须用真值，无真值必须标合成——防止"合成值冒充厂商真值"再次发生。

## 收尾条目

- [ ] **wrap-up**：全量测试与 lint 最终确认；写夜间总结（完成清单、测试状态、诚实未完成项、给用户的下一步建议）；最终提交。

## 用户醒来后的人工事项

- 注册 GitHub 仓库并 push；PyPI 发布需用户 token
- 价格快照人工核对（iter5 runbook 之前先粗核对一遍热门 10 个）
- 若要跑真实账本审计：用脱敏模式先小规模试运行
