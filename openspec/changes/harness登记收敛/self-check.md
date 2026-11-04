# self-check · harness 登记收敛（Step 3.5）

1. **Gap-包装时序**：registerTool 包装必须在一切注册之前（export default 首行）——晚于 registerAutohomeTools 则 registeredTools 缺员、自检全误报。→ design D1 明确"先于一切 register 调用"。
2. **Gap-_truth 残留进上下文**：剥离靠采集 handler 返回 content patch——若 handler 早退路径（data.status unavailable 等）漏剥离，_truth 泄入模型。→ 剥离放分支最外层：只要解析出 _truth 就剥离，账本入不入分开判。
3. **Gap-退役分支回归**：删第二弹分支后，get_config_detail（同样走 makeAutohomeTool）的名称/数字采集是否全覆盖？→ 该工具响应形态与 compare 同源（rows/cells/cols），harvestTruth 覆盖 ✓；单测补 get_config_detail 形态用例。
4. **Gap-前缀漂移**：ChatView 过滤前缀若手抄字符串，extension 改文案即静默断裂（M2 前缀断裂教训）→ 前缀对账单测（T1.7）双侧字面量一致断言。
5. **Gap-自检误报刷屏**：三查每轮跑+每轮告警 → 日志淹没。→ 只首报标志 + 集合运算 O(n) 廉价。
6. **Gap-AGENTS.md 措辞**：纪律 1 追加半句不得削弱"可复算"要求本身——措辞为"承担方式澄清"（supported_by 即可复算的结构化形态），非豁免。→ proposal D1/M3 文本已按此写。
7. **Gap-E2E 判据污染**：保底③喂源修正后，"未核验"真阳性（用户上来就问数字且 agent 跳过 resolve）必须仍被拦——T4.2 含纯闲聊轮与数字轮对照；门禁 E 组（含 identity 用例）回归。
8. **Gap-truncate 与 _truth 顺序**：截断 handler 在采集后跑，_truth 已剥离不会被截断逻辑看到——顺序注释补强（design D2）。

**结论：无悬空依赖；可进 Step5。**
