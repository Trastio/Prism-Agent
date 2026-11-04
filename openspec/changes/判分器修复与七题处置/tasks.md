# tasks · 判分器修复与七题处置（Step5 施工工单）

> 设计定稿=proposal.md 决策节（授权模式，拍板留痕）。两块串行：Block A（eval 判分器域）→ Block B（网关域）。
> 施工纪律：每修一处先加红绿测试；判分器改动不动既有 66 题判分结果（重放零回归兜底）。

## Block A · 判分器单源化+词表+锚+重放（eval/ 域）

- [x] A1 trap_check.mjs：导出 `checkOverreach(reply)` 纯函数 + `OVERREACH_RE` 常量（正则自 runner.mjs:340 迁入：`/销量.*印证|销量.*佐证|销量.*支撑.*舒适|市场.*归因.*产品力/`）；NEG_RE 追加 `不把[^。\n]{0,8}归因` 形态
- [x] A2 runner.mjs:340 越界分支改调 checkOverreach（行为对既有回复等价——除新免责形态外）；rescore.mjs:55 越界分支改调 checkOverreach 复核实判（不再纯信 reasons 字符串）
- [x] A3 tasks.json multi-10 t2 expect_gap 词表追加：`上一轮`、`没有上一轮`、`分析记录`、`会话记录`、`新对话`、`确认`（斜杠分隔追加，保留既有项）
- [x] A4 tasks.json sales-07：truth.anchors 删 `46.15%`（保留 `2,047`）；judge_rubric 末尾补"占比 46.15%（2047/4436）可由台数推出，不单列锚"；scoring-rules.json 删 `sales-07` pp 条目
- [x] A5 tasks.json sentiment-06：truth.anchors 删 `12.8%`（anchors 空数组保留结构，checked 转 false 合法）
- [x] A6 scoring-rules.json calibration_log 追加两条（2026-10-27；sales-07 摘派生比例锚 / sentiment-06 摘 TTL 窗漂移锚；六字段齐全，evidence 引 explore.md）
- [x] A7 红绿测试：trap_check.test.mjs +checkOverreach 4 例（免责"不把…归因/不归因/不将…归因"不判越界 + 真越界"销量印证了产品力"判）；truth_check.test.mjs +multi-10 新词表命中例 + 摘锚题 checked:false 例；runner/rescore 单源同分例（同 reply 两路判定一致）
- [x] A8 新 eval/replay_check.mjs：输入报告 json（可多份），对每 result 用当前判分器重放（verdict/trap 状态取报告字段，truth/rubric/越界用当前代码对 reply_full 实判），输出逐题 diff（旧分→新分+原因）；附最小单测
- [x] A9 跑 A8 于两份报告：`eval/reports/eval-2026-10-26T01-59-01-524Z.rescored.json` 与 `eval-2026-10-26T15-23-07-811Z.json`——预期六题（cross-02/config-06/sales-07/cross-09/multi-10/sentiment-06）变化，其余零回归；cross-09 若"广汽丰田"仍缺即归一化 bug，查明修复并记 explore 增补

## Block B · multi-12 abort 残留修复（网关域）

- [ ] B1 探 pi_gateway.mjs /abort 与 pi 会话接口：确认能否在 abort 成功后向该用户会话注入系统注记（"上一轮已被用户中止，未交付内容不应在新问题中引用"）；不可注入则记录证据转备选案
- [ ] B2 主案落地（pi_gateway.mjs）或备选案（SYSTEM.md 提示词一句+留痕降级理由）；生产/eval 同路径同行为
- [ ] B3 tests/abort_api.test.ts 补覆盖（主案时）；备选案时 smoke:prompt 校验 SYSTEM.md 变更过 prompt_gate

## Block C · E2E 与门禁（Step9 预演，施工子代理一并跑）

- [ ] C1 `python prism.py eval start snap-20261012-1222` 起栈，`node eval/runner.mjs --only=multi-12`（带 env 全链）实跑：t2 含 16,879 且无 E5/B10/MG4X 名称数字 → score≥4
- [ ] C2 `npm run smoke:verify`（或 eval 判分器单测全量）+ prompt_gate 全绿
- [ ] C3 eval stop 收栈

## 验收=proposal 六条；施工报告落 `施工报告.md`
