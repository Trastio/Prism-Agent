# Step 3 · 任务清单（口碑周更增量采集）

## 拍板记录（2026-11-01 用户）

| # | 项 | 拍板 |
|---|---|---|
| 1 | 周更频率 | 全池周更（否掉月度滚动默认案与日更分级案） |
| 2 | 名单口径 | **库内有口碑全集（≈96 系）**，不按销量分层 |
| 3 | 周帽默认 | **200 条**（全池新入库条数，触顶 budget_capped 早退） |
| 4 | 看板时点戳 | **本期最小做**（只读端点 + dash_series 一行） |
| 5 | 调度形态 | **像舆情那样自己更新**：Interactive 周任务 + onlogon 补跑，免管理员双任务 |
| 6 | 打标补扫（Step 8 加固） | **加**：周更跑内每系补打"有原文无标签"口碑，每系每周 ≤20 条（防覆盖率侵蚀） |
| 7 | 水位加固（Step 8 加固） | **连续 2 页全已知才停**（防翻页乱序滑深漏采，代价 ~+1 页/系） |
| — | 出圈 | 月度缺口扫描（单月 vs 3月合计）另立 change；异动简报二期；Atuohome 内部不探 |

## 施工任务（Step 5，fork 型子代理）

- T1 `recollect_koubei_with_full.py` 增量模式：`--mode=incremental`（full 语义零改动）——水位整页已知即停 / insert-skip 只插新 / 零删除断言 / `--budget-reviews` 全池帽
- T2 入口脚本 `scripts/koubei_weekly_update.py`：自动备份（sqlite backup API）→ 全池名单 → 增量跑 → collection_runs 台账 → 语义退出码 0/1/2/3 → already_running 锁 → `--catchup` 新鲜度自检（8 天阈值 + 日标记幂等 + Asia/Shanghai 固定时区）
- T3 `collection_runs` ORM 表（init_db 建表）+ `GET /dash/koubei/last-run` 只读端点 + `dash_series.html` 口碑区"口碑更新至"一行
- T4 `prism.py koubei-weekly` 薄子命令（subprocess 调 T2；dry-run 缺省、--live 门控）
- T5 测试 `tests/test_recollect_weekly.py`：水位停止纯函数 / insert-skip 幂等（二次跑零新增）/ budget_capped / 零删除断言 / 台账落痕 / catchup 判定纯函数（含时区边界）；既有测试零回归
- T6 schtasks 注册命令两条（PrismKoubeiWeekly 周日 04:00 / PrismKoubeiCatchup onlogon）写入本 change 部署说明

## 验收（Step 9）

1. dry-run 全池预估（零写入零出网）；
2. **ID 稳定性验证跑**：跑前全库 review_id 集合哈希落档 → live 增量 → 旧 ID 零丢失 + 新增数=台账；
3. 存量零扰动抽查 diff；
4. 同周二次跑幂等（new≈0，请求≈96 页打底）；
5. 出口闸抽验：query_reviews 的 supported_by 新旧 review_id 均可复算；
6. pytest 全量回归绿 + 注册双任务（与用户一起执行）。

## 审查（Step 7）：general-purpose 磁盘自读（代码全文，不给设计结论）
