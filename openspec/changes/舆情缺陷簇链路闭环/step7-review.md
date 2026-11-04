# Step 7 隔离代码审查 — 舆情缺陷簇链路闭环（2026-10-20）

审查方式：不采信设计自述，全部结论来自磁盘代码实读 + 全仓 grep + pytest 复跑。
复跑结果：`python -m pytest tests/test_defect_miner.py tests/test_cleanup_posts.py tests/test_time_window.py -q` → **55 passed**（仅 utcnow DeprecationWarning）。

---

## 一、审查重点逐项核验（A–G）

### A. 前端竞态守卫 — 通过
- `frontend/static/js/app.js:530` token 在 onVehicleChange 入口递增捕获；`:549-550` 切车瞬间复位 `defectThemes=[] / defectLoading=false`（旧卡隐藏）；`:571` Promise.all 后比对丢弃。
- `app.js:776` loadDefectThemes 进门捕获 `const token = this._vehicleChangeToken`（调用点仅 `:579` 一处，且在 token 校验之后）；`:780` await 后 `token !== this._vehicleChangeToken` 即丢弃——旧车响应无写入路径（赋值 `this.defectThemes = data` 是唯一写点，前面有守卫）。
- `:783` finally 条件复位 `if (token === this._vehicleChangeToken)`：token 不匹配时不复位，但该场景下 onVehicleChange `:550` 已把它复位为 false，随后新车自己的 loadDefectThemes 正常走 true→false。逐路径推演（B 进行中切 C / Promise.all 抛错 / apiFetch 抛错）均无 defectLoading 卡死路径。
- `:779` fetch 已不传 start/end（参数退役落地）。

### B. degraded 语义三层贯通 — 通过（一处 P0 例外见下）
- miner 层 `pipeline/analysis/defect_miner.py:334-369`：池空→`([],False)`（L337）、无合格簇→`([],False)`（L360）、judge 失败→`([],True)`（L364-366）；合法空与失败严格区分。`_judge_defect_clusters` LLM 异常（L273-277）与坏 JSON（L279-282）均 raise `DefectJudgeError`，不再静默 []。
- Phase 8 层 `api/routes/collection.py:122-144`：`degraded` → 只 warning 跳写（L125-128），旧载荷保留；否则 delete+insert。
- 端点层 `api/routes/dashboard.py:1671-1678`：degraded → 有行返回旧行、**无行返回 [] 但不落库**——空列表不会被当正常数据缓存（不写库即无 TTL 行，下次仍会重算）。TTL 命中路径（L1662-1665）只读不写。
- 车型锚 `_JUDGE_PROMPT`（L58-72）双处 `{vehicle_name}` 锚 + "主要讨论其他车型 is_defect=false"，`vehicle_name` 由 mine 内 veh_row 透传（L342-353）。格式化参数 n/vehicle_name/clusters_text 齐全，花括号已转义。

### C. 窗口一致性 — 通过
- Phase 8 `collection.py:120-124`：`d_end=today, d_start=today−29`，isoformat 传入。
- 端点 `dashboard.py:1669-1672`：逐字符同算法。
- `_complaint_pool`（defect_miner.py:91-101）：`since=fromisoformat(start)`（当天 00:00 含），`until=fromisoformat(end)+1day` 且条件 `< until`（end 当天 23:59:59 含）——30 个自然日双闭区间，两调用方完全一致。date-only 字符串 `fromisoformat` 合法。
- TTL 比对已删窗口条件（dashboard.py diff：`age < 86400 and row.window_start == start...` → `age < 86400`），单一窗口后正确；TTL 用 `datetime.utcnow()` 对 `computed_at`（`models/schemas.py:280` `server_default=func.now()`，SQLite CURRENT_TIMESTAMP=UTC），生产写入路径均不显式设 computed_at，口径自洽。

### D. 破坏性变更调用点 — **发现遗漏（P0）**
全仓 grep `mine_defect_themes\(` 共 9 个代码调用点：dashboard.py:1671 ✓、collection.py:122 ✓、test_defect_miner.py 4 处 ✓、test_collection_api.py（patch 处）✓、**api/routes/analysis.py:75 ✗ 未适配**。docs/superpowers/plans 下命中为历史设计文档非代码。proposal"调用方仅 collection.py/dashboard.py/测试（已 grep 全覆盖）"自述失实。

### E. prune 逻辑 — 通过
- `cleanup_posts.py:146-149` live 修剪 UPDATE 同时写 `post_count = len(kept)`，且在 `run_cleanup` 的 `with con:` 单事务内（L249-253），与三表删除同生共死。
- `prune_dangling_refs`（L154-192）：幂等（二跑全零，test_idempotent 实证）；干净行判据 `not removed and post_count == len(kept)` 跳过（L178）；仅 count 漂移行也修复（counts_fixed）。函数内 `con.commit()`（L191），异常时 main 的 `finally: con.close()` 无 commit → sqlite 隐式回滚，安全。
- main `--prune-only` 分支（L289-303）自带连接 + try/finally close + 异常退出码 1。
- `.env:21` `PRISM_CLEANUP_LIVE=1` 已落地（带备份注释）；LIVE 门在 `scripts/daily_update.py:206`（cleanup_posts 本体 CLI 是手动工具，语义与前版一致）。

