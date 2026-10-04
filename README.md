# The Ledger of Vanishing Tokens — Tellan

简体中文 · [English](README.en.md)

> 展示名 **The Ledger of Vanishing Tokens** 描绘逐渐消隐的 token 与它们留下的账目；Tellan 是该项目的短名。
[![PyPI](https://img.shields.io/pypi/v/tellan)](https://pypi.org/project/tellan/)
[![Python](https://img.shields.io/pypi/pyversions/tellan)](https://pypi.org/project/tellan/)
[![CI](https://github.com/cloudydreamland/TheLedgerOfVanishingTokens/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudydreamland/TheLedgerOfVanishingTokens/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
**LLM API 用量对账工具。把服务端用量、可行的本地估算和价格快照并列，帮助你定位值得复查的差异。**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## 为什么需要它 / Why

LLM 使用记录会分散在代理、客户端日志和账单导出中；不同 tokenizer、缓存和隐藏提示也会让本地估算与服务端用量不同。Tellan 帮助开发者把记录、估算和价格快照放在一起核对，并保留可复查的差异说明。它不能单独证明服务商计费错误。

`tellan` 把这件事做成一个**零必装依赖**的标准件：

- **哈希链账本**：每条 usage 记录连接前一条记录的哈希。记录被修改时，`tellan verify` 可发现链完整性变化并指出位置；它不是服务商签名，也不能防止有写权限的人重建账本。
- **三方核对**：并列厂商报数、本地可行的独立估算和价格快照，输出 `OK / SUSPECT_INFLATED / SUSPECT_DEFLATED / INSUFFICIENT_DATA` 等状态，方便进一步调查；结果不是供应商错账证明。
- **一页对账声明**：`tellan statement` 生成可交由第三方复核的 Markdown + JSON，列出争议记录、报数与复算结果、异常、账本哈希和复现命令。同一账本、同一版本应生成相同声明哈希。
- **区间估计**：不同模型的 tokenizer 与隐藏提示会影响复算。无法精确计数时，Tellan 输出估算范围 `[lo, hi]`；落在范围外代表值得复查，不等于确认错账。
- **最小化留存**：默认脱敏模式只存消息条数+长度+哈希前缀，原文不落盘。审计工具自己不能成为隐私泄漏源。
- **零必装依赖**：核心纯标准库；`tiktoken` 精确计数是可选 extras。

## 核心概念

```
                 ┌──────────────────────────────────────────────┐
                 │                三方对账（每条记录）             │
                 └──────────────────────────────────────────────┘

   ① 厂商报数              ② 本地复算（包围盒）           ③ 价格表
   usage.prompt_tokens     HeuristicCounter              prices.json 快照
   usage.completion_tokens [input_lo, input_hi]          input/output/cached
   reasoning_tokens…       [output_lo, output_hi]        per_1M
        │                        │                            │
        ▼                        ▼                            ▼
   ┌─────────────────────────────────────────────┐    ┌──────────────────┐
   │ 裁决：报数 ∈ [lo×0.9, hi×1.25] ？            │    │ 费用对账          │
   │   是 → OK                                    │    │ cost_reported    │
   │   高于 → SUSPECT_INFLATED（虚报）             │    │ vs               │
   │   低于 → SUSPECT_DEFLATED（缩水/截断）        │    │ cost_estimated   │
   │   无法复算 → INSUFFICIENT_DATA（诚实降级）    │    └──────────────────┘
   └─────────────────────────────────────────────┘
   附加异常检测：EMPTY_CONTENT_BILLED / OPAQUE_REASONING / TOKEN_INFLATION /
                TOKEN_DEFLATION / DUP_REQUEST_ID / PRICE_MISSING
```

**哈希链账本**：账本是 JSONL，每行一条记录。`hash = sha256(prev_hash + canonical_json(记录内容))`，首行 `prev_hash = "0"×64`（genesis）。任何人事后翻转账本中任意一行任意字节——包括 usage、包括 hash 本身——`verify()` 都会从那一行开始失败并报告 `first_bad_seq`。账本可以离线转交、长期归档，完整性不依赖存放者的诚实。

## 快速开始 / Quickstart

```bash
python -m pip install tellan
python -m pip install "tellan[tiktoken]"  # 可选增强，按需安装
```

从源码安装（开发或最新版）：

```bash
git clone https://github.com/cloudydreamland/TheLedgerOfVanishingTokens.git
cd TheLedgerOfVanishingTokens
python -m pip install .
```

### 方式一：代理模式（新流量）

把 base URL 指向本地代理，请求原样转发给上游，请求/响应（含 usage）自动入账：

```bash
# 默认脱敏：账本只存消息条数+长度+sha256 前 12 位，不落原文

tellan proxy --port 8317 --upstream https://api.deepseek.com --ledger my.ledger

# 另一个终端：把 base_url 换成 http://127.0.0.1:8317/v1 即可

# 审计这本账本（退出码：0 正常 / 1 有疑点 / 2 链损坏）

tellan audit my.ledger
tellan audit my.ledger --strategy auto --tolerance 0.25 --json
```

SSE streaming 逐 chunk 透传，尽力（best-effort）从流中抓取 usage；若上游流式响应不带 usage，该记录诚实标记为 INSUFFICIENT_DATA 而不是编一个数。

### 方式五：生成一页对账声明

```bash
tellan statement my.ledger -o statement.md --json-out statement.json
```

仓库内的[示例声明](docs/statement_example.md)基于合成账本，仅演示报告格式，不表示任何真实服务商存在计费问题。

### 方式二：审计已有 JSONL 日志（存量流量）

```python
from tellan import Ledger, reconcile_ledger, render_markdown

ledger = Ledger("provider_export.jsonl")   # 每行一条含 usage 的 JSON
ok, bad_seq = ledger.verify()
summary = reconcile_ledger(ledger.records())
print(render_markdown(summary))
```

### 方式三：导入中转站账目（new-api / one-api）

把中转站的账目导出（JSONL/CSV）入账本再对账——字段映射、脏数据、已知坑见 [docs/newapi.md](docs/newapi.md)：

```bash
tellan import logs.jsonl -l relay.ledger          # 退出码 0 全入账 / 1 有跳过 / 2 不可读
tellan audit relay.ledger                          # 卖方账本自洽性对账
```

### 方式四：生成报告

```bash
tellan report my.ledger -o report.md      # Markdown（汇总+直方图+异常+Top 偏差）
tellan report my.ledger -o report.json --json
tellan verify my.ledger                   # 只验链完整性
tellan bench                              # 内置基准（离线，验证检测管线）
```

基准真实数字见 [benchmarks/results.md](benchmarks/results.md)。

## 与现有方案的关系（如实）

| 方案 | 它做什么 | 与 tellan 的关系 |
|---|---|---|
| ccusage 等用量报告工具 | 汇总所支持的客户端日志并估算费用 | 适合查看已记录的使用情况；数据源和估算方法以各工具文档为准 |
| LiteLLM 等网关 | 转发模型请求并提供用量或费用观测 | 侧重网关和运营管线；按你的部署与对账需求评估 |
| Tellan | 导入或记录 usage，核对用量区间、价格快照和账本完整性 | 结果受输入数据、tokenizer 与价格时间点限制；差异是调查线索，不是错账定论 |

## 诚实边界（读这里再下结论）

- **heuristic 是包围盒，不是精确值**。`[0.5x, 1.6x]` 的盒宽 + `[0.9, 1.25]` 容差意味着：轻微多报不会报警（这是特性——避免噪声）；但代码类英文文本用词数×1.3 会系统性低估，盒可能偏窄。`reasoning_tokens` 是厂商自报的不可见消耗，无法复算，我们把它并入输出盒上沿并给 `OPAQUE_REASONING` 提示，而不是假装能算。
- **非 OpenAI 模型的复算永远非精确**。精确模式仅对 OpenAI 系模型可用（`pip install "tellan[tiktoken]"` + `--strategy tiktoken`）。对闭源 tokenizer 输出点估计的项目，等于在用猜的数对账。
- **价格表是快照估值**。内置 38 个热门模型的 `prices.json` 逐条标注"快照估值，发布前需人工核对，未联网逐条验证"，带 `as_of` 日期。它用于量级对账，不作为结算依据。
- **脱敏账本诚实降级**。默认脱敏模式下原文不入账，本地复算没有输入，对账退化为"报数 vs 价格表 + 异常检测"，状态标 `INSUFFICIENT_DATA`——审计工具不装懂。要复算请用 `--no-redact`（自担隐私责任）。
- **流式 usage 是 best-effort**。取决于上游是否在流中携带 usage。
- 内置基准全部是合成 fixture，验证的是检测管线，不构成对任何真实厂商行为的指控（见 benchmarks/results.md）。

## English quickstart

tellan ("bill verification") audits LLM API metering: it keeps a
tamper-evident hash-chain ledger of usage records, recomputes token counts
locally into honest bounding boxes, and reconciles **vendor-reported vs
locally-recounted vs price-snapshot** with per-record verdicts and anomaly
detection (empty-content-billed, token inflation/deflation, duplicate
request ids). Zero required dependencies; optional `tellan[tiktoken]` extra
enables exact recounting for OpenAI-family models.

```python
from tellan import Ledger, reconcile_ledger, render_markdown

ledger = Ledger("my.ledger")
ledger.append("chat_completion", model="gpt-4o",
              usage={"prompt_tokens": 100, "completion_tokens": 50},
              data={"request": {"messages": [{"role": "user", "content": "hi"}]}})
ok, bad_seq = ledger.verify()                    # hash-chain integrity
summary = reconcile_ledger(ledger.records())     # verdicts + anomalies + costs
```

```bash
tellan proxy --port 8317 --upstream https://api.openai.com --ledger my.ledger
tellan audit my.ledger   # exit 0 ok / 1 suspicious / 2 chain broken
```

See the Chinese sections above for the full picture; the honest-boundaries
section is the one to read before trusting any numbers, ours included.

## 开发

```bash
pip install -e ".[dev]"
python -m pytest        # 全部离线，不需要 API key
python -m ruff check .
```

设计文档：[GAP_PROOF.md](GAP_PROOF.md)（选题论证）· [ROADMAP.md](ROADMAP.md)（迭代计划）· [WORKLOG.md](WORKLOG.md)（开发日志）· [CHANGELOG.md](CHANGELOG.md)

## 反馈与参与

使用问题和功能建议可以在 [Discussions](https://github.com/cloudydreamland/TheLedgerOfVanishingTokens/discussions) 交流；可复现缺陷请提交 [Issue](https://github.com/cloudydreamland/TheLedgerOfVanishingTokens/issues)。请只附合成或脱敏后的最小样例，不要上传真实个人信息、API key 或业务原文。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## License

MIT
