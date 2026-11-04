# Self-check · 社媒深挖能力包（Step 3.5）

逐层审查四件套：依赖完整性 / 验收可验性 / 与既有机制的边界冲突。**7 Gap 全修**（修正已回写对应文档）。

## Gap 1 · pi 原生 skill 发现与 load_skill 的冲突（中等风险）
**问题**：skill 放 `.pi/skills/` 后 pi 可能自动发现并把描述注入系统提示词、教 agent 用 `read` 加载——read 被排除，agent 白试一次（fail-closed 拒绝）。
**修正**：技能指针行明确写"read 工具不可用，技能一律经 load_skill 加载"（design §2.1 已补）。描述进提示词本身是加分项（触发面+1），read 失败有 load_skill 描述兜底。
**验证位**：T2.2 RPC 实测一轮，确认无 read 调用尝试或失败后自救成功。

## Gap 2 · 回灌轮的每轮计数清零（高风险，若漏则第 2 轮秒 block）
**问题**：完成验证器保底回灌（sendUserMessage）触发新一轮 agent run——若 before_agent_start 不触发，tikhub 计数跨轮累积。
**分析**：身份强制移除 change 的执行层判据在回灌轮也生效（证明 agent run 均触发 before_agent_start），理论安全。
**修正**：T1.4 验收加实测项——连续两轮（首轮+回灌轮）各调 social_search，第二轮第 1 次调用不被 block。（tasks 已补）

## Gap 3 · 验证层数值台账误收 social_* 数字（红线边界）
**问题**：若数值台账采集不分类，tikhub 的粉丝数/点赞数进"库真值"，mixed 轮可能被当库数字严格校验。
**核实**：extension L885 数值采集仅 `TOOL_CATEGORIES.business` 工具——social_* 归 web 类天然不进台账，逻辑自洽。
**修正**：T4.1 加显式验证项——真实 mixed 轮后数值台账不含 tikhub 来源数字。（specs/verification-eval T1 已补）

## Gap 4 · /export/download 的鉴权与浏览器直链（中风险）
**问题**：浏览器 `<a>` 下载不走 fetch 带不了自定义 header；main.py 鉴权中间件若全覆盖，直链 401。
**修正**：T3.1 施工时确认鉴权中间件覆盖范围——/export/download 若在覆盖内，走与 /dash 同款豁免或 query 参数豁免；以"浏览器点开能下载"为验收。（tasks T3.1 已补）

## Gap 5 · main.py 的 dotenv 加载未确认
**问题**：/tikhub/status 需读 prism-api/.env，main.py 是否已 load_dotenv 未核实。
**修正**：T3.2 施工时若无则加（python-dotenv 依赖确认；FastAPI venv 里舆情项目在用，prism-api 待查）。（tasks T3.2 已补）

## Gap 6 · 端点参数未全部核对（bilibili + weibo 细节）
**问题**：explore 只核对了 douyin/xhs 用户端点参数；bilibili fetch_general_search、weibo fetch_advanced_search 参数未逐一核对。
**修正**：T1.1 施工前重拉 openapi.json 核对五平台全部端点参数（openapi 缓存已过期即重下）；bilibili 参数异常则降级为四平台（工具 enum 动态，不硬编码五）。（tasks T1.1 已补）

## Gap 7 · 8 次/轮 vs skill 流程的调用量（模板 A 全网扫描会超限）
**问题**：模板 A 五平台扫描（search×5+comments×5=10 次）> 8 次上限。
**修正**：SKILL.md 成本纪律细则加"分轮推进"：单轮先 2-3 个平台，用户续问或下轮补齐；缺口如实声明。同时写明"社媒深挖流程优先于三维度 SOP 的顺序推进"（AGENTS.md 分层规则的社媒场景说明，不改 AGENTS.md 本身）。（specs/skill-layer T3 已补）

## 其余核对项（无 Gap）

- export 参数体积：单 sheet rows≤200 写进工具描述建议（agent 生成大 JSON 参数易错）——低风险已吸收
- undici keep-alive 竞态：tikhub 调用不在长流尾，Bun 内置 fetch，不适用
- 16+2 评估题回归基线：T4.4/T5.3 已含
- EVAL_STATUS.md 登记：T4.2 内含
- ACCEPT 一致性：proposal 验收 6 条 ↔ specs 验收 ↔ tasks M5 全对齐
- 依赖链：M1→M2/M3（并行）→M4→M5（key 依赖显式）；M0 用户项不阻塞 M1-M4

## 结论

spec 层无悬空依赖、验收可验、边界冲突已识别修正。**可进 Step5 施工**（M1 起步：T1.1 工厂+端点映射）。
