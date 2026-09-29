"""recount.py 测试：包围盒不变量、CJK/ASCII 差异、fuzz、tiktoken 可选。"""

import random

import pytest

from tellan.recount import (
    BOX_HI,
    BOX_LO,
    FAMILY_WEIGHTS,
    HeuristicCounter,
    TiktokenCounter,
    TiktokenUnavailable,
    TokenEstimate,
    count_ascii_words,
    count_cjk_chars,
    counter_for,
    estimate_exchange,
    model_family,
    point_count,
)


def test_estimate_invariants_basic():
    est = HeuristicCounter().estimate_messages(
        [{"role": "user", "content": "你好世界"}], "deepseek-chat")
    assert isinstance(est, TokenEstimate)
    assert 0 <= est.input_lo <= est.input_hi
    assert est.output_lo == 0 and est.output_hi == 0
    assert est.strategy == "heuristic" and est.confidence == "coarse"


def test_empty_messages_zero():
    est = HeuristicCounter().estimate_messages([], "gpt-4o")
    assert est.input_lo == 0 and est.input_hi == 0


def test_ascii_words_counted():
    # 下划线不在 [A-Za-z0-9] 内，foo_bar 计为两个词
    assert count_ascii_words("hello world, foo_bar 42") == 5
    assert count_cjk_chars("hello world") == 0


def test_cjk_chars_counted_including_fullwidth():
    assert count_cjk_chars("你好。") == 3  # 句号为全角标点，计入 CJK
    assert count_cjk_chars("中文English") == 2


def test_cjk_vs_ascii_difference():
    counter = HeuristicCounter()
    cjk = counter.estimate_messages(
        [{"role": "user", "content": "一二三四五"}], "deepseek-chat")
    ascii_est = counter.estimate_messages(
        [{"role": "user", "content": "abcde"}], "deepseek-chat")
    assert cjk.input_hi > ascii_est.input_hi


def test_family_weights_change_estimate():
    text = "这是一段用于比较族权重的中文文本，长度适中。"
    legacy = point_count(text, "openai_legacy")
    deepseek = point_count(text, "deepseek")
    assert legacy > deepseek
    assert FAMILY_WEIGHTS["openai_legacy"] > FAMILY_WEIGHTS["deepseek"]


def test_box_multipliers_match_spec():
    assert BOX_LO == 0.5 and BOX_HI == 1.6


def test_box_contains_point_estimate():
    text = "估计包围盒必须包住点估计本身。"
    point = point_count(text, "qwen", 1, 0)
    counter = HeuristicCounter()
    est = counter.estimate_messages([{"role": "user", "content": text}], "qwen-max")
    assert est.input_lo <= point <= est.input_hi


def test_unknown_family_neutral_weight_and_note():
    est = HeuristicCounter().estimate_messages(
        [{"role": "user", "content": "你好"}], "totally-unknown-model")
    assert model_family("totally-unknown-model") == "unknown"
    assert any("unknown" in n or "未知" in n for n in est.notes)


def test_message_frame_overhead():
    counter = HeuristicCounter()
    one = counter.estimate_messages(
        [{"role": "user", "content": "hi"}], "gpt-4o")
    three = counter.estimate_messages(
        [{"role": "system", "content": "hi"},
         {"role": "user", "content": "hi"},
         {"role": "assistant", "content": "hi"}], "gpt-4o")
    assert three.input_hi > one.input_hi


def test_tool_call_overhead():
    counter = HeuristicCounter()
    base = [{"role": "user", "content": "hi"}]
    with_tools = [{"role": "user", "content": "hi"},
                  {"role": "assistant", "content": "",
                   "tool_calls": [{"function": {"name": "f", "arguments": "{}"}}]}]
    assert counter.estimate_messages(with_tools, "gpt-4o").input_hi > \
        counter.estimate_messages(base, "gpt-4o").input_hi


def test_monotonic_longer_text_never_smaller():
    counter = HeuristicCounter()
    short = counter.estimate_messages([{"role": "user", "content": "短"}], "glm-4.6")
    long_est = counter.estimate_messages(
        [{"role": "user", "content": "长" * 500}], "glm-4.6")
    assert long_est.input_lo >= short.input_lo
    assert long_est.input_hi >= short.input_hi


def test_estimate_exchange_both_sides():
    request = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]}
    response = {"choices": [{"message": {"role": "assistant",
                                         "content": "world answer"}}]}
    est = HeuristicCounter().estimate_exchange(request, response)
    assert est.input_hi > 0 and est.output_hi > 0
    assert est.output_lo <= est.output_hi


def test_estimate_exchange_content_parts_list():
    counter = HeuristicCounter()
    msgs_flat = [{"role": "user", "content": "你好"}]
    msgs_parts = [{"role": "user",
                   "content": [{"type": "text", "text": "你好"}]}]
    a = counter.estimate_messages(msgs_flat, "gpt-4o")
    b = counter.estimate_messages(msgs_parts, "gpt-4o")
    assert (a.input_lo, a.input_hi) == (b.input_lo, b.input_hi)


