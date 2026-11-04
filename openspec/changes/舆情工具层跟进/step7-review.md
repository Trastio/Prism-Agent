# Step7 隔离审查报告 · 舆情工具层跟进（2026-10-20）

审查者：独立子代理（fork 型，工具面 Read/Grep/Glob/Bash/Write + ToolSearch 加载器）。
方法：第 0 步工具自报通过（有 Read/Grep/Bash，未触发 NO-TOOLS）；全部审查文件磁盘直读；对可活体复现的维度做了端点实测与测试实跑（服务 8002/8000 在线）；不预设设计结论，只做实证复现。

实测环境快照：prism-api 8002 /health 200，舆情 8000 fleet-overview 200；/sentiment/vehicles-all 实测 26 台车（14 paused / 8 active / 4 inactive）；三个测试文件实跑 19 pass / 0 fail / 0 skip。

---

## 发现清单

### P0（必须修/阻断）

无。

### P1（应修）

**P1-1 空串 vehicle_name 静默解析到错车（数据张冠李戴，红线#1 风险）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\.pi\extensions\prism-guardrails\index.ts:346-349`（第一级 fuzzy）与 `:365-366`（第二级 fuzzy）
- 复现证据（node --import tsx 活体实测）：
  ```
  resolveVehicleId('')  →  {"id":"143aa265-…","status":"active"}   # = Model Y（fleet-overview 第 1 台）
  ```
- 推理链：`fleet.find(v => v.name && v.name.includes(vehicleName))` 在 `vehicleName=''` 时 `includes('')` 恒为 true → 命中 fleet 第一台（实测 Model Y）。schema `required: ['vehicle_name']` 只校验键存在，空串是合法 string（pi typebox 放行）；用户提问不带车名而模型硬调舆情工具时即触发。后果：把 Model Y 的舆情数据（含数字）当作用户对象的数据交付——静默错数据，比 fail-closed 更糟。第二级 `norm(v.name).includes(nm)` 同样 `includes('')` 恒真（当前被第一级先行命中掩盖）。
- 修法（一行）：`resolveVehicleId` 入口加空串守卫 `if (!vehicleName || !vehicleName.trim()) return null;`（与 resolve_series 的 P2-2 空身份键不入账同精神）。
- 对照：`undefined` 入参实测返回 null（`vehicleName.replace` 抛 TypeError 被第二级 try/catch 兜住落 unavailable 文案），无崩溃、语义可接受——仅空串是漏洞。

**P1-2 e2e_check.py trajectories 兜底三缺陷，直接污染 Step9 验收判定（假绿/假红）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\openspec\changes\舆情工具层跟进\e2e_check.py:33-44`（traj_pass）与 `:102-107`（末 N 行判定）
- 三条缺陷，前两条有活体实证：
  1. **末 N 行无 sessionId/user 过滤**：`.pi/sessions/trajectories.jsonl` 是全部会话共享追加的全局文件（index.ts:1006 appendFileSync），验收期间任何并发对话的行都会挤进末 2 行 → 把别人的 pass/fail 配对成本验收两问（误配对，任务书 G 维度点名方向）。行内本有 `sessionId` 字段（index.ts:992）可过滤，脚本未用。
  2. **"两问各对应末一行"假设在回灌场景错位**：实测本机 trajectories 末 5 行全部同属一个 sessionId，且 `submission.count` 从 2→4→5→7 递增——同一问的多次被拒-重提每轮 agent_settled 各落一行。回灌一旦发生，末 2 行很可能全是最后一问的行，上一问的判定根本没被读到。
  3. **无 submission 字段的行恒判 False（假红）**：appendTrajectory 只在 `submitCount > 0` 时写 `submission` 字段（index.ts:998），默认放行轮（verdict=pass 但未走出口闸）`submission` 缺失 → `(r.get('submission') or {}).get('pass')` → None → bool(None)=False。该问 settled verdict=pass、trajectories 兜底 False，两路判定自相矛盾，e2e 总判 FAIL。
- 修法建议：traj_pass 改为按行内 `sessionId`（或 conversation[0] 题面，tool_matrix.py map_task 同语义）过滤本验收会话的行、每问取该问最后一行；submission 缺失时回退读行内 `verdict` 字段而非恒 False。
- 边界说明：网关侧 settled verdict 读取已按 realSessionId 隔离（pi_gateway.mjs:473-475 + map_event.mjs:33-43，"原 fallback 全局 last-verdict.json 会跨会话串读"已修）——本缺陷仅存在于 e2e 脚本的 trajectories 兜底路径，不影响生产链路。

### P2（建议）

**P2-1 eval/tool_matrix.py TOOL_UNIVERSE 漏登记 sentiment_defects（任务书 C 维度"第五处漏登记"实锤之一）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\eval\tool_matrix.py:28-37`
- 证据：`'business': [...]` 枚举 22 个工具，sentiment 6 个（overview/trend/dimension/posts/competitive/events），无 sentiment_defects。文件头 `:16` 明文"改动 extension 后同步此表"——本 change 改了 extension 未同步。
- 影响评估：该脚本有"⚠ 未知工具"自报兜底（:136-138），sentiment_defects 的调用会落自报节而非静默丢弃；但"覆盖工具 x/全集"分母少 1、零覆盖清单缺列 sentiment_defects。统计失真不阻断，定 P2。

