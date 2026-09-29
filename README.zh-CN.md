# The Ledger of Vanishing Tokens — Tellan

[English](README.md) · 简体中文

> **The Ledger of Vanishing Tokens** · *Usage reconciliation and tamper-evident LLM billing audits*（LLM 用量对账与防篡改计量审计）。展示名已确定；包名、CLI 与 import 保持 `tellan`。
[![CI](https://github.com/cloudydreamland/TheLedgerOfVanishingTokens/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)

**LLM API 账单对账与计量审计标准件。厂商按 token 计费，token 数由厂商自己报——tellan 让你第一次有能力说"这个数不对"。**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## 为什么需要它 / Why

所有 LLM API 按 token 计费，但计量器在厂商手里：报多少、扣多少，用户只能照单全收。这不是假设性焦虑，而是被反复公开验证过的现实（数据实抓日 2026-09-28，详见 [GAP_PROOF.md](GAP_PROOF.md)）：

- **Gemini 2025-08 计费事故**：Google 官方承认 Gemini API 计费系统故障，向用户多收费用并承诺退款——连大厂都会算错，而用户当时几乎没有手段自己发现。
- **Theo 的一次 commit ≈ $970 cache write**：Agent 工作流里一次误操作产生近千美元的缓存写入费用，账单事后才看到，为时已晚。
- **2026-09 OpenRouter "content:null 还计费 345 tokens" 事件**：响应正文为空却照常计费，社区在论坛/Reddit 上反复出现同类抱怨。
- **tiktoken issue#375**：用户请求"对账/验证厂商报数"能力，官方明确不做——OpenAI 的立场是计数以服务端为准，验证是用户自己的事。
- **需求已被验证、供给是空白**：ccusage 18,763★ 只做"读本地日志自算花费"，不质疑厂商报数；而最大的直接竞品（对账方向）只有 218★。

`tellan` 把这件事做成一个**零必装依赖**的标准件：

- **哈希链账本**（Certificate Transparency 思路）：每条 usage 记录 `sha256(prev_hash + data)` 链式签名。中转站或日志被事后篡改，`tellan verify` 一眼识破，并指出首个坏记录的 seq。
- **三方对账**，不是 cost tracker：厂商报数、本地独立复算、价格表三方互证，给出 `OK / SUSPECT_INFLATED / SUSPECT_DEFLATED / INSUFFICIENT_DATA` 裁决。cost tracker 们全盘信任报数，只做乘法；tellan 质疑报数本身。
- **一页对账声明**：`tellan statement` 生成可交由第三方复核的 Markdown + JSON，列出争议记录、报数与复算结果、异常、账本哈希和复现命令。同一账本、同一版本应生成相同声明哈希。
- **区间估计而非点估计**：非 OpenAI 模型的 tokenizer 闭源，精确复算就是撒谎。tellan 诚实输出包围盒 `[lo, hi]`——报数落在盒内不算错，落在盒外才报警。
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
# 克隆仓库后，在项目根目录安装
python -m pip install .
# 发布到 PyPI 后可直接安装；tiktoken extras 按需选择
python -m pip install tellan
python -m pip install ".[tiktoken]"
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
| ccusage（18.8k★） | 读 18 种 coding CLI 本地日志，自算花费 | 同源数据不同立场：源码走读确认它**信任报数**（`cost.rs` 直接采用日志 usage，官方自述"Costs are estimates and may not reflect actual billing"，reasoning token 无计价逻辑）；tellan 质疑报数本身。可互补（它管统计，我们管裁决） |
| litellm cost tracking | SDK 内按报数×价格表算钱 | 纯乘法，无复算、无账本、无裁决 |
| langfuse/Helicone | LLM 可观测平台 | 记录与展示层，计量审计不是它们的题目 |
| AgentMeasure（218★，最大直接竞品） | Agent 会话度量 + 计量一致性 conformance | 度量不做逐条对账：无哈希链、无包围盒复算、无异常裁决；它"审计 124 个用量工具发现 45+ 计费 bug"恰是本项目生态位的行业证据。源码级结论见 [docs/competitors.md](docs/competitors.md) |
| 手动对账（看 dashboard） | 人肉抽查 | 规模化后不可行，且无防篡改能力 |

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

## License

MIT
