# new-api / one-api 账目导入指南（ROADMAP iter2 交付物）

> 字段依据：两家仓库 main 分支 `model/log.go` 的 Log 结构体（2026-09-28 实抓）。
> 本文档说明如何把中转站的账目导出导入 tellan 账本，再做对账。

## 一、导出路径

**路径 A（推荐，可编程）：API 拉取 JSONL。** 用你的站内令牌调日志接口，把返回的
JSON 数组逐行落成 `.jsonl`：

```bash
# new-api / one-api 同族日志接口（分页参数见你部署版本的 API 文档）。
# 注意：new-api 当前版本经 common.ApiSuccess + pageInfo 返回，条目在 data.items；
# 旧版/one-api 直接在 data。下面的提取脚本两种形态都兼容：
curl -s -H "Authorization: Bearer <系统访问令牌>" \
  "https://你的中转站/api/log/?p=1&page_size=100&type=2" \
  | python -c "import json,sys; d=json.load(sys.stdin)['data']; items=d['items'] if isinstance(d,dict) and 'items' in d else d; [print(json.dumps(r, ensure_ascii=False)) for r in items]" \
  >> logs.jsonl   # 有多页就翻页追加

tellan import logs.jsonl -l ledger.jsonl
```

**路径 B：UI 导出 CSV。** 部分版本的日志/看板页有导出按钮，导出的 CSV（含
Excel 的 UTF-8 BOM，已处理）可直接导入：

```bash
tellan import logs.csv -l ledger.jsonl
```

> 诚实说明：各部署版本 UI 差异较大，我们无法逐一核实"导出按钮"的形态与列名，
> 路径 B 的列名匹配靠内置别名表 + `--mapping` 兜底；**路径 A 是权威路径**。

## 二、字段映射表（Log 结构体 → tellan 账本记录）

| 导出字段（JSON 键） | 账本字段 | 说明 |
|---|---|---|
| `model_name` | `model` | 缺失 → 整行跳过（对账无意义） |
| `prompt_tokens` / `completion_tokens` | `usage.prompt_tokens` / `usage.completion_tokens` | 字符串/千分位宽容转换；双缺失跳过 |
| `created_at` | `ts` | 秒/毫秒/ISO 统一为 UTC ISO（毫秒精度）；**导入保留原始时间，不被导入时刻覆盖** |
| `request_id` | `request_id` | 缺失 → 合成 `imp-<sha12>`（同内容必同 id，meta 标 `request_id_synth`） |
| `upstream_request_id`（new-api） | `meta.upstream_request_id` | 中转站声称的上游 id——**它本身可造假**，仅作线索 |
| `quota` | `meta.quota` / `meta.quota_usd_est` | 站内点数，按 `quota_per_unit` 折算美元（est 后缀=估值） |
| `type` | （过滤） | 仅 `type==2`（消费）入账；充值 1/管理 3/错误 5/退款 6 等跳过并计数；中文词（"消费"）宽容入账并留痕 `meta.type_raw` |
| `use_time`（new-api）/ `elapsed_time`（one-api） | `meta.use_time` | **原样保留不换算**（new-api 秒、one-api 毫秒，两站口径不同，换算才是造假） |
| `username` / `token_name` / `channel` / `is_stream` / `content` | `meta.*` | `content` 是系统生成的描述文本（倍率/tokens 摘要），截断 200 字符留存 |
| `other`（new-api） | （未解析） | 站点自定义 JSON 字符串，各家内容不一，暂不解析（诚实：不知道里面是什么就不假装知道） |

CSV 中文列头（"模型名称/提示 tokens/补全 tokens/时间/额度/请求ID/类型"等）已内置
映射；部署版本列名不同时用 `--mapping '{"prompt_tokens": ["input_tokens"]}'` 覆盖
（与内置表合并，用户别名优先场景请把完整别名表写出）。

## 三、已知坑（如实清单）

1. **`quota_per_unit` 部署可配**。默认 500000 点 = $1，但站长可改。`quota_usd_est`
   只在确认你站的换算基数时才有意义：`--quota-per-unit <你的基数>`。
2. **导出只是"卖方账本"**。中转站导出的日志就是它自己的记账，导入对账回答的是
   "这份账本身自洽吗、和官方 API 报数一致吗"，不能证明站点没有账外记录。
3. **`type` 语义两家有差**（one-api 的 5=Test，new-api 的 5=Error），但**消费行
   都是 2**，过滤逻辑兼容；非数字类型宽容入账（见映射表）。
4. **秒/毫秒混杂**：Unix 时间戳自动判别（>1e11 视为毫秒）；如果你的部署返回了
   微秒（罕见），时间会偏早——发现请开 issue。
5. **Excel CSV 的坑已处理**：UTF-8 BOM、千分位逗号、字符串数字。xlsx **不支持**
   （需要第三方依赖，违背零必装原则）——请先另存为 CSV。
6. **入库 ≠ 复算可用**：导入记录只有报数没有原文（导出里本来就没有），`audit`
   时策略自动退化为"报数 vs 价格表 + 异常检测"，裁决多为 `INSUFFICIENT_DATA`
   或命中异常检测器——这是诚实降级，不是 bug。要全量复算请用 `tellan proxy`
   捕获自己的流量。
7. **内容完全相同的行 → 相同合成 id → 对账时 DUP_REQUEST_ID 会命中**。
   这是特性语义：同一批导出里出现两行一模一样的消费记录，本身就是可疑账目；
   但若你的站点确实会产生合法的重复行，请先在导出侧去重再导入。
8. **导入的历史账本 + 现行价格表 = 时间错位**：价格快照是"今天"的，审去年的
   账会拿今天的价（`quota_usd_est` 不受影响，它是站内点数折算）。修复计划见
   ROADMAP iter9（时间戳匹配价格）。

## 四、退出码

- `0`：全部行入账，无跳过
- `1`：导入完成但有跳过行（见摘要，逐条给出行号与原因）
- `2`：文件不可读 / 格式不识别 / 映射文件损坏
