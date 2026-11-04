# Step 2 · 方案（口碑周更增量采集，2026-11-01）

> 拍板已定（用户 2026-11-01）：**全池周更**。本方案实现该口径；单月 vs 3月合计窗归月度滚动缺口扫描（§8），明确出圈。

## 1. 目标

每周夜跑窗口一次：按车系抓**新口碑**入库+打标，不删不改任何既有行（出口闸 supported_by 行 ID 永不断链），预算帽触顶早退留痕，跑后台账落库、看板可示"口碑更新至 X 月 X 日"。

## 2. 设计

### 2.1 增量模式（复用 recollect 脚本，加模式开关）

`recollect_koubei_with_full.py` 新增 `--mode=incremental`（缺省 full 保持现役语义不变）：

- **名单**：`SELECT DISTINCT model_id FROM owner_reviews`（库内有口碑的车系全集 ≈96 系；不按销量分层）。
- **水位停止**：每系从第 1 页翻起；某页 items 的 review_id **全部已存在于库** → 该系停止（对翻页非严格稳定排序鲁棒）；翻到 pagecount 或连续空页也停（沿用限流冷却重试语义）。
- **只插新**：已知 review_id 在列表阶段即跳过（不抓详情页不打标）；新条目抓详情页原文 + 入库 + 打标（insert-skip：主键已存在跳过，不 UPDATE 不 DELETE）。
- **守卫按模式区分**：incremental = 纯插入，不适用"≥100 存量池拦截"（那守卫防的是 delete 破坏）；新守卫=断言"本跑删除行数恒为 0"（事务后置校验，非零即回滚+fail-closed）。full 模式守卫原样保留。
- **备份**：live 前自动 `sqlite3.backup()` 到 `data/backups/autohome-pre-weekly-{ts}.db`（不再依赖"存在旧备份"探测）；备份失败拒跑。
- **progress**：独立文件 `data/weekly_progress.jsonl`（与深采 progress 分家，语义不同：每周一文件按周滚动保留最近 N=8 份）。

### 2.2 预算帽（照舆情 budget_capped 语义）

- `--budget-reviews N`：全池**新入库**条数总帽（缺省 200）。触顶 → 未开始的车系标 `budget_capped` 早退，progress+台账留痕，exit 0（正常终态）。
- 速率护栏沿用：semaphore 3 + `--series-delay`（缺省 5s，比深采更温和）。

### 2.3 运行台账 + 看板"更新至"戳

- 新表 `collection_runs`（run_id, mode, started_at, finished_at, series_total, series_done, series_budget_capped, new_reviews, tagged, status, error）——weekly/full 两种模式共用，深采历史不回填。
- 看板最小改动：`GET /dash/koubei/last-run` 返回最近成功 run 的 finished_at + new_reviews → `dash_series.html` 口碑区一行"口碑更新至 X 月 X X"（一处显示，不做逐系戳）。

### 2.4 调度（拍板 2026-11-01：像舆情那样自己更新——双任务自动形态）

照抄舆情现役模式（Interactive 主任务 + onlogon 补跑任务，均免管理员）：

- **入口脚本** `prism-dashboards/scripts/koubei_weekly_update.py`（对标 daily_update.py）：自动备份 → 增量采集（全池名单）→ 台账落库 → 日志 `prism-dashboards/logs/koubei-weekly.log` 滚动追加；**语义退出码**（0=成功含 budget_capped / 1=部分车系失败 / 2=守卫或环境拦截 / 3=无事可做）；already_running 互斥锁；`--catchup` 模式=数据新鲜度自检（最近成功周更 finished_at > 8 天 → 补跑，幂等日标记 `logs/koubei_catchup_<YYYYMMDD>.done`，时区固定 Asia/Shanghai，判定窗=本地 07:00 后，missed_run_catchup 同款）。
- **主任务 `PrismKoubeiWeekly`**：schtasks 周日 04:00（给舆情 02:00 夜跑让 2h 头位；周更跑量分钟级，重叠无害），Interactive 形态（仅登录时运行，免管理员——PrismSentimentDaily 同款）。
- **补跑任务 `PrismKoubeiCatchup`**：onlogon 触发跑 `--catchup`（无人登录的周末静默跳过后，下次登录自动补，PrismSentimentCatchup 同款）。
- 注册命令（schtasks，免管理员）随 change 交付，注册动作在 Step 9 验收时与用户一起执行；prism.py 仍加 `koubei-weekly` 薄子命令（手动触发/dry-run 用，subprocess 调入口脚本）。

## 3. 明确出圈

- 月度滚动缺口扫描（§8，单月 vs 3月合计判据）——独立月度 change；
- 口碑异动简报（负面占比突变预警）——二期；
- Atuohome 侧刷新窗口协调——只选冷时段规避，不下探源项目内部。

## 4. 施工规格

- **Step 5 施工 = fork 型子代理**（惯例：general-purpose 无文件工具）；**Step 7 隔离审查 = general-purpose 磁盘自读**（不给设计结论，代码全文自读）。
- 测试：扩 `test_recollect_koubei_cap.py` 同款风格新增 `test_recollect_weekly.py`——水位停止纯函数 / insert-skip 幂等（同批二次跑零新增）/ budget_capped 早退 / 零删除断言 / progress 与台账落痕；prism.py 子命令**手动冒烟**（自动化测试未含，P2-7b 口径对齐：以 tasks.md 为准，本行更正）。
- **验收（含首跑验证）**：
  1. dry-run：全池预估打印，零写入零出网；
  2. **ID 稳定性验证跑**：跑前全库 review_id 集合哈希落档 → live 增量跑 → 断言旧 ID 集合 ⊆ 跑后集合（零丢失）+ 新增条数=台账 new_reviews；
  3. 存量零扰动：全库既有行内容抽样 diff 为零（不 UPDATE）；
  4. 幂等复跑：同周内二次跑 → new_reviews≈0、请求量≈96 页打底；
  5. 出口闸抽验：任选一系跑真实对话 query_reviews → supported_by 含新旧 review_id 均可复算；
  6. 全量 pytest 回归绿。
