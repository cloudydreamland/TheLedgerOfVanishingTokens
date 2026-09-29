"""recount.py — 本地独立复算 token，输出包围盒而非点估计。

设计立场：非 OpenAI 模型的 tokenizer 是闭源的，任何"精确复算"都是撒谎。
``HeuristicCounter`` 诚实地给一个包围盒 ``[lo, hi]``——厂商报数落在盒内
不算错，落在盒外才报警。``TiktokenCounter`` 仅对 OpenAI 系模型提供精确
计数（可选依赖，离线环境不可用）。

不变量（fuzz 测试覆盖）：估计值永不为负；lo <= hi。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

# CJK 统一表意文字 + 扩展A + 兼容表意 + 日文假名 + 谚文 + CJK符号标点 + 全角形式 + 扩展B面
_CJK_RE = re.compile(
    "[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\uff00-\uffef\U00020000-\U0002ffff]"
)
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")

# 每个中文字符平均折算的 token 数（按族）。来源：对各家 tokenizer 的公开经验值，
# 属粗粒度先验，用于构造包围盒而非精确计数（见 README"诚实边界"）。
FAMILY_WEIGHTS: dict[str, float] = {
    "openai_legacy": 1.3,  # gpt-3.5/gpt-4 系 cl100k：中文≈1.3 tok/字
    "openai_o200k": 0.75,  # gpt-4o/o 系 o200k
    "deepseek": 0.6,
    "qwen": 0.85,
    "glm": 0.85,
    "gemini": 0.85,
    "anthropic": 1.0,
    "unknown": 1.0,  # 认不出族时用中性权重，并把 confidence 标 coarse
}

# 族归一化的子串匹配表（按顺序首个命中生效）。
FAMILY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("deepseek", ("deepseek",)),
    ("qwen", ("qwen", "qwq", "doubao", "seed")),
    ("glm", ("glm", "chatglm", "codegeex")),
    ("gemini", ("gemini", "gemma")),
    ("anthropic", ("claude",)),
    ("openai_o200k", ("gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "o4", "gpt-oss")),
    ("openai_legacy", ("gpt-4", "gpt-3.5", "gpt-3", "kimi", "moonshot", "mistral",
                       "grok", "minimax", "yi-")),
]

# 包围盒倍率：点估计 × [LO, HI]。低端覆盖"厂商分词更省"的情形，
# 高端覆盖"逐字切分/特殊 token 收费"的情形。
BOX_LO = 0.5
BOX_HI = 1.6

MESSAGE_FRAME_OVERHEAD_TOKENS = 4.0
TOOL_CALL_OVERHEAD_TOKENS = 8.0
ASCII_TOKENS_PER_WORD = 1.3


@dataclass
class TokenEstimate:
    """一次复算的包围盒结果。lo/hi 均为整数 token 数，lo <= hi。"""

    input_lo: int
    input_hi: int
    output_lo: int
    output_hi: int
    strategy: str
    confidence: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_lo": self.input_lo,
            "input_hi": self.input_hi,
            "output_lo": self.output_lo,
            "output_hi": self.output_hi,
            "strategy": self.strategy,
            "confidence": self.confidence,
            "notes": list(self.notes),
        }


def model_family(model: str | None) -> str:
    """按模型名猜 tokenizer 族；认不出返回 unknown。"""
    name = (model or "").lower()
    for family, patterns in FAMILY_PATTERNS:
        if any(p in name for p in patterns):
            return family
    return "unknown"


def count_cjk_chars(text: str) -> int:
    return len(_CJK_RE.findall(text))


def count_ascii_words(text: str) -> int:
    return len(_ASCII_WORD_RE.findall(text))


def message_text(message: dict[str, Any]) -> tuple[str, int]:
    """抽取一条 message 的文本与工具调用数。兼容 str / 分块 content。"""
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    tool_calls = message.get("tool_calls") or []
    n_tools = len(tool_calls) if isinstance(tool_calls, list) else 0
    for tc in tool_calls if isinstance(tool_calls, list) else []:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            for key in ("name", "arguments"):
                if isinstance(fn.get(key), str):
                    parts.append(fn[key])
    return "".join(parts), n_tools


def point_count(text: str, family: str, n_messages: int = 0, n_tools: int = 0) -> float:
    """族权重点估计：CJK×权重 + ASCII 词×1.3 + 框架开销 + 工具开销。"""
    weight = FAMILY_WEIGHTS.get(family, FAMILY_WEIGHTS["unknown"])
    raw = count_cjk_chars(text) * weight + count_ascii_words(text) * ASCII_TOKENS_PER_WORD
    raw += n_messages * MESSAGE_FRAME_OVERHEAD_TOKENS
    raw += n_tools * TOOL_CALL_OVERHEAD_TOKENS
    return raw


def _box(point: float) -> tuple[int, int]:
    """点估计 → 包围盒；永不为负，且保证 lo<=hi（point=0 时 box=(0,0)）。"""
    p = max(0.0, point)
    lo = math.floor(p * BOX_LO)
    hi = math.ceil(p * BOX_HI)
    return lo, hi


class HeuristicCounter:
    """默认估计器：族权重启发式，输出包围盒，confidence 恒为 "coarse"。"""

    strategy = "heuristic"
    confidence = "coarse"

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(FAMILY_WEIGHTS)
        if weights:
            self.weights.update(weights)

    def estimate_messages(self, messages: list[dict[str, Any]], model: str) -> TokenEstimate:
        """对请求 messages（输入侧）做包围盒估计。"""
        family = model_family(model)
        text_parts: list[str] = []
        n_tools = 0
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            text, n = message_text(msg)
            text_parts.append(text)
            n_tools += n
        point = point_count("".join(text_parts), family, len(messages or []), n_tools)
        if family == "unknown":
            note = f"未知模型族 {model!r}，使用中性权重 1.0，包围盒加宽"
        else:
            note = f"族 {family}，权重 {self.weights[family]} tok/CJK字"
        lo, hi = _box(point)
        return TokenEstimate(lo, hi, 0, 0, self.strategy, self.confidence, [note])

    def estimate_exchange(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        model: str | None = None,
    ) -> TokenEstimate:
        """从完整请求/响应抽取文本，同时估计输入与输出两侧。"""
        model = model or request.get("model") or response.get("model") or ""
        in_est = self.estimate_messages(request.get("messages") or [], model)
        family = model_family(model)
        out_parts: list[str] = []
        for choice in response.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message") or choice.get("delta") or {}
            text, _ = message_text(msg)
            out_parts.append(text)
        out_text = "".join(out_parts)
        n_out_tools = sum(
            len((c.get("message") or {}).get("tool_calls") or [])
            for c in response.get("choices") or []
            if isinstance(c, dict)
        )
        n_out_choices = len([c for c in response.get("choices") or [] if isinstance(c, dict)])
        out_point = point_count(out_text, family, n_out_choices, n_out_tools)
        out_lo, out_hi = _box(out_point)
        notes = list(in_est.notes)
        if family == "unknown":
            notes.append("输出侧同用中性权重")
        return TokenEstimate(
            in_est.input_lo, in_est.input_hi, out_lo, out_hi,
            self.strategy, self.confidence, notes,
        )


class TiktokenCounter:
    """OpenAI 系精确计数（可选依赖 tiktoken）。

    import 失败时抛 :class:`TiktokenUnavailable`，报错信息给出安装指引。
    注意：tiktoken 首次加载 encoding 文件需要本地缓存或网络，离线环境
    请预热缓存（``tellan warmup`` 或 ``TIKTOKEN_CACHE_DIR``）后使用。

    **族门禁（iter3 决议）**：模型族不在 :data:`TIKTOKEN_COVERAGE` 内时抛
    :class:`TiktokenUnsupportedModel`（不再静默套用 o200k_base——用 OpenAI
    分词器数 DeepSeek 还标"精确"是撒谎）。调用方（reconcile）捕获后降级
    heuristic 包围盒并在 notes 留痕，行为裁决已文档化：docs/tiktoken.md。
    """

    strategy = "tiktoken"
    confidence = "exact"

    _ENCODINGS: ClassVar[dict[str, str]] = {
        "openai_o200k": "o200k_base",
        "openai_legacy": "cl100k_base",
    }

    def __init__(self) -> None:
        try:
            import tiktoken
        except ImportError as exc:  # pragma: no cover - 取决于环境
            raise TiktokenUnavailable(
                "tiktoken 未安装。精确复算仅支持 OpenAI 系模型，"
                "请先 `pip install 'tellan[tiktoken]'`，"
                "或在 heuristic 包围盒模式下使用任意模型。"
            ) from exc
        self._tiktoken = tiktoken
        self._enc_cache: dict[str, Any] = {}

    def _encoding_for(self, model: str) -> str:
        family = tiktoken_family(model)
        if family is None:
            raise TiktokenUnsupportedModel(
                f"模型 {model!r} 不在 tiktoken 覆盖清单内（含 kimi/moonshot 等自有"
                f"分词器模型族的负名单），精确计数不可用。覆盖范围：{TIKTOKEN_COVERAGE}。"
                "套用 OpenAI 分词器会产生系统性偏差，请改用 auto/heuristic（包围盒）。"
            )
        return self._ENCODINGS[family]

    def _count(self, text: str, model: str) -> int:
        enc_name = self._encoding_for(model)
        enc = self._enc_cache.get(enc_name)
        if enc is None:
            enc = self._tiktoken.get_encoding(enc_name)
            self._enc_cache[enc_name] = enc
        return len(enc.encode(text))

    def estimate_messages(self, messages: list[dict[str, Any]], model: str) -> TokenEstimate:
        total = 0
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            text, _ = message_text(msg)
            total += self._count(text, model)
            total += MESSAGE_FRAME_OVERHEAD_TOKENS
        return TokenEstimate(total, total, 0, 0, self.strategy, self.confidence,
                             [f"tiktoken 精确计数（{self._encoding_for(model)}）"])

    def estimate_exchange(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        model: str | None = None,
    ) -> TokenEstimate:
        model = model or request.get("model") or response.get("model") or ""
        in_est = self.estimate_messages(request.get("messages") or [], model)
        out_total = 0
        for choice in response.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message") or choice.get("delta") or {}
            text, _ = message_text(msg)
            out_total += self._count(text, model)
            out_total += int(MESSAGE_FRAME_OVERHEAD_TOKENS)
        return TokenEstimate(
            in_est.input_lo, in_est.input_hi, out_total, out_total,
            self.strategy, self.confidence, list(in_est.notes),
        )


class TiktokenUnavailable(ImportError):
    """tiktoken 不可用时的友好报错。"""


class TiktokenUnsupportedModel(TiktokenUnavailable):
    """``--strategy tiktoken`` 但模型族不在覆盖清单内。

    与"库没装"区分开：这是"装了但精确计数对该模型族无意义"。调用方应降级
    heuristic 并留痕（reconcile 已实现），不要静默套用 OpenAI 分词器。
    """


#: tiktoken 精确模式的覆盖清单（族 → encoding 与代表性模型）。
#: 判定走 :func:`model_family`；第三方 OpenAI 兼容端点只要透传 OpenAI 模型名
#: 即视为覆盖（分词器由模型决定，不由渠道决定）。国产模型族一律不在列——
#: 它们用自己的分词器，拿 tiktoken 数是错的。
TIKTOKEN_COVERAGE: dict[str, dict[str, str]] = {
    "openai_o200k": {
        "encoding": "o200k_base",
        "examples": "gpt-4o / gpt-4o-mini / gpt-4.1 / o3 / o4-mini / chatgpt-4o-latest",
    },
    "openai_legacy": {
        "encoding": "cl100k_base",
        "examples": "gpt-3.5-turbo / gpt-4 / gpt-4-turbo / text-embedding-3-*",
    },
}


#: heuristic 权重族与 tiktoken 覆盖是两回事：kimi/moonshot 等在权重上近似
#: openai_legacy（包围盒用途），但它们有**自有分词器**，精确模式必须拒绝。
_NON_TIKTOKEN_PATTERNS: tuple[str, ...] = ("kimi", "moonshot", "mistral", "grok",
                                           "minimax", "yi-")


def tiktoken_family(model: str | None) -> str | None:
    """tiktoken 覆盖判定：返回覆盖族名，不覆盖返回 None。

    先过负名单（自有分词器模型族），再查覆盖清单。
    """
    name = (model or "").lower()
    if any(p in name for p in _NON_TIKTOKEN_PATTERNS):
        return None
    family = model_family(name)
    return family if family in TIKTOKEN_COVERAGE else None


def warmup_tiktoken(
    encodings: list[str] | None = None,
    get_encoding: Any = None,
) -> dict[str, Any]:
    """预热 tiktoken encoding 缓存（离线 CI 先在有网步骤跑一次）。

    ``get_encoding`` 可注入（测试用）。返回每个 encoding 的加载状态与
    缓存目录提示（``TIKTOKEN_CACHE_DIR`` 可重定向）。
    """
    try:
        import tiktoken  # noqa: F401 - 仅确认可导入
    except ImportError as exc:
        raise TiktokenUnavailable(
            "tiktoken 未安装：`pip install 'tellan[tiktoken]'` 后再预热"
        ) from exc
    names = encodings or sorted({v["encoding"] for v in TIKTOKEN_COVERAGE.values()})
    load = get_encoding or __import__("tiktoken").get_encoding
    results: dict[str, str] = {}
    for name in names:
        try:
            load(name)
            results[name] = "OK"
        except Exception as exc:  # noqa: BLE001 - 下载失败/网络不可达都要如实报告
            results[name] = f"FAIL: {exc!r}"
    return {
        "encodings": results,
        "cache_dir_env": "TIKTOKEN_CACHE_DIR",
        "ok": all(v == "OK" for v in results.values()),
    }


def estimate_exchange(
    request: dict[str, Any],
    response: dict[str, Any],
    model: str | None = None,
) -> TokenEstimate:
    """便捷入口：用默认 HeuristicCounter 做一次完整交换的包围盒估计。"""
    return HeuristicCounter().estimate_exchange(request, response, model)


def counter_for(strategy: str = "auto") -> HeuristicCounter | TiktokenCounter:
    """按策略选择计数器。auto：能装 tiktoken 且可用则精确，否则包围盒。"""
    if strategy == "heuristic":
        return HeuristicCounter()
    if strategy == "tiktoken":
        return TiktokenCounter()
    if strategy == "auto":
        try:
            return TiktokenCounter()
        except TiktokenUnavailable:
            return HeuristicCounter()
    raise ValueError(f"未知策略 {strategy!r}，可选 auto|heuristic|tiktoken")
