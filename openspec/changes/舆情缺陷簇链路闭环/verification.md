# Verification（Step9，2026-10-20）

## 测试

- 全量 pytest：**907 passed / 1 failed**——唯一失败 `test_cache_bust.py::test_index_serves_mtime_versions` 为已知存量挂（10-16 起在账，与本 change 无关，git 未动该文件）。
- 本 change 触碰面专项：test_defect_miner / test_defect_cache_tz / test_cleanup_posts / test_collection_api / test_time_window = 78+5 全绿。
- `node --check frontend/static/js/app.js` 通过。

## 验收标准逐条（proposal §验收）

1. **复现路径关闭（前端竞态）**：loadDefectThemes 加 token 守卫 + onVehicleChange 复位 defectThemes/defectLoading（app.js，注释"竞态收口/竞态守卫"锚点）。node 语法过；浏览器走查留用户眼见为实（vanilla Vue 无自动化面）。
2. **LLM 失败保旧载荷**：单测三处实证——`test_mine_defect_themes_degraded_on_judge_failure`（([], True) 信号）、`test_pipeline_phase8_degraded_keeps_old_payload`（Phase 8 跳写）、`test_defect_themes_endpoint_degraded_keeps_stale`（端点返回旧载荷不落库）。真实链路历史佐证：10-17 06:11 两次 DNS 失败曾产出 0 themes（旧行为），新代码同场景保旧。
3. **窗口统一 30 天**：Phase 8 与端点同算法（`date.today() - timedelta(days=29)` ~ `today`）；`test_pipeline_phase8_persists_defect_themes` 增 window 断言；`test_defect_themes_uses_30d_authoritative_window` 极端用户窗（2020 年）被无视。**活端点实测**：T7 defect-themes 返回 3 簇 0.05s（TTL 命中，未触发重算——旧代码此场景必重算）。
4. **prune 闭环**：单测 5 个（dry-run 零写入/剔除+对齐/幂等/count 同步）。**生产库实跑**：`--prune-only` 修剪 197 组/剔除悬空 id 1,968 个/post_count 对齐 28 组；终态复核 **621 组悬空 0、post_count 不一致 0**。
5. **存量清理首跑（R40 执行）**：备份先行（backups/vehicle_sentiment_manual_20261020_pre-live-cleanup.db.gz，24MB）；dry-run 过目后 live：删帖 153（8 活跃车 09-17~09-19 越线帖）/评论 747/分析行 146/事务内修剪事件组 34，0.3s；paused 豁免 2,233 帖全保；终态活跃车越线残留 0。

## 服务与运维

- :8000 重启完成（原 supervisor 28160 孢生的 uvicorn 49792 载新代码；误起重复 supervisor 已杀净，单实例 health=200）。
- `.env` 新增 `PRISM_CLEANUP_LIVE=1`——此后 daily_update 收尾清理真删（R40 拍板执行）。
- 计划任务命令内 `TIKHUB_DAILY_BUDGET=4000` 与 .env 7000 的双预算漂移**未在本 change 动**（运维项，见 proposal §不做）。

## 声明项（未自动化/留观察）

- 前端切车竞态的浏览器级复现验证（需真人快速切车；守卫逻辑与主看板 14 请求同款成熟模式）。
- judge 车型锚的实际拦截效果（依赖 LLM 行为，观察 T7/T11 后续簇质量；单测只锁 prompt 含锚）。
- 存量悬空修复后事件展示（部分老事件 post_count 变小，个别可能从"≥2"档掉出轻卡事件卡——语义上这是修正而非回归）。
