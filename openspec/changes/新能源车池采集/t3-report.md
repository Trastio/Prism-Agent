# T3 报告 · 深采改造 + 3 车系试跑

日期：2026-10-16 20:00-20:40 · 施工：T3 子代理 · 写生产库（T0 备份在案：`data/backups/autohome-pre-nevpool-20261016-200017.db`，300MB，未动）

## 1. 改造点清单（`prism-dashboards/scripts/recollect_koubei_with_full.py`）

核心语义（翻页/详情页解析/打标）一律未动，只加：

| # | 改造 | 实现 |
|---|---|---|
| 1 | 单车系 cap | `--max-reviews N`（条数，缺省 None=不封顶向后兼容）；`pages_for()` 页粒度向上取整（20 条/页，300=15 页）；页内整页保留，实采可略超 cap 最多一页 |
| 2 | 名单入参 | `--pool-file`（缺省 `data/nev_pool.json`）取 tier=deep 的 series_id；容忍裸 list / {"pool":[...]} / {sid:record} 三种外壳；**缺省路径文件不存在 → 提示+回退 legacy 名单（config_snapshots 全量）；显式指定的文件不存在 → exit 2**（ID 一律从文件落地，不人工转写，红线#6） |
| 3 | 启动守卫 fail-closed | 目标车系 ∩ 存量分析池（owner_reviews 按 model_id 计数 ≥100）非空即拒跑并列冲突，dry-run 同样拦截；live 另要求 `data/backups/autohome-pre-nevpool-*.db` 存在（无备份不跑） |
| 4 | 门控 | 默认 dry-run（打印将采名单+逐系预估=页数+条数，**零写入零出网**，预估读 series_summaries.review_count）；`PRISM_COLLECT_LIVE=1` 才真采 |
| 5 | progress 断点 | 逐车系完成态追加 `data/recollect_deep_progress.jsonl`（series_id/status/collected/tagged_distinct/full_hits/elapsed_s/finished_at）；done/empty 跳过，failed 重跑 |
| 6 | 试跑实测修复：翻页去重 | 之家翻页非严格稳定排序，同一条口碑会在相邻页重复（铂智3X 实证 1 条重复→review_id 主键冲突→整批回滚拒写）；按 review_id 去重保首现，翻页/解析语义不变 |

单测：`tests/test_recollect_koubei_cap.py` 新增 33 个（cap 页数/守卫交集/守卫豁免/pool 三形态解析/预估纯函数/progress 读写容错/备份探测/CLI 解析/recollect_series cap 与去重行为——FakeAPI mock，零出网）。全量 pytest：本任务范围 104 passed（33 新 + 71 既有）。

## 2. 试跑三车系（真采，写生产库）

车系 ID 从 `series_summaries` 查得：铂智3X=7712、深蓝S05=7740、零跑C10=7382。命令：`PRISM_COLLECT_LIVE=1 ... recollect_koubei_with_full.py --series-ids=7712,7740,7382 --max-reviews 300`。

### 2.1 前后行数对账（库可复算）

| 车系 | 试跑前 owner_reviews | 试跑后 | review_tags（tags 行 / distinct review_id / 覆盖率） | 详情页全文命中 |
|---|---|---|---|---|
| 铂智3X 7712 | 0 | **149** | 397 / 146 / **98.0%** | 149/149 |
| 深蓝S05 7740 | 0 | **150** | 424 / 140 / **93.3%** | 150/150 |
| 零跑C10 7382 | 0 | **150** | 465 / 147 / **98.0%** | 150/150 |
| 合计 | 0 | **449** | 1286 / 433 | 449/449（100%） |

全库对账：owner_reviews 21,396 → **21,845**（+449 精确吻合）；review_tags 50,696 → 51,982（+1,286=424+465+397 吻合）。**28 个存量系（计数≥100）逐系行数与 T0 基线全部一致，零扰动**。三系打标覆盖均 ≥70% 验收线。数据质量抽查：post_date 覆盖 2025-02 ~ 2026-10-16（采到当天），spec 覆盖 8-14 个版型/系，标签分布合理（pro 头部=外观好看/空间大，con 头部=噪音大/悬挂硬/智能化不足）。

### 2.2 耗时与请求量实测

