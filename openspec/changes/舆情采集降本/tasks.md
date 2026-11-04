# 舆情采集降本 change · tasks（Step 5 派单用）

> 施工纪律：fork 型子代理 + 第 0 步守卫（ToolSearch 全量列举，无 Bash+Read 即报 NO-TOOLS 退出，主会话重派）；双保险交付=写结果文件 + select:SubagentHandback 摘要；重要文件绝对路径；编辑一律 Edit 工具（heredoc 反斜杠四犯禁令）。

## T0 前置（主会话自做，派单前）

- [ ] 库备份：`vehicle_sentiment.db` → `openspec/changes/舆情采集降本/snapshots/`（清理/极性双保险）
- [ ] git commit 当前工作区基线（现状含未提交的 prism-sentiment 改动，先固化）

## T1 参数批 + 停采摘除（一个子代理，纯配置/低风险）

- [ ] `platform_strategy.py`：社媒 max_keywords 15→6；PLATFORM_MAP 摘 weibo/kuaishou/news（注释停采日期）
- [ ] `scheduler.py`：`_build_collection_keywords` 拼序改 `core + rest[:2] + defect_wordlist`（注释同步：6 词构成=核心1+双2+缺陷3）；P1 轮换纯函数（`DEFECT_ROTATE_DAYS=2` 错位切片，确定性）+ 单测
- [ ] `scheduler.py`：initial 窗 `INITIAL_WINDOW_DAYS=30`（:919）；删 news 阶段（:976-986）+ `_collect_news` + `_store_posts` news 分支 + keyword_expander 链
- [ ] env 批：`COMMENT_TOP_N=10` / `COMMENT_MAX_PAGES=2` / refresh `_TOP_N=15` / `DEFECT_ROTATE_DAYS=2`（.env 或默认值，能 env 的不硬编码）
- [ ] 自验：单测（词序/轮换确定性/initial 窗）+ `--help` 冒烟 + news 关键词 grep 零残留调用

## T2 预算护栏（一个子代理）

- [ ] `tikhub_daily_usage` 表（建表幂等）+ `_send` 计数（tikhub_collector.py:259）+ `TikHubBudgetExceeded`
- [ ] `collect_vehicle` 捕获 → `budget_capped` 状态 + `collection_state.skipped_vehicles` JSON 登记
- [ ] `TIKHUB_DAILY_BUDGET=2200` env
- [ ] 自验：单测（计数累加/封顶抛异常/登记）；低预算值 dry-run 演练（验证 skip 路径）

## T3 清理任务（一个子代理）

- [ ] `scripts/cleanup_posts.py`：30 天线 + paused 豁免 WHERE + 级联 post_comments + analyzed_posts 处理 + `--dry-run` + 统计输出
- [ ] 挂 `daily_update.py` 尾部；引用审计 helper（event_groups/排行对将删帖引用检查）
- [ ] 自验：dry-run 清单 vs 直查 SQL 对账（≈5,814/26,020 预期）；paused 6 台不在清单断言；单测（边界日期/paused/空库）

## T4 极性直出（一个子代理）

- [ ] `post_comments.comment_polarity` 新列（迁移幂等）
- [ ] `local_absa.py` 极性直出模式（prompt/parse_polarity_output）+ `USE_LOCAL_MODEL` 路径接通
- [ ] `post_utils.derive_comment_sentiment` 双轨（新列优先/老列回退）；batch_runner 待打标筛选改 `comment_polarity IS NULL AND dim_sentiment IS NULL`
- [ ] 自验：单测（新评论直出/老评论回退/翻车帖 pos2neg·neg2pos 判定）；**不跑真模型**（GPU 留夜跑），用 mock 输出测解析与链路

## T5 调度（可与 T4 并行）

- [ ] `daily_update.py`：`--all` 删频率跳过（全量 active 直通）；frequency.py 保留不删
- [ ] schtasks 注册命令落 `scripts/`（install/uninstall 两个，含 Anaconda Python 绝对路径与 cwd 说明）——**不实际注册**（留验收 T7 时用户点头）
- [ ] 自验：`--all` 打印待更新=15 车名单断言

## T6 联调验收（主会话+子代理，T1-T5 全合后）

- [ ] 9 词对照实验（独立脚本，一天）→ 基线卡片
- [ ] 单车 dry-run 调用账 vs §3.8（≈96-98）
- [ ] 清理 dry-run → 人工过目 → 备份确认 → 首删 → 断言
- [ ] 出口闸 E2E（30 天口径活库）
- [ ] 计划任务注册 + 连续两日观察
- [ ] 口径 stamp 落档；EVAL_STATUS/sentiment 相关文档指针更新

## 派单编排（Step5）

波次 1：T1（含停采）→ 回收后波次 2：T2+T3 并行双代理 → 波次 3：T4+T5 并行 → T6 主会话统筹。
每个子代理任务单必含：explore.md 锚点表 + design.md 对应节 + 自验要求 + NO-TOOLS 守卫 + 绝对路径纪律。
