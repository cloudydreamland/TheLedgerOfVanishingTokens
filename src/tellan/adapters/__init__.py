"""adapters — 第三方账目/日志导出适配器。

把外部系统的导出文件映射为 tellan 账本记录。每个模块对应一个来源：
- ``newapi``：new-api / one-api 中转站账目导出（JSONL / CSV）
"""

from __future__ import annotations

from .newapi import (
    BUILTIN_ALIASES,
    DEFAULT_QUOTA_PER_UNIT,
    AdapterError,
    build_index,
    import_to_ledger,
    load_export,
)

__all__ = [
    "BUILTIN_ALIASES",
    "DEFAULT_QUOTA_PER_UNIT",
    "AdapterError",
    "build_index",
    "import_to_ledger",
    "load_export",
]
