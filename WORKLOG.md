# WORKLOG — iter0 开发日志

## iter0（2026-09-28 晚，主会话完成）：v0.1.0-rc1 全量构建

### 完成清单

- **ledger.py**：JSONL 追加式哈希链账本。`hash = sha256(prev_hash + canonical_json(payload))`，payload 为除链字段外全部记录内容（这样 usage/model 等任何字段被翻动都能察觉，而不只是 data 字段）；canonical 形式 `sort_keys + ensure_ascii=False + 紧凑分隔符`；genesis `prev_hash = "0"×64`；`verify()` 返回 `(ok, first_bad_seq)`；进程内线程锁串行化并发追加。篡改测试覆盖：data/usage/model/hash/prev_hash 字段翻转、删行断链、坏 JSON 行，全部在正确 seq 处失败。
- **recount.py**：`TokenEstimate` 包围盒（不变量：非负、lo<=hi，200 组 seeded fuzz 覆盖）；`HeuristicCounter`（CJK 字符含全角标点 × 族权重 + ASCII 词×1.3 + 每消息 4 tok 框架 + 每工具调用 8 tok；7 族权重预设 + unknown 中性降级；点估计 ×[0.5, 1.6]）；`TiktokenCounter`（可选依赖，缺依赖时友好报错；测试 importorskip + 离线不下载 encoding，本机未装故 1 skipped）；`estimate_exchange` 抽取 messages/choices 文本。
- **prices.py**：内置 38 模型价格快照（OpenAI/DeepSeek/Qwen/GLM/Moonshot/Claude/Gemini/Grok/豆包/Mistral），逐条 `source_note` 标注"快照估值，发布前需人工核对，未联网逐条验证" + `as_of`；`lookup` 三级别名归一化（精确→别名→双向包含，剥多层 provider 前缀）；`cost` 处理 OpenAI cached_tokens 与 Anthropic cache_read/cache_creation 双风格。
- **reconcile.py**：四方裁决（OK / SUSPECT_INFLATED / SUSPECT_DEFLATED / INSUFFICIENT_DATA），输入输出两侧独立检查容差盒 `[lo×0.9, hi×1.25]`；六个独立异常检测器各配正反测试；**诚实降级**：脱敏记录无法复算 → INSUFFICIENT_DATA；reasoning_tokens 不可复算 → 并入输出盒上沿 + OPAQUE_REASONING info，不假装能算；`reconcile_ledger` 汇总总报数/总估计区间/费用区间/异常计数/Top 偏差。
- **capture.py**：ThreadingHTTPServer + urllib 转发 `/v1/chat/completions`；SSE 逐 chunk 透传 + best-effort 抓流中 usage（文档如实标注）；默认脱敏（消息条数+长度+sha256 前 12 位，响应正文同样脱敏）；Authorization 原样转发但**任何模式都不入账本**（有测试）；上游不可达 → 502 + 账本记 proxy_upstream_unreachable。
- **report.py**：Markdown（汇总/偏差直方图 7 桶/异常表/Top 偏差）+ JSON 双格式。
- **bench.py + benchmarks/results.md**：11 个合成 fixture（deepseek-chat/reasoner、gpt-4o 代码、glm-4.6、qwen-plus、gemini thinking 膨胀、claude 缓存读写、content:null 计费、gpt-4o-mini、kimi-k2 工具调用、中转站截断）；**results.md 为脚本真实输出**（覆盖率 72.7%，未命中 3 条全部是故意操纵的 fixture，预期裁决 2/2、预期异常 2/2、EMPTY_CONTENT 检出 1/1）。
- **cli.py**：audit / verify / report / proxy / bench 五个子命令；退出码 0/1/2 约定并有测试。
- **文档**：README（痛点证据→核心概念 ASCII 图→Quickstart 三方式→竞品对照表→诚实边界→English quickstart）、GAP_PROOF、ROADMAP（iter1~iter8 未勾选）、CHANGELOG、LICENSE、.gitignore。
- **质量数字**：pytest **111 passed + 1 skipped**（tiktoken 未安装，诚实跳过）；ruff **0 error**；全部测试离线（mock 上游 = 线程内 ThreadingHTTPServer）。

