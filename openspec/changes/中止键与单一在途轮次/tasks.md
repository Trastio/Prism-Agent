# Tasks · 中止键与单一在途轮次

## M1 网关（后端通）

- [x] T1.1 mapEvent：aborted 一等事件 `{type:'aborted'}`
- [x] T1.2 /chat finally：清锁 + drain eventQueue（rpc 引用提升）
- [x] T1.3 POST /abort 路由（validateUserId + 幂等 + rpc.abort()）
- [x] T1.4 重启网关，curl 验证：无在途幂等 / 真流中止（脚本驱动 /chat/stream + 4s 后 abort + 断言 aborted 事件 + 锁清后第二问正常）

## M2 透传 + 前端

- [x] T2.1 main.py /chat/abort 透传端点
- [x] T2.2 Icons.tsx + ico-stop
- [x] T2.3 chat.ts：activeController + cancelActiveStream() + sawSettled 断线即中止 + abortChat()
- [x] T2.4 ChatView：按钮双态（type=button/onClick 分流/icon 切换/streamingRef）+ case 'aborted' + initialMessage 挂起等待
- [x] T2.5 eval/runner.mjs 未知 type 处理核对（忽略则不动，抛错则补 ignore）

## M3 测试与验收

- [x] T3.1 tests/abort_api.test.ts 新建（5 case）+ package.json smoke:verify 挂入
- [x] T3.2 npm run smoke:all 全绿 + 根/web tsc 零新增
- [ ] T3.3 UI 手测清单走查：双态按钮/中止状态/中止后再发/看板预填消息不丢
- [x] T3.4 E2E：全链路（浏览器或 API）复演用户场景——长答案中点中止→立发新问→正常获答

## Step6-10（按大 change 标准；Step7 主会话代审——子代理无本地工具已实证）

- [x] S6 simplify 自查
- [x] S7 code-review（主会话代行，独立性受限如实记录）
- [x] S8 receiving-review 修复
- [x] S9 verification（验收 5 条逐条实证）
- [x] S10 archive + 记忆更新
