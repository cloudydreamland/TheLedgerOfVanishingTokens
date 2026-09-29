"""calibrate_boxes.py — 盒宽校准脚本（ROADMAP iter3）。

用 tiktoken 对内置 fixture 实测"真盒宽"：对覆盖清单内的模型族，精确复算
输入/输出 token，与 heuristic 点估计对比，给出建议倍率，结果写
benchmarks/calibration.md（脚本真实输出，不手改）。

用法：
    python tools/calibrate_boxes.py            # 覆盖清单内的全部 fixture
    python tools/calibrate_boxes.py --out benchmarks/calibration.md

诚实边界：只对 tiktoken 覆盖清单内的模型族出数字；国产模型族没有真值可校准，
脚本会如实列出"无法校准"的 fixture 而不是编一个数字。
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tellan.bench import FIXTURES
from tellan.recount import (
    TIKTOKEN_COVERAGE,
    HeuristicCounter,
    TiktokenCounter,
    TiktokenUnavailable,
    message_text,
    model_family,
    point_count,
)


def _exact_counts(model: str, request: dict, response: dict) -> tuple[int, int] | None:
    """tiktoken 精确复算 (input, output)；不支持/不可用返回 None。"""
    try:
        counter = TiktokenCounter()
        est = counter.estimate_exchange(request, response, model)
    except TiktokenUnavailable:
        # 含 TiktokenUnsupportedModel：覆盖清单外/负名单模型族，无真值可校准
        return None
    return est.input_lo, est.output_lo  # 精确模式 lo==hi


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="benchmarks/calibration.md")
    args = ap.parse_args()

    try:
        TiktokenCounter()  # 探测可用性（encoding 懒加载，不在此处下载）
    except TiktokenUnavailable as exc:
        print(f"tiktoken 不可用，无法校准：{exc}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for fx in FIXTURES:
        model = fx["model"]
        family = model_family(model)
        if family not in TIKTOKEN_COVERAGE:
            rows.append({"name": fx["name"], "model": model, "family": family,
                         "status": "SKIP（覆盖清单外，无真值）"})
            continue
        exact = _exact_counts(model, fx["request"], fx["response"])
        if exact is None:
            rows.append({"name": fx["name"], "model": model, "family": family,
                         "status": "SKIP（tiktoken 失败）"})
            continue
        h = HeuristicCounter().estimate_exchange(fx["request"], fx["response"], model)
        in_texts = [message_text(m)[0] for m in fx["request"].get("messages", [])
                    if isinstance(m, dict)]
        in_point = point_count(
            "".join(in_texts), family, len(fx["request"].get("messages") or []),
            len(fx["request"].get("tools") or []),
        )
        out_texts = []
        for c in fx["response"].get("choices") or []:
            msg = c.get("message") or c.get("delta") or {}
            out_texts.append(message_text(msg)[0])
        out_point = point_count("".join(out_texts), family,
                                len(fx["response"].get("choices") or []), 0)
        in_exact, out_exact = exact
        rows.append({
            "name": fx["name"], "model": model, "family": family, "status": "OK",
            "in_exact": in_exact, "in_point": in_point,
            "in_ratio": (in_exact / in_point) if in_point else 0.0,
            "in_in_box": h.input_lo <= in_exact <= h.input_hi,
            "out_exact": out_exact, "out_point": out_point,
            "out_ratio": (out_exact / out_point) if out_point else 0.0,
            "out_in_box": h.output_lo <= out_exact <= h.output_hi,
        })

    lines: list[str] = [
        "# 盒宽校准（iter3 交付物，脚本真实输出）",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        ("- 方法：tiktoken 精确复算 vs heuristic 点估计（`point_count`），"
         "比率 = 精确 / 点估计；建议倍率 = 比率的 [min, max] 外扩 10%。"),
        ("- 诚实边界：只校准 tiktoken 覆盖清单内模型族；国产模型族无真值，"
         "包围盒倍率维持设计值 [0.5, 1.6] 并在下方如实列为「无法校准」。"),
        "",
    ]
    ok_rows = [r for r in rows if r["status"] == "OK"]
    lines.append("## 逐 fixture 结果\n")
    lines.append("| fixture | model | 输入精确/点估 | 输入入盒 | 输出精确/点估 | 输出入盒 |")
    lines.append("|---|---|---|---|---|---|")
    for r in ok_rows:
        lines.append(
            f"| {r['name']} | {r['model']} "
            f"| {r['in_exact']}/{r['in_point']:.0f} ({r['in_ratio']:.2f}x) "
            f"| {'是' if r['in_in_box'] else '**否**'} "
            f"| {r['out_exact']}/{r['out_point']:.0f} ({r['out_ratio']:.2f}x) "
            f"| {'是' if r['out_in_box'] else '**否**'} |"
        )
    skipped = [r for r in rows if r["status"] != "OK"]
    if skipped:
        lines.append("\n## 无法校准（诚实清单）\n")
        for r in skipped:
            lines.append(f"- {r['name']}（{r['model']}，族 {r['family']}）：{r['status']}")

    lines.append("\n## 分族建议倍率\n")
    by_family: dict[str, list[dict]] = {}
    for r in ok_rows:
        by_family.setdefault(r["family"], []).extend(
            [{"side": "输入", "ratio": r["in_ratio"], "in_box": r["in_in_box"]},
             {"side": "输出", "ratio": r["out_ratio"], "in_box": r["out_in_box"]}])
    for family, items in sorted(by_family.items()):
        ratios = [x["ratio"] for x in items]
        lo, hi = min(ratios), max(ratios)
        suggest_lo = max(0.1, round(lo * 0.9, 2))
        suggest_hi = round(hi * 1.1, 2)
        cover = sum(1 for x in items if x["in_box"]) / len(items)
        enc = TIKTOKEN_COVERAGE[family]["encoding"]
        lines.append(
            f"- **{family}**（{enc}，n={len(items)}）：比率 min/中位/max = "
            f"{lo:.2f}/{statistics.median(ratios):.2f}/{hi:.2f}；"
            f"当前盒覆盖率 {cover:.0%}；建议倍率 ≈ [{suggest_lo}, {suggest_hi}]"
            "（当前设计 [0.5, 1.6]；是否调整由人工决策，脚本只给证据）"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"校准完成：{len(ok_rows)} 个 fixture 校准 / {len(skipped)} 个无法校准 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
