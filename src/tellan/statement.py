"""statement.py — 对账声明工件（settlement statement）：一页可发给对方的审计声明。

设计目标（ROADMAP iter10）：把一次可疑账单差异变成**可直接转交**的工件——
被质疑条目、厂商报数 vs 本地复算并排、异常清单、复现命令块，全在一页
Markdown（+ 结构化 JSON 副本）里。

确定性约定：声明正文不含生成时刻、不含机器路径。同一路本文件内容 + 同一
tellan 版本 + 同一参数重跑，``statement_sha256`` 完全一致（有测试锁死）。
该哈希覆盖除 ``statement_sha256`` 与 ``reproduction``（含调用方路径）外的
全部内容；路径不参与哈希，账本换个目录重跑哈希不变。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import __version__
from .ledger import canonical_json
from .prices import DEFAULT_TABLE, META, SNAPSHOT_NOTE
from .reconcile import TOLERANCE_HI, TOLERANCE_LO

#: Markdown 中被质疑条目的展示上限（完整清单在 JSON 声明里）。
DISPUTED_DISPLAY_LIMIT = 20
_HASH_PREFIX = 12  # record_hash / statement_sha256 在 Markdown 里展示前缀


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def disputed_records(
    summary: dict[str, Any], seq_hash: dict[int | None, str | None]
) -> list[dict[str, Any]]:
    """挑出被质疑条目：SUSPECT_* 裁决，或带 error 级异常（如空内容计费）。"""
    out: list[dict[str, Any]] = []
    for v in summary.get("verdicts", []):
        verdict = v["verdict"]
        has_error = any(a["severity"] == "error" for a in verdict["anomalies"])
        if not verdict["status"].startswith("SUSPECT") and not has_error:
            continue
        out.append(
            {
                "seq": v["seq"],
                "model": v["model"],
                "request_id": v["request_id"],
                "record_hash": seq_hash.get(v["seq"]),
                "status": verdict["status"],
                "deviation_pct": verdict["deviation_pct"],
                "reported": verdict["reported"],
                "estimate": verdict["estimate"],
                "anomalies": verdict["anomalies"],
            }
        )
    return out


def build_statement(
    ledger_path: str | Path,
    records: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    strategy: str = "auto",
    tolerance_hi: float = TOLERANCE_HI,
    tolerance_lo: float = TOLERANCE_LO,
) -> dict[str, Any]:
    """由账本记录与对账汇总组装声明 dict（含 statement_sha256 与复现命令）。

    前置条件：调用方已完成 ``Ledger.verify()`` 且链完整——链损坏时声明
    拒绝出具（见 cli.cmd_statement），这里不做二次校验。
    """
    seq_hash = {r.get("seq"): r.get("hash") for r in records}
    head = records[-1].get("hash") if records else None
    body: dict[str, Any] = {
        "tellan_version": __version__,
        "ledger": {
            "n_records": summary.get("n_records", len(records)),
            "file_sha256": _sha256_file(ledger_path),
            "chain_head": head,
            "first_ts": records[0].get("ts") if records else None,
            "last_ts": records[-1].get("ts") if records else None,
        },
        "parameters": {
            "strategy": strategy,
            "tolerance_lo_factor": tolerance_lo,
            "tolerance_hi_factor": tolerance_hi,
            "price_table": {
                "models": len(DEFAULT_TABLE),
                "as_of": META.get("as_of", "unknown"),
                "source_note": SNAPSHOT_NOTE,
            },
        },
        "summary": {
            "status_counts": summary.get("status_counts", {}),
            "totals_reported": summary.get("totals_reported", {}),
            "totals_estimated": summary.get("totals_estimated"),
            "cost_reported_total": summary.get("cost_reported_total", 0.0),
            "cost_estimated_total_range": summary.get("cost_estimated_total_range"),
            "anomaly_counts": summary.get("anomaly_counts", {}),
            "top_deviations": summary.get("top_deviations", []),
        },
        "disputed": disputed_records(summary, seq_hash),
    }
    body["statement_sha256"] = hashlib.sha256(
        canonical_json(body).encode("utf-8")
    ).hexdigest()
    body["reproduction"] = _repro_commands(ledger_path, strategy, tolerance_hi)
    return body


def _repro_commands(
    ledger_arg: str | Path, strategy: str, tolerance_hi: float
) -> list[str]:
    """复现命令块：同版本 + 同参数应产出同一 statement_sha256。

    路径按调用方传入原样回显（便于复制），不参与声明哈希。
    """
    arg = str(ledger_arg)
    margin = tolerance_hi - 1.0
    margin_str = f"{margin:g}"
    file_hash_cmd = (
        "python -c \"import hashlib,sys;"
        "print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())\""
    )
    return [
        f"pip install tellan=={__version__}   # 与声明同版本（或同一 commit 源码安装）",
        f"{file_hash_cmd} {arg}   # 应等于 ledger.file_sha256",
        f"tellan verify {arg}",
        f"tellan audit {arg} --strategy {strategy} --tolerance {margin_str}",
        (
            f"tellan statement {arg} --strategy {strategy} --tolerance {margin_str} "
            "-o statement.md --json-out statement.json"
        ),
        "# 重跑得到的 statement_sha256 应与本声明一致",
    ]


# ------------------------------------------------------------------ rendering


def _cell(text: Any) -> str:
    """Markdown 表格单元格转义（管道符会破表）。"""
    return str(text).replace("|", "\\|")


def _short(h: str | None) -> str:
    if not h:
        return "-"
    return f"`{h[:_HASH_PREFIX]}…`"


def render_statement_markdown(st: dict[str, Any]) -> str:
    led = st["ledger"]
    params = st["parameters"]
    summary = st["summary"]
    lines: list[str] = []

    lines.append("# tellan 对账声明（Settlement Statement）")
    lines.append("")
    lines.append(
        f"> 由 tellan v{st['tellan_version']} 自动生成：厂商报数 vs 本地复算包围盒"
        " vs 价格快照的三方对账结果，供争议双方逐条核对。本声明只基于所附账本，"
        "不构成对任何厂商的指控；复算结论是统计包围盒上的\"超出/未超出\"，"
        "不是司法结论。文末附复现命令——同版本脚本重跑同一账本，"
        "应得到完全一致的声明（statement_sha256 一致）。"
    )
    lines.append("")

    # ---- 账本与完整性
    lines.append("## 账本与完整性")
    lines.append("")
    period = "-"
    if led["first_ts"] and led["last_ts"]:
        period = f"{led['first_ts']} ~ {led['last_ts']}（UTC）"
    lines.append(f"- 账本文件 sha256：`{led['file_sha256']}`")
    lines.append(f"- 记录数：{led['n_records']}")
    chain = f"完整（链尾 {_short(led['chain_head'])}，完整值见 JSON）" \
        if led["chain_head"] else "（空账本）"
    lines.append(f"- 哈希链：{chain}")
    lines.append(f"- 覆盖时间：{period}")
    lines.append("")

    # ---- 结论一览
    lines.append("## 结论一览")
    lines.append("")
    status = summary["status_counts"]
    lines.append(
        "- 裁决分布："
        + ("，".join(f"{k} {v}" for k, v in sorted(status.items())) if status else "无记录")
    )
    totals = summary["totals_reported"]
    lines.append(
        f"- 报数总量：input {totals.get('prompt_tokens', 0)} / "
        f"output {totals.get('completion_tokens', 0)} / "
        f"reasoning {totals.get('reasoning_tokens', 0)} / "
        f"cached {totals.get('cached_tokens', 0)}"
    )
    est = summary["totals_estimated"]
    if est:
        lines.append(
            f"- 本地复算区间：input [{est['input'][0]}, {est['input'][1]}] / "
            f"output [{est['output'][0]}, {est['output'][1]}]"
        )
    else:
        lines.append("- 本地复算区间：无可用估计（全部 INSUFFICIENT_DATA？）")
    cost_range = summary.get("cost_estimated_total_range") or [0.0, 0.0]
    lines.append(
        f"- 费用：厂商报数口径合计 {summary['cost_reported_total']:.4f}；"
        f"复算区间 [{cost_range[0]:.4f}, {cost_range[1]:.4f}]"
        "（价格快照，仅供量级参考，不作为结算依据）"
    )
    anomalies = summary["anomaly_counts"]
    lines.append(
        "- 异常："
        + ("，".join(f"`{k}`×{v}" for k, v in sorted(anomalies.items())) if anomalies else "无")
    )
    lines.append("")

    # ---- 被质疑条目
    lines.append("## 被质疑条目（SUSPECT 裁决或 error 级异常）")
    lines.append("")
    disputed = st["disputed"]
    if not disputed:
        lines.append("无被质疑条目——可复算记录的报数全部落在容差盒内。")
    else:
        lines.append("| seq | model | 报数 in/out | 复算盒 in/out | 偏差 | 裁决 |")
        lines.append("|---|---|---|---|---|---|")
        for d in disputed[:DISPUTED_DISPLAY_LIMIT]:
            est_d = d["estimate"]
            box_in = box_out = "-"
            if est_d:
                box_in = f"[{est_d['input_lo']}, {est_d['input_hi']}]"
                box_out = f"[{est_d['output_lo']}, {est_d['output_hi']}]"
            rep = d["reported"] or {}
            rep_in = rep.get("prompt_tokens", 0)
            rep_out = rep.get("completion_tokens", 0)
            dev = d["deviation_pct"]
            dev_str = f"{dev:+.1f}%" if dev is not None else "-"
            lines.append(
                f"| {d['seq']} | {_cell(d['model'] or '-')} | {rep_in}/{rep_out} "
                f"| {box_in} / {box_out} | {dev_str} | {d['status']} |"
            )
        if len(disputed) > DISPUTED_DISPLAY_LIMIT:
            lines.append("")
            lines.append(
                f"另有 {len(disputed) - DISPUTED_DISPLAY_LIMIT} 条未列出（完整清单见 JSON 声明）。"
            )
        lines.append("")
        lines.append("逐条明细（定位一条争议记录：用 record_hash 在账本 JSONL 中搜索）：")
        lines.append("")
        for d in disputed[:DISPUTED_DISPLAY_LIMIT]:
            rep = d["reported"] or {}
            head = (
                f"- **seq={d['seq']}** {d['model'] or '-'}"
                f"（request_id {d['request_id'] or '-'}；"
                f"record_hash {_short(d['record_hash'])}）："
                f"报数 in {rep.get('prompt_tokens', 0)} / "
                f"out {rep.get('completion_tokens', 0)}，"
                f"裁决 {d['status']}"
            )
            parts = [head]
            est_d = d["estimate"]
            if est_d:
                parts.append(
                    f"；复算策略 {est_d['strategy']}/置信度 {est_d['confidence']}，"
                    f"盒 in [{est_d['input_lo']}, {est_d['input_hi']}] "
                    f"out [{est_d['output_lo']}, {est_d['output_hi']}]"
                )
            lines.append("".join(parts))
            for a in d["anomalies"]:
                lines.append(
                    f"  - `{a['code']}`（{a['severity']}）：{_cell(a['detail'])}"
                )
    lines.append("")

    # ---- 规则与数据来源
    lines.append("## 对账规则与数据来源")
    lines.append("")
    lines.append(
        f"- 裁决规则：报数 ∈ [复算 lo×{params['tolerance_lo_factor']}, "
        f"复算 hi×{params['tolerance_hi_factor']}] 判 OK；输入/输出两侧独立检查；"
        "高出上沿判 SUSPECT_INFLATED，低于下沿判 SUSPECT_DEFLATED；"
        "原文不在账本（如脱敏模式）时 INSUFFICIENT_DATA，不计入质疑。"
    )
    lines.append(f"- 复算策略：`{params['strategy']}`（逐条实际策略与置信度见被质疑条目明细）。")
    pt = params["price_table"]
    note = pt["source_note"].rstrip("。；;")
    lines.append(
        f"- 价格表：内置快照 {pt['models']} 模型，as_of {pt['as_of']}——"
        f"{note}。"
    )
    n_missing = anomalies.get("PRICE_MISSING", 0)
    if n_missing:
        lines.append(
            f"- 价格缺失披露：{n_missing} 条记录价格表无该模型（`PRICE_MISSING`），"
            "其费用**未计入**上述合计——缺价按\"无法核对\"处理，不静默按 0。"
        )
    lines.append("")

    # ---- 复现
    lines.append("## 复现（同版本 + 同参数应逐字节复现本声明）")
    lines.append("")
    lines.append("```bash")
    lines.extend(st["reproduction"])
    lines.append("```")
    lines.append(
        f"- 声明哈希 statement_sha256：`{st['statement_sha256']}`"
        "（不依赖文件路径；账本内容 + tellan 版本 + 参数决定）"
    )
    lines.append("")

    # ---- 边界与局限
    lines.append("## 边界与局限（读这节再下结论）")
    lines.append("")
    lines.append(
        "- 哈希链证明账本**自链完整**（出具后未被篡改），不等于厂商签名："
        "有能力重构整条链的一方可以伪造账本（HMAC/外部锚定在设计选项中）。"
    )
    lines.append(
        "- 本地复算是包围盒估计不是真值：盒宽与容差意味着轻微多报不报警（抑噪是特性）；"
        "`SUSPECT_*` 的含义是\"报数超出诚实包围盒\"，不是\"已证实欺诈\"。"
    )
    lines.append(
        "- reasoning_tokens 是厂商自报的不可见消耗，无法复算，已并入输出盒上沿并提示"
        " `OPAQUE_REASONING`；流式 usage 缺失时该记录记 INSUFFICIENT_DATA，不编数。"
    )
    lines.append(
        "- 价格快照为估值（as_of 见上），费用数字仅供量级对账；结算以厂商账单为准。"
    )
    lines.append(
        "- 本声明由工具自动生成，不构成法律意见；对外主张请以可复现证据 + 人工复核为准。"
    )
    lines.append("")
    return "\n".join(lines)


def render_statement_json(st: dict[str, Any]) -> str:
    return json.dumps(st, ensure_ascii=False, indent=2, sort_keys=False)
