# archive · 判分器修复与七题处置（G-2，2026-10-27 十步走完）

> 伞计划收官 P1。explore→proposal→tasks→施工（双子代理并行 A/B）→主会话自验收→隔离审查→Step8 修复→Step9 实测→归档。

## 结论一句话

v1.2 七题真 badcase 经两跑对照+重放实证改判为 **5.5 题判分器假阴 + 1.5 题 agent 问题**；修复后离线重放六题全归位、multi-12 E2E 实跑 0→5、全门禁绿。**附带坐实 v1.2 修正基线含既有虚高（rescore 规则表缺口），正式基线等 P2 repeat=3。**

## 交付清单

| 域 | 交付 |
|---|---|
| 判分器单源化 | trap_check OVERREACH_RE/checkOverreach（runner+rescore 同源）；NEG_RE 补"不把…归因" |
| 验证层深修 | completion.ts NEG_RE 补形态 + **窗口延伸含被检词**（否定短语跨词匹配才成立——晨间不将/不对形态曾是死代码）+ v1.2 实录句回归锁 |
| 词表/锚 | multi-10 expect_gap +9 形态；sales-07 摘 46.15% 派生比例锚；sentiment-06 摘 12.8% TTL 漂移锚；calibration_log +3 条（含 sales-03 补账） |
| 重放基建 | replay_check.mjs（判分器改动零回归验证的标准工具，附不等价边界三条注明） |
| multi-12 根治 | pi_gateway /abort 双分支落标（幂等分支=eval runner 实跑路径，施工探明）→ 同会话下一轮 prompt 尾注"勿引用被中止内容"→ /session/messages 剥离（前端零泄漏）；abort_note.mjs 纯函数模块 |
| 吸收晨间半成品 | NEG_RE 扩词/text_forbid 否定豁免/elements 判据/blind 重切/SCORING_FP——全部入测试入账，工作树无悬空 diff（eval 域内） |
| e2e 测试 | abort_api.test.ts 登录态+身份定位修复（P1-4），注入/剥离双断言就位（PRISM_E2E_ABORT=1 门控） |

## 数字

- 判分器单测 129/129；smoke:verify 127/0；abort 9/0
- 重放：rescored 73 题 diff 15（6 预期+9 归因）、15:23 73 题 diff 6 全预期，其余零回归
- multi-12 E2E：0（两跑）→ 5（单跑）；langfuse 挂链 1 成功
- 审查 0P0/4P1/9P2 → 修 9+记 2（全有去处，见 review-response.md）

## 系统性发现（入档）

1. **舆情 TTL 窗 vs 快照冻结漂移**（sentiment-06 根因）：快照冻结但工具窗口按墙钟——根治（窗口锚定库内 max(date)）在愿望单。
2. **判分逻辑曾经四源**：runner 内联 / rescore reasons 字符串 / 验证层 NEG_RE / （提示词示例）——本 change 收敛为单源+验证层同改纪律；SCORING_FP 指纹防假回归。
3. **v1.2 rescored 基线虚高坐实**：4.63 → 工作树判分器重放 4.59/4.53——差量来自 rescore 规则表缺口（非 agent 退化）。

## 遗留

- replay 两条"记"项边界（工具截断/branch_on）——触发形态入库前先更新注释
- 中止标记为 RpcClient 内存态（30min 清理丢标风险，秒级窗口，如实声明）
- 断连即中止（S8 P1-4）是否落标——语义待拍板
- P2（全量 repeat=3）以本判分器起新基线 v1.3
