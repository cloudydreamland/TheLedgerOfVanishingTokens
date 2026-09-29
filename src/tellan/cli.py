"""cli.py — argparse 子命令入口。

子命令：audit / verify / report / statement / proxy / import / warmup / bench。
退出码约定：0 正常；1 有疑点（裁决 SUSPECT_* 或 error 级异常、导入有跳过行、
预热有 encoding 失败）；2 链损坏 / 输入不可读。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import AdapterError, import_to_ledger
from .bench import render_bench_markdown, run_bench
from .capture import CaptureProxy
from .ledger import Ledger
from .prices import SNAPSHOT_NOTE
from .reconcile import reconcile_ledger
from .report import render_json, render_markdown
from .statement import build_statement, render_statement_json, render_statement_markdown

EXIT_OK = 0
EXIT_SUSPECT = 1
EXIT_CHAIN_BROKEN = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tellan",
        description="Tellan — LLM API 账单对账与计量审计标准件",
    )
    parser.add_argument("--version", action="version", version=f"tellan {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="对账一本 JSONL 账本（先验链再裁决）")
    p_audit.add_argument("ledger", help="JSONL 账本路径")
    p_audit.add_argument("--strategy", choices=["auto", "heuristic", "tiktoken"],
                         default="auto", help="复算策略（默认 auto）")
    p_audit.add_argument("--tolerance", type=float, default=0.25,
                         help="输出侧容差（报数<=hi*(1+tol) 为 OK，默认 0.25）")
    p_audit.add_argument("--json", action="store_true", help="输出 JSON 汇总")

    p_verify = sub.add_parser("verify", help="只校验哈希链完整性")
    p_verify.add_argument("ledger", help="JSONL 账本路径")

    p_report = sub.add_parser("report", help="生成 Markdown/JSON 对账报告")
    p_report.add_argument("ledger", help="JSONL 账本路径")
    p_report.add_argument("-o", "--output", required=True, help="输出文件路径")
    p_report.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    p_report.add_argument("--strategy", choices=["auto", "heuristic", "tiktoken"],
                          default="auto")

    p_statement = sub.add_parser(
        "statement", help="生成一页对账声明（Markdown + JSON，可发给对方复核）"
    )
    p_statement.add_argument("ledger", help="JSONL 账本路径")
    p_statement.add_argument("-o", "--output", default=None,
                             help="Markdown 输出路径（缺省打印到 stdout）")
    p_statement.add_argument("--json-out", default=None, help="JSON 声明输出路径")
    p_statement.add_argument("--strategy", choices=["auto", "heuristic", "tiktoken"],
                             default="auto")
    p_statement.add_argument("--tolerance", type=float, default=0.25,
                             help="输出侧容差（0.25 → 上沿 1.25，默认 0.25）")

    p_proxy = sub.add_parser("proxy", help="启动本地捕获代理（阻塞运行）")
    p_proxy.add_argument("--port", type=int, default=8317)
    p_proxy.add_argument("--upstream", required=True, help="上游 base URL，如 "
                        "https://api.deepseek.com")
    p_proxy.add_argument("--ledger", required=True, help="账本 JSONL 路径")
    p_proxy.add_argument("--no-redact", action="store_true",
                         help="存原文（默认最小化留存：只存长度+哈希前缀）")

    p_import = sub.add_parser("import", help="导入 new-api/one-api 账目导出（JSONL/CSV）入账本")
    p_import.add_argument("export", help="导出文件路径（.json/.jsonl/.csv）")
    p_import.add_argument("-l", "--ledger", required=True, help="目标账本 JSONL 路径")
    p_import.add_argument("--format", choices=["auto", "jsonl", "csv"], default="auto")
    p_import.add_argument("--source", choices=["auto", "newapi", "oneapi", "custom"],
                          default="auto", help="导出来源（决定字段语义标注）")
    p_import.add_argument("--provider", default=None,
                          help="账本 provider 标注（默认 newapi-export 等）")
    p_import.add_argument("--quota-per-unit", type=float, default=None,
                          help="站内点数→美元换算基数（默认 500000=$1，按部署实配覆盖）")
    p_import.add_argument("--mapping", default=None,
                          help="自定义列映射 JSON：{\"规范字段\": [\"别名\", ...]}（与内置合并）")
    p_import.add_argument("--json", action="store_true", help="输出 JSON 摘要")

    p_warmup = sub.add_parser("warmup", help="预热 tiktoken encoding 缓存（离线 CI 先在有网步骤跑）")
    p_warmup.add_argument("--encoding", action="append", default=None,
                          help="只预热指定 encoding（可多次；默认按覆盖清单全量）")

    sub.add_parser("bench", help="运行内置 fixture 基准（离线）")
    return parser


def _has_serious_anomaly(summary: dict[str, Any]) -> bool:
    """error 级异常或任何 SUSPECT_* 裁决都算“有疑点”。"""
    for v in summary.get("verdicts", []):
        if v["verdict"]["status"].startswith("SUSPECT"):
            return True
        if any(a["severity"] == "error" for a in v["verdict"]["anomalies"]):
            return True
    return False


def cmd_audit(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    ok, bad_seq = ledger.verify()
    if not ok:
        print(f"链损坏：首个坏记录 seq={bad_seq}，audit 拒绝对被篡改账本裁决。",
              file=sys.stderr)
        return EXIT_CHAIN_BROKEN
    records = ledger.records()
    summary = reconcile_ledger(records, strategy=args.strategy,
                               tolerance_hi=1.0 + args.tolerance)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_audit_human(summary, args.ledger, bad_seq)
    return EXIT_SUSPECT if _has_serious_anomaly(summary) else EXIT_OK


def _print_audit_human(summary: dict[str, Any], path: str, bad_seq: int | None) -> None:
    print(f"账本 {path}：{summary['n_records']} 条记录，链完整。")
    status = summary["status_counts"]
    print("裁决：" + ("，".join(f"{k} {v}" for k, v in sorted(status.items()))
                     or "无记录"))
    totals = summary["totals_reported"]
    print(f"报数总量：input {totals['prompt_tokens']} / "
          f"output {totals['completion_tokens']}")
    est = summary.get("totals_estimated")
    if est:
        print(f"复算区间：input {est['input']} / output {est['output']}")
    print(f"费用报数合计：{summary['cost_reported_total']}；"
          f"复算费用区间：{summary['cost_estimated_total_range']}")
    if summary["anomaly_counts"]:
        print("异常：" + "，".join(f"{k}×{v}" for k, v in
                                   sorted(summary["anomaly_counts"].items())))
    else:
        print("异常：无")
    print(f"（价格来源：{SNAPSHOT_NOTE}）")


def cmd_verify(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    ok, bad_seq = ledger.verify()
    n = len(ledger)
    if ok:
        print(f"OK：{n} 条记录，哈希链完整。")
        return EXIT_OK
    print(f"FAIL：哈希链在 seq={bad_seq} 处损坏。账本被篡改或截断。", file=sys.stderr)
    return EXIT_CHAIN_BROKEN


def cmd_report(args: argparse.Namespace) -> str:
    ledger = Ledger(args.ledger)
    ok, bad_seq = ledger.verify()
    if not ok:
        print(f"链损坏（seq={bad_seq}），报告仍会生成，但请先处理完整性问题。",
              file=sys.stderr)
    summary = reconcile_ledger(ledger.records(), strategy=args.strategy)
    content = render_json(summary) if args.json else render_markdown(summary)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"报告已写入 {out}（{summary['n_records']} 条记录）")
    return EXIT_OK if not _has_serious_anomaly(summary) else EXIT_SUSPECT


def cmd_statement(args: argparse.Namespace) -> int:
    if not Path(args.ledger).exists():
        print(f"账本不存在：{args.ledger}", file=sys.stderr)
        return EXIT_CHAIN_BROKEN
    ledger = Ledger(args.ledger)
    ok, bad_seq = ledger.verify()
    if not ok:
        print(f"链损坏（首个坏记录 seq={bad_seq}）：声明拒绝出具——"
              "对被篡改账本出声明没有意义。先处理完整性问题。",
              file=sys.stderr)
        return EXIT_CHAIN_BROKEN
    records = ledger.records()
    summary = reconcile_ledger(records, strategy=args.strategy,
                               tolerance_hi=1.0 + args.tolerance)
    st = build_statement(args.ledger, records, summary, strategy=args.strategy,
                         tolerance_hi=1.0 + args.tolerance)
    md = render_statement_markdown(st)
    written: list[str] = []
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
        written.append(str(out))
    if args.json_out:
        jout = Path(args.json_out)
        jout.parent.mkdir(parents=True, exist_ok=True)
        with open(jout, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_statement_json(st))
        written.append(str(jout))
    if not written:
        print(md)
    else:
        n_disputed = len(st["disputed"])
        print(f"声明已写入 {'、'.join(written)}；被质疑条目 {n_disputed} 条；"
              f"声明哈希 statement_sha256={st['statement_sha256']}")
    return EXIT_SUSPECT if _has_serious_anomaly(summary) else EXIT_OK


def cmd_proxy(args: argparse.Namespace) -> int:
    ledger = Ledger(args.ledger)
    proxy = CaptureProxy(args.upstream, ledger, redact=not args.no_redact,
                         port=args.port)
    proxy.start()
    mode = "记录原文（--no-redact）" if args.no_redact else "脱敏模式（默认）"
    print(f"tellan proxy 监听 {proxy.base_url} → {args.upstream}；账本 "
          f"{args.ledger}；{mode}。Ctrl+C 停止。")
    try:
        proxy._server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        proxy.shutdown()
    return EXIT_OK


def cmd_import(args: argparse.Namespace) -> int:
    mapping = None
    if args.mapping:
        try:
            mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"映射文件不可读：{exc}", file=sys.stderr)
            return EXIT_CHAIN_BROKEN
    kwargs: dict[str, Any] = {
        "fmt": args.format,
        "source": args.source,
        "provider": args.provider,
    }
    if args.quota_per_unit is not None:
        kwargs["quota_per_unit"] = args.quota_per_unit
    ledger = Ledger(args.ledger)
    try:
        summary = import_to_ledger(ledger, args.export, mapping=mapping, **kwargs)
    except AdapterError as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return EXIT_CHAIN_BROKEN
    if args.json:
        print(json.dumps({k: v for k, v in summary.items() if k != "records"},
                         ensure_ascii=False, indent=2))
    else:
        print(f"导入 {summary['rows']} 行：入账 {len(summary['records'])} 条，"
              f"跳过 {len(summary['skipped'])} 条（格式 {summary['source_format']}，"
              f"来源 {summary['detected_source']}）。")
        for s in summary["skipped"][:10]:
            print(f"  跳过 L{s['line']}：{s['reason']}")
        if len(summary["skipped"]) > 10:
            print(f"  ……其余 {len(summary['skipped']) - 10} 条跳过略")
        print(f"账本：{args.ledger}")
    return EXIT_SUSPECT if summary["skipped"] else EXIT_OK


def cmd_warmup(args: argparse.Namespace) -> int:
    from .recount import TiktokenUnavailable, warmup_tiktoken

    try:
        result = warmup_tiktoken(encodings=args.encoding)
    except TiktokenUnavailable as exc:
        print(f"预热失败：{exc}", file=sys.stderr)
        return EXIT_CHAIN_BROKEN
    for name, status in result["encodings"].items():
        print(f"  {name}: {status}")
    print(f"缓存目录可用环境变量 {result['cache_dir_env']} 重定向"
          "（离线 CI：有网步骤预热 → 缓存该目录 → 离线步骤挂回）。")
    return EXIT_OK if result["ok"] else EXIT_SUSPECT


def cmd_bench(_args: argparse.Namespace) -> int:
    metrics = run_bench()
    print(render_bench_markdown(metrics))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "audit": cmd_audit,
        "verify": cmd_verify,
        "report": cmd_report,
        "statement": cmd_statement,
        "proxy": cmd_proxy,
        "import": cmd_import,
        "warmup": cmd_warmup,
        "bench": cmd_bench,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