| 车系 | 实采 | 耗时 | 请求构成 | 备注 |
|---|---|---|---|---|
| 7712 首跑 | 失败（0 入库） | 44s | 15 页列表+300 详情≈315 | 主键冲突整批回滚（见 §3.1），回滚保安全，progress 记 failed |
| 7740 | 150 | **207s** | 15 页+150 详情=165 | 打标 140 条占大头 |
| 7382 | 150 | **214s** | 15 页+150 详情=165 | 同上 |
| 7712 补跑 | 149 | **185s** | 15 页+149 详情=164 | 断点跳过 2 系，仅实跑 7712 |

请求量合计 ≈810 HTTP + 433 次 DeepSeek 打标调用；另探针诊断 ~10 请求。**打标是耗时大头（约 1.2s/条，串行 LLM）**，占单车系耗时 ~70%。

## 3. 偏差与实测发现（如实记录）

### 3.1 之家分页重复 → 主键冲突（已修）
7712 首跑 insert 阶段 `UNIQUE constraint failed: owner_reviews.review_id`：相邻页重复返回同一条口碑，results 内 review_id 撞主键，整批回滚（存量零损伤，系记 failed）。修复=采集端按 review_id 去重保首现（补跑实测去重 1 条：150→149），不动翻页/解析/打标语义。**T4 全量批若没这个修复会大面积炸**。

### 3.2 服务端 pageSize 钳制（未解，T4 需拍板）
脚本请求 pageSize=20，但持续请求后服务端钳到 10/页（响应回显 `pagesize=10` 实证）。7712 首跑时还是 20/页（15 页=300 条），轮到 7740/7382 已被钳为 10/页（15 页×10=**150 条**）——两系"恰好 150"即此故。`rowcount` 证明源站全量仍在（7712=746、7382=2700），**不是可得性问题，是反爬限速**。试跑后约 25 分钟探针仍在钳制态。影响：cap 语义按"15 页"停，钳制期单车系实采减半（150）。T4 可选项：(a) 接受 150/系；(b) 钳制期传 --max-reviews 600（30 页×10=300 条，耗时不变约 8 min/系）；(c) 夜跑低峰期望钳制解除。**建议 T4 采用 (b)+夜跑**。

### 3.3 守卫豁免语义（判断题，请复核）
首批 150 条入库后，7740/7382 自己过了 ≥100 门槛 → 字面守卫把 T4 续跑永久锁死（progress 跳过形同虚设，proposal 明确要求"失败清单续跑"）。收敛：**progress 终态 done/empty 且库内行数与记录精确相等**（证明行是本管线 delete+insert 写的）→ 豁免；行数对不上或无 progress 记录 → 照旧 ≥100 即拒（fail-closed 保留）。已实现+5 个单测锚定。守卫本体拦截已实测（对 6298 试跑被拒，exit 2）。

### 3.4 其他
- 环境偏差：`prism-dashboards/.venv` 不存在，实际用 Anaconda python（prism.py 同源 `~\Anaconda3\python.exe`），sqlalchemy 2.0.43/httpx 0.28.1。
- dry-run 预估（每系 315 请求）按 20 条/页估，钳制期实际请求量不变（页数同 15）但条数减半——预估口径偏差已声明。
- `--pool-file` 未对真实 nev_pool.json 集成验证（T1 并行施工中文件未落盘）；解析器容错三形态+单测覆盖，T4 开跑前建议先 `--pool-file` dry-run 冒烟一次。
- 全量 pytest 现有 1 失败：`test_gen_nev_pool.py::test_bind_exact_then_search_then_manual`（KeyError: '8'，gen_nev_pool.py:463）——**并行 T1 施工中文件，非本任务范围/非本任务回归**。
- progress 文件终态 4 行（1 failed+3 done），重试历史保留，断点续跑实测生效（第 3 次运行"跳过已完成 2 系，实跑 1 系"）。

## 4. T4 排程结论（27 车系一晚是否可行）

**可行，且余量充足。** 依据实测：钳制期 150 条/系 ≈ 3.0-3.6 min；不钳制 300 条/系 ≈ 8 min（采集 ~1.5 min + 打标 ~6 min，打标约 1.2s/条串行为主导）。

- 第一晚 27 系：不钳制 ≈ **3.6h**；钳制期半量 ≈ 1.6h。夜窗 10h+ 覆盖 2.7 倍余量。
- 第二晚 50 系：≈ **6.7h**（不钳制），可行但建议同晚挂 progress 断点+晨起补跑（重跑自动跳过已完成系）。
- 前提建议：夜跑按 §3.2-(b)（钳制期 --max-reviews 600）；首车系跑完即核 progress 与行数，异常先停。
