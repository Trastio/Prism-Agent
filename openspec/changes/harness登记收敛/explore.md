# explore · harness 登记收敛（启动自检 + 真值信封 + 保底喂源 + 回灌契约 + 技能目录 + 提示词受众分层）

- 日期：2026-10-13（Step1）
- 起因：carkit 融合 + 五轮真实复跑压测出"登记税/输出无契约"两类结构性问题（调研结论经用户拍板做成大 change，六项一起）

## 用户拍板记录

1. 大 change、严格十步、六项一起做（含 AGENTS.md 纪律1 半句澄清——设计层修改已获批）。
2. 纯差异问法不出现金额（skill v2 已做，本 change 不重复）。
3. 名称校验分层（R1-deep）**不在本 change**（愿望单维持）。

## 代码实况（本 explore 全部实测核验，行号为 2026-10-13 时点）

1. **extension 入口**：`export default function(pi)`（index.ts:1004）；注册序 registerAutohomeTools(:1008)→…→registerSkillTool(:1013)→registerExportTool(:1014)；before_agent_start(:1018)；第一个 tool_result 采集 handler(:1185)；第二个截断 handler(:1249)；agent_settled(:1319)。
2. **makeAutohomeTool.execute**(:305)：通用透传，qs 拼接→fetch→原样返回 JSON。今日已加 sel 字符串容错。
3. **数字台账采集**(:1189-1197)：全部 business 工具走 `extractLedgerValues`（numeric-ledger.ts:83）——**generic walk 只收 `typeof === 'number'`**，字符串数字（cells "410"/"15.4英寸"）不收（:96 注释明示"字符串值不抽"）。
4. **名称真值**(:1217-1237)：isNameSource = query_* | resolve_series | sentiment_*；collectNameTruth（grounding.ts:86）读 NAME_FIELDS 固定清单——rows[].name（概念名）不在内。
5. **第二弹形态分支**（今日加，:~1214）：compare_configs_valued/get_config_detail/get_trims 的 cells/price/概念名采集——**本 change 用 _truth 信封替代后退役**。
6. **保底③判据**(:1398-1410)：`tier==='library' && !isRetryTurn` → 读最新 `prism-session-series-key` entry；无且本轮未调 resolve_series → backfill。**该 entry 只在 before_agent_start(:1073) 由 ctx 的 seriesKey（前端选择）写入**——纯对话（不选车系）时恒空 → 追问轮误触发（用户会话实证 2 次）。
7. **backfill()**(:1358-1371)：`appendCustomMessageEntry('prism-verifier-retry', '[完成验证器·保底] '+guidance)` ——自定义消息在 branch 中呈 user 角色 → 前端历史渲染为用户气泡（用户实证看到）。
8. **load_skill 目录**（registerSkillTool :915-941）：description **硬编码技能清单**（今日手工补 config-compare）——漂移根源。skills.ts 已有 SKILLS_ROOT/listSkillFiles/readSkillFile，**无目录扫描函数**（需新增 listSkills）。
9. **ChatView**：isRetry 机制在（:296-329 渲染重试横幅 :451-460）；历史转换（D3 :74 "尽力转换"）**无 VERIFIER_PREFIX 过滤**——保底通知直出用户气泡；0 字 assistant 消息也会进列表（用户实证空气泡）。
10. **SYSTEM.md**（29 行）：第 9 条只禁 ctx 参数复述；AGENTS.md 纪律 1"每个数字带可复算 SQL"为报告时代措辞。
11. **前置已就位**（今日已修，本 change 依赖）：sel 容错、反代 multi_items、M2 魔毯口径、skill v2、config-compare 手工入目录。

## 待核（design 定稿）

- T1 pi.registerTool 包装点：extension init 内 wrap（记录 registeredTools 集合），自检在 before_agent_start 每轮跑（集合运算廉价）+ 日志去重（只首报）
- T2 _truth 信封出模型上下文的方式：采集 handler 收割后**从返回 content 中剥离 _truth**（模型不见、上下文零增）——顺序保证：采集 handler 先于截断 handler
- T3 social_* 的 _meta.keyword 机制保留不动（语义不同：查询词锚点），design 里声明边界
- T4 回灌通知的过滤契约落点：ChatView 历史转换 + 实时流两处按 VERIFIER_PREFIX（'[完成验证器·保底]'）过滤；main.py /session/messages 为纯透传不动
- T5 AGENTS.md 属设计层"运行时不可改（非设计冻结）"——本次为设计期修改，用户已拍板

## 范围

**做**：①启动自检 fail-loud（registerTool 包装记录 + 三表互检 + 技能目录解析校验）②真值信封 _truth（makeAutohomeTool 收割→采集器读→剥离，退役第二弹分支）③保底③喂源（resolve_series 成功写 session ledger）④回灌契约（ChatView 过滤 VERIFIER_PREFIX/空气泡 + 保底 guidance 追加"重述最小化"话术 + skill 同步）⑤load_skill 目录扫描生成（skills.ts listSkills + 描述动态拼装）⑥SYSTEM.md 输出受众分层（第 9 条扩围+新总则）+ AGENTS.md 纪律 1 澄清半句。
**不做**：名称校验分层（R1-deep，愿望单）；pi 官方 skills 机制迁移（自建 load_skill 保留）；social_ 改造；前端视觉重设计。

## 里程碑

M1 extension（①②③④话术⑤）fork 子代理 → M2 前端 ChatView 过滤（④界面侧）同子代理 → M3 提示词（⑥）主会话 → 验证（E2E 五问复跑 + 门禁 + smoke）主会话 → Step7 隔离审查子代理。
