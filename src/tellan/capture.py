"""capture.py — 本地 CaptureProxy：拦截 /v1/chat/completions 并入账。

基于 ThreadingHTTPServer + urllib 转发。默认**最小化留存**：请求消息只存
条数 + 每条长度 + sha256 前 12 位；响应正文只存结构 + 每段长度 + 哈希前缀，
usage 原样入账。``--no-redact`` 才存原文。Authorization 头永远不入账本
（无论是否脱敏）。

SSE streaming：逐 chunk 透传，并尽力（best-effort）从流中抓取 usage——
若上游未开启 ``stream_options.include_usage`` 之类机制，流式 usage 可能
缺失，此时该记录对账状态为 INSUFFICIENT_DATA。这是诚实边界，不伪造。
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .ledger import Ledger

CHAT_PATHS = {"/v1/chat/completions", "/chat/completions"}
PROXY_VERSION = "tellan/0.1.0rc1"


def redact_message(message: dict[str, Any]) -> dict[str, Any]:
    """单条消息 → {role, length, sha256_12}。原文一概不留。"""
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(
            p.get("text", "") for p in content if isinstance(p, dict)
        )
    else:
        text = "" if content is None else str(content)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return {"role": message.get("role"), "length": len(text), "sha256_12": digest}


def redact_request_body(body: dict[str, Any]) -> dict[str, Any]:
    """请求体脱敏视图：消息条数+长度+哈希前缀，其余元字段保留。"""
    messages = body.get("messages") or []
    return {
        "model": body.get("model"),
        "stream": bool(body.get("stream")),
        "message_count": len(messages),
        "messages": [redact_message(m) if isinstance(m, dict) else {"role": None}
                     for m in messages],
        "redacted": True,
    }


def redact_response_body(body: dict[str, Any]) -> dict[str, Any]:
    """响应体脱敏视图：choices 结构保留，content 替换为长度+哈希前缀。"""
    out: dict[str, Any] = {
        "model": body.get("model"),
        "redacted": True,
    }
    choices = body.get("choices")
    if isinstance(choices, list):
        redacted_choices = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message") or {}
            content = msg.get("content")
            text = content if isinstance(content, str) else ""
            redacted_choices.append({
                "index": choice.get("index"),
                "finish_reason": choice.get("finish_reason"),
                "message": {
                    "role": msg.get("role"),
                    "length": len(text),
                    "sha256_12": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
                    if text else "",
                },
            })
        out["choices"] = redacted_choices
    return out


class CaptureProxy:
    """启动一个本地反向代理，把 chat/completions 流量转发到 upstream 并入账。"""

    def __init__(
        self,
        upstream: str,
        ledger: Ledger,
        *,
        redact: bool = True,
        timeout: float = 120.0,
        port: int = 0,
    ) -> None:
        self.upstream = upstream.rstrip("/")
        self.ledger = ledger
        self.redact = redact
        self.timeout = timeout
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._make_handler())
        self._server.daemon_threads = True
        self.port: int = self._server.server_address[1]  # type: ignore[assignment]

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # ------------------------------------------------------------------ handler

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # 静默默认日志
                pass

            def do_POST(self) -> None:
                if not any(self.path.endswith(p) for p in CHAT_PATHS):
                    self._plain(404, b'{"error": "tellan: only chat/completions"}')
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw_body = self.rfile.read(length) if length else b"{}"
                try:
                    req_body = json.loads(raw_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._plain(400, b'{"error": "tellan: bad json body"}')
                    return

                upstream_url = proxy.upstream + "/v1/chat/completions"
                # 安全：Authorization 原样转发给上游，但绝不写入账本。
                headers = {"Content-Type": "application/json",
                           "User-Agent": PROXY_VERSION}
                auth = self.headers.get("Authorization")
                if auth:
                    headers["Authorization"] = auth
                request_id = self.headers.get("X-Request-Id") or ""

                req = urllib.request.Request(
                    upstream_url, data=raw_body, headers=headers, method="POST"
                )
                try:
                    resp = urllib.request.urlopen(req, timeout=proxy.timeout)
                except urllib.error.HTTPError as exc:
                    err_body = exc.read()
                    self._plain(exc.code, err_body)
                    proxy.ledger.append(
                        "proxy_upstream_error", model=req_body.get("model"),
                        provider=proxy.upstream, request_id=request_id,
                        meta={"status": exc.code},
                    )
                    return
                except (urllib.error.URLError, OSError) as exc:
                    self._plain(502, json.dumps(
                        {"error": f"tellan: upstream unreachable: {exc}"}
                    ).encode("utf-8"))
                    proxy.ledger.append(
                        "proxy_upstream_unreachable", model=req_body.get("model"),
                        provider=proxy.upstream, request_id=request_id,
                    )
                    return

                content_type = resp.headers.get("Content-Type", "application/json")
                self.send_response(resp.status)
                self.send_header("Content-Type", content_type)
                self.send_header("X-Tellan-Proxy", PROXY_VERSION)
                self.end_headers()

                resp_body: dict[str, Any] | None = None
                if "text/event-stream" in content_type:
                    usage = self._pipe_sse(resp)
                else:
                    payload = resp.read()
                    self.wfile.write(payload)
                    usage = None
                    try:
                        resp_body = json.loads(payload.decode("utf-8"))
                        usage = resp_body.get("usage")
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        resp_body = None
                try:
                    self.wfile.flush()
                except OSError:
                    pass

                fallback_id = (usage or {}).get("id") if isinstance(usage, dict) else None
                proxy.ledger.append(
                    "chat_completion",
                    model=req_body.get("model"),
                    provider=proxy.upstream,
                    request_id=request_id or fallback_id,
                    usage=usage,
                    meta={"stream": bool(req_body.get("stream")), "status": resp.status},
                    data={
                        "request": proxy._capture_request(req_body),
                        "response": proxy._capture_response(resp_body, usage),
                    },
                )

            def _pipe_sse(self, resp: Any) -> dict[str, Any] | None:
                """逐行透传 SSE；尽力抓取流中最后一个非空 usage。"""
                usage: dict[str, Any] | None = None
                for raw_line in resp:
                    try:
                        self.wfile.write(raw_line)
                    except OSError:
                        break
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("usage"):
                        usage = chunk["usage"]
                return usage

            def _plain(self, code: int, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    # ------------------------------------------------------------------ capture

    def _capture_request(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.redact:
            return redact_request_body(body)
        return {**body, "redacted": False}

    def _capture_response(
        self, resp_body: dict[str, Any] | None, usage: dict[str, Any] | None
    ) -> dict[str, Any]:
        if self.redact:
            base: dict[str, Any] = redact_response_body(resp_body or {})
        else:
            base = resp_body or {}
        if usage is not None:
            base["usage"] = usage
        return base
