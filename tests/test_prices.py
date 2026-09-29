"""prices.py 测试：别名归一化、费用数学、快照诚实声明。"""

import pytest

from tellan.prices import (
    DEFAULT_TABLE,
    ENTRIES,
    SNAPSHOT_NOTE,
    PriceTable,
    cost,
    lookup,
    normalize_model_name,
)


def test_snapshot_covers_major_models():
    assert 30 <= len(ENTRIES) <= 50
    names = {e.model for e in ENTRIES}
    for expected in ("gpt-4o", "gpt-4o-mini", "o3", "o4-mini", "deepseek-chat",
                     "deepseek-reasoner", "qwen-max", "glm-4.6", "kimi-k2",
                     "claude-sonnet-4", "gemini-2.5-pro"):
        assert expected in names, f"快照缺 {expected}"


def test_honest_source_note_every_entry():
    for e in ENTRIES:
        assert "快照" in e.source_note and "人工核对" in e.source_note
        assert "未联网" in e.source_note
        assert e.as_of and e.as_of != "unknown"


def test_snapshot_note_present():
    assert "快照" in SNAPSHOT_NOTE


def test_normalize_strips_provider_prefixes():
    assert normalize_model_name("openai/gpt-4o") == "gpt-4o"
    assert normalize_model_name("OpenAI/GPT-4O") == "gpt-4o"
    assert normalize_model_name("openrouter/anthropic/claude-sonnet-4") == \
        "claude-sonnet-4"


def test_lookup_exact():
    entry = DEFAULT_TABLE.lookup("gpt-4o")
    assert entry is not None and entry.model == "gpt-4o"


def test_lookup_case_and_whitespace():
    assert DEFAULT_TABLE.lookup("  GPT-4o ") is not None


def test_lookup_alias_prefix():
    assert DEFAULT_TABLE.lookup("openai/gpt-4o-mini").model == "gpt-4o-mini"
    assert DEFAULT_TABLE.lookup("deepseek/deepseek-chat").model == "deepseek-chat"


def test_lookup_dated_variant_substring():
    assert DEFAULT_TABLE.lookup("gpt-4o-2024-08-06").model == "gpt-4o"


def test_lookup_claude_dot_alias():
    assert DEFAULT_TABLE.lookup("claude-3.5-sonnet").model == "claude-3-5-sonnet"


def test_lookup_missing_returns_none():
    assert DEFAULT_TABLE.lookup("no-such-model-xyz") is None
    assert DEFAULT_TABLE.lookup("") is None


def test_module_level_lookup():
    assert lookup("glm-4.6") is not None


def test_currency_qwen_is_cny():
    assert DEFAULT_TABLE.lookup("qwen-max").currency == "CNY"
    assert DEFAULT_TABLE.lookup("gpt-4o").currency == "USD"


def test_cost_basic_math():
    entry = DEFAULT_TABLE.lookup("gpt-4o")  # 2.5 / 10.0
    result = cost({"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}, entry)
    assert result["amount"] == pytest.approx(12.5)
    assert result["currency"] == "USD"
    assert result["breakdown"]["input"] == pytest.approx(2.5)
    assert result["breakdown"]["output"] == pytest.approx(10.0)


def test_cost_with_openai_cached_tokens():
    entry = DEFAULT_TABLE.lookup("gpt-4o")  # cached 1.25
    usage = {"prompt_tokens": 1000,
             "prompt_tokens_details": {"cached_tokens": 400}}
    result = cost(usage, entry)
    expected = (600 * 2.5 + 400 * 1.25) / 1e6
    assert result["amount"] == pytest.approx(expected)


def test_cost_anthropic_cache_read_and_write():
    entry = DEFAULT_TABLE.lookup("claude-sonnet-4")  # in 3 / cached 0.3 / write 3.75
    usage = {"prompt_tokens": 6200, "completion_tokens": 10,
             "cache_read_input_tokens": 5200,
             "cache_creation_input_tokens": 880}
    result = cost(usage, entry)
    expected = (120 * 3 + 880 * 3.75 + 5200 * 0.3 + 10 * 15) / 1e6
    assert result["amount"] == pytest.approx(expected)


def test_cost_missing_cache_price_falls_back_to_input():
    entry = DEFAULT_TABLE.lookup("qwen-max")  # 无 cached 价格
    usage = {"prompt_tokens": 1000,
             "prompt_tokens_details": {"cached_tokens": 1000}}
    result = cost(usage, entry)
    assert result["amount"] == pytest.approx(1000 * 2.4 / 1e6)


def test_cost_zero_usage():
    entry = DEFAULT_TABLE.lookup("glm-4-flash")
    assert cost({"prompt_tokens": 0, "completion_tokens": 0}, entry)["amount"] == 0.0


def test_custom_table_isolation():
    table = PriceTable(entries=[])
    assert len(table) == 0
    assert table.lookup("gpt-4o") is None
