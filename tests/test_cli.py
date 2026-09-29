"""cli.py 测试：子命令 smoke 与退出码约定（0 正常 / 1 疑点 / 2 链损坏）。"""

import json

import pytest

from tellan.cli import main
from tellan.ledger import Ledger
from tellan.recount import HeuristicCounter

MODEL = "deepseek-chat"
_ZH = "用于 CLI 冒烟测试的中文请求，长度适中。" * 4
_REPLY = "这是助手回复内容。"


def _build_ledger(path, *, usage: dict | None = None) -> None:
    led = Ledger(path)
    if usage is None:
        est = HeuristicCounter().estimate_exchange(
            {"messages": [{"role": "user", "content": _ZH}]},
            {"choices": [{"message": {"role": "assistant", "content": _REPLY}}]},
            MODEL,
        )
        usage = {"prompt_tokens": (est.input_lo + est.input_hi) // 2,
                 "completion_tokens": (est.output_lo + est.output_hi) // 2}
    led.append("chat_completion", model=MODEL, request_id="r1", usage=usage,
               data={"request": {"model": MODEL,
                                 "messages": [{"role": "user", "content": _ZH}]},
                     "response": {"choices": [{"message": {"role": "assistant",
                                                           "content": _RETRY_REPLY()}}]}})


def _RETRY_REPLY() -> str:
    return _REPLY


# -------------------------------------------------------------------- verify


def test_verify_ok_exit_0(tmp_path, capsys):
    path = tmp_path / "l.jsonl"
    _build_ledger(path)
    assert main(["verify", str(path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_verify_broken_exit_2(tmp_path, capsys):
    path = tmp_path / "l.jsonl"
    _build_ledger(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["usage"]["prompt_tokens"] = 999999
    lines[0] = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["verify", str(path)]) == 2
    assert "seq=1" in capsys.readouterr().err


# --------------------------------------------------------------------- audit


def test_audit_clean_exit_0(tmp_path, capsys):
    path = tmp_path / "l.jsonl"
    _build_ledger(path)
    assert main(["audit", str(path)]) == 0
    out = capsys.readouterr().out
    assert "OK 1" in out


def test_audit_suspect_exit_1(tmp_path):
    path = tmp_path / "l.jsonl"
    est = HeuristicCounter().estimate_exchange(
        {"messages": [{"role": "user", "content": _ZH}]},
        {"choices": [{"message": {"content": _REPLY}}]}, MODEL)
    usage = {"prompt_tokens": est.input_lo,
             "completion_tokens": est.input_hi * 100}  # 明显膨胀
    _build_ledger(path, usage=usage)
    assert main(["audit", str(path)]) == 1


def test_audit_tampered_exit_2(tmp_path):
    path = tmp_path / "l.jsonl"
    _build_ledger(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("deepseek", "fakeseek", 1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["audit", str(path)]) == 2


def test_audit_json_output(tmp_path, capsys):
    path = tmp_path / "l.jsonl"
    _build_ledger(path)
    assert main(["audit", str(path), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["n_records"] == 1
    assert summary["status_counts"].get("OK") == 1


def test_audit_empty_ledger_exit_0(tmp_path, capsys):
    path = tmp_path / "empty.jsonl"
    assert main(["audit", str(path)]) == 0
    assert "0 条记录" in capsys.readouterr().out


def test_audit_tolerance_flag(tmp_path):
    path = tmp_path / "l.jsonl"
    est = HeuristicCounter().estimate_exchange(
        {"messages": [{"role": "user", "content": _ZH}]},
        {"choices": [{"message": {"content": _REPLY}}]}, MODEL)
    usage = {"prompt_tokens": est.input_hi + 1,
             "completion_tokens": (est.output_lo + est.output_hi) // 2}
    _build_ledger(path, usage=usage)
    strict = main(["audit", str(path), "--json"])
    loose = main(["audit", str(path), "--json", "--tolerance", "0.5"])
    assert (strict, loose) in ((0, 0), (1, 0))


# -------------------------------------------------------------------- report


def test_report_writes_markdown(tmp_path, capsys):
    path = tmp_path / "l.jsonl"
    _build_ledger(path)
    out = tmp_path / "report.md"
    assert main(["report", str(path), "-o", str(out)]) == 0
    content = out.read_text(encoding="utf-8")
    assert content.startswith("# tellan 对账报告")
    assert "deepseek-chat" in content


def test_report_json_format(tmp_path):
    path = tmp_path / "l.jsonl"
    _build_ledger(path)
    out = tmp_path / "report.json"
    assert main(["report", str(path), "-o", str(out), "--json"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "n_records" in data


# --------------------------------------------------------------------- bench


def test_bench_command_smoke(capsys):
    assert main(["bench"]) == 0
    out = capsys.readouterr().out
    assert "汇总指标" in out and "fixture" in out


# ------------------------------------------------------------------- version


def test_version_flag():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
