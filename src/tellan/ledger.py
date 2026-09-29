"""ledger.py — 哈希链 JSONL 账本（Certificate Transparency 思路的本地版）。

每行一条 JSON 记录::

    {"seq","ts","kind","model","provider","request_id","usage","meta",
     "data","prev_hash","hash"}

不变量：

- hash = sha256(prev_hash + canonical_json(payload))，payload 为除
  ``prev_hash``/``hash`` 外的全部字段，canonical 形式为
  ``json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))``。
- genesis 记录的 prev_hash 为 64 个 "0"。
- 账本中任何一行被事后翻转任意字节（包括 hash 本身），``verify()``
  都会从该行开始失败，并报告首个坏 seq。

append-only：本类绝不改写已有行；并发追加由进程内锁串行化。
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_PREV_HASH = "0" * 64
HASH_FIELD = "hash"
PAYLOAD_FIELDS = (
    "seq",
    "ts",
    "kind",
    "model",
    "provider",
    "request_id",
    "usage",
    "meta",
    "data",
)


def canonical_json(obj: Any) -> str:
    """稳定的序列化形式：键排序、保留非 ASCII、无冗余空白。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    """sha256(prev_hash + canonical_json(payload)).hexdigest()。"""
    material = prev_hash + canonical_json(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Ledger:
    """追加式哈希链账本，落盘为 JSONL（UTF-8）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._seq = 0
        self._last_hash = GENESIS_PREV_HASH
        if self.path.exists():
            for rec in self._read_records():
                self._seq = rec["seq"]
                self._last_hash = rec[HASH_FIELD]

    # ------------------------------------------------------------------ write

    def append(
        self,
        kind: str,
        *,
        ts: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        request_id: str | None = None,
        usage: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """追加一条记录，返回带链字段的完整记录。"""
        with self._lock:
            payload: dict[str, Any] = {
                "seq": self._seq + 1,
                # 历史记录导入时保留原始时间戳（对账的时间口径不能被导入时刻覆盖）
                "ts": ts if ts is not None else utc_now_iso(),
                "kind": kind,
                "model": model,
                "provider": provider,
                "request_id": request_id,
                "usage": usage,
                "meta": meta,
                "data": data,
            }
            record = dict(payload)
            record["prev_hash"] = self._last_hash
            record[HASH_FIELD] = compute_hash(self._last_hash, payload)
            line = canonical_json(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
                f.flush()
            self._seq = payload["seq"]
            self._last_hash = record[HASH_FIELD]
        return record

    # ------------------------------------------------------------------- read

    def _read_records(self) -> Iterator[dict[str, Any]]:
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    def records(self) -> list[dict[str, Any]]:
        """按 seq 顺序返回全部记录（文件不存在时为空表）。"""
        if not self.path.exists():
            return []
        return list(self._read_records())

    def __len__(self) -> int:
        return len(self.records())

    # ----------------------------------------------------------------- verify

    def verify(self) -> tuple[bool, int | None]:
        """校验整条链。

        返回 ``(ok, first_bad_seq)``；ok 时 first_bad_seq 为 None。
        任何一种损坏都在坏行处报告：JSON 解析失败、seq 不连续、
        prev_hash 断链、hash 重算不一致。
        """
        if not self.path.exists():
            return True, None
        prev_hash = GENESIS_PREV_HASH
        expected_seq = 1
        with open(self.path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    return False, idx
                if rec.get("seq") != expected_seq:
                    return False, _seq_or(rec, idx)
                if rec.get("prev_hash") != prev_hash:
                    return False, _seq_or(rec, idx)
                payload = {k: rec.get(k) for k in PAYLOAD_FIELDS}
                if compute_hash(prev_hash, payload) != rec.get(HASH_FIELD):
                    return False, _seq_or(rec, idx)
                prev_hash = rec[HASH_FIELD]
                expected_seq += 1
        return True, None


def _seq_or(rec: dict[str, Any], idx: int) -> int:
    seq = rec.get("seq")
    return seq if isinstance(seq, int) else idx
