# Step5 · T2 施工报告（日预算护栏 + 负面帖评论追加）

> 子代理：t2-guardrail（fork 型）· 日期：2026-10-16 · 依据 design.md D2 + explore §三 L1 + tasks.md T2
> 红线遵守：未 git commit、未重启任何服务、零付费 API 调用（测试全 mock/临时库/内存库）、只改 prism-sentiment 下文件

## 一、改动清单（源码 7 文件 + 测试 3 文件）

| 文件 | 改动 |
|---|---|
| `pipeline/collectors/budget.py`（**新建**） | 计数器：`count_and_check()`（ON CONFLICT+RETURNING 原子累加，超限抛异常且请求不发出）/ `today_usage()` / `daily_budget()`；`TikHubBudgetExceeded`（**故意不继承 TikHubError**——关键词级 except 会吞预算事件）；stdlib sqlite3 直连 + busy_timeout + CREATE TABLE IF NOT EXISTS 兜底；**计数器故障降级为放行**（护栏失效好过采集瘫痪，注释写明） |
| `pipeline/collectors/tikhub_collector.py` | `_send` 挂钩（:271，get/post/post_query 唯一通路，auth 检查后、URL 装配前）；budget 模块 re-export（scheduler 单一 import 面） |
| `models/schemas.py` | 新 ORM `TikhubDailyUsage`（date 主键）；`CollectionStatus.skipped_vehicles` 列（TEXT/JSON） |
| `models/database.py` | 迁移 **v18**（skipped_vehicles，check_column 幂等；usage 表靠 create_all 建，老库亦然，不需迁移） |
| `pipeline/scheduler.py` | ① 平台采集循环加 `except TikHubBudgetExceeded: raise`（:1073，防被平台级 except Exception 吞掉）② `collect_vehicle` 顶层专属分支（:1185：budget_capped 状态 + pipeline_phases 标记 + rollback + 登记）③ **模块级 `register_budget_skip(session, vehicle_id, err)`**（登记落法见偏差①）④ `fetch_top_comments` cap 豁免扩 `_negative_directed`（:1248，与 _defect_directed 同哨兵语义） |
| `pipeline/collectors/post_utils.py` | `NEGATIVE_PRESET_WORDS`（缺陷词 12 全集 + 维权/自燃/起火/断裂 = 16 词，注释写同源维护关系与 R28 预筛机制） |
| `pipeline/analysis/batch_runner.py` | `comment_negative_extra_n(platform)` 旋钮（env `COMMENT_NEGATIVE_EXTRA_N` 默认 10，白名单外语义与 comment_top_n 一致）；`select_top_posts_for_comments` 尾部新增负面追加段（每平台独立 cap、互动降序、零互动入选、排除已选/缺陷段、LISTING_CALIBER 照挂、标 `_negative_directed`）；docstring 同步 |
| `tests/conftest.py` | autouse `_budget_counter_tmp_db`：**DB_PATH 逐测试指临时库**——_send 现在会写计数，不隔离则任何走到 _send 的既有 MockTransport 测试会把计数行写进生产库（防污染关键） |
| `tests/test_t2_budget_guardrail.py`（**新建**） | 9 用例：累加/封顶/跨日重置/env 覆盖与回退/**异常不继承 TikHubError**（冒泡语义）/_send 触网前抛/IndexCollector 共享计数/登记（active 未采入选、今日已采·paused·自身排除、JSON 结构）/同日重算幂等 |
| `tests/test_t2_negative_extra.py`（**新建**） | 5 用例：旋钮（默认 10/env/停采 0）/零互动负面帖捞回+标记/cap+互动降序/排除已选与缺陷段覆盖/营销号口径挡掉/停采平台不扫 |

## 二、自验证据

- **新增单测**：`pytest tests/test_t2_budget_guardrail.py tests/test_t2_negative_extra.py` → **14 passed**（1 处初版断言算术错——neg2 是 10 赞非第 3 高，测试 bug 非代码 bug，已修）
- **全量**：`python -m pytest tests/ -q` → **878 passed / 1 failed**——唯一失败 `test_cache_bust.py::test_index_serves_mtime_versions` 为 T1 报告已实证的存量失败（git stash 基线复跑，与本 change 无关）；T1 时点 852+1 → 本轮 878+1（+26 = T1 新增 12 + T2 新增 14）
- **导入冒烟**：budget/scheduler/异常类/旋钮/词表全可导入；budget 默认 2200；词表 16 词；extra_n(douyin)=10 / extra_n(weibo)=0
- **接线 grep**：count_and_check() @ tikhub_collector:271；两处 except TikHubBudgetExceeded @ scheduler:1073/1185；_negative_directed @ scheduler:1248 + batch_runner:214

## 三、偏差与决策记录

1. **登记落法（directive 允许自选）**：daily_update 逐车串行触发，触顶时 scheduler 只见当前车——选了"scheduler 侧当场算剩余"：`register_budget_skip` 查全部 active 车，排除当前车与 `last_collected_at ≥ 今日 00:00` 的已采车，名单写进**触顶车行**的 skipped_vehicles JSON。做成**模块级纯函数**（非 scheduler 方法）便于单测直测；后续车再触发会秒败再登记同值，幂等无害。名单存**车名**（可读性优先；车名重复风险低，如需 id 可后续换）
2. **指数采集的预算异常被既有 try 吞掉（有意保留）**：指数段本就"失败只 warning 不炸采集"（看板增强项），且触顶时帖子已入库——若在那里抛反而会把成功采集误标失败。计数仍计入（_send 先计数后抛）
3. **护栏初值语义**：`TIKHUB_DAILY_BUDGET` 非正数回退 2200（不接受 0=禁用，防误配关掉护栏；要临时放开请设大数）
4. **REFRESH_TOP_N 沿用 T1 的 env 化模式**，T2 未重复动

## 四、遗留项（移交）

- T3：清理任务（cleanup_posts.py + paused 豁免）；T4：极性直出（comment_polarity 双轨）；T5：`--all` 删频率跳过 + schtasks
- T6/验收：低预算值**真机 dry-run 演练**（本 change 只做了 mock 层验证 skip 路径）；skipped_vehicles 的 agent/前端消费侧（stale 声明文案）按 proposal 边界留 change 2
- 测试断言 `__import__("sqlalchemy").select` 一处写法欠雅（省一行 import），Step6 simplify 可顺手规整
