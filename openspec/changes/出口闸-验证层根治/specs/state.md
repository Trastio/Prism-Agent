# spec · 会话状态台账（M3）

## 待办清单

1. series_key entry：before_agent_start 仅非空 append；2b 判据读取取最新非空（修回灌轮空值覆盖）
2. ctx 首轮时序：pi_gateway 把 ctx.json 写入挪到 get_state 之后，key=realSessionId（消除首轮 default.ctx.json 错位）
3. verdict 送达：mapEvent 加第三参 realSessionId（explore ③ 三处改动点）；last-verdict.json 标 sunset 注释
4. `prism-verifier-state` entry `{attempt, failureSig}`：agent_settled **保底路径**读写；删进程内存 lastFailureSigMap。**attemptMap 归属（3.5 Gap6 定死）**：保留在 verifyCompletion 内部、仅服务 mixed 分支（D4 维持现行）；library/none 保底的 attempt/can_continue 走 entry（N9 由 entry 达成）

## 设计细节

- entry 读取统一走 getEntries() 从后向前找（最新优先）
- 网关改动仅 3 处（explore ③），不触碰 RPC 协议层

## 验收标准

- N5：settled 事件 verdict 与 extension 写入一致率 100%；无跨会话串读
- N6：首轮带 series_key 新会话身份不丢；回灌轮不被空值覆盖
- N9：网关重启后同会话续聊，attempt/签名从 entry 恢复
