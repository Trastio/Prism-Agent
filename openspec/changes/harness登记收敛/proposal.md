# proposal · harness 登记收敛

- 日期：2026-10-13 · Step2
- 起因：carkit 融合压测出的两类结构性问题——"登记不闭环（漏登=静默失败）"与"对用户输出无契约"。调研证据见 explore.md。

## WHY

本次融合中两个能力（compare_configs_valued 工具、config-compare 技能）**从未在 agent 侧真正生效过**，靠多轮真实复跑才挖出——根因不是代码错，是"新增能力要摸 8+ 处分散登记点、缺一处即静默失败"的装配工艺。同时回灌通知直出用户气泡+结论重述两遍、正文裸奔内部名（get_trims/sales_trim），暴露"对用户说什么"从无契约。不收敛则：下一个新工具/新技能/新数据源还会以同样方式翻车，且每次都是事后人工复跑才发现。

## WHAT

六项收敛（不加新机制，全是把踩过的坑变成结构约束）：
①启动自检 fail-loud；②真值信封 _truth（收割→入账→剥离，退役形态分支）；③保底③喂源修正；④回灌契约（前端过滤+重述最小化话术）；⑤load_skill 目录扫描生成；⑥SYSTEM.md 输出受众分层 + AGENTS.md 纪律 1 澄清半句。

## 决策记录（用户已拍板）

| # | 决策 |
|---|---|
| D1 | 大 change、严格十步、六项一起（含 AGENTS.md 设计层半句） |
| D2 | A 前端过滤降级为纵深防御，主修是判据/契约层 |
| D3 | 名称校验分层（R1-deep）不在本 change |
| D4 | social_* 的 _meta.keyword 机制保留（语义不同） |
| D5 | 自检 fail-loud（打日志）而非 fail-closed（不阻断服务） |

## 影响范围

- extension index.ts（registerTool 包装+自检、makeAutohomeTool _truth 收割、采集 handler 读 _truth/剥 _truth/退役第二弹分支、resolve_series 写 ledger、保底 guidance 话术、load_skill 描述动态化）、skills.ts（listSkills）
- prism-web ChatView.tsx（VERIFIER_PREFIX 过滤+空气泡过滤）
- SYSTEM.md（第 9 条扩围+新总则）、AGENTS.md（纪律 1 澄清半句）
- 单测：自检/信封收割纯函数用例进 smoke

## 风险

1. **registerTool 包装**改变 pi 对象方法——包装必须保绑定（bind）且不吞异常；自检误报会刷日志（去重：只首报）
2. **_truth 剥离顺序**依赖 handler 注册顺序（采集先于截断）——顺序契约已有结构性保证（线B 注释），破坏点加注释
3. **resolve_series 写 ledger**：多次 resolve 多对象（对比题）写多条——判据读"最新非空"，语义正确（最新核验对象）；判据只判"有没有核验过"不判"核验的是谁"（对象对不对由 claim 的 supported_by 管控）
4. **AGENTS.md 属全局"永不动"层**——设计期修改已获用户拍板，措辞最小（半句澄清）
5. ChatView 过滤用前缀匹配——保底文案前缀变更曾断裂 retry 识别（M2 教训），前缀常量必须单源（从 VERIFIER_PREFIX 同源导出/复制时加对账断言）

## 验收（Step9 复核）

1. 自检：人为从 KNOWN_BUSINESS_TOOLS 删一项 → 网关日志出现登记漂移告警（fail-loud 实证）；正常启动零告警
2. 信封：makeAutohomeTool 三工具响应含 _truth 且**到达模型上下文的 content 已剥离**（轨迹 grep _truth=0）；数字/名称真值入账（E2E 无"不在工具真值集"误拒）
3. 保底③：纯对话追问轮不再触发身份保底（对照会话实证）
4. 回灌契约：前端历史/实时流不出现"[完成验证器·保底]"用户气泡、无空气泡；重述最小化话术在 guidance/skill 生效
5. 技能目录：动态生成（新放一个测试 skill 目录 → load_skill 描述自动含它，重启后）
6. 提示词：SYSTEM.md 受众分层生效（同问复跑正文无 get_trims/sales_trim 等内部名）；AGENTS.md 半句落盘
7. 回归：门禁 E1-E9 + smoke 全绿；tsc 零新增

## 不做

名称校验分层 / pi 官方 skills 迁移 / social_ 改造 / 前端视觉 / 40 并发压测 / langfuse 接线（各自独立事项）。
