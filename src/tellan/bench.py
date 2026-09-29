"""bench.py — 内置 fixture 基准：复算包围盒对报数的覆盖与异常检出。

所有 fixture 都是**合成**的：文本由本仓库撰写，报数（usage）是按各家
tokenizer 公开行为手工标注的“厂商风格”数字——诚实的 fixture 报数落在
包围盒内，被操纵的 fixture（膨胀/content-null/截断）落在盒外并触发异常。
benchmark 的意义是验证检测管线本身，不声称度量任何真实厂商。

运行 ``python -m tellan.cli bench`` 会输出真实测量结果（覆盖率/检出率/
耗时），数字禁止手写——以脚本输出为准。
"""

from __future__ import annotations

import time
from typing import Any

from .reconcile import reconcile_record


def _req(model: str, *messages: str) -> dict[str, Any]:
    return {"model": model,
            "messages": [{"role": "user", "content": m} for m in messages]}


def _resp(text: str, *, finish: str = "stop") -> dict[str, Any]:
    return {"choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": text}}]}


def _usage(prompt: int, completion: int, **extra: Any) -> dict[str, Any]:
    u: dict[str, Any] = {"prompt_tokens": prompt, "completion_tokens": completion}
    u.update(extra)
    return u


_ZH_300 = ("请帮我总结这段关于账目的说明。" * 18)  # ~300 CJK 字
_ZH_800 = ("本地独立复算是计量审计的唯一可信来源，因为厂商既当运动员又当裁判。" * 16)
_EN_CODE = (
    "Write a Python function that validates a checksum:\n"
    "def luhn_ok(digits: str) -> bool:\n"
    "    total = 0\n"
    "    for i, ch in enumerate(reversed(digits)):\n"
    "        d = int(ch)\n"
    "        if i % 2 == 0:\n"
    "            d *= 2\n"
    "            if d > 9:\n"
    "                d -= 9\n"
    "        total += d\n"
    "    return total % 10 == 0\n"
    "Add unit tests covering edge cases like empty input and non digit chars."
)
_MIXED = ("对比一下 qwen-max 和 deepseek-chat 在这个 200 行 CSV 上的处理速度，"
          "重点看 throughput 和 latency 的差异。")

