# Step 7 · 隔离审查（口碑周更增量采集，2026-11-01）

**结论：无 P0——数据安全红线全部守住（full 现役语义逐块核对等价、增量无任何删除路径、零删除断言真实生效、fail-closed 未弱化）；发现 P1×2（CLI 直跑增量名单口径错 71≠98 系、prism.py 子命令拒绝自己 docstring 示例的参数形式）、P2×9（含两处"零写入/退出码"声明与实现的差距、无人值守路径一处未捕获异常、施工报告分项数字错），均不阻断 Step 9 首跑，建议首跑前修 P1。**

审查方式：规格三件套 + 施工报告全文自读；6 个实现文件逐行；git diff 逐块归属核对；实际执行了 pytest 全量（205 绿复跑）、入口 dry-run、CLI 直跑增量 dry-run、full 模式 dry-run（守卫拦截 + 真实退出码 2）、`--catchup --check`、prism.py 子命令两种参数形式、finished_at 时区 roundtrip / 无表异常 / 白名单判定三个受控实验（临时库，未触碰仓库与生产库）。

---

## P0 专项核对（全部通过，零发现）

| 核对项 | 证据 |
|---|---|
| full 现役路径零改动 | git diff 逐块：full 采集分支纯缩进移位进 `else:`、内容逐字相同；守卫与 NEV 备份探测被 `if mode == "full"` 包裹（full 时逐字等价，含 SystemExit(2) 与打印文案）；`_parse_args` 新键缺省 `full/None` 且被 `test_parse_args_backward_compat_defaults` 钉住。仅两处 cosmetic 差异：`[LIVE]`→`[LIVE|full]` 打印前缀、stats dict 增加 `mode` 键（additive，无消费方受影响） |
| 增量无删除路径 | `recollect_series_incremental` + `_save_new_reviews` 全文无 DELETE/UPDATE；打标只对 inserted 逐条插入 ReviewTag |
| 零删除断言真实生效 | recollect_koubei_with_full.py:453-470：before 计数 → 插入 → after 计数 → 不等即 RuntimeError fail-closed；测试 test_save_new_reviews_zero_delete_assertion mock 计数偏差实触发 |
| insert-skip 幂等 | :455-462 known_ids 短路 + `s.get(OwnerReview, rid)` 事务内主键双保险；测试二次跑零新增实库断言 |
| 出口闸 supported_by 不断链 | 增量只插新行、review_id=k_{showId} 跨次稳定（explore §1.1），旧行零扰动（不 UPDATE）；旧行 ID 集合只增不减 |
| 水位语义 | :322-384 水位严格用库内 known_ids（不含本轮 seen），全新车系第 1 页全新不误停——施工报告 §三-1 声称的修复与代码吻合；test_incremental_unstable_pagination_not_early_stopped 覆盖乱序页 |
| 守卫/fail-closed 未弱化 | incremental 不跑 delete 守卫是 proposal §2.1 明文设计（守卫防 delete 破坏，增量无 delete）；full 分支守卫原样 |
| 备份前置 | 入口层 live 前 `sqlite3.backup()`（koubei_weekly_update.py:88-103, 245），失败 raise→exit 2 拒跑；备份产物有效性校验（is_file + size>0） |
| 目标库正确性 | 实证：工位现役生产 = docker compose 栈（prism-prism-dashboards-1 挂 `${PRISM_DATA_DIR:-./data}:/app/prism-dashboards/data`，8010 本机进程已不监听），deploy/data/autohome.db 即现役生产库；入口 dry-run 横幅打印该路径、30633 条与库实测一致；容器内跑则镜像无 deploy 目录自动回退挂载卷路径——两条形态都指向正确库 |
| 时区链路 | 实验：`datetime.now(timezone.utc)` 经 SQLAlchemy 存 SQLite 后 offset 被剥、读回 naive UTC 字符串；`/dash/koubei/last-run` 的 `replace(tzinfo=utc).astimezone(+8)` 与 `_last_weekly_success_utc` 的 `fromisoformat→replace utc` 两条消费路径均正确 |