def test_fuzz_never_negative_and_lo_le_hi():
    rng = random.Random(20260928)
    counter = HeuristicCounter()
    alphabet = "ab中。！１９Ｘｘ01 "
    for _ in range(200):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300)))
        messages = [{"role": "user", "content": text}]
        est = counter.estimate_messages(messages, rng.choice(
            ["deepseek-chat", "gpt-4o", "qwen-plus", "glm-4.6", "x-none"]))
        assert est.input_lo >= 0 and est.input_hi >= 0
        assert est.input_lo <= est.input_hi
        assert est.output_lo <= est.output_hi
        full = estimate_exchange({"messages": messages},
                                 {"choices": [{"message": {"content": text}}]})
        assert 0 <= full.input_lo <= full.input_hi
        assert 0 <= full.output_lo <= full.output_hi


def test_counter_for_strategies():
    assert counter_for("heuristic").strategy == "heuristic"
    assert counter_for("auto").strategy in ("heuristic", "tiktoken")
    with pytest.raises(ValueError):
        counter_for("bogus")


def test_tiktoken_unavailable_friendly_error(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "tiktoken", None)  # import 即抛 ImportError
    with pytest.raises(TiktokenUnavailable) as excinfo:
        TiktokenCounter()
    assert "pip install" in str(excinfo.value)


def test_tiktoken_exact_if_available_offline_cache():
    pytest.importorskip("tiktoken")
    try:
        counter = TiktokenCounter()
    except Exception as exc:  # noqa: BLE001 — encoding 未缓存且禁止联网下载 → 诚实跳过
        pytest.skip(f"tiktoken encoding 不可用（离线环境不下载）：{exc}")
    est = counter.estimate_messages([{"role": "user", "content": "hello world"}],
                                    "gpt-4o")
    assert est.strategy == "tiktoken" and est.confidence == "exact"
    assert est.input_lo == est.input_hi  # 精确模式无包围盒
    assert est.input_lo > 0


class TestIter3TiktokenGate:
    """ROADMAP iter3：族门禁、诚实降级、覆盖清单、预热。"""

    def test_tiktoken_unsupported_model_raises(self):
        """kimi/moonshot 等自有分词器模型族必须拒绝精确模式（负名单）。"""
        from tellan.recount import TiktokenCounter, TiktokenUnsupportedModel
        counter = TiktokenCounter()
        with pytest.raises(TiktokenUnsupportedModel):
            counter.estimate_exchange(
                {"model": "kimi-k2", "messages": [{"role": "user", "content": "hi"}]},
                {"choices": []}, "kimi-k2",
            )

    def test_tiktoken_exact_for_openai_model(self):
        """覆盖清单内模型：精确模式 lo==hi，confidence=exact。"""
        from tellan.recount import TiktokenCounter
        est = TiktokenCounter().estimate_exchange(
            {"model": "gpt-4o", "messages": [{"role": "user", "content": "hello world"}]},
            {"choices": [{"message": {"role": "assistant", "content": "hi there"}}]},
            "gpt-4o",
        )
        assert est.strategy == "tiktoken" and est.confidence == "exact"
        assert est.input_lo == est.input_hi and est.input_lo > 0

    def test_strategy_tiktoken_degrades_with_note(self):
        """--strategy tiktoken 遇不覆盖模型族 → 诚实降级 heuristic 并留痕。"""
        from tellan.reconcile import reconcile_record
        rec = {
            "seq": 1, "kind": "bench", "model": "deepseek-chat",
            "usage": {"prompt_tokens": 196, "completion_tokens": 12},
            "data": {"request": {"model": "deepseek-chat", "messages": [
                {"role": "user", "content": "中文内容" * 50}]},
                "response": {"choices": [{"message": {"content": "总结。"}}]}},
        }
        v = reconcile_record(rec, strategy="tiktoken")
        assert any("回退 heuristic" in n for n in v.estimate.notes)

    def test_tiktoken_family_negative_list(self):
        from tellan.recount import tiktoken_family
        assert tiktoken_family("gpt-4o") == "openai_o200k"
        assert tiktoken_family("gpt-3.5-turbo") == "openai_legacy"
        for name in ("kimi-k2", "moonshot-v1", "mistral-large", "grok-2", "yi-lightning"):
            assert tiktoken_family(name) is None, name

    def test_warmup_with_injected_loader(self):
        from tellan.recount import warmup_tiktoken
        calls: list[str] = []

        def fake_load(name: str) -> object:
            calls.append(name)
            return object()

        result = warmup_tiktoken(get_encoding=fake_load)
        assert result["ok"] is True and set(calls) == {"o200k_base", "cl100k_base"}

    def test_cli_warmup_smoke(self, monkeypatch, capsys):
        import tellan.cli as cli_mod
        import tellan.recount as rec_mod

        monkeypatch.setattr(rec_mod, "warmup_tiktoken",
                            lambda encodings=None: {"encodings": {"o200k_base": "OK"},
                                                    "cache_dir_env": "TIKTOKEN_CACHE_DIR",
                                                    "ok": True})
        rc = cli_mod.main(["warmup"])
        assert rc == 0 and "OK" in capsys.readouterr().out
