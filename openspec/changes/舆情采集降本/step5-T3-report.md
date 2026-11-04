# Step5 · T3 施工报告（30 天老帖物理清理）

> 子代理：t3-cleanup（fork 型）· 2026-10-16 凌晨 · 依据 design.md D3 + 方案 R40/R42
> ⚠️ 本轮含一起**生产库误删事故**（已止血+可完整恢复），见 §四——主会话须先裁决恢复与否再继续。

## 一、交付清单

| 文件 | 内容 |
|---|---|
| `scripts/cleanup_posts.py`（新） | 保留线清理器：`POST_RETENTION_DAYS=30` env、**paused 豁免**、三表级联（raw_posts/post_comments/analyzed_posts，均无 FK 手动 DELETE）、单事务+500 批分片、`--dry-run`/`--vehicle`/`--retention-days`、引用审计（event_groups.post_ids JSON + watch_items.source_ref 用户关注项，警告不强阻；defect_themes 为 24h TTL 派生缓存不审计）、published_at NULL 不删（无判据宁保守） |
| `scripts/daily_update.py` | 收尾挂接 `_run_post_cleanup()`：排在互动刷新后、**备份前**（备份清理后的库）；**默认 dry-run，env `PRISM_CLEANUP_LIVE=1` 才真删**（事故后门控，见 §四） |
| `tests/test_cleanup_posts.py`（新，15 用例） | 边界（30 天龄留/31 天删）/paused 豁免/级联三表/NULL 不删/dry-run 零副作用/空库/vehicle 过滤/引用审计正反/1200 帖批量分片/钩子导入/**钩子默认 dry-run+env 门控（事故回归）** |
| `tests/test_daily_update.py` | `test_main_recollected_after_refresh` 补丁 `_run_post_cleanup`（事故根因③修复） |
| `step5-T3-restore.py`（change 目录） | 事故恢复工具：从 pre-change 备份外科式回插（备份有现存无），dry-run 默认、`--live` 单事务执行；**已 dry-run 自测（5,248/40,125/4,845 待回插），未执行** |

## 二、自验证据

- `pytest tests/test_cleanup_posts.py tests/test_daily_update.py` → **17 passed**
- 全量 `pytest tests/` → **880 passed / 1 failed**（唯一失败 `test_cache_bust` 为 T1 报告已证的存量失败；880 含并行 T2 新增的护栏测试）
- **生产库 dry-run（只读）**：将删帖 0（active 老帖已因事故不存在，见 §四）、paused 存量保留 Model Y 319/星愿 517/铂智3X 298/银河A7 302/银河M9 299/银河TT 356（合计 2,091）——豁免生效实证
- 引用面审计（schemas.py 实测）：级联两表 `post_comments.post_id`(:214)/`analyzed_posts.post_id`(:81)；悬空引用对象 `event_groups.post_ids`(:242, JSON 存 RawPost.id) 与 `watch_items.source_ref`(:276, 用户手动关注清单)；`defect_themes.payload` 为 Phase 9 全量覆盖缓存（自愈，不审计）

## 三、与指令预期的偏差

1. **"首次清理后 ≈5,814 帖"的指令预期本身与 R42 矛盾**：5,814=全库近 30 天帖（含 paused），但 paused 豁免下 paused 的 30 天线外存量（≈2,035）也保留 → 正确预期 ≈7,849。方案 §八/R42 文本同款口径瑕疵，建议主会话顺手修正文档。
2. 挂接顺序自定：清理在备份**之前**（design 未明确；备份清理后的库体积更小、语义更合理，已在代码注释说明）。

## 四、⚠️ 事故全记录：全量套件期间生产库被真删

**现象**：施工后全量 pytest 一次，生产库 raw_posts 13,014→7,766、post_comments 79,129→39,004（删 active 车老帖 5,248 + 其评论 40,125 + 分析行 4,845；**paused 6 台 4,281 帖一根未动**——豁免逻辑按设计生效）。

**根因链（三因子叠加）**：
1. `tests/test_daily_update.py::test_main_recollected_after_refresh` 真跑 `du.main()`，原有补丁覆盖 refresh/backup 两个收尾，但**我新加的第三个收尾 `_run_post_cleanup` 它不知道**；
2. 我初版钩子默认真删（design 原意=daily 流程真清，未料测试会裸跑 main）；
3. `cleanup_posts.py` 的 `DB_PATH` 在**模块导入时捕获**，conftest 的 monkeypatch.setenv 隔离对它无效 → 测试环境解析到生产库路径。

**止血（三重，已验证）**：
- 钩子改**默认 dry-run**，`PRISM_CLEANUP_LIVE=1` 门控真删（恰好对齐指令"一切真删留 T6"）；
- `DB_PATH` 改 `db_path()` 调用时读取；
- 肇事测试补丁新钩子 + 事故回归测试两条（默认 dry-run/env 开启才 live）。
验证：修复后全量套件复跑，生产库计数不变（7,766/39,004）。

**恢复裁决（留主会话/用户，两选项）**：
- A. 外科恢复：`python ../openspec/changes/舆情采集降本/step5-T3-restore.py --live`（备份 75MB 完好，回插纯加法幂等，已 dry-run 核数）→ 之后 T6 按流程走 dry-run→人工过目→授权真删；
- B. 接受现状当首次清理：删除集与 R40/R42 授权语义**完全一致**（active+30 天线外+级联，抽验 5 帖全为 active 老帖），只是缺了"人工过目"这一步；省一次删除轮回，代价是流程纪律瑕疵需在 change 复盘记一笔。
- 备注：`test_cache_bust` 存量失败与本次无关（T1 已证）；删除期间无采集写入（停摆中），回插无冲突风险。

## 五、移交

- T6：dry-run 清单人工过目流程、`PRISM_CLEANUP_LIVE` 开启时机、出口闸 E2E（若选恢复 A 则按原计划；选 B 则清理项直接勾销）
- 方案文档：R42/§八 的"13,014→5,814"口径修为"→≈7,849"（偏差 1）
- 教训沉淀（建议入项目记忆）：**给 main() 加收尾钩子时，所有真跑 main 的测试都是隐式消费者**——新钩子要么默认无副作用（dry-run），要么同步补丁全部既有 main 测试；模块级 env 捕获会击穿 monkeypatch 隔离，路径类 env 一律调用时读。