FIXTURES: list[dict[str, Any]] = [
    {
        "name": "deepseek-chat 中文问答",
        "model": "deepseek-chat",
        "request": _req("deepseek-chat", _ZH_300),
        "response": _resp("这是总结。"),
        "usage": _usage(196, 12),  # 厂商风格：~0.6 tok/字 + 框架
    },
    {
        "name": "deepseek-reasoner 带推理",
        "model": "deepseek-reasoner",
        "request": _req("deepseek-reasoner", _ZH_300),
        "response": _resp("答案是 42。"),
        "usage": _usage(200, 86, completion_tokens_details={"reasoning_tokens": 74}),
    },
    {
        "name": "gpt-4o 英文代码",
        "model": "gpt-4o",
        "request": _req("gpt-4o", _EN_CODE),
        "response": _resp("Here is the reviewed function with tests."),
        # 报数 = tiktoken o200k_base 实测真值（iter3 校准实测 input=107/output=12）。
        # 构建时曾按 heuristic 点估计填 110/20，tiktoken 可用后戳穿其为合成值——
        # 诚实 fixture 的报数必须是"厂商真值"而不是"我们猜的数"。
        "usage": _usage(107, 12),
    },
    {
        "name": "glm-4.6 中文长文",
        "model": "glm-4.6",
        "request": _req("glm-4.6", _ZH_800),
        "response": _resp("摘要：账目工具用于对账。"),
        "usage": _usage(700, 18),
    },
    {
        "name": "qwen-plus 中英混合",
        "model": "qwen-plus",
        "request": _req("qwen-plus", _MIXED),
        "response": _resp("qwen-max 吞吐更高，deepseek-chat 延迟更低。"),
        "usage": _usage(60, 22),
    },
    {
        "name": "gemini-2.5-flash thinking（报数膨胀 2x）",
        "model": "gemini-2.5-flash",
        "request": _req("gemini-2.5-flash", _ZH_300),
        "response": _resp("结论如下。"),
        "usage": _usage(180, 1200, completion_tokens_details={"reasoning_tokens": 300}),
        "expect": "SUSPECT_INFLATED",
    },
    {
        "name": "claude-sonnet-4 缓存读写",
        "model": "claude-sonnet-4",
        "request": _req("claude-sonnet-4", _ZH_300),
        "response": _resp("好的，已记录。"),
        "usage": _usage(320, 10, cache_read_input_tokens=5200,
                        cache_creation_input_tokens=880),
    },
    {
        "name": "content:null 计费案例（OpenRouter 事件复现）",
        "model": "some-relay-model",
        "request": _req("some-relay-model", _ZH_300),
        "response": {"choices": [{"index": 0, "finish_reason": "stop",
                                  "message": {"role": "assistant", "content": None}}]},
        "usage": _usage(180, 345),
        "expect_anomaly": "EMPTY_CONTENT_BILLED",
    },
    {
        "name": "gpt-4o-mini 短问答",
        "model": "gpt-4o-mini",
        "request": _req("gpt-4o-mini", "你好，用一句话介绍你自己。"),
        "response": _resp("我是一个本地对账工具。"),
        "usage": _usage(12, 12),  # 报数 = tiktoken o200k_base 实测真值（iter3 校准）
    },
    {
        "name": "kimi-k2 工具调用",
        "model": "kimi-k2",
        "request": {"model": "kimi-k2", "messages": [
            {"role": "user", "content": "查一下北京天气"},
        ]},
        "response": {"choices": [{"index": 0, "finish_reason": "tool_calls",
                                  "message": {"role": "assistant", "content": "",
                                              "tool_calls": [
                                                  {"id": "call_1", "type": "function",
                                                   "function": {"name": "get_weather",
                                                                "arguments":
                                                                    "{\"city\": \"北京\"}"}}]}}]},
        # 合成值（无真值）：Kimi 分词器不在 tiktoken 覆盖内。取 heuristic 估计
        # （message_text 含工具调用文本，点估计 in=13/out=18），仅验证管线。
        "usage": _usage(13, 18),
    },
    {
        "name": "中转站输入截断（报数缩水）",
        "model": "deepseek-chat",
        "request": _req("deepseek-chat", _ZH_800),
        "response": _resp("已总结。"),
        "usage": _usage(40, 8),
        "expect": "SUSPECT_DEFLATED",
        "expect_anomaly": "TOKEN_DEFLATION",
    },
]


