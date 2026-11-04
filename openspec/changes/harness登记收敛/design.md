# design · harness 登记收敛

- 日期：2026-10-13 · Step2 design（决策 D1-D5 见 proposal）

## 架构总览

```
【工具接口层】pi.registerTool 包装 → registeredTools 集合
              makeAutohomeTool.execute → 响应附 _truth{numbers,names}（generic 收割）
【验证层】    采集 handler：读 _truth → 双账本（prism-numeric-truth/prism-name-truth）→ 剥离 _truth
              （第二弹形态分支退役；social _meta.keyword 分支保留）
              保底③：sessionSeriesKey 判据不变，喂源新增 resolve_series 成功写账
              回灌：guidance 追加重述最小化话术
【编排层】    （multi_items 已修，本 change 无）
【上下文层】  load_skill 描述 = base + listSkills() 动态目录（skills.ts 新增扫描）
【提示词层】  SYSTEM.md 输出受众分层总则 + 第9条扩围；AGENTS.md 纪律1 澄清半句
【前端】      ChatView 按 VERIFIER_PREFIX 过滤通知/空气泡（纵深防御）
```

## D1 启动自检 fail-loud

- extension init（export default function(pi) 首行，先于一切 register 调用）：
  ```ts
  const registeredTools = new Set<string>();
  const __origRegister = pi.registerTool.bind(pi);
  (pi as any).registerTool = (t: any) => { registeredTools.add(t?.name || String(t)); return __origRegister(t); };
  ```
- before_agent_start 每轮执行三查（集合运算，首轮之外用 `selfCheckReported` 标志去重只首报）：
  1. `TRUNCATABLE_TOOLS ⊄ registeredTools` → 告警列出缺失
  2. `KNOWN_BUSINESS_TOOLS ⊄ registeredTools` → 告警（submit_conclusion/resolve_series 均 register，应全覆盖）
  3. 技能目录：listSkills() 解析失败/为空 → 告警
- 输出 `console.error('[prism-guardrails][自检] 登记漂移: ...')`——gateway 日志可见；**不阻断服务**（D5 fail-loud 非 fail-closed）

## D2 真值信封 _truth

- **收割**：makeAutohomeTool.execute 在 `res.json()` 后附 `data._truth = harvestTruth(data)` 再返回。harvestTruth = generic 遍历：`rows[].name`→names；`rows[].cells` 字符串取前导数值（/-?\d+(?:\.\d+)?/）；`rows[].price|amount|unit_price`→numbers；`cols[].series_name|trim_name`→names、`cols[].msrp|price`→numbers；`trims[].name`→names、`trims[].price`→numbers（get_trims 形态）。去重 Set。
- **入账+剥离**（第一个采集 handler 顶部，business 分支之前）：
  ```ts
  若 payload 含 _truth：numbers→appendEntry('prism-numeric-truth',{values,kind:'truth',source:toolName})；
  names→appendEntry('prism-name-truth',{names,source:toolName})；
  然后 return { content: [剥离 _truth 后的 JSON text] }  // 模型上下文零增量
  ```
- **退役**：第二弹形态分支整段删除（其能力被 _truth 覆盖）；social _meta.keyword 分支保留（D4）；G1 isNameSource 分支保留（query_/resolve/sentiment 形态不同）。
- 顺序契约：_truth 剥离在采集 handler（先），截断在第二 handler（后）——"先入账再剥离再截断"，在两 handler 注释处补这句。

## D3 保底③喂源修正

resolve_series execute 成功路径（res.ok 且非 fail-closed）追加：
```ts
try { pi.appendEntry('prism-session-series-key', { series_key: String(params.series_key || '') }); } catch {}
```
- 判据本身不动（读最新非空 entry 的语义已正确）；喂源从"仅前端 ctx"扩为"前端 ctx + agent 实际核验"。
- 多对象对比题写多条——判据只答"会话核验过没有"，核验对象与结论的对应由 supported_by 管控（设计边界，写进 spec）。

## D4 回灌契约

- **前端过滤**（ChatView）：历史转换与实时渲染两处——user 角色文本 startsWith `'[完成验证器·保底]'` → 不入消息列表（或渲染为灰色系统细条，实现取简者）；assistant 空文本（trim 后 0 字）不入列表。前缀常量与 extension VERIFIER_PREFIX 对账：单测断言两边字面量一致（防 M2 前缀断裂教训重演）。
- **重述最小化**：backfill() 的 guidance 三处（保底①/②/③）统一追加："修正后仅需重新提交 CLAIM 并以一句话确认（如'已复核，结论维持'），不要重述全文结论。"；SKILL.md 纪律同步一条。
- 效果断言：真实回灌轮的 assistant 新增文本 ≤ 60 字（E2E 检查项）。

## D5 load_skill 目录扫描生成

- skills.ts 新增：
  ```ts
  export function listSkills(): { name: string; summary: string }[]  // 扫 SKILLS_ROOT/*/SKILL.md，正则抽 frontmatter name/summary
  ```
- registerSkillTool：description = `'加载技能工作流全文。可用技能：' + listSkills().map(s => \`${s.name}——${s.summary.slice(0, 60)}\`).join('；') + '。用户请求命中任一技能场景时，先 load_skill(name) 加载全文再动手。file 参数省略读 SKILL.md。read 工具不可用，技能一律经本工具加载。'`
- 注册时生成（进程启动一次）；新技能放目录+重启即入目录——配合 D1 第 3 查（解析失败告警）。

## D6 提示词受众分层

- **SYSTEM.md**：第 9 条扩围改写为"输出受众分层"总则（保留原 ctx 参数禁复述语义）：
  > 9. **输出受众分层（正文给人看，溯源给系统）**：回复正文禁止出现工具名/表名/字段名/引用格式原文（如 get_trims、sales_trim、tp、msrp、is_main、retail、config_diff:、supported_by 等内部标识），一律转译为职业语言（"销量明细表""指导价""终端价""库端主销标记"；"该字段暂未采集""最新月销量尚未结算"）。转译不是隐瞒——缺口照实说，说的姿势是人话。可复算溯源由 submit_conclusion 的 supported_by 结构化引用承担（前端可点击查看），不进正文。仅当用户主动追问数据来源/机制时才可提及内部名，且一句话带过、人话优先。
- **AGENTS.md** 纪律 1 句尾追加：`（对话产品场景：可复算性由 supported_by 结构化引用承担，正文面向用户用职业语言，不展示 SQL/行 ID/内部字段名——落地见 SYSTEM.md 输出受众分层）`
- SKILL.md config-compare 纪律补一条：正文人话（指向 SYSTEM.md 总则），提交参数格式与正文话术分开。

## 里程碑

- M1（fork 子代理 A）：extension 五处（D1/D2/D3/D4 话术/D5）+ skills.ts + 单测（自检集合运算/harvestTruth/_row_sig 邻接回归）
- M2（子代理 A 顺带）：ChatView 过滤 + 前缀对账单测
- M3（主会话）：SYSTEM.md/AGENTS.md/SKILL.md 文本
- 验证（主会话+fork）：五问复跑对照 + 门禁 + smoke + 自检误报演练
- Step7 隔离审查子代理（代码内嵌法）

## 环境坑（沿用）

重启统一 prism.py（PRISM_AUTO_APPROVE_UI=1）；extension 改动需重启 9200；tsc 基线 TS5097+datasource.ts TS2322；含反斜杠编辑走 Edit；门禁期间冻结服务操作。
