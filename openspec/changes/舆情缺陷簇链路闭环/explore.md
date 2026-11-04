# Explore：舆情缺陷簇链路闭环（2026-10-20）

## 起因

用户在 T7 看板的缺陷话题簇里看到 T11 的帖子（音质帖）。审计定性：**数据未串车，前端渲染串车**；同时挖出缺陷簇链路三处结构缺陷 + 两处运营断线。

## 已核实事实（全部库内/代码实证，2026-10-20）

1. **音质帖只存在于 T11 名下**（raw_posts 唯一行，douyin，subject=self）。T7 的 535 帖含"风云T11"字样 0 条；T7 缺陷簇 87 帖全部属 T7、零悬空；事件零跨车引用；全库评论无第二处文案。
2. **前端竞态（本次直接根因）**：`loadDefectThemes`（app.js:766-776）fire-and-forget 且无 `_vehicleChangeToken` 守卫；`onVehicleChange` 复位清单不含 `defectThemes` → 切车后旧车慢响应（LLM 重算秒级~几十秒）晚到覆盖新车缺陷簇卡。
3. **窗口互踩**：采集管线 Phase 8 用 90 天窗（collection.py:80 `start = end - timedelta(days=90)`）；前端浏览传 30 天窗（rangeStart/rangeEnd 默认）→ 每次切换 TTL `window_start==start` 不匹配 → 全量重算+全量覆盖（烧 LLM）。
4. **LLM 失败清空覆盖**：`_judge_defect_clusters` 失败/坏 JSON 静默返回 []（defect_miner.py:239-269），`mine_defect_themes` 无法区分"合法空簇"与"LLM 挂了"；Phase 8 与端点都会把好载荷覆盖成空。实证：T11 载荷 10-19 15:48 有 3 簇 → 19:47 Phase 8 重算写 0 簇（svc 日志 06:11 两次 DNS 失败→0 themes 同路径）。
5. **事件表悬空引用**：T7 的 21 个事件全部含已删帖 id（95/60/42 条不等）——10-16 首删执行时 S3 prune 尚未合入；此后清理一直 dry-run（.env 无 PRISM_CLEANUP_LIVE），prune 从未真跑。`prune_event_groups` 只剔"本次删集内"的 id，不修存量悬空；且不更新 `post_count`（轻卡 post_count≥2 兜底判据失真）。
6. 运营断线（本 change 外挂账，见 proposal §不做）：计划任务交互式限制（10-19/10-20 03:00 未跑，0x800710E0；10-19 傍晚手动补采 139 帖）；评论极性覆盖率 35-54%（TAG_IN_SERVICE 关闭后无夜跑）。

## 受影响面

- `pipeline/analysis/defect_miner.py`（judge 失败语义 + 车型锚）
- `api/routes/collection.py` Phase 8（固定 30 天窗 + degraded 保旧）
- `api/routes/dashboard.py` `/defect-themes`（TTL 语义 + 自愈重算 + degraded 保旧）
- `frontend/static/js/app.js`（竞态守卫 + 复位 + 参数退役）
- `scripts/cleanup_posts.py`（prune post_count 同步 + --prune-only 存量修复）
- `.env`（PRISM_CLEANUP_LIVE=1，执行已拍板的 R40）
- tests：test_defect_cache_tz.py 重写、test_collection_api.py Phase8 适配、test_defect_miner.py 检查、test_caliber_regression.py L109 utcnow 断言保持

## 消费方确认

- 缺陷簇端点仅完整版消费（轻卡 9 端点不含 defect-themes）→ 前端契约（返回数组）不变。
- 轻卡事件卡走 `/vehicles/{id}/events`（event_groups.post_count）→ prune 的 post_count 同步受益。
