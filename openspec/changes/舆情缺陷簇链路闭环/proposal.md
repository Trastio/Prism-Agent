# Proposal：舆情缺陷簇链路闭环（轻量十步，2026-10-20 用户拍板"开干"）

## WHY

缺陷簇这条链路前后端都没闭环：前端切车竞态把 A 车的簇画到 B 车看板上（用户实证）；后端窗口互踩（管线 90 天 vs 浏览 30 天）导致每次切换全量重算烧 LLM；LLM 一失败就把好载荷清空覆盖（T11 实证 3 簇→0）；事件表塞满已删帖悬空引用且 post_count 虚高。

## WHAT（5 任务）

### T1 前端竞态守卫（app.js）

- `loadDefectThemes` 进门捕获 `const token = this._vehicleChangeToken`；await 返回后 `token !== this._vehicleChangeToken` 即丢弃（与主看板 14 请求同款守卫，app.js:529 模式）。
- `onVehicleChange` 复位清单加 `defectThemes=[]` + `defectLoading=false`（切车瞬间旧卡隐藏）。
- fetch 不再传 start/end（端点参数退役，见 T3）。

### T2 defect_miner：LLM 失败语义 + 车型锚

- 新增 `DefectJudgeError`；`_judge_defect_clusters` LLM 异常/坏 JSON 时 **raise**（原：静默 []）。
- `mine_defect_themes` 返回 `(themes, degraded)`：judge 失败 → `([], True)`（degraded=保旧信号）；聚类无合格簇/池空 → `([], False)`（合法空，正常落库）。
- judge prompt 注入车型锚：`本看板车型为 {vehicle_name}。若簇内代表评论主要讨论其他车型（如对比推荐/吐槽他车），is_defect=false`。`vehicle_name` 从既有 veh_row 透传。

### T3 权威口径：统一 30 天窗 + TTL 自愈（collection.py Phase 8 + dashboard.py 端点）

- **Phase 8**：不再吃采集管线的 90 天窗，固定算 `end=今天, start=今天−29天`；`degraded=True` → **跳过写入保旧载荷**（原：无条件 delete+insert）。
- **端点 `/defect-themes/{id}`**：start/end 参数保留签名但退役（docstring 注明）；TTL 24h 内有行即返回（不再比对 window）；过期/无行 → 按同一 30 天窗自愈重算落库；degraded → 返回旧载荷（无行才返回 []）。
- 效果：载荷只由"夜间批产 + 过期自愈"两种路径产生，单一窗口，不再互踩。

### T4 事件表 prune 闭环（cleanup_posts.py）

- `prune_event_groups` 修剪时同步 `post_count = len(kept)`（修判据失真）。
- 新增 `--prune-only` 模式：全量扫 event_groups，剔除**库中已不存在**的 id（不限本次删集，修存量悬空）+ post_count 对齐；幂等、不删任何数据；配 `--dry-run` 先看数。
- `.env` 落 `PRISM_CLEANUP_LIVE=1`（执行 10-15 已拍板的 R40 30 天物理删除；首跑前手动备份）。

### T5 测试与验证

- test_defect_cache_tz.py 重写：TTL 命中与参数无关 / 过期触发重算（30 天窗）/ degraded 返回旧载荷。
- test_collection_api.py Phase 8 适配 tuple 返回 + 新增 degraded 保旧用例。
- 新增 prune-only 单测（悬空剔除/post_count 对齐/幂等）。
- `node --check app.js`；pytest 相关文件全绿；服务重启后端点实测。

## 验收标准

1. 复现路径关闭：快速切车（含目标车触发 LLM 重算场景）缺陷簇卡不再显示他车簇；切车瞬间旧簇隐藏。
2. 手动 mock LLM 失败 → 旧载荷保留（库内 computed_at/payload 不变）。
3. Phase 8 与端点写入的 window 一致（今天−29 ~ 今天）；浏览切换不再触发重算（日志无多余 Defect mining）。
4. `--prune-only --dry-run` 报告的悬空数与修复后实际剔除数一致；修复后事件 post_ids 零悬空、post_count=len(post_ids)。
5. 存量清理 live 首跑：dry-run 数字先行过目，备份先行，删数=快讯帖数（paused 豁免生效）。

## 不做（明确出界）

- 计划任务 S4U 化（需管理员权限，用户侧动作，另列运维清单）
- 评论极性打标回自动轮 / 智谱替代实验（待用户拍板过渡方案）
- 评论层跨车过滤（银河TT 簇里星愿评论类；先靠 judge 车型锚缓解，观察后再议）
- defect_themes 多窗口缓存（v11/v12 列保留不回滚，写入侧统一 30 天窗后自然单一）

## 风险

- mine 返回值改 tuple 是破坏性签名变更：调用方仅 collection.py/dashboard.py/测试（已 grep 全覆盖）。
- CLEANUP_LIVE 首跑删帖不可逆：备份先行 + dry-run 过目 + paused 豁免已内建。
- 服务在跑（:8000）：Python 改动需重启生效；重启窗口选在验证前，kill 树后复查探活（supervisor 自动复活坑）。
