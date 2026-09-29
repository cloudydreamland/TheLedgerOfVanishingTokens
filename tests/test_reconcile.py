"""reconcile.py 测试：三方裁决与六个异常检测器的正反例。"""

from typing import Any

from tellan.prices import DEFAULT_TABLE
from tellan.reconcile import (
    detect_dup_request_id,
    detect_empty_content_billed,
    detect_opaque_reasoning,
    detect_price_missing,
    detect_token_inflation,
    reconcile_ledger,
    reconcile_record,
)
from tellan.recount import HeuristicCounter

MODEL = "deepseek-chat"
_ZH = "这是一段用于对账测试的中文请求文本，长度保持适中以便估计。" * 3


def make_record(
    usage: dict[str, Any] | None,
    *,
    content: str | None = "这是回复。",
    model: str = MODEL,
    messages: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
    response: dict[str, Any] | None = None,
    seq: int = 1,
) -> dict[str, Any]:
    if messages is None:
        messages = [{"role": "user", "content": _ZH}]
    if response is None:
        response = {"choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant",
                                             "content": content}}]}
    return {
        "seq": seq, "kind": "chat_completion", "model": model,
        "request_id": request_id, "usage": usage,
        "data": {"request": {"model": model, "messages": messages},
                 "response": response},
    }


def honest_usage(model: str = MODEL) -> dict[str, Any]:
    """用包围盒中点构造“诚实厂商”报数，保证落盒内。"""
    est = HeuristicCounter().estimate_exchange(
        {"messages": [{"role": "user", "content": _ZH}]},
        {"choices": [{"message": {"role": "assistant", "content": "这是回复。"}}]},
        model,
    )
    return {
        "prompt_tokens": (est.input_lo + est.input_hi) // 2,
        "completion_tokens": (est.output_lo + est.output_hi) // 2,
    }


# ------------------------------------------------------------------- 裁决


def test_ok_case():
    verdict = reconcile_record(make_record(honest_usage()))
    assert verdict.status == "OK"
    assert verdict.estimate is not None
    assert verdict.anomalies == [] or all(a.severity == "info"
                                          for a in verdict.anomalies)


def test_inflated_detected():
    usage = honest_usage()
    usage["completion_tokens"] *= 5
    verdict = reconcile_record(make_record(usage))
    assert verdict.status == "SUSPECT_INFLATED"
    assert any(a.code == "TOKEN_INFLATION" for a in verdict.anomalies)


