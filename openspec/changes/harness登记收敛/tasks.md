# tasks · harness 登记收敛

## M1 extension + 技能目录（fork 子代理 A）
- [x] T1.1 registerTool 包装记录 registeredTools + before_agent_start 三查自检（fail-loud 去重只首报）。
  施工注：包装在 export default 首行（先于一切注册，bind 保绑定不吞异常）；三查逻辑抽纯函数 collectRegistrationDrift（src/shared/truth-envelope.ts）便于单测；listSkills 异常单独告警。
- [x] T1.2 makeAutohomeTool.execute 收割 _truth（harvestTruth 泛化遍历）并附到响应。
  施工注：harvestTruth 落 src/shared/truth-envelope.ts（纯函数零依赖，覆盖 rows/cells/cols/trims 三形态）。
- [x] T1.3 采集 handler 顶部读 _truth 入双账本并**剥离**（模型零增量）；第二弹形态分支整段退役。
  施工注：剥离在最外层（解析出 _truth 即剥，入账分开判——Gap2）；剥离后文本仍跑 generic walk（number 型兜底不丢覆盖）；第二弹分支留墓碑注释；两 handler 顺序契约注释已补（先入账→再剥离→再截断）。
- [x] T1.4 resolve_series 成功路径写 prism-session-series-key。
  施工注：成功判据=data.series_id 且非 ambiguous（歧义/虚构不记账——台账语义是"核验过真对象"）。
- [x] T1.5 backfill guidance 三处追加重述最小化话术。
  施工注：backfill() 单点拼装 msg，一处编辑覆盖保底①②③；前缀改用 VERIFIER_NOTICE_PREFIX 单源常量。
- [x] T1.6 skills.ts listSkills() + registerSkillTool 描述动态生成。
  施工注：frontmatter 正则抽 name/summary，单目录解析失败跳过、根不存在返回空（自检第 3 查接住）。施工事故：JSDoc 注释里写 `SKILLS_ROOT/*/SKILL.md` 的 `*/` 提前终结块注释致 4 测试文件编译挂——已改写措辞并全绿（教训：目录通配符不进块注释）。
- [x] T1.7 单测：自检集合运算/harvestTruth/前缀对账（ChatView 常量 vs VERIFIER_PREFIX 字面量一致）进 smoke。
  施工注：tests/truth_envelope.test.ts 7 case（compare/get_config_detail/get_trims 三形态+空响应+漂移检查+前缀对账含"不得引入带闭括号脆匹配"断言）；已挂 smoke:verify（package.json 文件列表追加）。

## M2 前端（fork 子代理 A 顺带）
- [x] T2.1 ChatView 历史转换+实时渲染：VERIFIER_PREFIX 用户气泡过滤、空气泡过滤。
  施工注：历史转换 user 分支按前缀 continue（前缀常量本地定义+文件对账单测）；assistant "text/thinking 双空不入列"；实时流 finally 处 prune 双空气泡（流式起头后无产出的空壳）。

## M3 提示词（主会话）
- [x] T3.1 SYSTEM.md 第 9 条改写为输出受众分层总则。
- [x] T3.2 AGENTS.md 纪律 1 澄清半句。
- [x] T3.3 SKILL.md（config-compare）正文人话纪律一条（第 7 条）。

## 验证（主会话 + fork）
- [ ] T4.1 自检误报演练：临时删白名单一项→网关日志告警→还原。
- [ ] T4.2 五问复跑对照（差异/差价/追问/纯闲聊）：submit 次数、正文无内部名、回灌轮文本≤60字、保底不误触发。
- [ ] T4.3 门禁 E1-E9 + smoke 全绿 + tsc 零新增。
- [ ] T4.4 动态技能目录演练：临时加测试技能目录→重启→load_skill 描述含它→清理。
