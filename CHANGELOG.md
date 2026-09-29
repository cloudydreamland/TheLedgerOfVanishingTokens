# CHANGELOG

## 未发布

### 新增

- **一页对账声明** `tellan statement`（iter10）：单页 Markdown + JSON 声明工件——被质疑条目（厂商报数 vs 本地复算盒并排、record_hash 逐条定位）、异常清单、对账规则与价格快照来源、复现命令块；`statement_sha256` 使"同账本 + 同版本重跑得到同一声明"可机器校验（路径不参与哈希）；链损坏或账本不存在拒绝出具（退出码 2，不写文件）；PRICE_MISSING 显式披露"费用未计入合计"，不静默按 0。演示工件 docs/statement_example.{md,json} + docs/demo_ledger.jsonl（合成数据，`tools/make_demo_statement.py` 确定性生成，复现命令已实跑验证）。
- **tiktoken 精确模式族门禁**（iter3）：覆盖清单数据化（`TIKTOKEN_COVERAGE`）+ 负名单（kimi/moonshot 等自有分词器模型族强制拒绝）；`--strategy tiktoken` 遇不覆盖模型自动降级 heuristic 并在 notes 留痕（不再静默套用 OpenAI 分词器）；新增 `tellan warmup` 预热命令；`tools/calibrate_boxes.py` 盒宽校准脚本与 `benchmarks/calibration.md` 实测报告；gpt-4o/gpt-4o-mini fixture 报数更正为 tiktoken 实测真值。
- **中转站账目导入** `tellan.adapters.newapi` + CLI `tellan import`：把 new-api/one-api 账目导出（JSONL/CSV，auto 识别，utf-8-sig/千分位/字符串数字宽容处理）映射入哈希链账本；秒/毫秒/ISO 时间戳统一为 UTC ISO 并**保留原始时间**（`Ledger.append` 新增可选 `ts`，向后兼容）；缺 request_id 合成确定性 `imp-<sha12>`；type==2 消费行过滤（两站兼容，中文类型词宽容入账留痕）；quota 按 `quota_per_unit`（默认 500000）折算美元估值；指南见 `docs/newapi.md`（含 8 条已知坑）。

### 文档

- iter1 竞品源码走读：新增 `docs/competitors.md`（ccusage `cost.rs` 源码级四栏对照、AgentMeasure/echo 自述级走读、风险更新）；README「与现有方案的关系」表升级为源码级结论。

## 0.1.0rc1 — 2026-09-28

首个公开候选版本。核心纯标准库，零必装依赖。

### 新增

- **哈希链账本** `tellan.ledger.Ledger`：JSONL 追加式，`sha256(prev_hash + canonical_json)` 链式签名，genesis `"0"×64`，`verify()` 报告首个坏 seq；任何一行的任何字节被事后翻动都可察觉。
- **本地复算** `tellan.recount`：`HeuristicCounter` 族权重包围盒（CJK×族权重 + ASCII 词×1.3 + 消息/工具框架开销，点估计 ×[0.5, 1.6]，confidence=coarse）；`TiktokenCounter` 可选精确计数（`tellan[tiktoken]`）；不变量（非负、lo<=hi）有 seeded fuzz 测试。
- **三方对账** `tellan.reconcile`：OK / SUSPECT_INFLATED / SUSPECT_DEFLATED / INSUFFICIENT_DATA 四态裁决，容差盒 `[lo×0.9, hi×1.25]`，输入输出独立裁决；六个异常检测器：EMPTY_CONTENT_BILLED、OPAQUE_REASONING、TOKEN_INFLATION、TOKEN_DEFLATION、DUP_REQUEST_ID、PRICE_MISSING。
- **价格快照** `tellan.prices`：38 个热门模型（逐条标注"快照估值，发布前需人工核对，未联网逐条验证"），别名归一化 lookup，缓存/推理/写入 token 分档 cost。
- **捕获代理** `tellan.capture.CaptureProxy`：/v1/chat/completions 转发 + 入账，SSE 透传（usage best-effort），默认脱敏（长度+哈希前缀），Authorization 永不入账本。
- **报告** `tellan.report`：Markdown（汇总/偏差直方图/异常表/Top 偏差）与 JSON。
- **内置基准** `tellan.bench`：11 个合成 fixture + 真实运行指标，结果见 `benchmarks/results.md`。
- **CLI**：`tellan audit / verify / report / proxy / bench`，退出码 0 正常 / 1 有疑点 / 2 链损坏。
- 完整类型标注 + `py.typed`；111 项测试全绿（+1 诚实跳过），ruff 0 error。
