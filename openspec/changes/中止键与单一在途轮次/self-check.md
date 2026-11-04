# Self-check · 3.5 自查收敛

- **G1 drain 时序**：/chat finally 里**先 drain eventQueue 再删锁**（删锁后新请求可进入，虽 JS 单线程同步无交错，顺序上仍以 drain→delete 为准）；rpc 声明提升到 try 外（现 L465 在 try 内）。
- **G3 /abort 的 body 解析**：复用 createServer 既有 POST body 读取辅助（与 /chat、/ui-response 同款），不另造。
- **G8 本地断流的事件语义**：sendChat catch AbortError → 发合成 `{type:'aborted'}`（非 error），用户中止兜底路径不产生错误气泡。
- **G9 断线即中止误触发**：error 事件 break（如"上一请求进行中"）时 !sawSettled 会补调 abort——幂等无害（此刻后端锁已清，返回 aborted:false），成本一次多余 HTTP，接受不特判。
- **G12 测试时长**：真流中止 E2E（DeepSeek 30-60s）不进 smoke:all——abort_api.test.ts 拆两组：fast（health/幂等×2，常跑）+ e2e（env PRISM_E2E_ABORT=1 才跑，T1.4/T3.4 手动执行）。
- G2 abort() 内 send('abort') 的 300s pending 残留：超时后静默 reject+重发 abort 命令，无害。
- G4 mapEvent 契约：消费方=main.py 透传（透明）/ChatView（switch 忽略未知）/eval runner（T2.5 核对）/无其他。
- G5 Enter 提交在 streaming 中早退（设计如此）；按钮改 type=button+onClick 分流。
- G6 streamingRef 供 2.5s 兜底定时器判 streaming 真值（闭包快照会失效）。
- G7 chat.ts 暴露 cancelActiveStream()。
- G10 abort 透传用短超时（15s）。
- G11 UI 手测清单在 T3.3 落具体步骤。
