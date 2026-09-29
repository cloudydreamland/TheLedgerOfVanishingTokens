"""make_demo_statement.py — 生成 docs/ 下的对账声明演示工件（离线、确定性）。

产出三个文件：

- ``docs/demo_ledger.jsonl``   演示账本（合成数据，固定时间戳）
- ``docs/statement_example.md``    ``tellan statement`` 的真实 Markdown 输出
- ``docs/statement_example.json``  对应 JSON 声明

诚实声明：账本内容全部为**本脚本合成的示例数据**，不含任何真实请求或真实
厂商报数；它演示的是声明的形态与复现方式，不构成对任何厂商的指控。

确定性：固定 ts + 固定内容 + ``--strategy heuristic``（与是否安装 tiktoken
无关），任何人重跑本脚本应得到逐字节相同的三个文件（有测试锁死声明哈希）。

用法::

    python tools/make_demo_statement.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tellan.cli import main as cli_main
from tellan.ledger import Ledger

DOCS = ROOT / "docs"
LEDGER = DOCS / "demo_ledger.jsonl"

# 固定时间戳：确定性要求 + 演示"覆盖时间"字段。全部为合成时刻。
_T = [f"2026-09-20T0{i}:15:00+00:00" for i in range(1, 9)]

_Q = ("请把这段会议纪要整理成三点摘要，保留负责人和截止时间。" * 2)
_A = "已整理：三点摘要，负责人与截止时间已标注。"


def _req(model: str) -> dict:
    return {"model": model,
            "messages": [{"role": "user", "content": _Q}]}


def _resp(text: str) -> dict:
    return {"choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}]}


def main() -> int:
    import os

    os.chdir(ROOT)  # 声明中的复现命令以仓库相对路径回显，便于他人照抄
    DOCS.mkdir(exist_ok=True)
    LEDGER.unlink(missing_ok=True)  # 从零重建，保证逐字节可复现
    led = Ledger(LEDGER)
    # 每条记录自带合成声明：拿到账本的人不用找文档就知道这是演示数据
    meta = {"synthetic": True, "note": "合成演示数据，非真实流量"}

    # 1-2) 诚实记录：报数取 heuristic 包围盒中点（合成"厂商报数"）
    from tellan.recount import HeuristicCounter

    est = HeuristicCounter().estimate_exchange(
        _req("deepseek-chat"), _resp(_A), "deepseek-chat")
    honest_usage = {"prompt_tokens": (est.input_lo + est.input_hi) // 2,
                    "completion_tokens": (est.output_lo + est.output_hi) // 2}
    for i, ts in enumerate(_T[:2]):
        led.append("chat_completion", ts=ts, model="deepseek-chat", meta=dict(meta),
                   request_id=f"demo-ok-{i + 1}", usage=dict(honest_usage),
                   data={"request": _req("deepseek-chat"), "response": _resp(_A)})

    # 3) glm-4.6 长文摘要（诚实）
    long_q = "本地独立复算是计量审计的唯一可信来源，因为厂商既当运动员又当裁判。" * 10
    est3 = HeuristicCounter().estimate_exchange(
        {"messages": [{"role": "user", "content": long_q}]},
        _resp("摘要：账目工具用于对账。"), "glm-4.6")
    led.append("chat_completion", ts=_T[2], model="glm-4.6",
               request_id="demo-ok-3", meta=dict(meta),
               usage={"prompt_tokens": (est3.input_lo + est3.input_hi) // 2,
                      "completion_tokens": (est3.output_lo + est3.output_hi) // 2},
               data={"request": {"model": "glm-4.6", "messages": [
                   {"role": "user", "content": long_q}]},
                   "response": _resp("摘要：账目工具用于对账。")})

    # 4) 报数大幅膨胀（SUSPECT_INFLATED + TOKEN_INFLATION）——数字为合成演示值
    led.append("chat_completion", ts=_T[3], model="gemini-2.5-flash",
               request_id="demo-inflate", meta=dict(meta),
               usage={"prompt_tokens": 180, "completion_tokens": 1200,
                      "completion_tokens_details": {"reasoning_tokens": 300}},
               data={"request": _req("gemini-2.5-flash"), "response": _resp("结论如下。")})

    # 5) content:null 计费（EMPTY_CONTENT_BILLED，error 级）
    led.append("chat_completion", ts=_T[4], model="some-relay-model",
               request_id="demo-null", meta=dict(meta),
               usage={"prompt_tokens": 180, "completion_tokens": 345},
               data={"request": _req("some-relay-model"),
                     "response": {"choices": [{"index": 0, "finish_reason": "stop",
                                               "message": {"role": "assistant",
                                                           "content": None}}]}})

    # 6) 价格表未知模型（PRICE_MISSING 披露：缺价不静默按 0）
    led.append("chat_completion", ts=_T[5], model="mystery-alpha-latest",
               request_id="demo-price-missing", meta=dict(meta),
               usage=dict(honest_usage),
               data={"request": _req("mystery-alpha-latest"), "response": _resp(_A)})

    # 7-8) qwen-plus 混合输入（诚实）
    mixed_q = ("对比一下 qwen-max 和 deepseek-chat 在这份 200 行 CSV 上的处理速度，"
               "重点看 throughput 和 latency。" * 2)
    est7 = HeuristicCounter().estimate_exchange(
        {"messages": [{"role": "user", "content": mixed_q}]},
        _resp("qwen-max 吞吐更高，deepseek-chat 延迟更低。"), "qwen-plus")
    usage7 = {"prompt_tokens": (est7.input_lo + est7.input_hi) // 2,
              "completion_tokens": (est7.output_lo + est7.output_hi) // 2}
    for i, ts in enumerate(_T[6:]):
        led.append("chat_completion", ts=ts, model="qwen-plus",
                   request_id=f"demo-ok-{i + 4}", meta=dict(meta),
                   usage=dict(usage7),
                   data={"request": {"model": "qwen-plus", "messages": [
                       {"role": "user", "content": mixed_q}]},
                       "response": _resp("qwen-max 吞吐更高，deepseek-chat 延迟更低。")})

    # 用 CLI 真跑一次 statement（heuristic：与是否安装 tiktoken 无关，跨环境一致）
    rc = cli_main([
        "statement", "docs/demo_ledger.jsonl",
        "-o", "docs/statement_example.md",
        "--json-out", "docs/statement_example.json",
        "--strategy", "heuristic",
    ])
    print(f"exit={rc}；已写入 docs/demo_ledger.jsonl / statement_example.md / "
          "statement_example.json")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
