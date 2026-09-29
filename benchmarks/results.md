# benchmarks/results.md — Tellan v0.1.0rc1 内置基准真实结果

> 生成方式：`python -m tellan.cli bench`（脚本输出原文粘贴，数字未手工修改）。
> 环境：Windows 11 / Python 3.13.2 / 单线程纯 CPU / 无网络。
> **诚实声明**：全部 fixture 为合成文本与手工标注的"厂商风格"报数，用于验证
> 检测管线本身，不声称度量任何真实厂商的真实行为。价格表为快照（见 README）。

## 汇总指标（真实脚本输出）

- fixture 数：11（全部合成，见上方诚实声明）
- 容差包围盒覆盖率（报数∈[lo×0.9, hi×1.25] 且输出侧同）：72.7%
- 输入侧盒内覆盖率：90.9%
- 输出侧盒内覆盖率：81.8%
- EMPTY_CONTENT_BILLED 检出：1/1
- 预期裁决命中：2/2
- 预期异常命中：2/2
- 总耗时：2.7 ms（平均 0.245 ms/条，单线程纯 CPU）

## 逐 fixture 明细

| fixture | model | 裁决 | 报数(in/out) | 输入盒 | 输出盒 | 异常 | 耗时ms |
|---|---|---|---|---|---|---|---|
| deepseek-chat 中文问答 | deepseek-chat | OK | 196/12 | [83,266] | [3,12] | - | 0.304 |
| deepseek-reasoner 带推理 | deepseek-reasoner | OK | 200/86 | [83,266] | [3,87] | OPAQUE_REASONING | 0.214 |
| gpt-4o 英文代码 | gpt-4o | OK | 110/20 | [38,123] | [6,21] | - | 0.164 |
| glm-4.6 中文长文 | glm-4.6 | OK | 700/18 | [226,725] | [7,23] | - | 0.237 |
| qwen-plus 中英混合 | qwen-plus | OK | 60/22 | [17,56] | [8,29] | - | 0.17 |
| gemini-2.5-flash thinking（报数膨胀 2x） | gemini-2.5-flash | SUSPECT_INFLATED | 180/1200 | [116,374] | [4,314] | OPAQUE_REASONING,TOKEN_INFLATION | 0.213 |
| claude-sonnet-4 缓存读写 | claude-sonnet-4 | OK | 320/10 | [137,439] | [5,18] | - | 0.233 |
| content:null 计费案例（OpenRouter 事件复现） | some-relay-model | SUSPECT_INFLATED | 180/345 | [137,439] | [2,7] | EMPTY_CONTENT_BILLED,PRICE_MISSING,TOKEN_INFLATION | 0.589 |
| gpt-4o-mini 短问答 | gpt-4o-mini | OK | 16/12 | [6,22] | [6,20] | - | 0.163 |
| kimi-k2 工具调用 | kimi-k2 | OK | 14/28 | [6,21] | [9,30] | - | 0.169 |
| 中转站输入截断（报数缩水） | deepseek-chat | SUSPECT_DEFLATED | 40/8 | [160,514] | [3,11] | TOKEN_DEFLATION | 0.201 |

## 结果解读（对应上面真实数字）

- **容差包围盒覆盖率**中未命中的 3 条全部是**故意操纵**的 fixture
  （报数膨胀 2x、content:null 计费、中转站输入截断）——检测管线把它们的
  裁决与异常全部命中（预期裁决 2/2、预期异常 2/2）。
- 8 条诚实标注报数 100% 落在容差盒内，说明盒宽 [0.5x, 1.6x] × 容差
  [0.9, 1.25] 对"厂商风格"数字没有系统性误报。
- 单条对账耗时亚毫秒级，1000 条账本的审计成本可忽略（见测试
  `test_perf_1000_appends_smoke`）。

## 局限（诚实）

- 启发式对**代码类英文文本**偏保守（o200k 按子词与符号切分，词数×1.3 会
  低估），gpt-4o fixture 的"诚实报数"因此标注在盒内偏上沿。
- reasoning_tokens 属不可见消耗，无法复算；当前做法是并入输出盒上沿并给
  OPAQUE_REASONING info 提示，而非假装能算。
- 若安装 `tellan[tiktoken]`，OpenAI 系模型可切精确模式（`--strategy
  tiktoken`），但其余模型族仍是包围盒。
