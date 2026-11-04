# Step7 隔离审查报告（舆情采集降本 change，2026-10-16）

> 审查者：独立 fork 子代理。所有发现均附 file:line 与推理/复现链条，未采信任何施工方自验结论。
> 全量 pytest 独立复跑：**900 passed / 1 failed**（唯一失败 `test_cache_bust::test_index_serves_mtime_versions`，与本 change 无关——非重跑基线证明，仅确认其为唯一失败且属静态索引域）。
> 红线遵守：零生产代码修改、零 commit、零服务重启、零付费 API 调用、生产库只读（mode=ro）。

## 结论速览：**P0 × 0 · P1 × 1 · P2 × 4**。首跑（10-17 03:00）安全：无会炸链路的问题；P1 是触顶场景下的可观测性缺口，不触顶则无感。

---

## P1-1 · budget_capped 状态被管线覆写为 completed——触顶对运维完全不可见

**链条（全实证）**：
1. `scheduler.py:1200` 触顶返回 `{"status": "budget_capped"}`（DB 侧 register_budget_skip 已正确落 budget_capped + skipped_vehicles，:1193 内存相位也写了 budget_capped）
2. `api/routes/collection.py:59` 管线包装层只判 `result.get("status") == "error"`——budget_capped **不匹配，继续走 Phase 2-9**（Phase 4 补评论 :84-87 与 Phase 9 互动刷新 :132-140 会再次撞 `TikHubBudgetExceeded`，但被 try/except 吞成 warning——无害但白跑）
3. `collection.py:143` 终态无条件写 `{"phase": "completed", ...}` 进内存 dict
4. `/pipeline-status`（collection.py:371-373）TTL 30 分钟内（`pipeline_state.py:82-88`）优先返回内存 dict → 返回 completed
5. `daily_update.py:156-161` 只认 `phase == "error"` → 打印"**完成: 新帖 0**"，该车不计 failed → **退出码 0**

**后果**：若今晚触顶，明早 `daily_task.log` 显示 15/15 成功——触顶事件只存在于服务端 `[BUDGET CAP]` 日志与 skipped_vehicles 列。方案 L6 的"budget_capped 可见 + as_of 不掩盖陈旧"只兑现了登记半边，可见性半边被吞。skipped_vehicles 数据不丢（register_budget_skip 独立 session 已 commit），纯运维误导。
**修法建议（Step8）**：① collection.py:59 改 `in ("error", "budget_capped")` 早退（保留 scheduler 写的内存相位即可）；② daily_update.py:156 加 `elif final.get("phase") == "budget_capped":` 打印触顶并入 failed 列表。两行级改动。

## P2 发现（4 条）

**P2-1 · 护栏计数=逻辑调用数，非物理请求数**
`tikhub_collector.py:283` `count_and_check()` 在重试循环**外**——`_send` 内部最多 `_max_attempts`（默认 5）次 HTTP 重试只计 1。400 类"不计费"重试无害；**429/5xx 类计费重试会使物理计费请求超过预算上限**（预算 2,200 逻辑调用 ≈ 最坏 11,000 物理请求）。方向上护栏从"防失控"降为"防逻辑失控"。建议：计数移入重试循环，或在 budget.py 文档声明逻辑调用口径。

**P2-2 · 首跑 xhs 空窗补采变薄（口径权衡，非 bug）**
停摆 8 天 → 首跑增量窗 ≈10 天（scheduler.py:921 −2 天缓冲）→ `_xhs_time_filter` 落"一月内"粗档；Step6 接线后 xhs 只翻 1 页（`_search_max_pages`，tikhub_collector.py:680）+ 6 词（旧配置 2 页×15 词）。10-08~10-14 空窗段帖的一次性补采覆盖显著弱于旧配置；之后窗口收窄（≤7 天档），该段帖**不会再被搜到**——趋势线在空窗段永久偏薄。可接受（记入口径）或一次性手工补采（临时 env 覆盖 xhs 页数/对该窗单车 initial）。

**P2-3 · 每日双份互动刷新（存量行为，预算下值得砍）**
每车管线 Phase 9 已刷（collection.py:130-140，含刷后重算热度），daily_update 尾部 `_run_engagement_refresh()`（daily_update.py:169）又全量刷一遍——**每天刷新调用×2**（≈300 次/天量级）。非本 change 引入，但新预算口径下是可省项。

