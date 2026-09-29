# tellan 对账声明（Settlement Statement）

> 由 tellan v0.1.0rc1 自动生成：厂商报数 vs 本地复算包围盒 vs 价格快照的三方对账结果，供争议双方逐条核对。本声明只基于所附账本，不构成对任何厂商的指控；复算结论是统计包围盒上的"超出/未超出"，不是司法结论。文末附复现命令——同版本脚本重跑同一账本，应得到完全一致的声明（statement_sha256 一致）。

## 账本与完整性

- 账本文件 sha256：`f4cf35c68c05ddc2043a1fa88ca07afddd78efa59f450391ba7dd331db75f1e1`
- 记录数：8
- 哈希链：完整（链尾 `b490462d3a49…`，完整值见 JSON）
- 覆盖时间：2026-09-20T01:15:00+00:00 ~ 2026-09-20T08:15:00+00:00（UTC）

## 结论一览

- 裁决分布：OK 6，SUSPECT_INFLATED 2
- 报数总量：input 899 / output 1647 / reasoning 300 / cached 0
- 本地复算区间：input [320, 1034] / output [57, 496]
- 费用：厂商报数口径合计 0.0035；复算区间 [0.0002, 0.0015]（价格快照，仅供量级参考，不作为结算依据）
- 异常：`EMPTY_CONTENT_BILLED`×1，`OPAQUE_REASONING`×1，`PRICE_MISSING`×2，`TOKEN_INFLATION`×2

## 被质疑条目（SUSPECT 裁决或 error 级异常）

| seq | model | 报数 in/out | 复算盒 in/out | 偏差 | 裁决 |
|---|---|---|---|---|---|
| 4 | gemini-2.5-flash | 180/1200 | [24, 80] / [4, 314] | +554.0% | SUSPECT_INFLATED |
| 5 | some-relay-model | 180/345 | [29, 93] / [2, 7] | +701.5% | SUSPECT_INFLATED |

逐条明细（定位一条争议记录：用 record_hash 在账本 JSONL 中搜索）：

- **seq=4** gemini-2.5-flash（request_id demo-inflate；record_hash `4512de196051…`）：报数 in 180 / out 1200，裁决 SUSPECT_INFLATED；复算策略 heuristic/置信度 coarse，盒 in [24, 80] out [4, 314]
  - `OPAQUE_REASONING`（info）：reasoning_tokens=300，该部分消耗不可见也不可复算
  - `TOKEN_INFLATION`（error）：输出报数 1200 > 包围盒上沿 314×1.5
- **seq=5** some-relay-model（request_id demo-null；record_hash `055391b34a17…`）：报数 in 180 / out 345，裁决 SUSPECT_INFLATED；复算策略 heuristic/置信度 coarse，盒 in [29, 93] out [2, 7]
  - `EMPTY_CONTENT_BILLED`（error）：content 为空/None 但 completion_tokens=345（无 reasoning 说明），疑似 opaque 计费
  - `TOKEN_INFLATION`（error）：输出报数 345 > 包围盒上沿 7×1.5
  - `PRICE_MISSING`（warning）：价格表无 'some-relay-model'，费用对账跳过

## 对账规则与数据来源

- 裁决规则：报数 ∈ [复算 lo×0.9, 复算 hi×1.25] 判 OK；输入/输出两侧独立检查；高出上沿判 SUSPECT_INFLATED，低于下沿判 SUSPECT_DEFLATED；原文不在账本（如脱敏模式）时 INSUFFICIENT_DATA，不计入质疑。
- 复算策略：`heuristic`（逐条实际策略与置信度见被质疑条目明细）。
- 价格表：内置快照 38 模型，as_of 2025-10-01——内置价格快照。所有价格为快照估值，发布前需人工核对，未联网逐条验证。价格随时可能变化，仅用于量级对账，不作为结算依据。
- 价格缺失披露：2 条记录价格表无该模型（`PRICE_MISSING`），其费用**未计入**上述合计——缺价按"无法核对"处理，不静默按 0。

## 复现（同版本 + 同参数应逐字节复现本声明）

```bash
pip install tellan==0.1.0rc1   # 与声明同版本（或同一 commit 源码安装）
python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" docs/demo_ledger.jsonl   # 应等于 ledger.file_sha256
tellan verify docs/demo_ledger.jsonl
tellan audit docs/demo_ledger.jsonl --strategy heuristic --tolerance 0.25
tellan statement docs/demo_ledger.jsonl --strategy heuristic --tolerance 0.25 -o statement.md --json-out statement.json
# 重跑得到的 statement_sha256 应与本声明一致
```
- 声明哈希 statement_sha256：`84459088d22bb1cfc2a6fdc120cd98905d156f98fcf02231a33ad3f28f983fe0`（不依赖文件路径；账本内容 + tellan 版本 + 参数决定）

## 边界与局限（读这节再下结论）

- 哈希链证明账本**自链完整**（出具后未被篡改），不等于厂商签名：有能力重构整条链的一方可以伪造账本（HMAC/外部锚定在设计选项中）。
- 本地复算是包围盒估计不是真值：盒宽与容差意味着轻微多报不报警（抑噪是特性）；`SUSPECT_*` 的含义是"报数超出诚实包围盒"，不是"已证实欺诈"。
- reasoning_tokens 是厂商自报的不可见消耗，无法复算，已并入输出盒上沿并提示 `OPAQUE_REASONING`；流式 usage 缺失时该记录记 INSUFFICIENT_DATA，不编数。
- 价格快照为估值（as_of 见上），费用数字仅供量级对账；结算以厂商账单为准。
- 本声明由工具自动生成，不构成法律意见；对外主张请以可复现证据 + 人工复核为准。
