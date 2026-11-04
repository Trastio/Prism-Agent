# Tasks · 出口闸舆情源登记

## M1 闸通（关键路径）

- [x] T1.1 prism-api/main.py：`SENTIMENT_DB` 常量 + `_open_sentiment()`（只读、惰性开）
- [x] T1.2 /verify/claim：sentiment_* 六族引用分支（D2 全表）+ LIKE 转义 + fail-closed（仅 sentiment_* 受影响）
- [x] T2.1 extension submit_conclusion description + 拒绝提示补舆情格式
- [x] T2.2 6 个舆情工具 description 补引用格式行
- [x] T1.3 重启 api 服务，curl /verify/claim 手测 4 case

## M2 护栏与测试

- [x] T3.1 grounding.ts verifyNames 前缀放行（design T3 代码）
- [x] T5.1 src/verify/grounding.test.ts：前缀放行 3 case + 确认旧 8 case 不回归
- [x] T5.2 tests/verify_claim_api.test.ts 新建（活服务 4 case，skip 模式）
- [x] T5.3 package.json smoke:verify 挂入新测试文件
- [x] M2 验收：npm run smoke:all 全绿

## M3 前端 + E2E

- [x] T4.1 ChatView.tsx 免责文案替换（design T4）
- [x] T6.1 E2E：prism.py 重启全栈 → 前端/API 复问"最近风云T7有什么舆情么" → 断言：首提过闸 / 无保底回灌 / verdict=pass / lastReject 无 sentiment 拒绝 / 界面无故障感文案
- [x] T6.2 E2E 防御：`supported_by=["sentiment_posts:00000000-…]` 必拒（fail-closed 有效）

## Step6-10

- [x] S6 simplify 自查
- [x] S7 code-review
- [x] S8 receiving-review 修复
- [x] S9 verification（验收 4 条全过）
- [x] S10 archive + 记忆更新
