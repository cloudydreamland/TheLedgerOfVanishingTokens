"""Tellan — LLM API 账单对账与计量审计标准件。

三方对账：厂商报数 vs 本地复算包围盒 vs 价格表。
哈希链账本：任何事后篡改可被 verify 察觉。
"""

# 版本号必须先于子模块 import 定义：statement 等子模块在包初始化期间
# `from . import __version__` 取的就是这个属性。
__version__ = "0.1.0rc1"

from .ledger import GENESIS_PREV_HASH, Ledger, canonical_json, compute_hash
from .prices import DEFAULT_TABLE, PriceEntry, PriceTable, cost, lookup
from .reconcile import Verdict, reconcile_ledger, reconcile_record
from .recount import (
    HeuristicCounter,
    TiktokenCounter,
    TiktokenUnavailable,
    TokenEstimate,
    counter_for,
    estimate_exchange,
    model_family,
)
from .report import render_json, render_markdown
from .statement import (
    build_statement,
    render_statement_json,
    render_statement_markdown,
)

__all__ = [
    "DEFAULT_TABLE",
    "GENESIS_PREV_HASH",
    "HeuristicCounter",
    "Ledger",
    "PriceEntry",
    "PriceTable",
    "TiktokenCounter",
    "TiktokenUnavailable",
    "TokenEstimate",
    "Verdict",
    "__version__",
    "build_statement",
    "canonical_json",
    "compute_hash",
    "cost",
    "counter_for",
    "estimate_exchange",
    "lookup",
    "model_family",
    "reconcile_ledger",
    "reconcile_record",
    "render_json",
    "render_markdown",
    "render_statement_json",
    "render_statement_markdown",
]
