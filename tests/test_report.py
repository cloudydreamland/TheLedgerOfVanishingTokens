"""report.py 测试：Markdown/JSON 渲染与直方图分桶。"""

from tellan.reconcile import reconcile_ledger
from tellan.report import deviation_histogram, render_json, render_markdown


def _summary_with_deviations(devs: list[float]) -> dict:
    verdicts = [
        {"seq": i + 1, "model": "m", "request_id": None,
         "verdict": {"status": "OK", "deviation_pct": d, "reported": {},
                     "estimate": None, "cost_reported": None,
                     "cost_estimated_range": None, "anomalies": []}}
        for i, d in enumerate(devs)
    ]
    return {
        "n_records": len(devs), "status_counts": {"OK": len(devs)},
        "totals_reported": {"prompt_tokens": 0, "completion_tokens": 0,
                            "reasoning_tokens": 0, "cached_tokens": 0},
        "totals_estimated": None, "cost_reported_total": 0.0,
        "cost_estimated_total_range": [0.0, 0.0],
        "anomaly_counts": {"OPAQUE_REASONING": 1},
        "top_deviations": [], "verdicts": verdicts,
    }


def test_histogram_buckets_counts():
    summary = _summary_with_deviations([-60.0, 5.0, 30.0, 60.0])
    buckets = dict(deviation_histogram(summary))
    assert buckets["< -50%"] == 1
    assert buckets["-10% ~ +10%"] == 1
    assert buckets["+25% ~ +50%"] == 1
    assert buckets["> +50%"] == 1
    assert buckets["-25% ~ -10%"] == 0


def test_histogram_ignores_none():
    summary = _summary_with_deviations([None, 3.0])  # type: ignore[list-item]
    buckets = dict(deviation_histogram(summary))
    assert sum(buckets.values()) == 1


def test_markdown_contains_all_sections():
    summary = _summary_with_deviations([1.0, 40.0])
    md = render_markdown(summary)
    for section in ("# tellan 对账报告", "## 汇总", "## 偏差直方图", "## 异常",
                    "## 偏差最大 Top"):
        assert section in md
    assert "OPAQUE_REASONING" in md
    assert "快照估值" in md  # 诚实声明必须出现在报告里


def test_markdown_empty_summary():
    md = render_markdown(reconcile_ledger([]))
    assert "无异常" in md
    assert "无（没有可计算偏差的记录）" in md


def test_json_roundtrip():
    import json

    summary = _summary_with_deviations([2.5])
    parsed = json.loads(render_json(summary))
    assert parsed["n_records"] == 1
    assert parsed["verdicts"][0]["verdict"]["deviation_pct"] == 2.5
