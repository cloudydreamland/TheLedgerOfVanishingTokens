"""newapi.py — new-api / one-api 中转站账目导出适配器。

把中转站的账目导出（JSONL / CSV）映射为 tellan 账本记录，供 ``tellan
audit`` 直接对账。字段表以两家仓库 main 分支的 ``model/log.go`` Log 结构体
为权威依据（2026-09-28 实抓）：

- new-api：id/user_id/created_at/type/content/username/token_name/model_name/
  quota/prompt_tokens/completion_tokens/use_time/is_stream/channel/channel_name/
  token_id/group/ip/request_id/upstream_request_id/other
- one-api：同上少 use_time（叫 elapsed_time，毫秒）、无 upstream_request_id、
  多 system_prompt_reset
- 两家的消费记录都是 ``type == 2``（one-api 为 iota，new-api 为显式常量），
  顶层充值/管理/错误/退款行不构成用量，一律跳过并计数。

已知脏数据与处理（ROADMAP iter2 约定）：

- 缺 request_id → 用 sha256(规范化行)[:12] 合成稳定 id（前缀 ``imp-``，
  meta 标 ``request_id_synth``），同输入必得同 id；
- usage 为字符串（含千分位逗号）→ ``_coerce_int`` 宽容转换，转不动整行跳过；
- 时间戳秒/毫秒/ISO 混杂 → ``_norm_ts`` 统一为 UTC ISO；
- quota 是站内点数不是美元 → 按 ``quota_per_unit``（默认 500000 = $1，部署可配）
  折算 ``quota_usd_est``，诚实标注"est"。
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONSUME_TYPE = 2

#: 规范字段 → 别名表（new-api/one-api JSON 键 + 常见中文 CSV 列头）。
#: 用户 ``--mapping`` 提供的 {"canonical": [...]} 会**合并**进这张表。
BUILTIN_ALIASES: dict[str, list[str]] = {
    "created_at": ["created_at", "时间", "创建时间", "timestamp"],
    "model_name": ["model_name", "模型", "模型名称", "model"],
    "prompt_tokens": ["prompt_tokens", "提示tokens", "提示 tokens", "输入tokens", "输入 tokens"],
    "completion_tokens": ["completion_tokens", "补全tokens", "补全 tokens", "输出tokens", "输出 tokens"],
    "quota": ["quota", "额度", "配额", "消费额度"],
    "request_id": ["request_id", "请求ID", "请求 ID"],
    "upstream_request_id": ["upstream_request_id", "上游请求ID", "上游请求 ID"],
    "type": ["type", "类型"],
    "username": ["username", "用户", "用户名"],
    "token_name": ["token_name", "令牌", "令牌名称", "令牌名"],
    "channel": ["channel", "channel_id", "渠道", "渠道ID", "渠道 ID"],
    "is_stream": ["is_stream", "流式", "是否流式"],
    "use_time": ["use_time", "elapsed_time", "耗时", "用时"],
    "content": ["content", "内容", "详情"],
}

DEFAULT_QUOTA_PER_UNIT = 500000.0  # one-api 家族默认：500000 quota = $1，部署可配

_MAX_CONTENT_DESC = 200


class AdapterError(ValueError):
    """导出文件整体不可读/格式不识别（区别于单行跳过）。"""


def _coerce_int(value: Any) -> int | None:
    """宽容整数转换：接受 int / float / "123" / "1,234" / " 12 " / "12.0"。

    空值返回 None；转不动的垃圾抛 ValueError（由调用方跳行计数）。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"bool 不是合法 token 数: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("，", "")
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return int(float(text))  # "12.0" 之类
    raise ValueError(f"无法转换为整数: {value!r}")


def _coerce_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "是", "yes"}:
        return True
    if text in {"false", "0", "否", "no"}:
        return False
    return None