### F. 测试真测假测 — 通过（两处小瑕见 P2）
- `test_defect_miner.py:507-527` degraded 用例：真种子 2 帖 16 评论 + call_llm raise → 断言 `([], True)`，真走 degraded 分支。
- `test_defect_miner.py:709-760` 端点 degraded：预置 25h 旧行 + mine 返回 `([], True)` → 断言**返回旧载荷且库内行原封不动**，真走端点 degraded 分支。
- `test_collection_api.py:257-294` Phase 8 degraded：预置旧载荷 → mine `([],True)` → 断言旧行未删未覆盖；`:210-254` 落库用例断言 window=`today−29~today`。
- `test_time_window.py:164-218` 30 天权威窗：真端点 + monkeypatch `_cluster_complaints` 捕获池，验证用户窗 2020 被无视、40 天前帖不进池、coalesce 兜底仍生效。
- `test_cleanup_posts.py:230-296` prune 系列全真 sqlite 临时库断言 DB 终态（post_count 同步/悬空剔除/幂等/dry-run 不写）。
- 未发现断言恒真；`test_caliber_regression.py:110-112` 的 utcnow 源码文本断言较弱但属回归护栏非本 change 新增。

### G. post_count 消费方 — 通过
- 原生前端 `frontend/index.html:366` `{{ e.post_count }} 帖`：修剪后如实显示（空组可显示"0 帖"，与"空组保留=话题记录"语义一致）。
- `prism-web/src/components/dashboards/SentimentBoard.tsx:151` `filter(e => e.post_count >= 2)`：即"≥2 兜底"。post_count 对齐前该判据被虚高计数污染（已删帖仍计入，死事件滞留轻卡）；对齐后判据恢复准确，**无显示层破坏，反而修正一处隐性失真**。数据源 `:103` `/vehicles/{id}/events` → `dashboard.py:1445` post_count 纯透传。
- `api/routes/reports.py:219/332` order_by post_count desc：计数变小只影响排序，无破坏。

---

## 二、问题清单

### P0-1（必须修复）：analysis.py 第三个调用点未适配 tuple 返回——破坏性变更遗漏，T11 清空覆盖 bug 在 /analysis/trigger 路径复活

- **位置**：`prism-sentiment/api/routes/analysis.py:75-86`
- **摘录**：
  ```python
  dstats = await mine_defect_themes(vehicle_id, session)      # ← 现在是 (themes, degraded) 元组
  pipeline_phases[vehicle_id]["defect_themes"] = len(dstats)  # ← 恒等于 2
  ...
  session.add(DefectTheme(..., window_start=start_d, window_end=end_d,
                          payload=json.dumps(dstats)))        # ← 写入 "[[...], false]"
  ```
- **影响**（四连）：
  1. `json.dumps(dstats)` 把元组写成 `[[簇列表], false]`——payload 结构损坏。TTL 端点 `dashboard.py:1665` 命中后原样吐给前端，`index.html:391` 的 `v-for` 遍历这个二元数组，`defectThemes.length==2` 恒真 → 渲染 2 张 `d.severity/d.name` 均为 undefined 的坏卡（class `sev-undefined`），持续 24h。
  2. `degraded` 被完全忽略：judge 失败时 `([], True)` 照样 delete 旧行 + 写入 `[[], true]`——**本 change 要修的"LLM 失败清空覆盖好载荷"在 /analysis/trigger 路径原样存在**。
  3. 窗口也不一致：`start_d = end_d - timedelta(days=30)`（31 天跨）且 window 传 `date` 对象非字符串，与两处权威写入口径（−29、isoformat）漂移。
  4. `len(dstats)` 恒 2 污染 pipeline_phases 遥测（终态 dict 覆盖，影响短暂）。
- **活路径实证**：`scripts/reanalyze.py:80` 直接 POST `/api/analysis/trigger/{id}`；`tests/test_analysis_api.py:70` 覆盖该端点；`docs/舆情项目-架构.md:140` 将其列为含写副作用的活端点。git status 确认 analysis.py 不在本次改动文件中。
- **建议**：按 Phase 8 同款适配（解包元组 / degraded 跳写 / −29 窗 / isoformat），或最低成本先摘除该块的 DefectTheme 写入只留遥测；同步修 P1-1 的 mock。

### P1-1（随 P0 一并修）：旧签名 mock 掩蔽 P0，测试全绿属假阴性

