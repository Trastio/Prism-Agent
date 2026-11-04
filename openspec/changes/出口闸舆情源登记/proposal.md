# Proposal · 出口闸舆情源登记

## WHY

舆情是"外挂第四组"，对话 Agent 重构后舆情问答成常规对话，但出口闸的 supported_by 源注册表只有三维度（销量/口碑/配置）。后果：**任何带数字的舆情结论必被拒 → 必触发"漏提交"保底重试**——多绕一轮（约 10s + token）、前端弹"验证器重试"免责文案、用户以为故障（2026-10-11 风云T7 实案）。附带 verifyNames 对品牌/车系前缀词（风云→"空间"）的误报，在拒绝信息里雪上加霜。

## WHAT（三处修复）

1. **闸补舆情源（治本）**：`/verify/claim` 新增 sentiment_* 行 ID 分支，直读 vehicle_sentiment.db（只读）；6 种引用格式与舆情工具对齐 + 宽容模型自造格式。
2. **verifyNames 前缀放行（R1 最小修）**：纯 CJK token 是某真值名前缀且余部非 CJK → 放行（风云→风云T7、银河→银河E5）。其余逻辑不动，8 测试集不变。
3. **文案对齐**：6 个舆情工具描述 + submit_conclusion 描述/拒绝提示补舆情行 ID 格式（教模型引用对）；前端重试轮免责文案改友好。

## 决策（D1-D5）

- **D1 校验位置**：扩 prism-api `/verify/claim`（直读 sentiment DB），不在 sentiment 服务加端点——复用"服务端真值"既有模式，一改两不改。
- **D2 引用格式**：`sentiment_overview|trend|competitive:{车系名}`（车辆存在即过，与 resolveVehicleId 同语义：精确→包含）；`sentiment_dimension:{车系名}/{维度}`（车辆存在 + dim_sentiment 含维度）；`sentiment_posts:{post_uuid}`（raw_posts.id 精确）；`sentiment_events:{event_uuid}`（event_groups.id 精确；`sentiment_events:{车系名}` 退化为车辆存在）；`sentiment_board:{车系名}/任意`（宽容分支，模型自造格式）。舆情库不可达 → 仅 sentiment_* 引用 fail-closed。
- **D3 名称放行规则**：仅"前缀包含"一种新放行；不动 findClosest 阈值（动了会破张冠李戴检测：蔚来Z9/一汽丰田GAC 两 case 依赖 d<3）。
- **D4 教学位置**：格式提示只加在 extension 工具描述与拒绝文案（会话内可见），AGENTS.md 不动（它不枚举源格式）。
- **D5 前端文案**："本段为验证器自动校验后的修正回复（原因：…），此前一条回答的证据已补交复核"——不再是"不是对上一句提问的直接回答"这种故障感表述。

## 影响范围

- `prism-api/main.py`（/verify/claim + PRISM_SENTIMENT_DB env）
- `.pi/extensions/prism-guardrails/index.ts`（描述文案 ×8 处）
- `src/verify/grounding.ts`（verifyNames 前缀放行）
- `prism-web/src/components/ChatView.tsx`（文案）
- 新增 `tests/verify_claim_api.test.ts`（活服务 4 case）+ `src/verify/grounding.test.ts` 增 case

## 验收

1. E2E：复问"最近风云T7有什么舆情么"→ 首次 submit_conclusion 即过闸（supported_by=sentiment_overview:风云T7），无保底回灌，trajectories verdict=pass 且 lastReject 无 sentiment 拒绝。
2. smoke:all 全过（含 grounding 8 旧 case 不回归 + 新前缀 case）。
3. verify_claim_api.test.ts：真车系过 / 假车系拒 / 真 post_id 过 / 假 uuid 拒。
4. 假设防御：supported_by 给 `sentiment_posts:不存在uuid` 必须拒（fail-closed 有效）。

## 不做

- 不改 sentiment 服务任何代码
- 不动数值台账（sentiment 数值采集已工作）
- 不重写 verifyNames 相似度算法（只加前缀放行，残余风险：真值集里完全没有的跨会话车系名仍可能误报——记录为已知限制）
- 不动 AGENTS.md