---

## P1（正确性缺陷，2 条）

### P1-1 CLI 直跑 `--mode=incremental` 名单口径错：71 系 ≠ 库内全集 98 系
- **位置**：prism-dashboards/scripts/recollect_koubei_with_full.py:916-925（`__main__` 名单解析块无 mode 分支）；与 :36 docstring"名单缺省 = SELECT DISTINCT model_id FROM owner_reviews"直接矛盾
- **复现**（实测）：`python scripts/recollect_koubei_with_full.py --mode=incremental`（dry-run）→ `名单来源 ...nev_pool.json: tier=deep 共 71 系`——`__main__` 块先读 nev_pool.json 把名单填实，`recollect_all` 内部的 `_pool_series_ids_from_db()`（98 系全集）被短路
- **后果**：手动 CLI 直跑增量会漏 27 系；若 nev_pool.json 缺失则回退 config_snapshots 全量名单（对增量模式语义错误且请求量大）。主路径不受影响（koubei_weekly_update.py 直调 `rec.recollect_all(mode="incremental")` 不经 `__main__`，实测 98 系正确）
- **处置**：`__main__` 块按 mode 分支——incremental 且未显式 `--series-ids` 时不读 pool 文件、传 None 交给 `recollect_all` 走库内名单

### P1-2 prism.py 子命令白名单拒绝空格形式的带值参数（docstring 示例自相矛盾）
- **位置**：prism.py:460-465（passthrough 逐项校验）；:456 docstring 示例 `python prism.py koubei-weekly --live --budget-reviews 200`
- **复现**（实测）：`python prism.py koubei-weekly --budget-reviews 200` → `不支持的参数：200`，拒跑（return 1）；`--budget-reviews=200`（= 形式）正常。`--db path` 空格形式同挂。白名单把裸值 "200" 当独立参数判定
- **后果**：docstring 给出的示例命令无法执行；用户手动触发时易困惑（fail-closed 方向，无数据风险，缺省 budget=200 使裸 `--live` 不受影响）
- **处置**：白名单成对消费（合法 flag 的下一个非 `--` 项放行），或 docstring/部署说明统一只写 `=` 形式

---

## P2（质量项，9 条）

### P2-1 `page_all_known` 空页 docstring 与实现矛盾
- recollect_koubei_with_full.py:299-302：docstring 说"空页返回 True（…对空页返回 True 与之兼容）"，实现 `bool(page_review_ids) and all(...)` 对空页返回 **False**；测试 test_page_all_known_none 钉的是 False
- 调用方（:376）永不传空页（空页在 :354-356 提前 break），无生产行为差异。纯文档错误，但误导后来者。处置：改 docstring 为"空页返回 False；调用方在 items 为空时走自然停止路径"

### P2-2 退出码 3（"无事可做"）声明但从未返回
- koubei_weekly_update.py:7（docstring）与 部署说明.md:56 均声明 `3=无事可做`；全文无任何 `return 3`（catchup 判定不跑时返回 0）。schtasks 不消费退出码，无功能后果。处置：实现它（catchup 不补跑时 return 3）或删声明

### P2-3 dry-run 并非严格"零写入"（init_db 建表）
- recollect_koubei_with_full.py:686 `init_db()` 无条件执行，dry-run 也跑：首挂新库会 CREATE TABLE（collection_runs）并过迁移门控。**实证**：deploy 库现有空 collection_runs 表即今晚 20:04 两次 dry-run 所建（日志在案），而 prism-dashboards 开发库至今无此表。对现役库幂等无伤，但与"零写入零出网"承诺有差距；好处是端点/catchup 提前就绪。处置：文档注明"dry-run 仅首跑建表（幂等），此后零写入"，或 dry-run 跳过 init_db（不建议，代价大于收益）

