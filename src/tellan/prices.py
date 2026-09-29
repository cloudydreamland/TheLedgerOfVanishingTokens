"""prices.py — 内置价格快照与费用计算。

诚实声明：内置 ``prices.json`` 是**快照估值**，``source_note`` 逐条标注
"发布前需人工核对，未联网逐条验证"。``lookup`` 做别名归一化（小写、去
provider 前缀、包含匹配），``cost`` 按缓存/推理 token 分档计价。审计
结论引用价格时应附 ``as_of`` 日期。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PRICES_PATH = Path(__file__).with_name("prices.json")

# 常见 provider 前缀（如 "openai/gpt-4o" → "gpt-4o"）。
_PROVIDER_PREFIXES = (
    "openai/", "anthropic/", "google/", "deepseek/", "moonshot/", "zhipu/",
    "qwen/", "dashscope/", "xai/", "mistral/", "doubao/", "openrouter/",
    "together/", "fireworks/", "groq/", "azure/", "bedrock/",
)


@dataclass
class PriceEntry:
    model: str
    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float | None
    cache_write_per_1m: float | None
    currency: str
    source_note: str
    as_of: str
    aliases: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_per_1m": self.input_per_1m,
            "output_per_1m": self.output_per_1m,
            "cached_input_per_1m": self.cached_input_per_1m,
            "cache_write_per_1m": self.cache_write_per_1m,
            "currency": self.currency,
            "source_note": self.source_note,
            "as_of": self.as_of,
        }


def _load_snapshot() -> tuple[list[PriceEntry], dict[str, Any]]:
    with open(_PRICES_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = [
        PriceEntry(
            model=item["model"],
            input_per_1m=float(item["input_per_1m"]),
            output_per_1m=float(item["output_per_1m"]),
            cached_input_per_1m=(
                float(item["cached_input_per_1m"])
                if item.get("cached_input_per_1m") is not None else None
            ),
            cache_write_per_1m=(
                float(item["cache_write_per_1m"])
                if item.get("cache_write_per_1m") is not None else None
            ),
            currency=item.get("currency", "USD"),
            source_note=item.get("source_note", "快照估值，发布前需人工核对，未联网逐条验证"),
            as_of=item.get("as_of", raw.get("_meta", {}).get("as_of", "unknown")),
            aliases=list(item.get("aliases", [])),
        )
        for item in raw["prices"]
    ]
    return entries, raw.get("_meta", {})


ENTRIES, META = _load_snapshot()
SNAPSHOT_NOTE: str = META.get(
    "note", "快照估值，发布前需人工核对，未联网逐条验证。"
)


def normalize_model_name(model: str) -> str:
    """小写、去空白、剥 provider 前缀（可多层）。"""
    name = (model or "").strip().lower()
    changed = True
    while changed:
        changed = False
        for prefix in _PROVIDER_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                changed = True
    return name


class PriceTable:
    """别名归一化的价格查询表（内置快照的内存视图）。"""

    def __init__(self, entries: list[PriceEntry] | None = None) -> None:
        self.entries = entries if entries is not None else ENTRIES

    def lookup(self, model: str) -> PriceEntry | None:
        """精确 → 别名 → 包含匹配（双向）。找不到返回 None。"""
        name = normalize_model_name(model)
        if not name:
            return None
        for entry in self.entries:
            if normalize_model_name(entry.model) == name:
                return entry
        for entry in self.entries:
            keys = [entry.model, *entry.aliases]
            if any(normalize_model_name(k) == name for k in keys):
                return entry
        for entry in self.entries:
            keys = [entry.model, *entry.aliases]
            if any(name in normalize_model_name(k) or normalize_model_name(k) in name
                   for k in keys):
                return entry
        return None

    def __contains__(self, model: str) -> bool:
        return self.lookup(model) is not None

    def __len__(self) -> int:
        return len(self.entries)


DEFAULT_TABLE = PriceTable()


def lookup(model: str) -> PriceEntry | None:
    """便捷入口：在内置快照表中查价格。"""
    return DEFAULT_TABLE.lookup(model)


def cost(usage: dict[str, Any], price: PriceEntry) -> dict[str, Any]:
    """按价格表计算一次 usage 的费用。

    处理三种输入侧 token：普通 input、cached（prompt_tokens_details.cached_tokens
    或 Anthropic 风格 cache_read_input_tokens）、cache 写入
    （cache_creation_input_tokens，按 cache_write_per_1m，缺省视同 input 价）。
    推理 token（reasoning_tokens）已含在 completion_tokens 内，按输出价计。

    返回 ``{"amount", "currency", "breakdown"}``；字段缺失按 0 处理。
    """
    details_in = usage.get("prompt_tokens_details") or {}
    cached = int(
        usage.get("cache_read_input_tokens")
        or details_in.get("cached_tokens")
        or 0
    )
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    prompt = int(usage.get("prompt_tokens") or 0)
    plain_input = max(0, prompt - cached - cache_write)
    completion = int(usage.get("completion_tokens") or 0)

    c_input = plain_input * price.input_per_1m / 1_000_000
    write_price = price.cache_write_per_1m if price.cache_write_per_1m is not None \
        else price.input_per_1m
    c_write = cache_write * write_price / 1_000_000
    read_price = price.cached_input_per_1m if price.cached_input_per_1m is not None \
        else price.input_per_1m
    c_read = cached * read_price / 1_000_000
    c_out = completion * price.output_per_1m / 1_000_000
    return {
        "amount": round(c_input + c_write + c_read + c_out, 10),
        "currency": price.currency,
        "breakdown": {
            "input": round(c_input, 10),
            "cache_write": round(c_write, 10),
            "cache_read": round(c_read, 10),
            "output": round(c_out, 10),
        },
    }