**P2-4 · run_cleanup dry-run 早返回泄漏自有连接**
cleanup_posts.py:200-201：`dry_run or not post_ids` 早返回时 `own=True` 的连接未 close（live 路径 :211-212 有 close）。每天泄漏 1 个 sqlite 连接，实际影响近零。

## 验证通过面（抽查证据）

| 审查项 | 结论 |
|---|---|
| paused 豁免 SQL | `v.status != 'paused'`（cleanup_posts.py:76），inactive 零帖天然不受影响 ✓ |
| NULL published_at 不删 | :75 `IS NOT NULL` 前置 ✓ |
| 级联+修剪同事务 | :205-209 `with con:` 单事务，失败整体回滚 ✓ |
| PRISM_CLEANUP_LIVE 门控 | daily_update.py:205 调用时读（T3 教训落实）✓；注：CLI 直跑 `cleanup_posts.py` 不带 `--dry-run` 即真删（T6 手工首删所用路径）——与钩子门控分离，属已知设计，记录不改 |
| 极性双轨 | derive 三分支+两列皆空回退 neutral（post_utils.py，口径注释清晰）；队列两列皆空才入选+哨兵 "none" 防死循环（batch_runner run_comment_analysis，env 调用时读）✓ |
| 端点极性轨 | overview/trend 均选两列、polarity 优先、unanalyzed 单列（dashboard.py:491-543 域）✓ |
| register_budget_skip | 幂等（同值重写）、排除自身/今日已采/paused，测试为四车夹具行为断言（test_t2_budget_guardrail.py:118-147）✓ |
| _send 唯一通路 | get/post/post_query 全过 _send；chezhiwang 直连 httpx 是免费 HTML 源（非 TikHub），无计费绕行 ✓ |
| 异常语义 | TikHubBudgetExceeded 不继承 TikHubError（budget.py:33 + 专项测试 :83）——关键词级 except 不吞 ✓ |
| max_pages 接线 | 仅 xhs/dy 活跃平台（:680/:934），initial 保持 env 3 页，归档平台不经该函数 ✓ |
| 事故回归 | 肇事测试 test_main_recollected_after_refresh 已补三收尾钩子（test_daily_update.py:55-58，注释在案）✓ |
| 测试断言强度 | 抽查 5 个新文件（断言 105 处）：预算/清理/极性均为行为断言（值比对/异常抛出/状态检查），未发现"必然通过"假绿 ✓ |
| 生产库首跑就绪 | 15 active / 计数器明日新行 / skipped_vehicles+comment_polarity 列在位 / 7,766 帖（只读核验）✓ |
| 首跑预算余量 | 估算 ≈1,800 逻辑调用（搜索 270+评论 900+刷新 600 双份+指数 30）< 2,200 ✓——含 douyin 抖动重试仍应有余量；触顶则走 P1-1 所述（被掩盖的）优雅降级 |

## 审查文件清单

全读：cleanup_posts.py / daily_update.py / budget.py / test_daily_update.py（肇事测试域）
段落精读：scheduler.py（register_budget_skip :92-140 / 平台循环 :1058-1100 / collect_vehicle 收尾与 catch :1168-1212 / rotate+拼序 :176-262）· collection.py（_run_full_pipeline :44-160 / get_pipeline_status :342-384）· tikhub_collector.py（_send :259-296 / _search_max_pages :104 / 搜索翻页挂点 :680/:934）· post_utils.py（derive_comment_sentiment / NEGATIVE_PRESET_WORDS）· batch_runner.py（run_comment_analysis / 负面追加段）· dashboard.py（overview/trend）· pipeline_state.py（_is_phase_stale）
测试抽查：test_t2_budget_guardrail / test_cleanup_posts / test_t1_cost_reduction / test_t4_polarity_direct / test_t2_negative_extra
意图来源：explore/design/proposal/tasks + step5-T1~T5 报告 + 方案文档 R30-R44 修订链
生产库：只读核验 4 项

## 移交 Step8 建议

修 P1-1（两行级，两个文件）；P2-1 定口径声明或移计数；P2-2 由用户拍板（接受偏薄 or 手工补采）；P2-3/P2-4 记录待办。