### P2-4 `_last_weekly_success_utc` 对无表库抛未捕获异常（无人值守路径）
- koubei_weekly_update.py:158-173（函数）+ :301-303（run_catchup 无兜底）。实验实锤：库无 collection_runs 表时 sqlite3 抛 `OperationalError: no such table`，run_catchup 不捕获 → onlogon 任务直接 traceback 崩溃（exit 1，无日标记）
- 当前生产库表已建（P2-3 副产品）+ 部署说明前置"先手动 --live 验证跑"，实际触发窗口小；但 catchup 是无人值守路径，崩了没人看。处置：函数内 try 捕获返回 None（语义=从未跑过→补跑→init_db 建表，自愈闭环）

### P2-5 `_pool_series_ids_from_db` 不过滤 NULL/空 model_id
- recollect_koubei_with_full.py:499-504：`str(r[0])` 会把 NULL 变成字符串 "None" 入名单 → 对 "None" 系发请求 → 之家返回空 → 冷却重试 → failures（噪音失败，不损数据）。生产库实测 0 行 NULL/空（distinct=98 干净）。处置：`WHERE model_id IS NOT NULL AND model_id != ''`

### P2-6 acquire_lock 的 PowerShell 探活超时按死锁清理（活锁覆盖风险）
- koubei_weekly_update.py:182-197：`timeout=15` 的 Get-Process 探测超时走 `except: pass` → 覆盖锁 → 双实例并发。powershell 冷启动慢时可能误判。数据安全方向无虞（insert-skip 主键双保险+无删除路径），最坏=双份 progress 行与重复请求。处置：超时与探测失败区分对待（超时时宁可拒跑 return 0，探测明确"进程不在"才清理）

### P2-7 测试覆盖缺口（四项）
- a) **入口主流程零测试**：run_weekly（锁→横幅→备份→增量→台账串联）、backup_db、resolve_db_path 的 env/deploy/开发库回退分支（只测了 --db 显式与 missing 两支）均无测试——T2 是本 change 风险最集中的新文件
- b) **proposal §4 声明"prism.py 子命令冒烟"测试未交付**——tasks.md T5 未列此项，两规格文件不一致，甲方裁决（若按 proposal 则缺口，若按 tasks.md 则 proposal 应更正）
- c) test_catchup_stale_triggers（test_recollect_weekly.py:277）断言 `(ok is True and "10" in why) or ok is True`——运算符优先级使前半永真化，why 内容实际未测到
- d) finished_at aware→naive roundtrip 无测试（我实测健康，但这是时点戳/catchup 两条链路的根基，值得钉一个）

### P2-8 施工报告分项数字错
- 施工报告.md:37："既有 190 零回归 + 新增 15"。实测：HEAD 时代 7 个测试文件共 183 个测试函数 + 新文件 22 个 = 205 ✓（与 pytest 吻合）；报告自己的分类明细（3+4+2+1+1+7+2+2）加总也是 22。总数对、两个分项都错（190/15 应为 183/22）。无功能后果，台账数字应更正

### P2-9 文档/边角集合（不单独立案的小项）
- 部署说明.md:21 "给舆情 02:00 夜跑让 2h 头位"——现役 PrismSentimentDaily 实际触发 03:00（PowerShell 实查），背景叙述口径小出入，不影响命令正确性
- koubei_weekly_update.py:254-262 vs 290-293：SystemExit 分支写台账 error 行，普通 Exception 分支（如备份失败 RuntimeError）不写——台账覆盖不对称，排障时日志 BLOCKED/ERROR 行有兜底
- run_catchup 补跑被锁占用（run_weekly 返回 0"已有运行实例"）时仍写日标记——当天不再补，次日判定自愈；语义可辩（当天确实"判定过"），记录备查
- 施工报告 §五"容器同文件立即可见（WAL 同机挂载）"：Docker Desktop Windows bind mount 上 SQLite WAL 的文件锁语义是已知坑域（现役 sentiment 库同形态在跑=既有形态），建议 Step 9 首跑后顺手验证容器侧 last-run 端点读到新台账行
- 中断重连不省页：入口每周滚动 progress 后，live 中断重跑会重探全部系（水位 1 页/系 ≈98 页打底兜底，语义自洽，注记即可）

