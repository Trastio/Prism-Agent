# verification · sales as_of 修复（2026-10-15）

| 项 | 结果 |
|---|---|
| pytest 全量 | **15/15 绿**（新增 3：非空+形态 / 与 /dash/as_of 同源 / month 过滤不劫持 as_of） |
| 活端点 | `/dashboard/sales?…month=8` → `as_of: 2026-9月末`、retail=4436（修复前 as_of=''） |
| 同源锁 | 单测断言 /dashboard/sales._meta.as_of == /dash/as_of.sales（两处永不打架） |
| 回归 | reviews/config 分支零触碰；month change 12 例全数保持绿 |

主会话直修（微 change 声明见 proposal）；api 已重启生效。
