# Step8 · 隔审处置（2026-10-20）

审查：step7-review.md（第二个子代理，重试制命中完整工具面；第一个 NO-TOOLS 守卫零成本退出）。
计数 0P0 / 2P1 / 8P2 → **修 8 / 记 2**。主会话逐条核实后处置，全部实证成立。

## 修复（8）

| # | 发现 | 处置 |
|---|---|---|
| P1-1 | 空串 vehicle_name 静默解析到错车（includes('') 恒真，实测返 Model Y） | resolveVehicleId 入口守卫：空/纯空白 → null（fail-closed）。复跑单测 4/4 |
| P1-2 | e2e_check.py trajectories 兜底三缺陷（无窗口过滤/回灌多行错位/无 submission 行假红） | 重写 traj_pass：UTC 时间窗过滤（ localtime 时区 bug 一并修）+ 只认 submission 行 + 窗口末行=终态；重放验证双 True |
| P2-1 | eval/tool_matrix.py TOOL_UNIVERSE 漏 sentiment_defects（违反其头注同步要求） | 已补 |
| P2-2 | eval/trap_check.mjs GATE_DESC 静态副本缺 defects 段（泄漏判分覆盖缺口） | 已补，与 index.ts 出口闸描述逐字同步；smoke:trap 31/0 |
| P2-4 | fallback 失败与"真未收录"语义合并（服务宕也报"不在收录范围"） | fallback catch 加日志留痕 + unavailable 文案升级为合并措辞（"或舆情服务暂时不可达，可稍后重试"） |
| P2-5 | /sentiment/vehicles-all 表级异常裸 500 | execute 包 sqlite3.Error → 503（对照 /verify/claim 防护语义） |
| P2-6 | sentiment_tools.test.ts 注释失真 + 降级分支是死路径 | 注释对齐；删降级分支改 fail-loud（token 读不到=栈不完整，红是正确信号，与 auth_smoke 同哲学） |
| P2-7 | index.ts 注释计数漂移 4 处（21/6/6 组/25 个，含"14 Atuohome"旧口径） | 全部对齐：23 个/7/7 组/23 个（3+7+11+1+1） |

## 记录不修（2）

| # | 发现 | 裁决理由 |
|---|---|---|
| P2-3 | fuzzy 多候选静默选车（"风云"实测命中 T9 非 T7；风云族 6 台全 active，旧"无冲突"论断过时） | 既有行为非本 change 引入；有前置防线兜底（工具描述强制 resolve_series 前置核验，E2E 第二轮实测 agent 确实先调了 resolve_series；resolve_series 对"风云"会触发 ask-user 歧义问询）。真要治是独立小改（fuzzy 多候选→问询），列观察 |
| P2-8 | REF_RE（index.ts:879）不含 sentiment_ 前缀——保底③漏提交提取不覆盖舆情引用（审查者标"疑"） | 既有缺口面随第 7 工具扩大，但主路径（submit_conclusion 出口闸）不受影响；改保底提取面会改变回灌触发行为，需独立验证，不动 |

## 修复后终验

- 服务重启：8002 + 9200（PRISM_AUTO_APPROVE_UI=1）✅
- smoke:verify 129（128/0/1skip）✅；smoke:trap 31/0 ✅；tsc 11=基线零新增 ✅
- E2E 复跑两问：内容判定全过（停更/冻结/配置/无误报）；Q2 agent 自发走 resolve_series→全舆情工具链；出口闸双 pass=True（轨迹实证 15:56:24/15:56:48 + 兜底函数重放双 True）