### 评审记录（对抗评审：资深工程师 / 项目经理 / 老板）

- **工程视角**：①初版 hash 只盖 data 字段的话，翻动 usage 察觉不到——改为盖除链字段外全部 payload，测试锁死该性质；②状态裁决最初只看输出侧，中转站截断（输入缩水、输出正常）会被误判方向——改为输入输出独立裁决；③工具调用响应会误报 EMPTY_CONTENT_BILLED——已修并有反例测试；④kimi-k2 工具调用 fixture 曾触发 EMPTY_CONTENT 误报，被测试当场抓住。**遗留**：账本无签名，攻击者可整体重造链——诚实定位是"防事后篡改/抵赖，不防根信任伪造"，HMAC/外部锚定进 ROADMAP iter7。
- **产品视角**：①脱敏与复算矛盾必须显式说出来，不能让用户以为 audit 万能——README 诚实边界 + INSUFFICIENT_DATA 状态解决；②价格表会腐烂——source_note + as_of + iter5 刷新工具链；③流式 usage 缺失时不能编数——INSUFFICIENT_DATA。
- **老板视角**："你跟 ccusage 有什么区别？"——一句话：它管统计你花了多少，我们管验证厂商报的数对不对；前者 18.7k★ 证明需求，后者是空白。竞品表格已按此口径写。

### 批评转化（进 ROADMAP 的新条目）

- 竞品源码级对照缺失 → iter1
- 中转站生态（new-api/one-api）是最大受害者群体，需要导出适配器 → iter2
- tiktoken 覆盖面与盒宽校准缺失 → iter3
- bench 数字应升级为可发布的偏差排行榜 → iter4
- 价格表溯源与过期提醒 → iter5
- 代理生产化（重试/TLS/大响应/跨进程账本）→ iter6
- 账本伪造与代理绕过的红队轮 → iter7
- 发布工程 → iter8

### 诚实未完成项

- tiktoken 精确模式**本机未安装未实测**（测试诚实跳过）；其行为正确性依赖 offline 缓存，未验证。
- 流式 usage 抓取未在"上游不开 include_usage"场景下做端到端测试（逻辑上 INSUFFICIENT_DATA 兜底，但未专门测试该路径）。
- 价格快照 38 条均未联网核对，仅凭公开记忆的量级估值——这是设计立场（诚实标注），但意味着**首次使用前应人工核对**。
- 启发式对代码类英文文本偏保守（gpt-4o fixture 诚实报数只能标在盒内偏上沿，见 results.md）。
- Windows 上 `--port` 绑定冲突、代理长连接保活、超大响应等生产场景未覆盖（iter6）。
- 未构建 sdist/wheel、未发 PyPI、未 push（按任务约束）。

---

## iter1（2026-09-28 夜间自动迭代 第 1 轮）：竞品源码走读

### 完成清单

- `docs/competitors.md`：四栏对照（信任报数/账本/复算/价格表来源）× 6 方案 + ccusage 源码级细节 + AgentMeasure/echo 自述级走读 + 结论与风险更新 + 证据清单（全部带当日实抓日期）。
- README「与现有方案的关系」表升级为源码级结论（ccusage 行、AgentMeasure 行重写，链到走读文档）。
- ROADMAP 追加 iter9（时间戳匹配价格）、iter10（对账声明工件）。

### 走读关键发现

1. **ccusage（18.8k★）源码级确认信任报数**：`rust/crates/ccusage-core/src/cost.rs` 的 `calculate_cost_from_tokens` 直接采用日志 `message.usage`，唯一防御是 `saturating_add` 防溢出；默认 `auto` 模式优先采用日志预存 `costUSD`；官方文档自述 "Costs are estimates and may not reflect actual billing"；**reasoning token 在算费源码中完全不存在**。裁决赛道无人占据，源码级确认。
2. **可吸收的设计**：时间戳匹配价格（`find_at`，DeepSeek 分段调价）、模型别名链式回退、缓存 5m/1h 细分计价、长上下文阶梯计价 → 前者已成 iter9，后三项记录在案待排期。
3. **反面教材**：ccusage 价格查不到静默返回 0.0——对账工具大忌，我们的对应物是 PRICE_MISSING + INSUFFICIENT_DATA，写进文档当立场。
4. **AgentMeasure（218★）**：UNPROVABLE 纪律与"never silently zero"值得尊敬；AMS-1 一页纸结算声明是好产物形态 → iter10；其"审计 124 个用量工具、45+ 已验证计费 bug、19 个上游修复"是本项目生态位最强的行业证据；商业定价（$990 一次性/$490 月）证明付费意愿。
5. **echo（546★）**：代理式计量=计量方/收费方/受益方三位一体，结构性论证了独立审计的必要性；无审计概念，不构成竞争。