def _norm_ts(value: Any) -> str | None:
    """时间戳统一为 UTC ISO（毫秒精度）。

    支持：unix 秒（~1e9）、unix 毫秒（~1e12）、ISO 字符串、纯数字字符串。
    判据：> 1e11 视为毫秒。naive ISO 按 UTC 处理（导出方一般不给时区）。
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            seconds = float(text)
        except ValueError:
            # datetime.fromisoformat accepted the UTC designator only from
            # Python 3.11; normalize it for the supported Python 3.10 floor.
            if text.endswith(("Z", "z")):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    if seconds > 1e11:  # 毫秒
        seconds /= 1000.0
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="milliseconds")


def _resolve(row: dict[str, Any], field: str, index: dict[str, str]) -> Any:
    """按 别名表→行键 的映射取值（CSV 表头可能带 BOM/空白）。"""
    for alias in index.get(field, []):
        if alias in row:
            v = row[alias]
            if isinstance(v, str):
                v = v.strip()
                if v == "":
                    continue
            return v
    return None


def _synth_request_id(fields: dict[str, Any]) -> str:
    """缺 request_id 时合成稳定 id：同输入必得同 id（可重复审计）。"""
    material = json.dumps(fields, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
    return "imp-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def detect_source(row: dict[str, Any]) -> str:
    """按特征键区分导出来源（new-api 独有 upstream_request_id/use_time）。"""
    keys = set(row.keys())
    if {"upstream_request_id", "use_time", "channel_name"} & keys:
        return "newapi"
    if {"elapsed_time", "system_prompt_reset"} & keys:
        return "oneapi"
    return "custom"


def build_index(mapping: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """合并内置别名表与用户映射（用户别名追加在 builtin 之后，先到先得）。"""
    index: dict[str, list[str]] = {f: list(a) for f, a in BUILTIN_ALIASES.items()}
    if mapping:
        for field, aliases in mapping.items():
            index.setdefault(field, [])
            for alias in aliases:
                if alias not in index[field]:
                    index[field].append(alias)
    return index


def row_to_record(
    row: dict[str, Any],
    *,
    index: dict[str, list[str]],
    source: str,
    provider: str,
    quota_per_unit: float,
) -> tuple[dict[str, Any], str | None]:
    """单行 → 账本记录。

    返回 (record, skip_reason)。skip_reason 非 None 表示该行不入账。
    """
    type_raw = _resolve(row, "type", index)
    try:
        rtype = _coerce_int(type_raw)
    except ValueError:
        rtype = None  # 中文词（"消费"）等非数字类型：宽容入账，原文留痕
    if rtype is not None and rtype != CONSUME_TYPE:
        return {}, f"type={rtype}（非消费行，不入账）"

    prompt = _coerce_int(_resolve(row, "prompt_tokens", index))
    completion = _coerce_int(_resolve(row, "completion_tokens", index))
    if prompt is None and completion is None:
        return {}, "prompt/completion tokens 双缺失"
    model = _resolve(row, "model_name", index)
    if not model:
        return {}, "缺模型名"

    ts = _norm_ts(_resolve(row, "created_at", index))
    quota = _coerce_int(_resolve(row, "quota", index))
    request_id = _resolve(row, "request_id", index)
    upstream_id = _resolve(row, "upstream_request_id", index)
    content = _resolve(row, "content", index)

    usage: dict[str, Any] = {}
    if prompt is not None:
        usage["prompt_tokens"] = prompt
    if completion is not None:
        usage["completion_tokens"] = completion

    meta: dict[str, Any] = {
        "source_export": source,
        "imported": True,
        "quota": quota,
        "quota_per_unit": quota_per_unit,
        "quota_usd_est": (round(quota / quota_per_unit, 6) if quota is not None else None),
        "type": rtype,
    }
    if rtype is None and type_raw not in (None, ""):
        meta["type_raw"] = str(type_raw)
    if ts is None:
        meta["ts_missing"] = True
    for key, field in (
        ("username", "username"), ("token_name", "token_name"),
        ("channel", "channel"), ("is_stream", "is_stream"),
        ("use_time", "use_time"),
    ):
        value = _resolve(row, field, index)
        if value is not None and value != "":
            if key == "is_stream":
                value = _coerce_bool(value)
            meta[key] = value
    if upstream_id:
        # 中转站声称的上游请求 id——注意它本身可造假，链上留痕仅作线索
        meta["upstream_request_id"] = upstream_id
    if content:
        meta["content_desc"] = str(content)[:_MAX_CONTENT_DESC]

    record: dict[str, Any] = {
        "kind": "chat_completion",
        "ts": ts,
        "model": str(model),
        "provider": provider,
        "request_id": str(request_id) if request_id else None,
        "usage": usage,
        "meta": meta,
    }
    if record["request_id"] is None:
        record["request_id"] = _synth_request_id(
            {"ts": ts, "model": str(model), "usage": usage, "quota": quota}
        )
        meta["request_id_synth"] = True
    return record, None


def load_export(
    path: str | Path,
    *,
    fmt: str = "auto",
    source: str = "auto",
    provider: str | None = None,
    quota_per_unit: float = DEFAULT_QUOTA_PER_UNIT,
    mapping: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """导出文件 → 规范记录列表 + 跳过清单。

    fmt: auto（首行 ``{`` 判 JSONL，否则按 CSV）/ jsonl / csv。
    CSV 用 utf-8-sig 读（Excel 导出带 BOM 是常态）。
    """
    path = Path(path)
    if not path.exists():
        raise AdapterError(f"文件不存在: {path}")
    raw = path.read_text(encoding="utf-8-sig")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise AdapterError("文件为空")
    if fmt == "auto":
        fmt = "jsonl" if lines[0].lstrip().startswith("{") else "csv"
    rows: list[dict[str, Any]]
    if fmt == "jsonl":
        rows = []
        for no, ln in enumerate(lines, 1):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError as exc:
                raise AdapterError(f"第 {no} 行不是合法 JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise AdapterError(f"第 {no} 行不是 JSON 对象")
            rows.append(obj)
    elif fmt == "csv":
        reader = csv.DictReader(raw.splitlines())
        if not reader.fieldnames:
            raise AdapterError("CSV 缺表头")
        rows = [dict(r) for r in reader]
    else:
        raise AdapterError(f"未知格式: {fmt}")

    index = build_index(mapping)
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    detected = source
    for no, row in enumerate(rows, 1):
        row_source = detect_source(row)
        if detected == "auto" and row_source != "custom":
            detected = row_source
        eff_source = row_source if source == "auto" else source
        eff_provider = provider or (
            f"{eff_source}-export" if eff_source != "custom" else "relay-export"
        )
        try:
            record, skip = row_to_record(
                row, index=index, source=eff_source if eff_source != "auto" else "custom",
                provider=eff_provider, quota_per_unit=quota_per_unit,
            )
        except (ValueError, TypeError) as exc:  # 脏数据/时间戳解析失败等，跳行计数
            skipped.append({"line": str(no), "reason": f"解析失败：{exc}",
                            "preview": canonical_preview(row)})
            continue
        if skip is not None:
            skipped.append({"line": str(no), "reason": skip,
                            "preview": canonical_preview(row)})
        else:
            records.append(record)
    if detected == "auto":
        detected = "custom"  # 没有任何特征键命中，如实报告
    return {
        "records": records,
        "skipped": skipped,
        "rows": len(rows),
        "source_format": fmt,
        "detected_source": detected,
    }


def canonical_preview(row: dict[str, Any], limit: int = 120) -> str:
    text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return text[:limit]


def import_to_ledger(
    ledger: Any,
    path: str | Path,
    *,
    fmt: str = "auto",
    source: str = "auto",
    provider: str | None = None,
    quota_per_unit: float = DEFAULT_QUOTA_PER_UNIT,
    mapping: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """导出文件入账（逐条 append，继承哈希链）。返回 load_export 摘要。"""
    summary = load_export(
        path, fmt=fmt, source=source, provider=provider,
        quota_per_unit=quota_per_unit, mapping=mapping,
    )
    for record in summary["records"]:
        ledger.append(
            record["kind"],
            ts=record.get("ts"),
            model=record.get("model"),
            provider=record.get("provider"),
            request_id=record.get("request_id"),
            usage=record.get("usage"),
            meta=record.get("meta"),
        )
    return summary
