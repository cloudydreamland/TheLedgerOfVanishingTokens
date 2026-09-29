"""adapters.newapi 测试：字段映射、脏数据处理、类型过滤、入账链完整性。

字段表依据：new-api / one-api main 分支 ``model/log.go`` 的 Log 结构体
（2026-09-28 实抓）。fixture 按真实 JSON 键构造。
"""

from __future__ import annotations

import json

import pytest

from tellan.adapters import AdapterError, load_export
from tellan.adapters.newapi import (
    DEFAULT_QUOTA_PER_UNIT,
    _coerce_int,
    _norm_ts,
    _synth_request_id,
    import_to_ledger,
)
from tellan.cli import main
from tellan.ledger import Ledger

# ------------------------------------------------------------- new-api JSONL


def _newapi_row(**over: object) -> dict:
    row = {
        "id": 101,
        "user_id": 7,
        "created_at": 1759000000,
        "type": 2,
        "content": "模型倍率 1.0000，分组倍率 1.0000，提示 100，补全 50",
        "username": "alice",
        "token_name": "my-token",
        "model_name": "deepseek-chat",
        "quota": 1500,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "use_time": 3,
        "is_stream": True,
        "channel": 2,
        "channel_name": "中转A",
        "token_id": 9,
        "group": "default",
        "ip": "1.2.3.4",
        "request_id": "req-abc-1",
        "upstream_request_id": "chatcmpl-up-42",
        "other": "{\"frt\": 233}",
    }
    row.update(over)
    return row


def _write_jsonl(tmp_path, rows: list[dict]) -> object:
    p = tmp_path / "export.jsonl"
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return p