**P2-2 eval/trap_check.mjs 工具描述静态副本缺 sentiment_defects 段（第六处枚举残留）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\eval\trap_check.mjs:57-64`
- 证据：trap-01（提示词/描述泄漏检测）的期望文本是 submit_conclusion 描述的静态副本，止于 `sentiment_events:事件ID`，无 `sentiment_defects:风云T7`（index.ts:659 新描述已含）。
- 影响：模型若泄漏新增的 sentiment_defects 片段（约一行），30 字滑窗匹配不到旧副本 → 该段泄漏不判分。旧片段仍被覆盖，影响面小。注：trap_check.mjs 在最近提交 195326c 刚做过判分扩词，此为同文件遗漏。

**P2-3 fuzzy 兜底在多候选车系族静默选车且顺序依赖（库演化后冲突已真实存在）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\.pi\extensions\prism-guardrails\index.ts:348-349`（一级）、`:365-366`（二级）
- 活体实证（/sentiment/vehicles-all 26 台 + node 实测）：
  - "风云"族 6 台（T7/T9/T9L/T11/A9/A9L 全 active）→ 传"风云"命中 fleet 顺序第 3 位**风云T9**（非用户大概率所指的风云T7）；
  - "银河"族 4 台（E5/A7/M9/TT 全 paused）→ 命中银河E5（恰好合理，但由顺序决定）；
  - "元"族 2 台（元UP/元PLUS 均 inactive）→ 命中元UP（inactive 停用文案路径正确）；
  - 对照 "T7" 全库唯一命中风云T7，无歧义。
- 推理链：`find(...includes...)` 取第一个命中，顺序 = 舆情端点返回序（vehicles-all 的 SQL 无 ORDER BY，依赖 sqlite 行序）；库新增车会改变命中对象。与 resolve_series 的 ambiguous/candidates 歧义语义不对齐。出口闸舆情源登记 design.md R-b 曾记录"现库 23 车无此冲突"——现库 26 台且风云族 6 台，该论断已过时。属既有设计限制被库演化放大 + 本 change 的 fallback 叠了一层同语义；不改闸门的前提下建议至少固定 ORDER BY（如按 name 或活跃度排序）+ 在结果不可唯一时优先精确/返回歧义提示。

**P2-4 fallback 失败与"真未收录"语义合并（服务故障误报为数据缺口）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\.pi\extensions\prism-guardrails\index.ts:369`（二级 catch return null）与 `:403`（统一 unavailable 文案"不在舆情系统收录范围"）
- 推理链：第二级 fetch 失败（网络异常 / 401（token 未注入）/ 5xx）一律 return null → 工具报"车系 X 不在舆情系统收录范围"。服务宕机、token 配置缺失与真未收录不可区分，违反红线#1"缺失数据如实声明"的粒度（宕机≠未收录）。本 change 的核心目标恰是消除"paused 车误报未收录"，同类语义合并问题在故障路径上仍然存在。实测佐证：/sentiment/vehicles-all 不带 token 返回 401——若网关未注入 PRISM_SERVICE_TOKEN，全部 paused 车会退回"未收录"误报而无人察觉。
- 修法建议：二级失败（非 404）与"名单可查但不含该车"分支分开，前者报"舆情名单服务不可用"。

**P2-5 /sentiment/vehicles-all 表级 sqlite 异常未语义化**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\prism-api\main.py:615-621`
- 推理链：`sqlite3.connect` 失败已捕 → 503；但 `conn.execute('SELECT id, name, status, brand FROM vehicles')` 抛错（表缺失/库损坏）未被 except 捕获 → FastAPI 裸 500。对照同文件 /verify/claim 对 sqlite3.Error 有 `except (ValueError, sqlite3.Error): ok=False`（:1142）的防护。下游表现为 extension 侧 `res.ok=false` → null → 又落 P2-4 的"未收录"文案。
- 注（疑，未做破坏性实测）：表缺失场景按 sqlite 行为推断为 OperationalError→500，未实际删除生产表验证。

