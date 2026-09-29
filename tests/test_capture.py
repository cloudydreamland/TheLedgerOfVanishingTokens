"""capture.py 测试：本地 mock 上游（线程 + http.server）端到端。"""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from tellan.capture import CaptureProxy, redact_request_body
from tellan.ledger import Ledger

CHAT_JSON = {
    "id": "chatcmpl-123", "model": "deepseek-chat",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "这是上游回复。"}}],
    "usage": {"prompt_tokens": 42, "completion_tokens": 17},
}
SECRET = "sk-test-secret-do-not-leak"


class _UpstreamHandler(BaseHTTPRequestHandler):
    behavior: ClassVar[str] = "json"  # 由 fixture 修改："json" | "sse"
    seen_auth: ClassVar[list[str]] = []

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        _UpstreamHandler.seen_auth.append(self.headers.get("Authorization") or "")
        if self.behavior == "sse":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {"id": "c1", "choices": [{"delta": {"content": "你"}}]},
                {"id": "c1", "choices": [{"delta": {"content": "好"}}]},
                {"id": "c1", "choices": [{"delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
            ]
            for chunk in chunks:
                line = b"data: " + json.dumps(chunk, ensure_ascii=False).encode(
                    "utf-8") + b"\n\n"
                self.wfile.write(line)
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            payload = json.dumps(CHAT_JSON, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


@pytest.fixture()
def upstream():
    _UpstreamHandler.behavior = "json"
    _UpstreamHandler.seen_auth = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _post(proxy_base: str, body: dict, *, headers: dict | None = None,
          path: str = "/v1/chat/completions") -> tuple[int, bytes, dict]:
    last_exc: Exception | None = None
    for _ in range(2):  # Windows 套接字偶发中断重试一次（传输层，断言不弱化）
        req = urllib.request.Request(
            proxy_base + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)
        except (ConnectionAbortedError, ConnectionResetError) as exc:
            last_exc = exc
    raise last_exc  # type: ignore[misc]


def test_nonstream_end_to_end_redacted(tmp_path, upstream):
    ledger = Ledger(tmp_path / "l.jsonl")
    proxy = CaptureProxy(upstream, ledger)
    proxy.start()
    try:
        status, body, _ = _post(
            proxy.base_url,
            {"model": "deepseek-chat", "stream": False,
             "messages": [{"role": "user", "content": "机密的中文提问内容"}]},
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        assert status == 200
        assert json.loads(body)["usage"]["completion_tokens"] == 17
    finally:
        proxy.shutdown()

    records = ledger.records()
    assert len(records) == 1
    rec = records[0]
    assert rec["kind"] == "chat_completion"
    assert rec["usage"] == CHAT_JSON["usage"]
    assert rec["model"] == "deepseek-chat"
    assert rec["data"]["request"]["redacted"] is True
    assert rec["data"]["request"]["message_count"] == 1
    msg = rec["data"]["request"]["messages"][0]
    assert msg["role"] == "user" and msg["length"] > 0 and len(msg["sha256_12"]) == 12


def test_authorization_never_in_ledger(tmp_path, upstream):
    ledger = Ledger(tmp_path / "l.jsonl")
    proxy = CaptureProxy(upstream, ledger)
    proxy.start()
    try:
        status, _, _ = _post(proxy.base_url,
                             {"model": "m", "messages": [{"role": "user",
                                                          "content": "hi"}]},
                             headers={"Authorization": f"Bearer {SECRET}"})
        assert status == 200
    finally:
        proxy.shutdown()
    raw = (tmp_path / "l.jsonl").read_text(encoding="utf-8")
    assert SECRET not in raw
    assert "Authorization" not in raw


def test_redacted_no_plaintext_in_ledger(tmp_path, upstream):
    plaintext = "绝不入库的原文句子"
    ledger = Ledger(tmp_path / "l.jsonl")
    proxy = CaptureProxy(upstream, ledger)
    proxy.start()
    try:
        _post(proxy.base_url, {"model": "m",
                               "messages": [{"role": "user", "content": plaintext}]})
    finally:
        proxy.shutdown()
    raw = (tmp_path / "l.jsonl").read_text(encoding="utf-8")
    assert plaintext not in raw
    # 上游回复原文同样不入库
    assert "这是上游回复" not in raw


def test_no_redact_stores_plaintext(tmp_path, upstream):
    plaintext = "这句原文会被保存"
    ledger = Ledger(tmp_path / "l.jsonl")
    proxy = CaptureProxy(upstream, ledger, redact=False)
    proxy.start()
    try:
        _post(proxy.base_url, {"model": "m",
                               "messages": [{"role": "user", "content": plaintext}]})
    finally:
        proxy.shutdown()
    raw = (tmp_path / "l.jsonl").read_text(encoding="utf-8")
    assert plaintext in raw
    rec = ledger.records()[0]
    assert rec["data"]["request"]["redacted"] is False
    assert SECRET not in raw  # 即使 no-redact，Authorization 也不入库


def test_stream_sse_passthrough_and_usage(tmp_path, upstream):
    _UpstreamHandler.behavior = "sse"
    ledger = Ledger(tmp_path / "l.jsonl")
    proxy = CaptureProxy(upstream, ledger)
    proxy.start()
    try:
        status, body, headers = _post(
            proxy.base_url,
            {"model": "m", "stream": True,
             "messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        proxy.shutdown()
    assert status == 200
    assert "text/event-stream" in headers.get("Content-Type", "")
    text = body.decode("utf-8")
    assert text.count("data: ") == 4  # 3 chunk + [DONE]
    assert '"content": "你"' in text or '"content":"你"' in text
    rec = ledger.records()[0]
    assert rec["usage"] == {"prompt_tokens": 7, "completion_tokens": 2}
    assert rec["meta"]["stream"] is True


def test_upstream_unreachable_returns_502_and_logs(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    # 绑定一个端口然后立刻关掉，制造"不可达上游"
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead_port = s.getsockname()[1]
    proxy = CaptureProxy(f"http://127.0.0.1:{dead_port}", ledger)
    proxy.start()
    try:
        status, body, _ = _post(proxy.base_url,
                                {"model": "m", "messages": [{"role": "user",
                                                             "content": "x"}]})
        assert status == 502
        assert b"unreachable" in body
    finally:
        proxy.shutdown()
    assert ledger.records()[0]["kind"] == "proxy_upstream_unreachable"


def test_non_chat_path_404(tmp_path, upstream):
    ledger = Ledger(tmp_path / "l.jsonl")
    proxy = CaptureProxy(upstream, ledger)
    proxy.start()
    try:
        status, _, _ = _post(proxy.base_url, {"x": 1}, path="/v1/embeddings")
        assert status == 404
    finally:
        proxy.shutdown()
    assert len(ledger) == 0


def test_auth_header_forwarded_to_upstream(tmp_path, upstream):
    ledger = Ledger(tmp_path / "l.jsonl")
    proxy = CaptureProxy(upstream, ledger)
    proxy.start()
    try:
        _post(proxy.base_url, {"model": "m", "messages": []},
              headers={"Authorization": f"Bearer {SECRET}"})
    finally:
        proxy.shutdown()
    assert _UpstreamHandler.seen_auth == [f"Bearer {SECRET}"]


def test_redact_request_body_shape():
    body = {"model": "m", "messages": [{"role": "user", "content": "你好世界"}]}
    view = redact_request_body(body)
    assert view["message_count"] == 1
    assert view["messages"][0] == {
        "role": "user",
        "length": 4,
        "sha256_12": __import__("hashlib").sha256("你好世界".encode())
        .hexdigest()[:12],
    }
    assert "你好" not in json.dumps(view, ensure_ascii=False)
