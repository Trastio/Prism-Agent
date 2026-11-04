# 评估迭代基建包 · Step3.5 self-check（2026-10-14，同法再审：闭环逐环节+历史留下一轮交叉）

## 设计内已防的 Gap

- [x] **G1 web 禁用误伤社媒题**：PRISM_EVAL_WEB 只剔 pi-web-access 4 工具，social_* 独立类别不波及（design B5）
- [x] **G2 金标比对假阳**（表述不同/累计 vs 月值）：anchors 只放题级主结论数字、口径数字不入、换算规则外置首跑后校准（B3）
- [x] **G3 轨迹分离后 runner 读不到 verdict**：三点同源 env+端到端一致性验收（A5/A7）
- [x] **G5 trap_params 兼容**：缺参 fail-closed false，与既有 default 语义一致（B1）
- [x] **G7 stats 配对无基线**：dry-run 验收 + 报告归档 eval/reports/ 后自然形成基线链（D1/B11）
- [x] **并行施工撞文件**：派单按文件域划分（A=extension轨迹行+ops；B1=runner/tasks/trap_check；B2=rubric/extension setActiveTools+sentiment 时间——**注意 B2 与 A 都动 extension index.ts**：A 动 :781 一行，B2 动 setActiveTools/trend 时间函数，非同函数；**约定 B2 等 A 合并后再开工或串行同一文件**）；CD=stats/ci/脚本
- [x] 消融不做/保留集=frozen/判分外置——explore §3 已记

## 施工时验证点（探索性，不阻塞设计）

- [ ] **G4 langfuse 实例标签**：插件配置源 env 覆盖能力未证——施工验证，兜底 writer metadata（A4）
- [ ] **G6 多轮逐轮 verdict**：trajectories 是否每轮记——若只终轮，逐轮 truth+trap 正则兜底（B2-7）
- [ ] **G8 prism.py eval env 透传链**：只证过 PRISM_FASTAPI 一例，A5 第一步核（若 spawn env 白名单制需改 prism.py）
- [ ] pi 事件是否含 token usage（B2-5）
- [ ] langfuse v4 legacy score 端点在批量下的限流（A3 联调观察）

## 完整性终审（第二次补扫后）

25 项（12+8+5 原生）全覆盖：A6/B13/D8（M 系）已入 blocks；有意排除 4 件（LLM-as-Judge/恢复评测/annotation 存储/轨迹前缀）理由在 proposal。**对照方案 §10.0.1：L1-0 三件∈B1/B(A5)；L1-3 九项∈B；L1-4∈C；L1-6∈D——轮 1 工程全数入包**，无再借"轮 1 中段"名义游离的工程项。L1-5 补题（出题非工程）与本 change 解耦正确。