def test_newapi_consume_row_maps_fully(tmp_path):
    p = _write_jsonl(tmp_path, [_newapi_row()])
    s = load_export(p)
    assert s["detected_source"] == "newapi"
    assert len(s["records"]) == 1 and not s["skipped"]
    rec = s["records"][0]
    assert rec["kind"] == "chat_completion"
    assert rec["model"] == "deepseek-chat"
    assert rec["request_id"] == "req-abc-1"
    assert rec["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    meta = rec["meta"]
    assert meta["source_export"] == "newapi"
    assert meta["upstream_request_id"] == "chatcmpl-up-42"
    assert meta["quota_usd_est"] == round(1500 / DEFAULT_QUOTA_PER_UNIT, 6)
    assert meta["is_stream"] is True
    assert meta["content_desc"].startswith("模型倍率")
    assert rec["ts"] is not None and meta.get("ts_missing") is None


def test_non_consume_rows_skipped_with_reason(tmp_path):
    p = _write_jsonl(tmp_path, [
        _newapi_row(type=1),   # topup
        _newapi_row(type=5),   # error
        _newapi_row(type=6),   # refund
        _newapi_row(),         # consume，正常入账
    ])
    s = load_export(p)
    assert len(s["records"]) == 1
    assert len(s["skipped"]) == 3
    assert all("非消费行" in x["reason"] for x in s["skipped"])


def test_missing_request_id_synthesized_stable(tmp_path):
    # 字节级相同的行 → 相同合成 id（确定性语义：重复导出行天然可对齐）
    assert _synth_request_id({"a": 1}) == _synth_request_id({"a": 1})
    assert _synth_request_id({"a": 1}) != _synth_request_id({"a": 2})
    s = load_export(_write_jsonl(tmp_path, [
        _newapi_row(request_id=""),
        _newapi_row(request_id="", quota=9999),  # 内容不同 → id 必须不同
    ]))
    assert len(s["records"]) == 2
    ids = [r["request_id"] for r in s["records"]]
    assert all(i.startswith("imp-") for i in ids)
    assert len(set(ids)) == 2, "内容不同的行必须得到不同合成 id"
    assert all(r["meta"]["request_id_synth"] for r in s["records"])


def test_dirty_usage_strings_and_thousands(tmp_path):
    p = _write_jsonl(tmp_path, [
        _newapi_row(prompt_tokens=" 200 ", completion_tokens="1,234"),
        _newapi_row(prompt_tokens="12.0", completion_tokens=0),
        _newapi_row(prompt_tokens="abc", completion_tokens=1),
    ])
    s = load_export(p)
    assert len(s["records"]) == 2
    assert s["records"][0]["usage"] == {"prompt_tokens": 200, "completion_tokens": 1234}
    assert s["records"][1]["usage"] == {"prompt_tokens": 12, "completion_tokens": 0}
    assert len(s["skipped"]) == 1 and "解析失败" in s["skipped"][0]["reason"]


def test_timestamp_seconds_ms_and_iso(tmp_path):
    assert _norm_ts(1759000000) == _norm_ts(1759000000000)
    assert _norm_ts("1759000000") == _norm_ts(1759000000)
    iso = _norm_ts("2025-09-28 12:00:00")  # naive 视为 UTC
    assert iso is not None and iso.startswith("2025-09-28T12:00:00.000+00:00")
    p = _write_jsonl(tmp_path, [
        _newapi_row(created_at=1759000000),
        _newapi_row(created_at=1759000000000),
        _newapi_row(created_at="2025-09-28T12:00:00Z"),
    ])
    s = load_export(p)
    ts_list = [r["ts"] for r in s["records"]]
    assert ts_list[0] == ts_list[1]
    assert all(t.startswith("20") for t in ts_list)


def test_oneapi_row_detected_and_mapped(tmp_path):
    row = {
        "id": 5, "user_id": 1, "created_at": 1759000000, "type": 2,
        "content": "使用 $0.0021", "username": "bob", "token_name": "t",
        "model_name": "gpt-4o", "quota": 1050, "prompt_tokens": 10,
        "completion_tokens": 20, "channel": 1, "request_id": "r-9",
        "elapsed_time": 1500, "is_stream": False, "system_prompt_reset": False,
    }
    s = load_export(_write_jsonl(tmp_path, [row]))
    assert s["detected_source"] == "oneapi"
    rec = s["records"][0]
    assert rec["meta"]["source_export"] == "oneapi"
    assert rec["meta"]["use_time"] == 1500  # one-api 毫秒，原样保留不换算
    assert rec["provider"] == "oneapi-export"


def test_missing_model_skipped(tmp_path):
    p = _write_jsonl(tmp_path, [_newapi_row(model_name="")])
    s = load_export(p)
    assert not s["records"] and "缺模型名" in s["skipped"][0]["reason"]


# ---------------------------------------------------------------------- CSV


def test_csv_chinese_headers_bom_and_thousands(tmp_path):
    p = tmp_path / "export.csv"
    p.write_text(
        "\ufeff模型名称,提示 tokens,补全 tokens,时间,额度,请求ID,类型\n"
        "glm-4.6,\"1,000\",\"2,500\",2025-09-27T10:00:00Z,700,req-csv-1,消费\n",
        encoding="utf-8",
    )
    s = load_export(p)
    assert s["source_format"] == "csv"
    assert len(s["records"]) == 1
    rec = s["records"][0]
    assert rec["model"] == "glm-4.6"
    assert rec["usage"] == {"prompt_tokens": 1000, "completion_tokens": 2500}
    assert rec["ts"].startswith("2025-09-27T10:00:00")
    assert rec["meta"]["quota"] == 700


def test_csv_type_column_chinese_word(tmp_path):
    """CSV 里类型常是中文词（"消费"）——宽容入账，原文留痕到 meta.type_raw。

    只对**可解析为数字且 ≠2** 的类型跳过（充值/错误/退款行）。
    """
    p = tmp_path / "export.csv"
    p.write_text(
        "模型名称,提示tokens,补全tokens,时间,额度,类型\n"
        "glm-4.6,10,5,1759000000,30,消费\n",
        encoding="utf-8",
    )
    s = load_export(p)
    assert len(s["records"]) == 1
    assert s["records"][0]["meta"]["type_raw"] == "消费"


def test_custom_mapping_merge(tmp_path):
    p = tmp_path / "custom.csv"
    p.write_text(
        "input_tokens,output_tokens,model,quota\n500,30,moonshot-v1,80\n",
        encoding="utf-8",
    )
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps({"prompt_tokens": ["input_tokens"],
                    "completion_tokens": ["output_tokens"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    s_no_map = load_export(p)
    assert not s_no_map["records"]  # 没映射时无法识别
    s = load_export(p, mapping=json.loads(mapping_path.read_text(encoding="utf-8")))
    assert s["records"][0]["usage"] == {"prompt_tokens": 500, "completion_tokens": 30}


def test_quota_per_unit_override(tmp_path):
    p = _write_jsonl(tmp_path, [_newapi_row(quota=1000)])
    s = load_export(p, quota_per_unit=1000.0)
    assert s["records"][0]["meta"]["quota_usd_est"] == 1.0


# ------------------------------------------------------------------- 入账与链


def test_import_to_ledger_preserves_ts_and_chain(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    led = Ledger(ledger_path)
    led.append("chat_completion", model="m", usage={"prompt_tokens": 1})
    p = _write_jsonl(tmp_path, [_newapi_row()])
    s = import_to_ledger(led, p)
    assert len(s["records"]) == 1
    ok, bad = Ledger(ledger_path).verify()
    assert ok and bad is None
    records = Ledger(ledger_path).records()
    assert records[1]["meta"]["imported"] is True
    assert records[1]["ts"] is not None  # 原始 ts 归一化后入账


def test_adapter_error_missing_file(tmp_path):
    with pytest.raises(AdapterError):
        load_export(tmp_path / "nope.jsonl")


def test_adapter_error_empty_file(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("\n\n", encoding="utf-8")
    with pytest.raises(AdapterError):
        load_export(p)


# ---------------------------------------------------------------------- CLI


def test_cli_import_exit_0_and_verify(tmp_path, capsys):
    p = _write_jsonl(tmp_path, [_newapi_row()])
    led = tmp_path / "led.jsonl"
    rc = main(["import", str(p), "-l", str(led), "--json"])
    assert rc == 0
    assert main(["verify", str(led)]) == 0


def test_cli_import_with_skips_exit_1(tmp_path):
    p = _write_jsonl(tmp_path, [_newapi_row(type=1), _newapi_row()])
    rc = main(["import", str(p), "-l", str(tmp_path / "led.jsonl")])
    assert rc == 1


def test_cli_import_bad_file_exit_2(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("not json\n", encoding="utf-8")
    rc = main(["import", str(p), "--format", "jsonl",
               "-l", str(tmp_path / "led.jsonl")])
    assert rc == 2


def test_cli_import_missing_mapping_file_exit_2(tmp_path):
    p = _write_jsonl(tmp_path, [_newapi_row()])
    rc = main(["import", str(p), "-l", str(tmp_path / "led.jsonl"),
               "--mapping", str(tmp_path / "nope.json")])
    assert rc == 2


# ------------------------------------------------------------------ 工具函数


def test_coerce_int_rejects_garbage():
    with pytest.raises(ValueError):
        _coerce_int("abc")
    assert _coerce_int(None) is None
    assert _coerce_int("") is None
    assert _coerce_int("，1，234，") == 1234  # 全角逗号
