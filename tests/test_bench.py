"""bench.py 测试：内置 fixture 的真实运行结果与预期检出。"""

from tellan.bench import FIXTURES, render_bench_markdown, run_bench


def test_fixture_inventory():
    assert len(FIXTURES) == 11
    names = {fx["name"] for fx in FIXTURES}
    assert any("content" in n for n in names)
    assert any("reasoner" in n for n in names)
    assert any("缓存" in n for n in names)


def test_run_bench_metrics_shape():
    metrics = run_bench()
    for key in ("n_fixtures", "tolerance_box_coverage", "input_box_coverage",
                "output_box_coverage", "empty_content_detected",
                "expected_status_hits", "expected_anomaly_hits", "total_ms",
                "per_fixture_ms_avg", "results"):
        assert key in metrics
    assert metrics["n_fixtures"] == len(FIXTURES)
    assert 0.0 <= metrics["tolerance_box_coverage"] <= 1.0
    assert metrics["total_ms"] > 0


def test_empty_content_fixture_is_caught():
    metrics = run_bench()
    assert metrics["empty_content_detected"] == "1/1"


def test_expected_outcomes_hit():
    """合成 fixture 的预期裁决/异常必须全部命中（管线自检）。"""
    metrics = run_bench()
    assert metrics["expected_status_hits"] == "2/2"
    assert metrics["expected_anomaly_hits"] == "2/2"


def test_honest_fixtures_in_tolerance_box():
    """诚实标注的 fixture 报数必须落容差盒（验证盒宽设定的合理性）。"""
    metrics = run_bench()
    for r in metrics["results"]:
        if r["expected_status"] is None and r["expected_anomaly"] is None:
            assert r["in_tolerance_box"], f"{r['name']} 意外出盒"


def test_render_bench_markdown_table():
    metrics = run_bench()
    md = render_bench_markdown(metrics)
    assert "## 汇总指标" in md and "## 逐 fixture 明细" in md
    assert "EMPTY_CONTENT_BILLED" in md
    assert md.count("\n| ") >= len(FIXTURES)
