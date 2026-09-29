"""statement.py 测试：声明构建、确定性哈希、渲染分节与 CLI 退出码。"""

import hashlib
import json

from tellan import __version__
from tellan.cli import main
from tellan.ledger import Ledger, canonical_json
from tellan.reconcile import reconcile_ledger
from tellan.recount import HeuristicCounter
from tellan.statement import (
    build_statement,
    render_statement_json,
    render_statement_markdown,
)

MODEL = "deepseek-chat"
_ZH = "用于声明测试的中文请求文本，长度适中。" * 3
_REPLY = "这是助手回复内容。"


def _mid_usage() -> dict:
    est = HeuristicCounter().estimate_exchange(
        {"messages": [{"role": "user", "content": _ZH}]},
        {"choices": [{"message": {"role": "assistant", "content": _REPLY}}]}, MODEL)
    return {"prompt_tokens": (est.input_lo + est.input_hi) // 2,
            "completion_tokens": (est.output_lo + est.output_hi) // 2}


def _append_exchange(led: Ledger, *, usage: dict, model: str = MODEL,
                     rid: str | None = None, content: str | None = _REPLY) -> None:
    led.append("chat_completion", model=model, request_id=rid, usage=usage,
               data={"request": {"model": model,
                                 "messages": [{"role": "user", "content": _ZH}]},
                     "response": {"choices": [{"message": {"role": "assistant",
                                                           "content": content}}]}})


def _make_ledger(path, *, n_honest: int = 2, inflated: bool = False,
                 empty_content: bool = False, unknown_model: bool = False) -> Ledger:
    led = Ledger(path)
    for i in range(n_honest):
        _append_exchange(led, usage=_mid_usage(), rid=f"ok-{i}")
    if inflated:
        u = _mid_usage()
        _append_exchange(led, rid="bad-inflate",
                         usage={"prompt_tokens": u["prompt_tokens"],
                                "completion_tokens": u["completion_tokens"] * 100})
    if empty_content:
        _append_exchange(led, rid="bad-null", content=None,
                         usage={"prompt_tokens": 50, "completion_tokens": 345})
    if unknown_model:
        _append_exchange(led, usage=_mid_usage(), model="mystery-model-x", rid="pm-1")
    return led


def _statement_for(path, **kwargs):
    led = Ledger(path)
    records = led.records()
    summary = reconcile_ledger(records, **kwargs)
    return build_statement(path, records, summary, **kwargs)


# ------------------------------------------------------------------ build


def test_disputed_lists_inflation_and_empty_content(tmp_path):
    path = tmp_path / "l.jsonl"
    _make_ledger(path, inflated=True, empty_content=True)
    st = _statement_for(path)
    statuses = [d["status"] for d in st["disputed"]]
    assert "SUSPECT_INFLATED" in statuses
    codes = {a["code"] for d in st["disputed"] for a in d["anomalies"]}
    assert {"TOKEN_INFLATION", "EMPTY_CONTENT_BILLED"} <= codes


def test_disputed_record_hash_matches_ledger(tmp_path):
    path = tmp_path / "l.jsonl"
    _make_ledger(path, inflated=True)
    st = _statement_for(path)
    real = {r["seq"]: r["hash"] for r in Ledger(path).records()}
    for d in st["disputed"]:
        assert d["record_hash"] == real[d["seq"]]
        assert len(d["record_hash"]) == 64


def test_statement_sha256_excludes_path_and_repro(tmp_path):
    """同一账本内容放不同路径：声明哈希必须一致（路径不参与哈希）。"""
    p1 = tmp_path / "a" / "l.jsonl"
    _make_ledger(p1, inflated=True)
    p2 = tmp_path / "b" / "other.ledger"
    p2.parent.mkdir(parents=True)
    p2.write_bytes(p1.read_bytes())  # 逐字节复制：同内容，不同路径
    st1 = _statement_for(p1)
    st2 = _statement_for(p2)
    assert st1["statement_sha256"] == st2["statement_sha256"]
    # 且哈希可由声明体自证（排除 statement_sha256 与 reproduction 两个装配字段）
    body = {k: v for k, v in st1.items()
            if k not in ("statement_sha256", "reproduction")}
    assert st1["statement_sha256"] == hashlib.sha256(
        canonical_json(body).encode("utf-8")).hexdigest()


def test_parameters_and_price_meta_recorded(tmp_path):
    path = tmp_path / "l.jsonl"
    _make_ledger(path)
    st = _statement_for(path, strategy="heuristic", tolerance_hi=1.25)
    assert st["parameters"]["strategy"] == "heuristic"
    assert st["parameters"]["tolerance_hi_factor"] == 1.25
    assert st["parameters"]["price_table"]["as_of"] == "2025-10-01"
    assert "快照估值" in st["parameters"]["price_table"]["source_note"]


def test_empty_ledger_statement(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.touch()
    st = _statement_for(path)
    assert st["ledger"]["n_records"] == 0
    assert st["ledger"]["chain_head"] is None
    assert st["disputed"] == []


# ------------------------------------------------------------------ render


def test_markdown_contains_all_sections(tmp_path):
    path = tmp_path / "l.jsonl"
    _make_ledger(path, inflated=True, empty_content=True, unknown_model=True)
    st = _statement_for(path)
    md = render_statement_markdown(st)
    for section in ("# tellan 对账声明", "## 账本与完整性", "## 结论一览",
                    "## 被质疑条目", "## 对账规则与数据来源", "## 复现",
                    "## 边界与局限"):
        assert section in md
    assert "bad-inflate" in md or "SUSPECT_INFLATED" in md
    assert "EMPTY_CONTENT_BILLED" in md
    assert "PRICE_MISSING" in md and "未计入" in md  # 缺价不静默按 0
    assert f"pip install tellan=={__version__}" in md
    assert "tellan statement" in md
    assert st["statement_sha256"] in md


def test_markdown_clean_ledger_no_disputed(tmp_path):
    path = tmp_path / "l.jsonl"
    _make_ledger(path)
    md = render_statement_markdown(_statement_for(path))
    assert "无被质疑条目" in md


def test_json_roundtrip(tmp_path):
    path = tmp_path / "l.jsonl"
    _make_ledger(path, inflated=True)
    st = json.loads(render_statement_json(_statement_for(path)))
    assert st["ledger"]["file_sha256"] == hashlib.sha256(
        path.read_bytes()).hexdigest()
    assert len(st["disputed"]) == 1
    assert st["reproduction"][-1].startswith("# 重跑得到的 statement_sha256")


# --------------------------------------------------------------------- CLI


def test_cli_statement_writes_files_and_exit_codes(tmp_path):
    clean = tmp_path / "clean.jsonl"
    _make_ledger(clean)
    md_out, json_out = tmp_path / "s.md", tmp_path / "s.json"
    assert main(["statement", str(clean), "-o", str(md_out),
                 "--json-out", str(json_out)]) == 0
    assert md_out.exists() and json_out.exists()

    bad = tmp_path / "bad.jsonl"
    _make_ledger(bad, inflated=True)
    assert main(["statement", str(bad), "-o", str(tmp_path / "bad.md")]) == 1


def test_cli_statement_deterministic_bytes(tmp_path, capsys):
    """同账本同参数跑两遍：Markdown 逐字节一致，statement_sha256 一致。"""
    path = tmp_path / "l.jsonl"
    _make_ledger(path, inflated=True)
    out1, out2 = tmp_path / "s1.md", tmp_path / "s2.md"
    assert main(["statement", str(path), "-o", str(out1),
                 "--json-out", str(tmp_path / "s1.json")]) == 1
    assert main(["statement", str(path), "-o", str(out2),
                 "--json-out", str(tmp_path / "s2.json")]) == 1
    assert out1.read_bytes() == out2.read_bytes()
    assert (tmp_path / "s1.json").read_bytes() == (tmp_path / "s2.json").read_bytes()
    assert "statement_sha256=" in capsys.readouterr().out


def test_cli_statement_stdout_without_output(tmp_path, capsys):
    path = tmp_path / "l.jsonl"
    _make_ledger(path)
    assert main(["statement", str(path)]) == 0
    assert "# tellan 对账声明" in capsys.readouterr().out


def test_cli_statement_refuses_broken_chain(tmp_path, capsys):
    path = tmp_path / "l.jsonl"
    _make_ledger(path, inflated=True)
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["usage"]["prompt_tokens"] = 1
    lines[0] = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "s.md"
    assert main(["statement", str(path), "-o", str(out)]) == 2
    assert out.exists() is False
    assert "拒绝出具" in capsys.readouterr().err


def test_cli_statement_refuses_missing_ledger(tmp_path, capsys):
    assert main(["statement", str(tmp_path / "nope.jsonl")]) == 2
    assert "不存在" in capsys.readouterr().err
