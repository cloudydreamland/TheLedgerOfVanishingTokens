"""ledger.py 测试：哈希链、篡改检测、genesis、并发与性能 smoke。"""

import json
import threading
import time

import pytest

from tellan.ledger import GENESIS_PREV_HASH, Ledger, canonical_json, compute_hash


@pytest.fixture()
def ledger_path(tmp_path):
    return tmp_path / "ledger.jsonl"


def test_genesis_prev_hash(ledger_path):
    led = Ledger(ledger_path)
    rec = led.append("chat")
    assert rec["prev_hash"] == GENESIS_PREV_HASH == "0" * 64


def test_record_fields_complete(ledger_path):
    rec = Ledger(ledger_path).append(
        "chat", model="deepseek-chat", provider="https://api.deepseek.com",
        request_id="rid-1", usage={"prompt_tokens": 1},
        meta={"stream": False}, data={"request": {}},
    )
    for key in ("seq", "ts", "kind", "model", "provider", "request_id",
                "usage", "meta", "data", "prev_hash", "hash"):
        assert key in rec


def test_hash_is_sha256_of_prev_plus_canonical(ledger_path):
    led = Ledger(ledger_path)
    rec = led.append("chat", model="m", data={"x": "中"})
    payload = {k: rec[k] for k in
               ("seq", "ts", "kind", "model", "provider", "request_id",
                "usage", "meta", "data")}
    assert rec["hash"] == compute_hash(rec["prev_hash"], payload)


def test_canonical_json_keeps_unicode_and_sorts():
    s = canonical_json({"b": 1, "a": "中文"})
    assert s == '{"a":"中文","b":1}'


def test_verify_ok_after_multiple_appends(ledger_path):
    led = Ledger(ledger_path)
    for i in range(5):
        led.append("chat", model=f"m{i}")
    assert led.verify() == (True, None)
    assert len(led) == 5


def test_verify_empty_ledger_ok(ledger_path):
    assert Ledger(ledger_path).verify() == (True, None)


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _flip_middle_field(ledger_path, field, mutate):
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2])
    mutate(rec, field)
    lines[2] = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_tamper_data_detected_at_seq(ledger_path):
    led = Ledger(ledger_path)
    for i in range(5):
        led.append("chat", model=f"m{i}", data={"i": i})
    _flip_middle_field(ledger_path, "data", lambda r, f: r[f].update(i=999))
    ok, bad = led.verify()
    assert ok is False and bad == 3


def test_tamper_usage_detected(ledger_path):
    led = Ledger(ledger_path)
    for i in range(5):
        led.append("chat", usage={"prompt_tokens": 10})
    _flip_middle_field(ledger_path, "usage",
                       lambda r, f: r[f].update(prompt_tokens=99999))
    ok, bad = led.verify()
    assert ok is False and bad == 3


def test_tamper_hash_detected(ledger_path):
    led = Ledger(ledger_path)
    for i in range(3):
        led.append("chat")
    _flip_middle_field(ledger_path, "hash",
                       lambda r, f: r.update(**{f: "f" * 64}))
    ok, bad = led.verify()
    assert ok is False and bad == 3


def test_tamper_prev_hash_detected(ledger_path):
    led = Ledger(ledger_path)
    for i in range(3):
        led.append("chat")
    _flip_middle_field(ledger_path, "prev_hash",
                       lambda r, f: r.update(**{f: "a" * 64}))
    ok, bad = led.verify()
    assert ok is False and bad == 3


def test_tamper_model_field_detected(ledger_path):
    """翻转任一字节（含非链字段 model）都必须被察觉。"""
    led = Ledger(ledger_path)
    for i in range(4):
        led.append("chat", model="deepseek-chat")
    _flip_middle_field(ledger_path, "model", lambda r, f: r.update(**{f: "glm-4.6"}))
    ok, bad = led.verify()
    assert ok is False and bad == 3


def test_corrupt_json_line_reports_line_number(ledger_path):
    led = Ledger(ledger_path)
    for i in range(3):
        led.append("chat")
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    lines[1] = "{{{ not json"
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, bad = led.verify()
    assert ok is False and bad == 2


def test_seq_continuous(ledger_path):
    led = Ledger(ledger_path)
    for i in range(10):
        rec = led.append("chat")
        assert rec["seq"] == i + 1


def test_truncated_chain_detected(ledger_path):
    """删掉中间一行 = prev_hash 断链。verify 在第一条校验不过的记录处报告，
    即被删记录的后继（seq 3，其 prev_hash 对不上 genesis 之后的链头）。"""
    led = Ledger(ledger_path)
    for i in range(4):
        led.append("chat", model=f"m{i}")
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, bad = led.verify()
    assert ok is False and bad == 3


def test_reopen_continues_chain(ledger_path):
    Ledger(ledger_path).append("chat", model="m1")
    led2 = Ledger(ledger_path)
    rec = led2.append("chat", model="m2")
    assert rec["seq"] == 2
    assert led2.verify() == (True, None)


def test_unicode_content_roundtrip(ledger_path):
    led = Ledger(ledger_path)
    text = "账目：中文字段与 emoji 💴 都要原样保留"
    led.append("chat", data={"note": text})
    assert led.records()[0]["data"]["note"] == text
    assert led.verify() == (True, None)


def test_concurrent_append_thread_safe(ledger_path):
    led = Ledger(ledger_path)
    def worker():
        for _ in range(25):
            led.append("chat", model="m")
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(led) == 100
    assert led.verify() == (True, None)


def test_perf_1000_appends_smoke(ledger_path):
    led = Ledger(ledger_path)
    t0 = time.perf_counter()
    for i in range(1000):
        led.append("chat", usage={"prompt_tokens": i})
    elapsed = time.perf_counter() - t0
    assert len(led) == 1000
    assert led.verify() == (True, None)
    assert elapsed < 10.0  # smoke 上限；本机实际远低于此
