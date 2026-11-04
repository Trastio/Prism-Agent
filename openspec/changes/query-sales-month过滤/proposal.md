# query_sales month 参数实装 · 提案（小 change）

> 2026-10-15 ｜ 清理记名债务：guardrails index.ts:270-271 "B1-6 month 债"
> Step1 explore 完成（主会话实测，链路与根因如下）

## 根因（实测）

链路：`query_sales(工具) → GET api:8002 /dashboard/sales?series_key=&year=&month= → main.py /dashboard/{dtype}`

**main.py:281 路由签名 `(dtype, request, series_key, series_id, year)` 根本没有 month 形参** → FastAPI 默认丢弃未知 query 参数 → 工具侧 index.ts:246 忠实发送 month 却被静默吞掉。B1-6 当时把工具描述里的 month 删了（不骗模型传参），execute 分支保留待清理。

## 修法（三层）

1. **api 路由**（prism-api/main.py `/dashboard/{dtype}`）：
   - 签名加 `month: int | None = None`（0-12 之外 → 400，fail-loud 不静默）
   - sales 月度聚合分支：SQL 追加 `AND CAST(TRIM(REPLACE(month,'月末','')) AS INTEGER)=?`（月末口径的既有 `month LIKE '%月末'` **原样保留在前面**——month 过滤只缩行集，不改口径）
   - sales group_by=spec 分支：行内过滤（正则取 month 前导数字 == 入参；**禁用 LIKE 'N月末'**——'1月末' 会误匹配 '11月末'）
2. **工具侧**（.pi/extensions/prism-guardrails/index.ts）：
   - query_sales schema 恢复 `month: { type: 'number', description: '月份 1-12，可选；只筛该月（月末行口径不变）' }`
   - B1-6 注释更新为"已实装（本 change）"，execute 分支 :246 不动（本来就对）
3. **测试**：prism-api/tests/ 加 3-4 例——month=8 只回 8 月行；month 过滤下月末口径不破（无月中行泄漏）；spec 分支 month 过滤正确（含 1 vs 11 陷阱）；month=13 → 400

## 红线注意

- 月末口径是销量红线：过滤只做行集缩减，`%月末` 限定必须仍在 SQL WHERE 中先生效
- 不动 eval/（B 包施工中）；不动 market_routes（那是看板页自己的 API，本债只涉及 agent 工具链）

## 验收

1. 单测全绿（新增 + prism-api 既有测试零回归）
2. 重启 api(8002) 后活端点实测：`/dashboard/sales?series_key=银河E5&year=2026&month=8` 恰返回 1 行月度聚合（4436 口径）且 `_meta.as_of` 在；month=9 返回空 rows（T7 口径债同理不编数）
3. spec 分支带 month 实测一轮
4. 工具描述含 month；重启网关后模型侧可传参（smoke 1 题即可）
