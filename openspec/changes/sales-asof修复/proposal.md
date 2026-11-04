# sales as_of 恒空修复 · 提案（微 change · 主会话直修）

> 2026-10-15 ｜ 发现于 query-sales-month过滤 change Step9 验证（既有疣，非该 change 回归）
> 用户拍板开工：与登录门禁（Change A）同日，本件先行直修

## 根因

`prism-api/main.py _live_meta` sales 分支查 `SELECT MAX(fetched_at) FROM sales_trim`，**该表无 fetched_at 列** → OperationalError 被 `except sqlite3.Error` 吞 → sales 的 as_of 恒为空串。工具契约"返回带 as_of"在销量维度从未兑现（reviews/config 两表有列，正常）。

## 修法（单一来源原则）

sales 分支改用 **/dash/as_of 端点同源口径**：最新"月末"批 `SELECT year, MAX(CAST(month AS INTEGER)) ... WHERE month LIKE '%月末' GROUP BY year ORDER BY year DESC LIMIT 1` → `f"{year}-{M}月末"`。月中批=价格快照零售滞后为空，但批存在即算数据时点（与看板显示一致，两处永不打架）。主文件改动一处函数，10 行级。

## 验收（全过）

1. pytest 15/15（新增 3 例：as_of 非空+形态 / 与 /dash/as_of 同源 / month 过滤不影响 as_of）
2. 活端点：`/dashboard/sales?...month=8` → `as_of: 2026-9月末`，retail=4436 不受影响
3. reviews/config 分支零触碰

## 直修声明

微 change（单函数 10 行 + 3 测），主会话直修不走子代理——用户拍板"做一个小的change"语境下适用；Step7 由既有测试+活端点复测代偿。
