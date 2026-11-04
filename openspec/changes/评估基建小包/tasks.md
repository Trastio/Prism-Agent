# 评估基建小包 · 任务单

> 施工=子代理（fork 型重试制）；勾选事后勾（2026-10-15 全部完成）。

- [x] T1 渲染器：report JSON → 四 sheet md+xlsx；离线渲染 v1.1 既有报告出样张（60/54/6 对账一致）
- [x] T2 首错轮判定逻辑 + 单测（最早缺锚/违禁轮；timeout 除外；NaN 守卫）
- [x] T3 runner：批跑收尾产物 SHA-256 sidecar manifest（洞2；Step8 后记相对路径可跨机复算）
- [x] T4 runner：报告顶层 acceptance_boundary（Step8 后改 results 行驱动，boundary 与 summary 永不失配）+ 渲染进页脚（洞3）
- [x] T5 scoring-rules.json：calibration_log 回填 4 条（Step8 后第 1 条改 2026-10-13 并标注"回填记录非校准事件"）+ 政策声明；判分键零触碰（单测锁）
- [x] T6 runner：取消题 abort_after_turn 机制（调 /chat/abort；真题入库后启用）
- [x] T7 单测：16 项（12 施工 + 4 审查补测：多轮衰减分支/NaN 守卫/timeout 分类/rows 驱动 boundary）
- [x] T8 离线验证：渲染样张与成绩单对账 + 低分 6 题首错轮全有值（单轮题=1）
- [x] T9 Step7 隔离审查（eval-infra-review：P0=0/P1=4/P2=7）→ review-response（修8/裁决1/记录2）
- [x] T10 Step9 统一验证 + verification.md + 归档（67/67 全套绿；真实批跑兜底随 v1.2 轮）