**P2-6 tests/sentiment_tools.test.ts 注释失真 + 降级分支逻辑缺陷（F 维度）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\tests\sentiment_tools.test.ts:8`、`:13`、`:26-37`、`:40-47`
- 三点：
  1. `:8` 注释称 paused 车经"fallback **/api/vehicles** 命中"——实际实现走 Prism 侧 `/sentiment/vehicles-all`（index.ts:353-356 明确注释"fallback 不走舆情 /api/vehicles（同样只返回 active）"）。注释陈旧且与实现相反，误导后来者。
  2. 降级分支（token 文件读取失败时设 `PRISM_SENTIMENT_BASE=http://127.0.0.1:8000`）只覆盖第一级解析：第二级 fetch 仍打 `${FASTAPI}/sentiment/vehicles-all`（8002）且无 token → 401 → null → case 2（银河E5 paused）在该降级模式下必失败而非 skip。
  3. skip 门 `serviceUp()` 只探 8002：降级模式宣称直连 8000 可跑一级，但 8002 down 时整体 skip，降级路径形同虚设。
- 实测现状：本机 token 文件存在 + 双服务在线 → 4 case 全绿（无实害）；上述为条件触发缺陷。另确认：node --test 每文件独立子进程，index.ts 模块级 monkey-patch fetch 无跨测试文件副作用（同文件内 serviceUp/login 请求带多余 X-Prism-Service 头，无害）。