### 三视角对抗评审记录

- **资深开发者**：走读方法对 ccusage 下钻到了源码，对 AgentMeasure/echo 只有 README 级——结论强度不同却写在同一张表里，会误导读者。→ 已在文档开头加方法声明与"自述级"标注；后续若二者发新版需复走读（不另立条目，挂在 iter1 遗留）。
- **资深项目经理**：真正威胁是 ccusage 加"验证模式"（渠道+工程力碾压），对冲点 = new-api/one-api 中转生态切口（它 18 个数据源里没有）+ 代理捕获（它只读日志）；本条已写进 docs/competitors.md 风险节，不新增条目（代理加固 iter6、中转适配 iter2 已在表上）。
- **公司老板**：AgentMeasure 收 $990/次对账证明预算存在，但它的 0 watching/218★ 说明"标准/规范"形态涨不动 star；我们的传播物应该是 iter4 偏差排行榜 + iter10 可申诉声明这类"能截图转发的东西"，而不是规范文档。方向确认，不改路线。

### 上网调研发现

- ccusage 活跃度极高（2,176 commits、issue 积压 2 个、Rust 重写进行中），18.8k★；echo 101 个 open PR、活跃开发；AgentMeasure 9 issue/2 PR、0 watching。全部 2026-09-28 实抓。
- 未发现任何一家在 2026-09 有"独立复算/对账裁决"路线的动向。

### 诚实未完成项

- AgentMeasure 与 echo 仅 README/文档级精读，未逐行走读其源码（文档中已如实标注"自述级"）。
- ccusage 只定点读了 `cost.rs` 与 `cost-modes.md`，未走读其 18 个数据源适配器（对 tellan 的代理捕获无直接参考价值，性价比低，如实说明）。
- 本轮纯文档轮，无代码变更；pytest/ruff 作为门禁照跑。

---

## iter2（2026-09-28 夜间自动迭代 第 3 轮）：new-api/one-api 账目导出适配器

### 完成清单

- `src/tellan/adapters/`（包）+ `newapi.py`：JSONL/CSV（auto 识别、utf-8-sig）→ 账本记录；内置别名表（JSON 键 + 中文 CSV 列头）+ `--mapping` 合并覆盖；秒/毫秒/ISO 时间戳统一（UTC ISO 毫秒）；字符串/千分位/全角逗号宽容整数转换；缺 request_id 合成 `imp-<sha12>`（确定性，同内容同 id）；type==2 过滤（两站兼容），中文词类型宽容入账留痕 `meta.type_raw`；quota 按 `quota_per_unit`（默认 500000，可覆盖）折算 `quota_usd_est`；new-api `upstream_request_id` 留痕（标注"可造假，仅线索"）。
- **`Ledger.append` 加可选 `ts` 参数**（向后兼容，默认行为不变）：导入历史记录必须保留原始时间戳，否则对账时间口径被导入时刻覆盖，iter9 时间戳匹配价格也依赖此。
- CLI `tellan import`（退出码 0 全入账 / 1 有跳过 / 2 不可读）；`docs/newapi.md`（导出路径/字段映射表/8 条已知坑）；README 快速开始加"方式三：导入中转站账目"。
- 新测试 19 项（130 passed + 1 skipped 全绿，ruff 0 error）：完整映射、类型过滤、脏数据三态、时间戳三格式、one-api 识别、中文 CSV（BOM+千分位）、自定义映射、quota 覆盖、入账链完整+ts 保留、CLI 四路径、错误处理。

### 三视角对抗评审记录

