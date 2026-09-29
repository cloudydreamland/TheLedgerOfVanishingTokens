# tiktoken 精确模式：覆盖面、降级行为与 CI 策略（ROADMAP iter3 交付物）

> 覆盖清单与行为决议（2026-09-28 夜间，iter3）。校准数据见
> [benchmarks/calibration.md](../benchmarks/calibration.md)（脚本真实输出）。

## 一、覆盖清单（谁能用 `--strategy tiktoken`）

| 模型族 | encoding | 代表模型 | 判定 |
|---|---|---|---|
| `openai_o200k` | `o200k_base` | gpt-4o / gpt-4o-mini / gpt-4.1 / o3 / o4-mini | ✅ 精确 |
| `openai_legacy`（真 OpenAI 系） | `cl100k_base` | gpt-3.5-turbo / gpt-4 / gpt-4-turbo | ✅ 精确 |
| **负名单**（自有分词器，heuristic 权重族碰巧同箱但**绝不**精确计数） | — | kimi / moonshot / mistral / grok / minimax / yi-* | ❌ 强制拒绝 |
| deepseek / qwen / glm / gemini / anthropic / unknown | — | 同名模型 | ❌ 覆盖外 |

- **第三方 OpenAI 兼容端点**：分词器由模型决定、不由渠道决定。中转站透传
  `gpt-4o` 模型名 → 覆盖；透传 `deepseek-chat` → 覆盖外。
- **为什么有负名单**：heuristic 权重族把 kimi/moonshot 等并入 `openai_legacy`
  （包围盒用途合理），若精确模式复用该族就会拿 cl100k 硬数 Kimi 文本还标
  "exact"——校准脚本实测这种偏差可达 3 倍（kimi 工具调用 fixture）。

## 二、行为决议：降级并留痕（不报错）

`--strategy tiktoken` 遇到覆盖外/负名单模型 → **自动降级 heuristic 包围盒**，
`estimate.notes` 留痕"精确模式不可用，回退 heuristic（包围盒）：模型 … 不在
tiktoken 覆盖清单内…"。理由：审计批处理不该因一条非 OpenAI 记录整体失败；
诚实性由留痕与 `confidence` 字段保证（降级后 confidence=coarse）。该决议由
`reconcile_record` 统一实现并有测试锁定（`TestIter3TiktokenGate`）。

## 三、encoding 缓存预热与 CI 策略

tiktoken 首次加载 encoding 需要网络下载（缓存到本地目录，可用
`TIKTOKEN_CACHE_DIR` 重定向）。三种 CI 方案（按推荐排序）：

1. **预热步骤 + 缓存目录**：有网步骤跑 `tellan warmup`（加载覆盖清单全部
   encoding）→ 把缓存目录存 artifact → 离线步骤设 `TIKTOKEN_CACHE_DIR` 挂回。
2. **黄金数字**：提交 `benchmarks/calibration.md` 的实测真值（已做），离线 CI
   只跑 heuristic 路径 + 断言黄金数字文件未被手改（由脚本再生成比对）。
3. **CI 不装 tiktoken**：`pytest.importorskip` 路径自动跳过精确模式测试
   （现状已支持）。

## 四、校准结论摘要（详表见 calibration.md）

- gpt-4o（o200k）：输入比率 1.39x、输出 0.92x——当前盒 [0.5, 1.6] 覆盖。
- gpt-4o-mini（o200k）：0.87x / 0.98x——覆盖。
- **诚实更正**：gpt-4o / gpt-4o-mini 两个 fixture 的"厂商风格报数"构建时是按
  heuristic 点估计填的，tiktoken 可用后戳穿其为合成值——已改为实测真值，
  并在 fixture 注释中说明来历（教训见 WORKLOG iter3）。
- 国产模型族（deepseek/glm/qwen/gemini/claude/kimi）**无真值，无法校准**，
  包围盒倍率维持设计值 [0.5, 1.6]，脚本在 calibration.md 中如实列为
  「无法校准」而不是编数字。
