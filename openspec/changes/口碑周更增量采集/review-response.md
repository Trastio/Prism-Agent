# Step 8 · 审查处置（review-response，2026-11-01）

审查源：step7-review.md（P0×0 / P1×2 / P2×9 + 混入 2）。处置人：主会话（Step 8 直修）。

## 修复（已验证）

| # | 级 | 问题 | 处置 | 验证 |
|---|---|---|---|---|
| P1-1 | P1 | CLI 直跑 incremental 名单=pool 71 系 ≠ 库内全集 | `__main__` 按 mode 分支：incremental 未显式指定时传 None 交 recollect_all 解析（--pool-file 显式给定时照旧尊重） | 实跑 `--mode=incremental` → "库内有口碑全集 98 系" ✓ |
| P1-2 | P1 | prism.py 白名单拒空格形式带值参数（docstring 示例自相矛盾） | 白名单成对消费（--budget-reviews/--db 的空格形式 flag+值一起放行） | 实跑 `prism.py koubei-weekly --budget-reviews 200` → 正常透传 dry-run ✓ |
| P2-4 | P2 | `_last_weekly_success_utc` 无表库裸崩（catchup 无人值守路径） | OperationalError → 返回 None（语义=从未跑过→补跑→init_db 建表，自愈闭环） | 代码路径核 + 既有 catchup 测试零回归 |
| P2-2 | P2 | 退出码 3 声明未实现 | run_catchup 判定"不补跑"时 return 3（=无事可做） | 代码核 |
| P2-1 | P2 | page_all_known 空页 docstring 与实现矛盾 | docstring 更正（空页返回 False；调用方空页提前走自然停止） | 文档 |
| P2-5 | P2 | 库名单含 NULL/空 model_id 防御 | WHERE model_id IS NOT NULL AND TRIM(model_id)!='' | pytest |
| P2-7c | P2 | 永真化断言（or 优先级） | 改为两天数形态均可且必须命中 why | pytest |
| P2-8 | P2 | 施工报告分项数字错（190+15） | 更正 183+22（总数 205 本就对） | 文档 |
| P2-9a | P2 | 部署说明"舆情 02:00"与现役 03:00 不符 | 更正 + 注明实查来源 | 文档 |
| P2-3 | P2 | dry-run 非严格零写入（init_db 建表） | 部署说明如实声明（首跑建表幂等；不采纳"跳过 init_db"——代价大于收益） | 文档 |
| P2-7b | P2 | proposal 声明 prism 冒烟测试 vs tasks 未列（两规格不一致） | 裁决=以 tasks.md 为准（手动冒烟已实录），proposal 措辞更正 | 文档 |

修复后：**pytest 205/205 绿**（复跑）。

## 记录不修（留台账）

| # | 项 | 理由 |
|---|---|---|
| P2-6 | 锁探活超时按死锁清理（活锁覆盖风险） | 数据安全无虞（insert-skip 主键双保险+无删除路径），最坏=重复请求；改"超时拒跑"会引入 powershell 冷启动误拒跑的新风险，记录观察 |
| P2-7a | 入口主流程零测试（run_weekly 串联/backup_db/resolve_db_path 分支） | 编排层 mock 成本高；catchup/解析纯函数已测，live 首跑（Step 9）是主流程的第一次真实串联；后置补强 |
| P2-7d | finished_at aware→naive roundtrip 无测试 | 审查者受控实验实测健康；Step 9 首跑后端点实读即天然验证，顺手钉 |
| P2-9b | 台账不对称（SystemExit 分支写 error 行、Exception 分支不写） | 日志 BLOCKED/ERROR 行有兜底，排障不缺信息 |
| P2-9c | catchup 补跑被锁占用仍写日标记 | 语义可辩（当天确已判定），次日自愈 |
| P2-9e | 中断重连不省页（重探全部系） | 水位 1 页/系兜底，语义自洽；注记 |

## 混入项剥离（Step 10 归档注意）

- dash_series.html 的 tab 互换、dashboard_routes.py 的 122 车系过滤——工作树既有未提交改动（10-31 包），非本 change 产物，归档提交时按文件分离。

## Step 8 追加议题（主会话自查发现，非审查产出——用户 2026-11-01 拍板：两项全修）

1. **打标缺口 → 已修（加补扫）**：`_backfill_untagged()`——每系每周补打"有原文无标签"口碑至多 20 条（BACKFILL_TAG_LIMIT），关键词优先零成本；progress 记 `backfilled_tags`、stats 记 `backfilled_tags_total`；幂等复跑零补（测试钉死）。
2. **水位漏采窗 → 已修（连续 2 页）**：`WATERMARK_CONFIRM_PAGES=2`——单页已知继续翻，连续第 2 页全已知才停；乱序页计数清零；测试改造（单页不停/两页停/乱序自然尽三态）。

修复后全量测试 **206/206 绿**（205+补扫 1；水位两测试改造净零增），dry-run 冒烟实跑文案与 budget=200 正确。