- **资深开发者**：①发现并修复自己引入的 F841/TRY004 lint 错与一处错误编辑（except 块被误替换成 return——lint 与测试当场抓住，如实记录）；②字节级相同的两行导出会得到相同合成 id，令 DUP_REQUEST_ID 在对账时命中——确认为特性语义（卖方账本重复行本身可疑），已写进 docs 已知坑第 7 条；③Ledger.append 签名变更向后兼容（全量旧测试未动全绿佐证）。
- **资深项目经理**：import 是打进 8.6 万星中转生态的桥，但普通用户只能拉自己的日志（GetUserLogs），token_name 字段可能为空——字段缺失路径已覆盖（宽容跳过/留痕）；README 快速开始已补 import 入口提升可见性；**真实站点贴合率是验收标准，本轮未达成**→ 转 iter11。
- **公司老板**：本轮把"86k 星生态的审计切口"从口号变成了可安装的一行命令（tellan import logs.jsonl -l relay.ledger），这是与 ccusage 差异化最直接的一步（它的 18 个数据源里没有中转站导出）；但推广前必须过 iter11 真实样本关，否则第一批 issue 就会淹死在"我的导出解析不了"上。

### 上网调研发现

- new-api main 分支 controller/log.go 实抓（2026-09-28）：部分旧日志接口已标"该接口已废弃"；当前 GetAllLogs/GetUserLogs 走 common.ApiSuccess + pageInfo，**条目在 data.items**——据此修正了 docs/newapi.md 的拉取示例（初稿写的 data 是错的，源码核对时抓出）。
- Log struct 字段表两家实抓（new-api 21 字段/one-api 15 字段），消费行 type==2 两站兼容确认。
- GitHub API 本轮仅用 2 次（router/controller 定点），限额健康。

### 诚实未完成项

- 未接触任何真实站点导出（无管理员凭据），字段表是 main 分支源码级结论——部署版本可能漂移，iter11 前所有"已验证"均指源码级+fixture 级。
- one-api 的 CSV 导出形态未考证（其 UI 是否有导出按钮未核实），文档只承诺 JSONL 权威路径。
- new-api `other` 字段（站点自定义 JSON）未解析——里面可能是缓存/推理 token 明细，值得将来开条目做按站适配。

### 门禁事故记录（诚实存档）

- 本轮首次提交时 `test_capture.py::test_non_chat_path_404` 出现一次 `ConnectionAbortedError`（Windows 线程 HTTP server 的套接字中断竞态），且因命令链管道写法失误让带红提交溜过（1b7cb21）。重跑 capture 9/9 与全量 130 passed 均绿，确认为偶发抖动而非回归；加固条目转 iter12。教训：门禁判定不得依赖 shell 管道的尾部退出码，已改为直接看 pytest 退出码。

---

## iter3（2026-09-28 夜间自动迭代 第 5 轮）：tiktoken 精确模式覆盖面与 CI 策略

### 完成清单

- **族门禁 + 负名单**：`TiktokenCounter._encoding_for` 不再静默兜底 o200k_base——覆盖外抛新异常 `TiktokenUnsupportedModel`（`TiktokenUnavailable` 子类）；负名单（kimi/moonshot/mistral/grok/minimax/yi-*，自有分词器）显式拒绝；`tiktoken_family()` 公开判定函数；`TIKTOKEN_COVERAGE` 覆盖清单数据化。
- **行为决议（文档化）**：`--strategy tiktoken` 遇不覆盖模型 → 降级 heuristic 包围盒 + notes 留痕（不整体报错，批处理友好；诚实性由 notes 与 confidence=coarse 保证）。
- **`tellan warmup` 命令**：预热 encoding 缓存（可注入 loader，测试不联网），CI 策略三方案写入 docs/tiktoken.md。
- **校准脚本 `tools/calibrate_boxes.py`**：tiktoken 真实安装（0.14.0）后对内置 fixture 实测——gpt-4o 输入比率 1.39x / 输出 0.92x、gpt-4o-mini 0.87x / 0.98x，当前盒 [0.5,1.6] 全覆盖；国产模型族 9 条如实列「无法校准」。结果写入 benchmarks/calibration.md（脚本真实输出）。
- docs/tiktoken.md（覆盖面/降级决议/CI 策略）；新测试 7 项：137 passed 全绿 + ruff 0 error。