- **位置**：`prism-sentiment/tests/test_degradation_visibility.py:102-104`
- **摘录**：
  ```python
  async def _fake_mine(*a, **kw):
      calls.append("mine_defects")
      return []          # ← 旧签名裸 list；生产已改 (themes, degraded)
  ```
- **影响**：该测试只断言"调用过"，mock 返回旧签名使 analysis.py:75 在新签名下零异常零断言——P0 的破坏性变更**完全无测试防护**，55 passed 不能证明这条路径健康。
- **建议**：mock 改返回 `([], False)`；补一条 `/analysis/trigger` 路径下 defect_themes 落库结构断言（payload 必须是簇列表 JSON 而非二元数组）。

### P2-1：degraded 且无行时返回 []，前端与"合法空"不可区分，文案误导
- `dashboard.py:1678` 无行返回 `[]`；`index.html:389` 空态文案"区间内无缺陷话题簇（评论不足或未达准入门槛）"——在"从未成功产过簇的新车 + LLM 失败"场景把"判定失败"展示成"没有缺陷"，正是 T11 的语义事故残影（仅边界场景，后端有行时已正确保旧）。建议响应带 degraded 标志或空态文案分两态；顺带"区间内"措辞随 start/end 退役已过时。

### P2-2：TTL 用例种子时区不自洽，判别力弱
- `test_defect_miner.py:624` `computed_at=datetime.now()`（本地时）种进 UTC 语义列：若 endpoint 回归 `datetime.now()`（H1 老 bug）该用例仍过；判别实际由 `test_defect_cache_tz.py:20`（utcnow 种子）承担。另 `test_defect_cache_tz.py:64-66` 外层 patch 被内层 `:79` 遮蔽成死代码。建议种子统一 utcnow、删死 patch。

### P2-3：`datetime.utcnow()` DeprecationWarning（Python 3.12+ 弃用）
- `dashboard.py:1663`（及 test_defect_miner.py:676/732）。当前 naive-UTC 对 naive-UTC 比较正确；建议统一迁移 `datetime.now(timezone.utc)`（注意 DB 列为 naive，须同步去 tzinfo），避免未来版本断裂。

### P2-4：Phase 8 遥测计数先于落库
- `collection.py:130` `pipeline_phases[...]["defect_themes"] = len(themes)` 在 delete/insert/commit 之前设置；后续写库抛异常时残留未持久化的计数值（终态 completed dict 会覆盖，影响窗口极短）。建议移到 commit 后。

### P2-5：docstring "Phase 9" 命名漂移
- `models/schemas.py:272-273`、`scripts/cleanup_posts.py:17` 仍称"Phase 9 全量覆盖"，collection.py 现标 Phase 8。顺手对齐。

### P2-6：app.js 工作树混行
- `git diff` 显示 app.js 有 ~20 个 hunk（L33~L1109），远超本 change 自述的两处块（onVehicleChange 复位 + loadDefectThemes 守卫，均已实证正确）。疑与并行未提交改动（尾巴包/舆情缺口爬链闭环）混在同一工作树——本仓有"工作树混行"前科（上轮审查 P2-6 同名项）。Step9 提交前须按 change 分离，保证可追溯。

### P2-7：run_cleanup dry-run 早退不关连接（存量，非本 change 引入）
- `cleanup_posts.py:244-245` `if dry_run or not post_ids: return result` 绕过 L255-256 的 `con.close()`（own 连接泄漏至 GC）。diff 证实该行为前版已存在，本 change 未触碰；daily_update 高频调用路径建议顺手补 try/finally。

### P2-8：LLM 停机期间端点无退避
- `dashboard.py:1662-1678` degraded 不刷新 computed_at（正确——不能把失败伪装成新数据），代价是停机期间每次开看板都同步重跑 mine（池查询+聚类+最长 30s LLM 超时，`defect_miner.py:274` timeout=30），缺陷簇卡可卡 30s/次。非回归（旧行为同卡且更糟），建议后续加短期负缓存/退避。

---

## 三、结论

**需修复后归档。**

- 本 change 声称的六项改动（T1-T5）本身施工质量高：竞态守卫无泄漏路径、degraded 三层语义贯通且不写库、30 天窗双写入口逐字符一致、prune 幂等且有真测试、55 passed 复跑全绿、post_count 消费方无显示层破坏。
- 但 D 项破坏性变更 grep 遗漏了活调用点 `api/routes/analysis.py:75`：tuple 未适配 → payload 结构损坏 + degraded 覆盖写（T11 复活）+ 窗口漂移，且被旧签名 mock 完全掩蔽。P0-1 与 P1-1 修复并补一条结构断言测试后，方可进入 Step8/归档。
- P2 各项不阻断，建议随 P0 修复批次顺手处置（至少 P2-1 文案与 P2-6 混行分离需在 Step9 前处理）。
