"""report.py — 对账报告渲染：Markdown 与 JSON 双格式。

输入是 :func:`tellan.reconcile.reconcile_ledger` 的汇总 dict，输出纯文本。
所有写入由调用方负责（本模块只返回字符串）。
"""

from __future__ import annotations

import json
from typing import Any

# 偏差直方图分桶（百分比）。标签为左闭右开区间，最后一个为开区间。
HISTOGRAM_BUCKETS: list[tuple[float, float, str]] = [
    (-10.0, 10.0, "-10% ~ +10%"),
    (10.0, 25.0, "+10% ~ +25%"),
    (25.0, 50.0, "+25% ~ +50%"),
    (50.0, float("inf"), "> +50%"),
    (-25.0, -10.0, "-25% ~ -10%"),
    (-50.0, -25.0, "-50% ~ -25%"),
    (float("-inf"), -50.0, "< -50%"),
]


def deviation_histogram(summary: dict[str, Any]) -> list[tuple[str, int]]:
    """按分桶统计各记录偏差，返回 [(桶标签, 数量)]，固定桶序。"""
    counts = {label: 0 for _, _, label in HISTOGRAM_BUCKETS}
    for v in summary.get("verdicts", []):
        dev = v["verdict"].get("deviation_pct")
        if dev is None:
            continue
        for lo, hi, label in HISTOGRAM_BUCKETS:
            if lo <= dev < hi:
                counts[label] += 1
                break
    ordered = {label: 0 for _, _, label in HISTOGRAM_BUCKETS}
    for lo, hi, label in HISTOGRAM_BUCKETS:
        ordered[label] = counts[label]
    # 保持定义顺序输出
    result = []
    seen: set[str] = set()
    for _, _, label in HISTOGRAM_BUCKETS:
        if label not in seen:
            result.append((label, ordered[label]))
            seen.add(label)
    return result


def _fmt_cost(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{x:.4f}"


def render_markdown(summary: dict[str, Any], title: str = "tellan 对账报告") -> str:
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("> 由 tellan 自动生成。价格来自内置快照（source_note 标注"
                 "“快照估值，发布前需人工核对，未联网逐条验证”），费用数字仅供量级参考。")
    lines.append("")

    # ---- 汇总
    lines.append("## 汇总")
    lines.append("")
    lines.append(f"- 账本记录数：{summary.get('n_records', 0)}")
    status = summary.get("status_counts", {})
    lines.append(
        "- 裁决分布：" + "，".join(f"{k} {v}" for k, v in sorted(status.items()))
        if status else "- 裁决分布：无记录"
    )
    totals = summary.get("totals_reported", {})
    lines.append(
        f"- 报数总量：input {totals.get('prompt_tokens', 0)} / "
        f"output {totals.get('completion_tokens', 0)} / "
        f"reasoning {totals.get('reasoning_tokens', 0)} / "
        f"cached {totals.get('cached_tokens', 0)}"
    )
    est = summary.get("totals_estimated")
    if est:
        lines.append(
            f"- 复算区间：input [{est['input'][0]}, {est['input'][1]}] / "
            f"output [{est['output'][0]}, {est['output'][1]}]"
        )
    else:
        lines.append("- 复算区间：无可用估计（全部 INSUFFICIENT_DATA？）")
    lines.append(
        f"- 费用报数合计：{_fmt_cost(summary.get('cost_reported_total'))}；"
        f"复算费用区间：[{_fmt_cost((summary.get('cost_estimated_total_range') or [0, 0])[0])}"
        f", {_fmt_cost((summary.get('cost_estimated_total_range') or [0, 0])[1])}]"
    )
    lines.append("")

    # ---- 直方图
    lines.append("## 偏差直方图")
    lines.append("")
    lines.append("| 区间（报数相对复算中点） | 条数 |")
    lines.append("|---|---|")
    for label, count in deviation_histogram(summary):
        bar = "#" * min(count, 40)
        lines.append(f"| {label} | {count} {bar} |".rstrip())
    lines.append("")

    # ---- 异常
    lines.append("## 异常")
    lines.append("")
    anomalies = summary.get("anomaly_counts", {})
    if anomalies:
        lines.append("| 异常码 | 次数 |")
        lines.append("|---|---|")
        for code, count in sorted(anomalies.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{code}` | {count} |")
    else:
        lines.append("无异常。")
    lines.append("")

    # ---- Top 偏差
    lines.append("## 偏差最大 Top")
    lines.append("")
    tops = summary.get("top_deviations", [])
    if tops:
        lines.append("| seq | model | 裁决 | 偏差 |")
        lines.append("|---|---|---|---|")
        for d in tops:
            dev = d.get("deviation_pct")
            dev_str = f"{dev:+.1f}%" if dev is not None else "-"
            lines.append(
                f"| {d.get('seq')} | {d.get('model') or '-'} "
                f"| {d.get('status')} | {dev_str} |"
            )
    else:
        lines.append("无（没有可计算偏差的记录）。")
    lines.append("")
    return "\n".join(lines)


def render_json(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=False)