### 本轮抓出的真问题（重要）

1. **gpt-4o / gpt-4o-mini fixture 的"厂商风格报数"是假的**：构建时 tiktoken 未装，报数实际按 heuristic 点估计填写；tiktoken 装上后精确复算（107/12 vs 报数 110/20）立刻戳穿——honest fixture 测试失败是对的。已改为实测真值并在注释说明来历 → 新条目 iter13（usage 来源披露字段）。
2. **kimi-k2 曾被分进 openai_legacy 族**：heuristic 权重族与 tiktoken 覆盖是两回事，校准实测 cl100k 硬数 Kimi 文本偏差达 3x——负名单修复。
3. **校准脚本初版口径错误**：手工抽 content 漏掉 tool_calls 文本（out_point 4 vs 真实 18），改用 `message_text` 与实现同口径。
4. **捕获测试抖动二连**：`test_non_chat_path_404` 的 Windows ConnectionAbortedError 两小时内出现两次——`_post` 加传输层重试一次（断言不弱化），iter12 的根因排查仍保留。

### 三视角对抗评审记录

- **资深开发者**：`TiktokenUnsupportedModel` 放进 `TiktokenUnavailable` 继承树使 reconcile 单点 catch 兼容两种失败——最小改动；`warmup` 的 loader 注入让测试零联网；校准脚本与实现共用 `message_text`/`point_count` 才能同口径（初版踩坑已修）。
- **资深项目经理**：降级留痕 vs 硬报错的决议对批处理场景正确，但报告里降级记录要更显眼（当前埋在 notes）——报告增强已有 iter4 排行榜条目可承载，不另立；fixture 真值问题是信任问题 → iter13 必做。
- **公司老板**：本轮把"精确模式"从营销词变成有实测数据背书的承诺（calibration.md 可直接放进 README 当证据）；tiktoken 安装后 skip 测试转真跑也补上了此前的诚实欠账。

### 上网调研发现

- tiktoken 0.14.0 实装验证：encoding 下载在本机网络可达，o200k_base/cl100k_base 均加载成功。
- 未发现 tiktoken 有模型→encoding 之外的公开按族授权接口；覆盖判定以 OpenAI 官方模型名单为准，负名单维护靠社区 issue 驱动。

### 诚实未完成项

- 国产模型族盒宽倍率仍是设计值（无真值），待 iter4 排行榜积累真实报数分布后回代。
- `pytest.importorskip` 的既有测试现在真跑（tiktoken 已装），其 encoding 加载依赖本机缓存——CI 离线环境需按 docs/tiktoken.md 方案 1 预热（本机已验证可行）。
- kimi 等负名单模型的真值核验通道（HF 分词器加载）超出零依赖约束，未做，如实标注。

## iter10（2026-09-28 日间，增长计划主入口轮）：对账声明工件 `tellan statement`

### 与协议的偏差（先说明）

ROADMAP 协议的下一项是 iter4（偏差排行榜）；本轮先做 iter10，依据是 OPEN_SOURCE_GROWTH_PLAN §5.5 把"一页审计声明"列为 tellan 的主入口交付物（"让开发者能把一次可疑账单差异变成一份可发给财务、供应商或团队复核的证据报告"），且纯合成数据排行榜有被误读为真实厂商数据的传播风险。iter4 仍是下一轮协议项。

### 完成清单

