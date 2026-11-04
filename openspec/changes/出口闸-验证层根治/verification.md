# 出口闸-验证层根治 · Step9 verification

> 2026-10-08 · N1-N10 逐项核验。**状态：9/10 达成**——N7 的"修复 isVerifierRetryTurn 后全绿轮"被 DeepSeek API 故障阻塞（2026-10-07 19:0x 起 totalTokens=0 空响应、pi auto_retry 事件），恢复后 `node eval/runner.mjs --gate` 一条命令补验。

## N1-N10 核验表

| # | 验收点 | 证据 | 状态 |
|---|---|---|---|
| N1 | 长会话闲聊"你是谁"：settled≤2、最终回复干净、pass | 门禁第六轮 E1 PASS（4 步长会话含派生结论+非query来源后闲聊）；M2 冒烟同场景 2.2s/0 工具/settled=1 | ✅ |
| N2 | 派生数字 + derived 声明 → submission pass | 门禁 E2 PASS（第五、六轮）；第一轮 E2E 实录（gatetest4：derived 58.8/14.1 弱信任回写 + tool 真值回写 + verified entry） | ✅ |
| N3 | 编造提交 → 拒绝 → 同轮修正 → pass，无 user 消息注入 | 门禁 E3 PASS（两轮）；拒绝与修正全在 submit 工具循环内（tool_result 返回） | ✅ |
| N4 | 未提交保底拦截（唯一回灌场景） | 门禁第二轮 E5 PASS（保底①触发实证）；六轮 E5 eitherGuardOrGate（模型合规提交走闸，同为合法） | ✅ |
| N5 | settled verdict 一致率 100%（雷1消除） | M3 修复（mapEvent realSessionId + settled 时 get_state 刷新）；ctxtest2 实证：settled 事件 verdict.sessionId = extension 写入路径（01a1172f…），不再走全局 last-verdict.json | ✅ |
| N6 | 首轮 series_key 不丢；回灌轮不被空值覆盖（雷2消除） | ctxtest2 实证：series_key=银河E5 → prism-session-series-key entry + identity-coverage 落盘；T-S1 只 append 非空 + 保底③读最新非空；E1 会话空 series 0 条 entry | ✅ |
| N7 | 门禁 E1-E9 ci.sh 全绿 | **第六轮 9/9 全绿**（报告 2026-10-07T18:34 后一轮）；**待补**：isVerifierRetryTurn 前缀修复（smoke:guard 抓到的真 bug）后的确认轮——被 DeepSeek API 故障阻塞；修复为收敛性变更（retry 识别恢复 → 回灌只减不增），且有 smoke:guard 15/15（含前缀回归用例）把守 | 🟡 9/9 已达成，确认轮待 API 恢复 |
| N8 | smoke:all 全过不回归 | **50/50**（completion 3 + grounding 12 + numeric-ledger 7 + tool_call 17 + identity_api 4 + smoke:guard 15 计入）；smoke:guard 重写为新判据（保留 2026-10-04/10-07 历史误报用例语义）；tsc 根目录存在历史遗留 TS5097 类错误（v1.4 N8 已注明基线，本轮无新增，extension tsx 加载 OK） | ✅（tsc 注明） |
| N9 | 网关重启后 attempt/签名从 entry 恢复 | 机制达成：链级计数读 prism-verified entry（session 文件持久载体，取代内存 Map 与独立 sig entry）；端到端重启续聊实测留作可选加强项 | ✅（机制）/ 可选实测 |
| N10 | 工具层：舆情 6 工具可用、失败结构化、bash 归零 | E7 PASS（bash=0 + 无错误 + 报告缺口）；sentiment_events 路径修复实测（银河E5 返回真实事件数据，不再是 404）；C3 unavailable 结构 + 台账跳过（单测） | ✅ |

## 五轮门禁迭代（问题→修复→验证）

4/9 → 7/9 → 7/9 → 8/9 → 8/9 → **9/9**（六轮）→ 第七轮因 DeepSeek API 故障无效（E3-E9 空响应 totalTokens=0，非代码回归——E1/E6/E7/E8 在故障初仍过）

## 施工中修掉的基础设施级 bug（超出原方案清单）

1. pi.exe(Bun) 内 better-sqlite3 NAPI panic → extension 永久禁进程内查库，行ID校验服务端化（/verify/claim）
2. PRISM_AUTO_APPROVE_UI 缺失 → permission-system 弹窗无应答 → pi 挂死第一个工具
3. 网关 nextEvent waiter 忽略入参 → undefined.type 崩 → 客户端空 error
4. get_state/new_session/switch_session 字段路径三连错（resp.data.*）
5. writeVerdictFile 无 can_continue → P1-6"fail 继续读"从未生效（回灌轮对客户端不可见）
6. submission 统计只扫 assistant.content 内嵌形态（toolResult 实为顶层条目）
7. 乒乓回灌（①③交替绕过同因截断）→ 链级总量硬顶 + 保底③ retry 让路 + 行 ID 格式教学
8. isVerifierRetryTurn 前缀断裂（'[完成验证器·保底]' 不匹配 '[完成验证器]'）→ smoke:guard 重写抓到
9. 环境：上游库重建 series_alias 消失 → identity 降级（精确名才放行宁拒不猜）

## 结论

9/10 达成；N7 确认轮待 DeepSeek API 恢复后一条命令补验（预期全绿：修复为收敛性 + 回归用例已把守）。Step10 archive 在确认轮绿后执行。
