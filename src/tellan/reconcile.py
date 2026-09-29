"""reconcile.py — 三方对账：厂商报数 vs 本地复算包围盒 vs 价格表。

裁决规则（默认容差）：输出侧报数落在 ``[output_lo*0.9, output_hi*1.25]``
为 OK，高于上沿判 SUSPECT_INFLATED，低于下沿判 SUSPECT_DEFLATED；
无请求文本可复算（如脱敏账本）时 INSUFFICIENT_DATA——审计工具不装懂。

异常检测器彼此独立、可单测：EMPTY_CONTENT_BILLED / OPAQUE_REASONING /
TOKEN_INFLATION / TOKEN_DEFLATION / DUP_REQUEST_ID / PRICE_MISSING。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .prices import DEFAULT_TABLE, PriceTable
from .prices import cost as price_cost
from .recount import HeuristicCounter, TiktokenUnavailable, TokenEstimate, counter_for

TOLERANCE_LO = 0.9   # 报数 >= estimate_lo * 0.9
TOLERANCE_HI = 1.25  # 报数 <= estimate_hi * (1 + 0.25)
INFLATION_FACTOR = 1.5   # 输出报数 > hi*1.5 → TOKEN_INFLATION
DEFLATION_FACTOR = 0.5   # 输入报数 < lo*0.5 → TOKEN_DEFLATION


@dataclass
class Anomaly:
    code: str
    severity: str  # "error" | "warning" | "info"
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


@dataclass
class Verdict:
    status: str  # OK | SUSPECT_INFLATED | SUSPECT_DEFLATED | INSUFFICIENT_DATA
    deviation_pct: float | None
    reported: dict[str, Any]
    estimate: TokenEstimate | None
    cost_reported: float | None
    cost_estimated_range: tuple[float, float] | None
    anomalies: list[Anomaly] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "deviation_pct": self.deviation_pct,
            "reported": self.reported,
            "estimate": self.estimate.as_dict() if self.estimate else None,
            "cost_reported": self.cost_reported,
            "cost_estimated_range": list(self.cost_estimated_range)
            if self.cost_estimated_range else None,
            "anomalies": [a.as_dict() for a in self.anomalies],
        }


# ------------------------------------------------------------------ detectors
# 约定：每个检测器是独立函数，命中返回 Anomaly，未命中返回 None。


def detect_empty_content_billed(record: dict[str, Any]) -> Anomaly | None:
    """content 为空/None 却计费 completion_tokens>0，且无 reasoning 解释。"""
    usage = record.get("usage") or {}
    completion = int(usage.get("completion_tokens") or 0)
    if completion <= 0:
        return None
    details = usage.get("completion_tokens_details") or {}
    if int(details.get("reasoning_tokens") or 0) > 0:
        return None
    if _response_content_is_empty(record):
        return Anomaly(
            "EMPTY_CONTENT_BILLED", "error",
            f"content 为空/None 但 completion_tokens={completion}（无 reasoning 说明），"
            "疑似 opaque 计费",
        )
    return None


def _response_content_is_empty(record: dict[str, Any]) -> bool:
    data = record.get("data") or {}
    response = data.get("response")
    if not isinstance(response, dict):
        return False
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        # 无 choices 的非标准响应（如 responses API）：看 output_text 字段
        return "output_text" in response and not response.get("output_text")
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        msg = choice.get("message") or choice.get("delta") or {}
        # 有工具调用的响应不算空内容：计费对象是工具调用参数
        if msg.get("tool_calls"):
            return False
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return False
        if isinstance(content, list) and any(
            isinstance(p, dict) and (p.get("text") or "").strip() for p in content
        ):
            return False
        if content is None:
            return True
    return True


def detect_opaque_reasoning(record: dict[str, Any]) -> Anomaly | None:
    """reasoning_tokens>0：推理消耗不可见，info 级提示。"""
    usage = record.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    reasoning = int(details.get("reasoning_tokens") or 0)
    if reasoning > 0:
        return Anomaly(
            "OPAQUE_REASONING", "info",
            f"reasoning_tokens={reasoning}，该部分消耗不可见也不可复算",
        )
    return None


def detect_token_inflation(
    record: dict[str, Any], estimate: TokenEstimate | None
) -> Anomaly | None:
    """输出报数 > 输出包围盒上沿 × 1.5。"""
    if estimate is None:
        return None
    reported_out = int((record.get("usage") or {}).get("completion_tokens") or 0)
    threshold = estimate.output_hi * INFLATION_FACTOR
    if reported_out > threshold:
        return Anomaly(
            "TOKEN_INFLATION", "error",
            f"输出报数 {reported_out} > 包围盒上沿 {estimate.output_hi}×{INFLATION_FACTOR}",
        )
    return None


def detect_token_deflation(
    record: dict[str, Any], estimate: TokenEstimate | None
) -> Anomaly | None:
    """输入报数 < 输入包围盒下沿 × 0.5：疑似中转站截断上下文后仍按全量计费外
    的另一面——报数远小于真实发送量，或请求被悄悄缩水。"""
    if estimate is None:
        return None
    reported_in = int((record.get("usage") or {}).get("prompt_tokens") or 0)
    threshold = estimate.input_lo * DEFLATION_FACTOR
    if reported_in < threshold:
        return Anomaly(
            "TOKEN_DEFLATION", "warning",
            f"输入报数 {reported_in} < 包围盒下沿 {estimate.input_lo}×{DEFLATION_FACTOR}，"
            "疑似请求被截断或报数失真",
        )
    return None


def detect_dup_request_id(
    record: dict[str, Any], seen_request_ids: set[str]
) -> Anomaly | None:
    """同一 request_id 在账本出现两次：重放或日志复制。"""
    rid = record.get("request_id")
    if not rid:
        return None
    if rid in seen_request_ids:
        return Anomaly("DUP_REQUEST_ID", "warning", f"request_id={rid} 在账本中重复出现")
    seen_request_ids.add(rid)
    return None


def detect_price_missing(
    record: dict[str, Any], table: PriceTable
) -> Anomaly | None:
    """价格表查不到该模型：费用侧只能放弃。"""
    model = record.get("model") or ""
    if table.lookup(model) is None:
        return Anomaly("PRICE_MISSING", "warning", f"价格表无 {model!r}，费用对账跳过")
    return None


# ------------------------------------------------------------------ reconcile


def _reported_in_box(reported: int, lo: int, hi: int, tol_lo: float, tol_hi: float) -> bool:
    return lo * tol_lo <= reported <= hi * tol_hi


def reconcile_record(
    record: dict[str, Any],
    table: PriceTable = DEFAULT_TABLE,
    strategy: str = "auto",
    tolerance_hi: float = TOLERANCE_HI,
    tolerance_lo: float = TOLERANCE_LO,
    seen_request_ids: set[str] | None = None,
) -> Verdict:
    """对单条账本记录做三方对账，返回裁决。"""
    usage = record.get("usage") or {}
    model = record.get("model") or ""
    data = record.get("data") or {}
    request = data.get("request") if isinstance(data, dict) else None
    response = data.get("response") if isinstance(data, dict) else None
    anomalies: list[Anomaly] = []

    # 1) 复算包围盒（有请求文本才做；脱敏账本诚实降级）
    estimate: TokenEstimate | None = None
    messages = (request or {}).get("messages") if isinstance(request, dict) else None
    if messages:
        try:
            counter = counter_for(strategy)
            estimate = counter.estimate_exchange(request or {}, response or {}, model)
        except TiktokenUnavailable as exc:
            # 两种情况都诚实降级：tiktoken 没装 / 模型族不在覆盖清单（用 OpenAI
            # 分词器数国产模型是系统性偏差）。降级必须在 notes 留痕。
            counter = HeuristicCounter()
            estimate = counter.estimate_exchange(request or {}, response or {}, model)
            estimate.notes.append(f"精确模式不可用，回退 heuristic（包围盒）：{exc}")
        # 厂商自报的 reasoning_tokens 是不可见消耗，无法复算；诚实做法是把它
        # 并入输出盒上沿（OPAQUE_REASONING 异常会另行提示），只裁决可见部分。
        reasoning = int(((usage or {}).get("completion_tokens_details") or {})
                        .get("reasoning_tokens") or 0)
        if reasoning > 0 and estimate is not None:
            estimate = TokenEstimate(
                estimate.input_lo, estimate.input_hi,
                estimate.output_lo, estimate.output_hi + reasoning,
                estimate.strategy, estimate.confidence,
                [*estimate.notes,
                 f"输出盒并入厂商自报 reasoning_tokens={reasoning}（不可见部分，无法复算）"],
            )

    # 2) 裁决：输入/输出两侧独立检查报数是否落在容差盒内
    status = "INSUFFICIENT_DATA"
    deviation_pct: float | None = None
    reported_in = int(usage.get("prompt_tokens") or 0)
    reported_out = int(usage.get("completion_tokens") or 0)
    if not usage:
        status = "INSUFFICIENT_DATA"
    elif estimate is not None:
        in_ok = _reported_in_box(reported_in, estimate.input_lo, estimate.input_hi,
                                 tolerance_lo, tolerance_hi)
        out_ok = _reported_in_box(reported_out, estimate.output_lo, estimate.output_hi,
                                  tolerance_lo, tolerance_hi)
        mid_in = (estimate.input_lo + estimate.input_hi) / 2
        mid_out = (estimate.output_lo + estimate.output_hi) / 2
        dev_in = ((reported_in - mid_in) / mid_in * 100) if mid_in else 0.0
        dev_out = ((reported_out - mid_out) / mid_out * 100) if mid_out else 0.0
        if in_ok and out_ok:
            status = "OK"
            deviation_pct = round(dev_out, 1) if mid_out else None
        elif in_ok:  # 只有输出侧出盒
            deviation_pct = round(dev_out, 1)
            status = "SUSPECT_INFLATED" if dev_out > 0 else "SUSPECT_DEFLATED"
        elif out_ok:  # 只有输入侧出盒
            deviation_pct = round(dev_in, 1)
            status = "SUSPECT_INFLATED" if dev_in > 0 else "SUSPECT_DEFLATED"
        else:  # 两侧都出盒，按总量裁决
            rep_total = reported_in + reported_out
            mid_total = mid_in + mid_out
            dev_total = ((rep_total - mid_total) / mid_total * 100) if mid_total else 0.0
            deviation_pct = round(dev_total, 1)
            status = "SUSPECT_INFLATED" if dev_total > 0 else "SUSPECT_DEFLATED"
    else:
        status = "INSUFFICIENT_DATA"

    if estimate is not None and deviation_pct is None and usage:
        mid_out = (estimate.output_lo + estimate.output_hi) / 2
        if mid_out:
            deviation_pct = round((reported_out - mid_out) / mid_out * 100, 1)

    # 3) 异常检测
    for detector_result in (
        detect_empty_content_billed(record),
        detect_opaque_reasoning(record),
        detect_token_inflation(record, estimate),
        detect_token_deflation(record, estimate),
        detect_dup_request_id(record, seen_request_ids if seen_request_ids is not None
                              else set()),
        detect_price_missing(record, table),
    ):
        if detector_result is not None:
            anomalies.append(detector_result)

    # 4) 费用
    cost_reported: float | None = None
    cost_range: tuple[float, float] | None = None
    entry = table.lookup(model)
    if usage and entry is not None:
        cost_reported = price_cost(usage, entry)["amount"]
    if estimate is not None and entry is not None:
        lo_usage = {
            "prompt_tokens": estimate.input_lo, "completion_tokens": estimate.output_lo,
        }
        hi_usage = {
            "prompt_tokens": estimate.input_hi, "completion_tokens": estimate.output_hi,
        }
        cost_range = (
            price_cost(lo_usage, entry)["amount"],
            price_cost(hi_usage, entry)["amount"],
        )

    return Verdict(status, deviation_pct, dict(usage), estimate, cost_reported,
                   cost_range, anomalies)


def summarize_usage(usages: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "prompt_tokens": sum(int(u.get("prompt_tokens") or 0) for u in usages),
        "completion_tokens": sum(int(u.get("completion_tokens") or 0) for u in usages),
        "reasoning_tokens": sum(
            int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
            for u in usages
        ),
        "cached_tokens": sum(
            int((u.get("prompt_tokens_details") or {}).get("cached_tokens")
                or u.get("cache_read_input_tokens") or 0)
            for u in usages
        ),
    }


def reconcile_ledger(
    records: list[dict[str, Any]],
    table: PriceTable = DEFAULT_TABLE,
    strategy: str = "auto",
    tolerance_hi: float = TOLERANCE_HI,
    tolerance_lo: float = TOLERANCE_LO,
) -> dict[str, Any]:
    """对整本账本做对账，输出汇总：总报数 vs 总估计区间、费用区间、
    异常计数、偏差 Top 表。"""
    seen_rids: set[str] = set()
    verdicts: list[dict[str, Any]] = []
    for rec in records:
        verdict = reconcile_record(rec, table, strategy, tolerance_hi, tolerance_lo,
                                   seen_request_ids=seen_rids)
        verdicts.append({"seq": rec.get("seq"), "model": rec.get("model"),
                         "request_id": rec.get("request_id"), "verdict": verdict})

    usages = [r.get("usage") or {} for r in records if r.get("usage")]
    totals_reported = summarize_usage(usages)
    totals_estimated: dict[str, Any] | None = None
    est_in_lo = sum(v["verdict"].estimate.input_lo for v in verdicts
                    if v["verdict"].estimate)
    est_in_hi = sum(v["verdict"].estimate.input_hi for v in verdicts
                    if v["verdict"].estimate)
    est_out_lo = sum(v["verdict"].estimate.output_lo for v in verdicts
                     if v["verdict"].estimate)
    est_out_hi = sum(v["verdict"].estimate.output_hi for v in verdicts
                     if v["verdict"].estimate)
    if any(v["verdict"].estimate for v in verdicts):
        totals_estimated = {
            "input": [est_in_lo, est_in_hi],
            "output": [est_out_lo, est_out_hi],
        }

    cost_reported_total = sum(
        v["verdict"].cost_reported or 0.0 for v in verdicts
    )
    cost_lo = sum((v["verdict"].cost_estimated_range or (0.0, 0.0))[0] for v in verdicts)
    cost_hi = sum((v["verdict"].cost_estimated_range or (0.0, 0.0))[1] for v in verdicts)

    anomaly_counts: dict[str, int] = {}
    for v in verdicts:
        for a in v["verdict"].anomalies:
            anomaly_counts[a.code] = anomaly_counts.get(a.code, 0) + 1

    status_counts: dict[str, int] = {}
    for v in verdicts:
        status_counts[v["verdict"].status] = status_counts.get(v["verdict"].status, 0) + 1

    deviations = [
        {
            "seq": v["seq"],
            "model": v["model"],
            "status": v["verdict"].status,
            "deviation_pct": v["verdict"].deviation_pct,
        }
        for v in verdicts
        if v["verdict"].deviation_pct is not None
    ]
    deviations.sort(key=lambda d: abs(d["deviation_pct"] or 0.0), reverse=True)

    return {
        "n_records": len(records),
        "status_counts": status_counts,
        "totals_reported": totals_reported,
        "totals_estimated": totals_estimated,
        "cost_reported_total": round(cost_reported_total, 6),
        "cost_estimated_total_range": [round(cost_lo, 6), round(cost_hi, 6)],
        "anomaly_counts": anomaly_counts,
        "top_deviations": deviations[:10],
        "verdicts": [
            {**v, "verdict": v["verdict"].as_dict()} for v in verdicts
        ],
    }