- **statement.py**：`build_statement`（声明组装 + `statement_sha256`）与 `render_statement_markdown` / `render_statement_json`。哈希覆盖 tellan 版本、账本文件 sha256、链尾、覆盖时间、参数（策略/容差/价格表 as_of 与来源注记）、对账汇总、被质疑条目（SUSPECT_* 或 error 级异常，附 record_hash）；**路径与复现命令不参与哈希**——同账本内容换目录重跑哈希不变（测试锁死）。Markdown 单页：账本与完整性 / 结论一览 / 被质疑条目（并排表 + 逐条明细，展示上限 20 条，完整清单在 JSON）/ 规则与数据来源 / 复现命令块 / 边界与局限。PRICE_MISSING 显式披露"费用未计入合计"，不静默按 0。
- **cli.py**：`statement` 子命令（`-o` Markdown、`--json-out` JSON、`--strategy`、`--tolerance`；两者都缺省时 Markdown 打印到 stdout）。链损坏或账本不存在**拒绝出具**（exit 2，不写任何文件）；有被质疑条目 exit 1。
- **__init__.py**：导出 statement 三函数；`__version__` 前移到子模块 import 之前（statement 在包初始化期间读取它，否则 ImportError）。
- **tools/make_demo_statement.py + docs 工件**：确定性合成演示账本（固定 ts；每条记录 meta 自带 `synthetic: true` 声明）+ CLI 真实输出的 `docs/statement_example.{md,json}`。演示含 6 条诚实 + 1 条大幅膨胀 + 1 条 content:null 计费 + 1 条价格表未知模型。
- **README**：标题采用确认展示名 *The Ledger of Vanishing Tokens*（包名/CLI/import 保持 `tellan` 不变）；特性列表补声明一条；方式五（一页对账声明，真实输出 + 演示工件链接）；English quickstart 补 statement。
- **质量数字**：新测试 13 项（逐字节确定性、跨路径同哈希且哈希体自证、质疑条目与 record_hash 对账、坏链/账本缺失拒绝、空账本、stdout 模式、退出码 0/1/2）；全量 **150 passed**（原 137），ruff 0 error。

### 本轮抓出的真问题

1. **确定性测试初版自身有 bug**：两次独立 `append` 的 ts 不同 → 账本内容不同 → 哈希必不同；跨路径不变性应复制同一文件来验证（已改）。教训确认：账本的**字节内容**才是声明身份，路径不是。
2. **演示膨胀记录曾不进质疑清单**：gemini 族权重 0.85 + reasoning_tokens 并入盒上沿，把 2x 膨胀吸进了容差盒——包围盒如实工作，不是 bug，但演示不典型；改用明显膨胀的合成值并在脚本注明。这同时是给用户的真实预期管理：轻微膨胀本来就不报警（抑噪是特性）。
3. **ruff ISC004**（本仓启用隐式字符串拼接检查）两处、`noqa: E402` 未启用一处——按仓库配置修正。
4. `Ledger` 对不存在路径返回空账本（audit/verify 惯例），但给"不存在的文件"出具 sha256 为空内容的声明是荒谬的——`cmd_statement` 显式拒绝（exit 2）。

### 三视角对抗评审记录

- **资深开发者**：statement_sha256 的覆盖范围是本轮关键决策——路径参与哈希则"换目录重跑同哈希"不可能成立，故哈希体只含内容字段，`reproduction`（含调用方路径）与哈希字段本身排除在外，JSON 顺序 body → statement_sha256 → reproduction，测试用 canonical_json 重算自证。`--json-out`/`-o` 语义与 `report` 对齐；JSON 不打印到 stdout（避免管道破坏）。
- **资深项目经理**：声明的价值在"能转交"：record_hash 展示前 12 位 + request_id 足够定位，完整哈希在 JSON；被质疑条目上限 20 条防大账本刷屏。demo 三工件 + README 真实输出 + 复现命令构成现成首发物料——发帖可直接贴 statement_example.md。
- **公司老板**：这是项目第一个"内容形态"产出（不只工具能力）：对中转站客服场景，"把账本和声明一起发过去"是自然动作；演示数据合成且三重标注（脚本 docstring、记录 meta、README），不构成对任何厂商的指控。

### 上网调研发现

- 无新增外部调研（本轮为纯离线工程迭代；竞品口径沿用 iter1 `docs/competitors.md`）。

### 诚实未完成项

- 声明的 JSON 里 disputed 含逐条复算盒与异常明细，但不复制原始请求/响应内容——需要审计级全文仍用 `tellan report --json` 或直接读账本。
- 价格 as_of 过期提醒（iter5）与时间戳匹配价格（iter9）未做：声明目前只能披露快照日期，不能按账本时刻匹配价格。
- 复现命令假设对方可安装同版本包；PyPI 发布前，"同版本"实际指同一 commit（命令块已注明源码安装选项）。
- 真实账单 / 真实中转站导出验证仍为零（iter11 前置条件未满足）；本迭代全部演示数据为合成。
