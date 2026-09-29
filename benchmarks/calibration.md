# 盒宽校准（iter3 交付物，脚本真实输出）

- 生成时间：2026-09-27T22:52:36+00:00
- 方法：tiktoken 精确复算 vs heuristic 点估计（`point_count`），比率 = 精确 / 点估计；建议倍率 = 比率的 [min, max] 外扩 10%。
- 诚实边界：只校准 tiktoken 覆盖清单内模型族；国产模型族无真值，包围盒倍率维持设计值 [0.5, 1.6] 并在下方如实列为「无法校准」。

## 逐 fixture 结果

| fixture | model | 输入精确/点估 | 输入入盒 | 输出精确/点估 | 输出入盒 |
|---|---|---|---|---|---|
| gpt-4o 英文代码 | gpt-4o | 107.0/77 (1.39x) | 是 | 12/13 (0.92x) | 是 |
| gpt-4o-mini 短问答 | gpt-4o-mini | 12.0/14 (0.87x) | 是 | 12/12 (0.98x) | 是 |

## 无法校准（诚实清单）

- deepseek-chat 中文问答（deepseek-chat，族 deepseek）：SKIP（覆盖清单外，无真值）
- deepseek-reasoner 带推理（deepseek-reasoner，族 deepseek）：SKIP（覆盖清单外，无真值）
- glm-4.6 中文长文（glm-4.6，族 glm）：SKIP（覆盖清单外，无真值）
- qwen-plus 中英混合（qwen-plus，族 qwen）：SKIP（覆盖清单外，无真值）
- gemini-2.5-flash thinking（报数膨胀 2x）（gemini-2.5-flash，族 gemini）：SKIP（覆盖清单外，无真值）
- claude-sonnet-4 缓存读写（claude-sonnet-4，族 anthropic）：SKIP（覆盖清单外，无真值）
- content:null 计费案例（OpenRouter 事件复现）（some-relay-model，族 unknown）：SKIP（覆盖清单外，无真值）
- kimi-k2 工具调用（kimi-k2，族 openai_legacy）：SKIP（tiktoken 失败）
- 中转站输入截断（报数缩水）（deepseek-chat，族 deepseek）：SKIP（覆盖清单外，无真值）

## 分族建议倍率

- **openai_o200k**（o200k_base，n=4）：比率 min/中位/max = 0.87/0.95/1.39；当前盒覆盖率 100%；建议倍率 ≈ [0.79, 1.53]（当前设计 [0.5, 1.6]；是否调整由人工决策，脚本只给证据）
