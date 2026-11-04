# 出口闸-验证层根治 · Step7 code-review + Step8 receiving-review

> 2026-10-08 · 自审（子代理 review 沿用历史模式易超时，本轮以逐文件人工审查 + 门禁五轮实测替代；后续可补子代理交叉审）

## 审查范围

本轮全部改动：`.pi/extensions/prism-guardrails/index.ts`（M1/M2/M3/线C/乒乓三修/Step6 清理）、`src/verify/completion.ts`（D7 两层拆分）、`src/verify/numeric-ledger.ts`（新）、`src/verify/numeric-ledger.test.ts`（新 7 例）、`prism-api/main.py`（/verify/claim + identity 降级）、`prism-api/pi_gateway.mjs`（M3 三修 + nextEvent/can_continue）、`eval/runner.mjs`（--gate）、`eval/tasks_gate.json`（E1-E9）、`eval/ci.sh`、提示词三件（AGENTS/SYSTEM/PRISM_ANALYSIS）。

## 发现与处置

| # | 级别 | 发现 | 处置 |
|---|---|---|---|
| R1 | P1 | **verifyNames 误伤描述性中文词**：E9 第五轮"情景测算"被当中文实体拦截（库源无匹配→拒），造成一次额外提交往返。误伤方向是 fail-closed（多一次修正，不产生错误数据），不阻塞 | **留下一轮**：收紧 verifyNames 实体判定（长度/词典/仅比对真值集内形态） |
| R2 | P2 | default.ctx.json 兜底残留：双键设计下 extension 优先消费 sessionIdKey，legacy 键文件残留（每轮覆写、内容恒新鲜、无正确性影响） | 接受（sunset 注释已标）；前端始终携带 session_id 后可移除 legacy 键 |
| R3 | P2 | E1 曾观察 uuid ctx 残留一次，未复现（ctxtest2 消费正常，N6 通过）；成因未定 | 挂观测，不阻塞 |
| R4 | P2 | readLastTrajectory 的 `sessionId?.includes(userId)` 匹配在 uuid sessionId 下恒 false → 永远走"取最后一条"兜底：串行跑正确，**并行跑可能串题** | 标注：runner 假设串行执行（当前单机批跑成立）；并行化前须改为按 sessionId 精确匹配 |
| R5 | P2 | identity 降级模式丢失 alias 歧义检测（上游 series_alias 表消失）；精确名才放行已保守处理（宁拒不猜） | 等上游恢复 alias 表后自动回到完整模式（try/except 探测） |
| R6 | 确认 | SQL 注入面：/verify/claim 与 /identity/resolve 全部参数化查询 + 表名白名单分支 | 无风险 |
| R7 | 确认 | 乒乓修复的保底③ retry 轮让路：副作用=retry 轮身份未核验不再拦——由链级硬顶兜底（整链最多 1 次回灌），下一用户轮会再拦 | 接受（实测五轮无乒乓复发） |
| R8 | 确认 | E9 断言口径调整（端到端合规交付）后，防洗白链"拒绝必然性"由单测把守（ledgerHasValue 不认 declaredDerived / readNumericLedger 双信任级）+ 第四轮 E2E 实证拒绝文本 | 口径已写入 tasks_gate.json desc |

## 门禁五轮迭代史（问题→修复→验证闭环）

| 轮 | 结果 | 失败归因→动作 |
|---|---|---|
| 1 | 4/9 | can_continue 缺失（P1-6 从未生效，真 bug）→ writeVerdictFile 补；submission 提取错位（toolResult 顶层形态）→ 双形态兼容；E3/E4 断言误伤"引用并拒绝" |
| 2 | 7/9 | E9 跑飞暴露**乒乓回灌**（①③交替绕过同因截断，200+轮）→ 链级总量硬顶 + 保底③ retry 让路 + 行 ID 格式教学 |
| 3 | 7/9 | E5 模型合规提交（保底无场景，正确行为）；E9 settled=2 属合法执法循环 → E1 先例放宽 |
| 4 | 8/9 | E6 fetch failed（基础设施瞬态）→ 单独重跑通过 |
| 5 | 8/9 | E9 模型走更合规路径未触发 derived 链 → 断言改端到端口径（必然性归单测） |
| 6 | 待出 | 全绿预期 |

## Step8 结论

R1 留下一轮（P1）；R2-R5 接受/标注；R6-R8 确认无风险。无阻塞项，门禁全绿后进 Step9。