def test_deflated_detected():
    usage = honest_usage()
    usage["prompt_tokens"] = max(1, usage["prompt_tokens"] // 20)
    verdict = reconcile_record(make_record(usage))
    assert verdict.status == "SUSPECT_DEFLATED"
    assert any(a.code == "TOKEN_DEFLATION" for a in verdict.anomalies)


def test_insufficient_data_without_messages():
    usage = honest_usage()
    record = make_record(usage)
    record["data"] = {"request": {"model": MODEL}, "response": {}}
    verdict = reconcile_record(record)
    assert verdict.status == "INSUFFICIENT_DATA"


def test_insufficient_data_without_usage():
    verdict = reconcile_record(make_record(None))
    assert verdict.status == "INSUFFICIENT_DATA"


def test_deviation_pct_none_when_insufficient():
    verdict = reconcile_record(make_record(None))
    assert verdict.deviation_pct is None


def test_deviation_pct_sign_follows_direction():
    high = reconcile_record(make_record({**honest_usage(),
                                         "completion_tokens": 10 ** 6}))
    low = reconcile_record(make_record({**honest_usage(),
                                        "completion_tokens": 0,
                                        "prompt_tokens": 10 ** 6}))
    assert high.deviation_pct is not None and high.deviation_pct > 0
    assert low.status in ("SUSPECT_DEFLATED", "SUSPECT_INFLATED")


def test_tolerance_widening_flips_verdict():
    usage = honest_usage()
    usage["completion_tokens"] = int(usage["completion_tokens"] * 2) + 50
    strict = reconcile_record(make_record(usage))  # 默认容差 1.25
    loose = reconcile_record(make_record(usage), tolerance_hi=10.0)
    assert strict.status != "OK"
    assert loose.status == "OK"


def test_cost_fields_present_when_price_known():
    verdict = reconcile_record(make_record(
        {"prompt_tokens": 1000, "completion_tokens": 500}, model="gpt-4o"))
    assert verdict.cost_reported is not None and verdict.cost_reported > 0
    assert verdict.cost_estimated_range is not None
    lo, hi = verdict.cost_estimated_range
    assert 0 <= lo <= hi


def test_verdict_as_dict_roundtrip():
    verdict = reconcile_record(make_record(honest_usage()))
    d = verdict.as_dict()
    assert d["status"] == "OK"
    assert d["estimate"]["strategy"] == "heuristic"


# ------------------------------------------------------- 异常检测器正反例


def test_empty_content_billed_positive():
    record = make_record({"prompt_tokens": 10, "completion_tokens": 345},
                         content=None)
    anomaly = detect_empty_content_billed(record)
    assert anomaly is not None and anomaly.code == "EMPTY_CONTENT_BILLED"
    assert anomaly.severity == "error"


def test_empty_content_billed_negative_normal_content():
    assert detect_empty_content_billed(
        make_record({"prompt_tokens": 10, "completion_tokens": 5})) is None


def test_empty_content_billed_negative_reasoning_explains():
    """content 为空但 reasoning>0：有解释，不算 EMPTY_CONTENT（另有 info 提示）。"""
    record = make_record(
        {"prompt_tokens": 10, "completion_tokens": 345,
         "completion_tokens_details": {"reasoning_tokens": 340}},
        content=None,
    )
    assert detect_empty_content_billed(record) is None


def test_empty_content_billed_negative_zero_completion():
    assert detect_empty_content_billed(make_record(
        {"prompt_tokens": 10, "completion_tokens": 0}, content=None)) is None


def test_empty_content_billed_negative_tool_calls():
    resp = {"choices": [{"index": 0, "message": {
        "role": "assistant", "content": "",
        "tool_calls": [{"function": {"name": "f", "arguments": "{}"}}]}}]}
    record = make_record({"prompt_tokens": 10, "completion_tokens": 28},
                         response=resp)
    assert detect_empty_content_billed(record) is None


def test_opaque_reasoning_positive():
    record = make_record({"prompt_tokens": 10, "completion_tokens": 100,
                          "completion_tokens_details": {"reasoning_tokens": 90}})
    anomaly = detect_opaque_reasoning(record)
    assert anomaly is not None and anomaly.severity == "info"


def test_opaque_reasoning_negative():
    assert detect_opaque_reasoning(
        make_record({"prompt_tokens": 10, "completion_tokens": 100})) is None


def test_token_inflation_needs_estimate():
    assert detect_token_inflation(make_record(honest_usage()), None) is None


def test_price_missing_positive_and_negative():
    record = make_record(honest_usage(), model="mystery-relay-model")
    assert detect_price_missing(record, DEFAULT_TABLE) is not None
    record = make_record(honest_usage(), model="gpt-4o")
    assert detect_price_missing(record, DEFAULT_TABLE) is None


def test_dup_request_id_second_occurrence():
    seen: set[str] = set()
    assert detect_dup_request_id(make_record(None, request_id="r1"), seen) is None
    anomaly = detect_dup_request_id(make_record(None, request_id="r1"), seen)
    assert anomaly is not None and anomaly.code == "DUP_REQUEST_ID"


def test_dup_request_id_ignores_empty():
    seen: set[str] = set()
    assert detect_dup_request_id(make_record(None, request_id=None), seen) is None
    assert seen == set()


# ------------------------------------------------------------ 整本对账


def test_reconcile_ledger_summary_shape():
    records = [make_record(honest_usage(), seq=i + 1, request_id=f"r{i}")
               for i in range(3)]
    records.append(make_record({**honest_usage(), "completion_tokens": 99999},
                               seq=4, request_id="r-bad"))
    summary = reconcile_ledger(records)
    for key in ("n_records", "status_counts", "totals_reported",
                "totals_estimated", "cost_reported_total",
                "cost_estimated_total_range", "anomaly_counts",
                "top_deviations", "verdicts"):
        assert key in summary
    assert summary["n_records"] == 4
    assert summary["totals_reported"]["prompt_tokens"] > 0
    assert "SUSPECT_INFLATED" in summary["status_counts"]
    assert summary["anomaly_counts"].get("TOKEN_INFLATION") == 1


def test_reconcile_ledger_top_deviations_sorted():
    records = [
        make_record({**honest_usage(), "completion_tokens": 123}, seq=1,
                    request_id="a"),
        make_record({**honest_usage(), "completion_tokens": 99999}, seq=2,
                    request_id="b"),
    ]
    summary = reconcile_ledger(records)
    devs = [d["deviation_pct"] for d in summary["top_deviations"]]
    assert devs == sorted(devs, key=lambda x: abs(x), reverse=True)


def test_reconcile_ledger_estimated_range_brackets_reported():
    records = [make_record(honest_usage(), seq=1, request_id="a")]
    summary = reconcile_ledger(records)
    est = summary["totals_estimated"]
    rep = summary["totals_reported"]
    assert est["input"][0] <= rep["prompt_tokens"] <= est["input"][1]
    assert est["output"][0] <= rep["completion_tokens"] <= est["output"][1]


def test_reconcile_ledger_empty():
    summary = reconcile_ledger([])
    assert summary["n_records"] == 0
    assert summary["totals_estimated"] is None
    assert summary["top_deviations"] == []


def test_dup_detected_across_ledger():
    records = [make_record(honest_usage(), seq=1, request_id="same"),
               make_record(honest_usage(), seq=2, request_id="same")]
    summary = reconcile_ledger(records)
    assert summary["anomaly_counts"].get("DUP_REQUEST_ID") == 1
