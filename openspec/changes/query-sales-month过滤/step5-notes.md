# query_sales month 实装 · Step5 施工笔记（2026-10-15）

## 改动文件（3）

| 文件 | 改动 |
|---|---|
| `prism-api/main.py` | ①:281 路由签名加 `month: int \| None = None` + 1-12 校验（fail-loud 400）②sales group_by=spec 分支：行内 `re.match(r'^(\d+)')` 前导数字过滤（禁 LIKE 'N月末'，1/11 陷阱）③月度聚合分支：SQL 追加 `AND CAST(TRIM(REPLACE(month,'月末','')) AS INTEGER)=?`（`%月末` 口径限定原样保留在前） |
| `.pi/extensions/prism-guardrails/index.ts` | :267-273 query_sales schema 恢复 `month` 参数（"月份 1-12，可选；只筛该月（月末行口径不变）"）；B1-6 债注释改为"已清" |
| `prism-api/tests/test_dashboard_sales_month.py` | 新增 5 例（见下） |

## 测试输出（原样）

```
cd prism-api && python -m pytest tests/ -q
.......... [100%]
10 passed in 5.01s
```
（既有 test_export_api 5 例 + 新增 month 5 例 = 10，零回归）

新增 5 例：月度聚合子集零回归（含 E5 2026-8=4436 真值锚）/ 不存在月→空 rows（动态选缺失月，全 12 月有数据则 skip）/ spec 过滤子集+1/11 陷阱回归锁 / month=13 与 0 → 400 / reviews 分支带 month 参数无副作用。

## 活端点实测（重启 api 单服务后，PID 24952 → 新进程；复刻 launch() 语义，其余五服务未动，gateway/dashboards 探活 200 复核）

| 请求 | 结果 |
|---|---|
| `?series_key=银河E5&year=2026&month=8` | 200，恰 1 行：`retail_sum=4436, row_count=5, tp_avg=106754.67`（金标锚吻合） |
| `?...&month=9` | 200，1 行：`retail_sum=null, tp_avg=106378.0`（全 NULL 聚合语义，与无 month 时同现——既有行为，如实呈现不编数） |
| `?...&month=13` | 400 `month must be 1-12, got 13` |
| `?group_by=spec&month=8` | 200，15 行，月形态集合 = `['8月末']`（月末口径无泄漏，无月中/他月混入） |

## 如实声明（proposal 验收 2 的预测修正）

proposal 写"month=9 返回空 rows"——实测为**1 行 retail_sum=null**：SUM 对全 NULL 组返回 NULL 行是既有聚合语义（无 month 参数时该行同样在结果里），非本 change 引入。agent 侧看到 null 即"库内无零售"，与 sales-11/12 金标口径一致，不构成编数风险。

## 工具侧生效说明

index.ts 的 schema 在 pi.exe spawn 时读取：**新起的 pi 进程即生效，已在跑的 pi 会话仍是旧 schema；网关重启可强刷**（按指令未重启网关，留主会话决定时机）。

## 未尽项

无阻塞项。netstat 输出为 GBK（text=True 会 UnicodeDecodeError）——与 prism.py 记忆坑同源，本笔记留档。