def run_bench(table: Any = None) -> dict[str, Any]:
    """跑全部 fixture，返回真实测量指标（不联网，纯本地）。"""
    results: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for fx in FIXTURES:
        record = {
            "seq": len(results) + 1,
            "kind": "bench",
            "model": fx["model"],
            "usage": fx["usage"],
            "data": {"request": fx["request"], "response": fx["response"]},
        }
        t1 = time.perf_counter()
        verdict = reconcile_record(record)
        elapsed_ms = (time.perf_counter() - t1) * 1000
        est = verdict.estimate
        u = fx["usage"]
        in_box = bool(
            est and est.input_lo * 0.9 <= u["prompt_tokens"] <= est.input_hi * 1.25
        )
        out_box = bool(
            est and est.output_lo * 0.9 <= u["completion_tokens"] <= est.output_hi * 1.25
        )
        codes = {a.code for a in verdict.anomalies}
        results.append({
            "name": fx["name"],
            "model": fx["model"],
            "status": verdict.status,
            "input_box": [est.input_lo, est.input_hi] if est else None,
            "output_box": [est.output_lo, est.output_hi] if est else None,
            "reported": {"prompt_tokens": u["prompt_tokens"],
                         "completion_tokens": u["completion_tokens"]},
            "input_in_box": in_box,
            "output_in_box": out_box,
            "in_tolerance_box": in_box and out_box,
            "anomalies": sorted(codes),
            "elapsed_ms": round(elapsed_ms, 3),
            "expected_status": fx.get("expect"),
            "expected_anomaly": fx.get("expect_anomaly"),
        })
    total_ms = (time.perf_counter() - t0) * 1000
    n = len(results)
    empty_fx = [r for r in results if r["expected_anomaly"] == "EMPTY_CONTENT_BILLED"]
    empty_hit = sum(1 for r in empty_fx if "EMPTY_CONTENT_BILLED" in r["anomalies"])
    status_ok = sum(
        1 for r in results
        if r["expected_status"] and r["status"] == r["expected_status"]
    )
    expected_total = sum(1 for r in results if r["expected_status"])
    anomaly_ok = sum(
        1 for r in results
        if r["expected_anomaly"] and r["expected_anomaly"] in r["anomalies"]
    )
    expected_anoms = sum(1 for r in results if r["expected_anomaly"])
    return {
        "n_fixtures": n,
        "tolerance_box_coverage": round(
            sum(1 for r in results if r["in_tolerance_box"]) / n, 3),
        "input_box_coverage": round(sum(1 for r in results if r["input_in_box"]) / n, 3),
        "output_box_coverage": round(sum(1 for r in results if r["output_in_box"]) / n, 3),
        "empty_content_detected": f"{empty_hit}/{len(empty_fx)}",
        "expected_status_hits": f"{status_ok}/{expected_total}",
        "expected_anomaly_hits": f"{anomaly_ok}/{expected_anoms}",
        "total_ms": round(total_ms, 2),
        "per_fixture_ms_avg": round(total_ms / n, 3),
        "results": results,
    }


def render_bench_markdown(metrics: dict[str, Any]) -> str:
    """把 run_bench 的真实结果渲染成 results.md 的表格段落。"""
    lines: list[str] = []
    lines.append("## 汇总指标（真实脚本输出）")
    lines.append("")
    lines.append(f"- fixture 数：{metrics['n_fixtures']}（全部合成，见上方诚实声明）")
    lines.append(f"- 容差包围盒覆盖率（报数∈[lo×0.9, hi×1.25] 且输出侧同）："
                 f"{metrics['tolerance_box_coverage']:.1%}")
    lines.append(f"- 输入侧盒内覆盖率：{metrics['input_box_coverage']:.1%}")
    lines.append(f"- 输出侧盒内覆盖率：{metrics['output_box_coverage']:.1%}")
    lines.append(f"- EMPTY_CONTENT_BILLED 检出：{metrics['empty_content_detected']}")
    lines.append(f"- 预期裁决命中：{metrics['expected_status_hits']}")
    lines.append(f"- 预期异常命中：{metrics['expected_anomaly_hits']}")
    lines.append(f"- 总耗时：{metrics['total_ms']} ms（平均 "
                 f"{metrics['per_fixture_ms_avg']} ms/条，单线程纯 CPU）")
    lines.append("")
    lines.append("## 逐 fixture 明细")
    lines.append("")
    lines.append("| fixture | model | 裁决 | 报数(in/out) | 输入盒 | 输出盒 | 异常 | 耗时ms |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in metrics["results"]:
        ib = f"[{r['input_box'][0]},{r['input_box'][1]}]" if r["input_box"] else "-"
        ob = f"[{r['output_box'][0]},{r['output_box'][1]}]" if r["output_box"] else "-"
        anomalies = ",".join(r["anomalies"]) if r["anomalies"] else "-"
        rep = f"{r['reported']['prompt_tokens']}/{r['reported']['completion_tokens']}"
        lines.append(
            f"| {r['name']} | {r['model']} | {r['status']} | {rep} | {ib} | {ob} "
            f"| {anomalies} | {r['elapsed_ms']} |"
        )
    lines.append("")
    return "\n".join(lines)