---

## 混入项（工作树既有未提交改动，非本 change 声明范围，Step 10 归档注意剥离）

1. **dash_series.html**：peer-tabs 顺序互换（情绪画像在前）+ 默认 tab profile + sessionStorage 默认值（dash_series.html diff 中段）——看板重构遗留。施工报告 §一⚠️ 已声明该文件"混有工作树既有未提交改动，本 change 只动 page-sub 一行"，声明与实际吻合 ✓
2. **dashboard_routes.py:185-190**：koubei_dashboard 的 122 车系过滤（`summ is None: continue`）——施工报告的混入声明只点名了 dash_series"等文件"，未点名此处的具体内容；归属请 Step 10 时向该改动来源 change 核对

---

## 施工报告声称的验证是否属实（逐项核对）

| 施工报告声称 | 核对结果 |
|---|---|
| pytest 全量 205/205 绿 | ✅ 属实（复跑 205 passed in 1.58s）；⚠️ 分项"190+15"数字错，实际 183+22（P2-8） |
| dry-run 端到端实测（横幅/30633 条/98 系/budget 200） | ✅ 属实（复跑逐字吻合；横幅目标库=deploy 库=现役容器生产库，正确） |
| `--catchup --check` 实测"需补跑 · 无成功周更记录" | ✅ 属实（复跑一致） |
| `prism.py koubei-weekly` 透传冒烟 + 非法参数拦截实测 | ✅ 属实，但**拦截过宽**：合法空格形式 `--budget-reviews 200` 也被拦（P1-2），报告未发现 |
| full 路径"逐行未动" | ✅ 语义等价成立（diff 逐块核对）；严格说 `[LIVE|full]` 打印前缀与 stats `mode` 键两处 cosmetic 变化，不构成行为改动 |
| 名单缺省=库内有口碑全集（实测 98 系） | ✅ 入口路径属实；❌ CLI 直跑路径 71 系（P1-1），报告未发现 |
| 水位严格用库内既有（§三-1 修复） | ✅ 代码与测试吻合 |
| `--live` 未跑（留 Step 9） | ✅ 属实（生产库台账空表、无 weekly_progress、无 pre-weekly 备份件、progress 无滚动件，四项实证） |
| R1 双库漂移 / R2 failures.json 落点 / R3 tagged=0 / R4 并发写 | ✅ 四项遗留均如实，与代码核对无误 |
| 退出码 0/1/2/3（T2） | ⚠️ 0/1/2 属实，3 未实现（P2-2） |
| "零写入零出网"（dry-run 承诺） | ⚠️ 出网属实；写入有 init_db 建表例外（P2-3，实证） |
| 测试分类明细（水位3/增量4/幂等断言2/预算帽1/台账1/catchup7/滚动2/解析2） | ✅ 分类与文件实测吻合（加总 22，与 P2-8 的总数口径错互为印证） |
| schtasks 双任务命令（部署说明） | ✅ 形态与现役 PrismSentimentDaily/Catchup 同款（Interactive 免管理员，PowerShell 实查两任务在册）；本 change 命令显式 `cd /d` 比舆情同款更防呆；`/sc weekly /d SUN /st 04:00` 与 `/sc onlogon` 语法正确；logs 目录已存在（重定向前提成立） |

## 给 Step 9 的建议顺序

1. 先修 P1-1 / P1-2（各 ~10 行）；P2-4（catchup 兜底 try）建议顺手修
2. 其余 P2 可记台账后置（P2-3/P2-9 属文档对齐，P2-7 测试补强可并入后续）
3. 首跑 `--live` 时按 tasks.md 验收清单走（ID 稳定性断言脚本施工报告未附，Step 9 现场做）