**P2-7 index.ts 头部/分区注释计数漂移（与 :47 自相矛盾）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\.pi\extensions\prism-guardrails\index.ts:4`（"注册 21 个业务工具"，实为 23）、`:5`（"sentiment_* 6"，实为 7）、`:328`（"舆情 Board 工具（6 组…"，实为 7 个）、`:1220`（"3 口径视图 + 6 舆情 + 14 Atuohome…= 25 个"，实为 3+7+11+2=23，Atuohome 现为 11 个）
- 证据：同文件 `:47` 注释"3 query + 7 sentiment + 11 dashboards + resolve_series + submit_conclusion"与 KNOWN_BUSINESS_TOOLS 实际 23 个一致（tool_call.test.ts:130 断言 23 过）——同文件两套注释互相矛盾。未来按头部注释核对工具面会误判。

**P2-8 REF_RE 不含 sentiment_ 前缀，舆情引用在保底路径不提取（既有缺口，面扩大）**
- 位置：`C:\Users\<you>\Desktop\Prism-Agent\.pi\extensions\prism-guardrails\index.ts:879`
- 推理链：`extractClaim` 的行 ID 正则 `((?:review_tags|sales_trim|config_snapshots|mv_\w+):…)` 不认任何 sentiment_* 引用 → 保底路径（漏提交回灌/agent_settled 兜底）下 evidence_ids 恒空。主路径不受影响（submit_conclusion 走 params.supported_by，经 /verify/claim 校验 sentiment_defects 实测通过）。非本 change 引入（sentiment_overview 等同样不在），但第 7 个舆情引用格式加入后该缺口覆盖面继续扩大。标"疑"级风险：当前无已知 badcase 由它触发。

---

## 无问题确认清单（查过且确认没问题）

1. **A 维度 · resolveVehicleId 返回形态变化的调用方**：全仓 grep 唯一代码调用方 index.ts:400（makeSentimentTool execute，按新形态 `resolved.id`/`resolved.status` 使用，正确）；其余命中全部为文档/归档快照（openspec 各 change 的 proposal/explore/.bak、会话备份.md），非活代码。tests/sentiment_tools.test.ts 按新形态断言。**无漏改调用方**。
2. **B 维度 · _prism_frozen_note 下游污染（四个消费方逐一核实）**：
   - harvestTruth（truth-envelope.ts:15-59）：全仓唯一调用点是 makeAutohomeTool（index.ts:515）——sentiment 工具响应根本不经过它；且收割只认 rows/cols/trims/diff 结构，注入字段不在任何收割路径。
   - collectNameTruth（grounding.ts:86-100）：按 NAME_FIELDS 11 个**精确键名**匹配（series/brand/model_name/tag_category/manufacturer/series_name/车型名称/canonical_name/dim/event_tag/platform），`_prism_frozen_note` 不在列，句子值不会被收为名称真值。
   - extractLedgerValues（numeric-ledger.ts:83-99）：字符串值一律不抽（:96 明确注释），note 句子（"该车舆情已停更（paused）…"，无数字）不入数字台账；note 文案当前不含数字，无 kind='truth' 误入账风险（注：若未来改写 note 加数字，因字符串值不抽仍不会入账）。
   - truncateToolResult（truncate.ts:89-120）：只删数组元素、不删对象键 → `_prism_frozen_note` 键保留；对象响应顶层 spread 的 `_truncated` 与其并存无冲突；注入仅在对象响应（index.ts:427-429，数组响应 top-posts 跳过，帖自带日期数据自明）。
3. **C 维度 · 主链登记完整性（extension + main.py）**：KNOWN_BUSINESS_TOOLS（index.ts:53）、TRUNCATABLE_TOOLS（:178）、registerSentimentTools 第 7 个注册（:470-473）、submit_conclusion 描述（:659）、拒绝提示（:765）、main.py `_SENTIMENT_TABLES`（:1063）六处全部到位；TOOL_CATEGORIES.business 由 KNOWN_BUSINESS_TOOLS 派生、truthEmitters 运行时收集、collectRegistrationDrift 三表互检均为派生检查无需登记。SYSTEM.md / PRISM_GENERAL.md / prism-web 前端无 sentiment 工具枚举残留。漏登记仅在 eval 侧两处（P2-1/P2-2）。
4. **D 维度 · /sentiment/vehicles-all 与 auth/路由交互**：实测带 X-Prism-Service 令牌 200、不带 401（auth_gate :185 生效）；extension 的 globalThis.fetch 补丁（index.ts:39-45）对 `${FASTAPI}` 前缀 URL 注入头，而 SENTIMENT_BASE 缺省值 `${FASTAPI}/sentiment-board` 同前缀 → 两级解析请求都带令牌。路由无吞没：`/sentiment/vehicles-all`（:612）与 `/sentiment-board/{path:path}`（:628）路径前缀不同，FastAPI 注册顺序无碍（实测 200 即证）。SSRF/路径白名单：该端点无路径参数、不经过 sentiment_proxy 的 path 白名单，无攻击面。sqlite connect 失败 → 503 语义化；空库（表在行空）→ `[]` → extension 侧 find 不中 → null，行为正确。
5. **E 维度 · 两级解析边界（活体实测）**：undefined → null（第二级 `vehicleName.replace` TypeError 被 try/catch 捕获，无崩溃，落 unavailable 文案）；"T7" 全库唯一命中风云T7（T11/T9/A9 均不含 T7 子串）；"银河E5" paused 二级命中 + 冻结链路正确；"元UP" inactive → "已停用"文案路径正确；active 快路径（风云T7 精确、Model Y 大小写变体）实测正常；第一级 fleet-overview 只回 active 8 台（无 status 字段），extension 侧硬编码 'active' 与数据事实一致。名单 26 台跨两次拉取稳定，无并发写入干扰。
6. **F 维度 · 测试质量与实跑**：三测试文件（sentiment_tools / verify_claim_api / tool_call）实跑 19 pass / 0 fail / 0 skip；verify_claim case 6（defects 真车过/假车拒）与 case 7（paused 车银河E5 引用过——出口闸查全量 vehicles 不筛 status，与两级解析对齐）覆盖到位且绿；skip 语义（服务不可达 → it 级 skip，与 identity_api.test.ts 同模式）合理；defect-themes 真调不进自动门禁（防 LLM 自愈烧钱）的取舍有注释说明，合理。
7. **G 维度 · 网关侧 verdict 无串读**：settled 事件本身无 sessionId（map_event.mjs:34-35 注释引 pi docs），但网关读 verdict.json 已按 realSessionId 分目录（pi_gateway.mjs:473-475 刷新 + map_event.mjs:36-40 定位），跨会话串读问题在生产链路已治；本维度缺陷仅剩 e2e 脚本兜底路径（见 P1-2）。
8. **出口闸新表行为**：`sentiment_defects:风云T7`（真车）实测通过、`sentiment_defects:不存在的车系XYZW` 实测拒绝（测试 case 6 绿）；_check_sentiment_ref default 分支 `_sent_vehicle_exists`（main.py:1104）与工具层两级解析语义对齐（精确去空格 → 包含）。

---

## 计数摘要

- **P0：0 条**
- **P1：2 条**（空串解析到错车；e2e trajectories 兜底三缺陷）
- **P2：8 条**（tool_matrix 漏登记；trap_check 副本缺段；fuzzy 多候选顺序依赖；fallback 失败语义合并；端点表级异常 500；测试注释失真+降级缺陷；index.ts 注释计数漂移；REF_RE 不含舆情前缀）
