# Review Response（Step8，2026-10-20）

审查来源：step7-review.md（隔离子代理，第二次派发命中完整工具面；第一次 NO-TOOLS 守卫退出零成本）。
审查结论"需修复后归档"——P0×1 / P1×1 / P2×8。处置如下。

## 修复（4 条）

| 级别 | 发现 | 处置 | 验证 |
|---|---|---|---|
| **P0** | **第三调用点漏适配**：`api/routes/analysis.py:75`（/analysis/trigger 管线，scripts/reanalyze.py 直接消费）——proposal 自述"grep 全覆盖"失实。元组被 `json.dumps` 写成 `"[[...], false]"` 损坏 payload（TTL 24h 内吐给前端渲染坏卡）、degraded 被忽略（T11 清空覆盖在此路径复活）、窗口列写 date 对象且实际走 mine 默认 7 天窗、`len(dstats)` 恒 2 污染遥测 | **已修**：镜像 Phase 8 权威模式（30 天窗 isoformat 传入 + degraded 跳写保旧 + 遥测计数移到落库后） | `test_analysis_trigger_produces_defects_events` 重写：payload 结构断言（元组形状即刻失败）+ 30 天窗断言 |
| **P1** | 该路径零测试防护：test_degradation_visibility 的 mock 返回裸 `[]` 旧签名，仅断言"调用过"→ P0 全程假阴性 | **已修**：mock 改元组 + 共享 session mock 采集 DefectTheme 写库入参；**新增** `test_analysis_trigger_degraded_keeps_old_payload`（degraded 不写库） | 两用例绿（首版录制器类撞 ORM delete() 构造，改走共享 session mock 方案） |
| P2④ | Phase 8 遥测计数先于落库（commit 失败仍计数） | **已修**：collection.py/analysis.py 两处移到 commit 后 | 单测过 |
| P2⑤ | defect_miner 模块头 docstring 漂移（"Phase 9"“静默返回空”均为旧语义） | **已修**：头注释同步三元组语义/三调用点 | — |

## 记录不修（4 条，不阻塞）

- **P2①** degraded 且无行时端点返回 []，前端文案显示"暂无发酵事件"（语义残影，边界场景：该车从未算出过簇+恰逢 LLM 停机）。改法要动前端契约（加 degraded 标志），收益窄，留观察。
- **P2②** test_defect_miner.py:624 TTL 用例种子用本地时 now（因 +8h 偏移恒命中，不判别 H1 修复正误）+ test_defect_cache_tz 的死 patch 残段——测试质量瑕疵非行为缺陷，H1 已由 calibar_regression 的 utcnow 断言锚定。
- **P2③** utcnow DeprecationWarning（Python 未来版移除）——全仓既有模式，统一迁移另起小轮。
- **P2⑧** LLM 停机期间端点自愈重试同步阻塞最长 30s/次（无负缓存）——非回归（旧行为同款），建议后续加"失败短 TTL 负缓存"，与 P2① 同属降级体验优化。

## 外部事项（超出本 change，转运维清单）

- **P2⑥ app.js 工作树 20 hunk 中 18 个非本 change**（并行会话的完整版图表改造：dimPosChart/dimNegChart 拆分等，未提交）——**提交时按 hunk 分离**（本 change 仅 2 hunk：onVehicleChange 复位 + loadDefectThemes 守卫），并行改动留给其归属会话收账。
- **P2⑦** run_cleanup dry-run 早退不关连接——存量非本次引入，随下轮清理脚本维护顺手修。

## 终态

pytest 全量 **908 passed / 1 failed（test_cache_bust 已知存量挂）**。可归档。

## 教训沉淀

1. **"grep 全覆盖"式自查必须给出 grep 命令与命中清单**——本 change 自查时只搜了 pipeline/ 与已知调用文件，漏掉 api/routes/analysis.py 这类"管线收敛时复制的第二入口"。破坏性签名变更的调用方清点用 `grep -rn "fn(" --include="*.py" .` 全仓跑一遍再下结论。
2. 隔离审查第二次实证抓到主会话自查盲区（P0 是真行为缺陷且已有活消费方 reanalyze.py）——重试制（NO-TOOLS→重派）零成本换真审查，流程正确。
