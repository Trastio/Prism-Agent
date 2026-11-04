# Review Response · 中止键与单一在途轮次

## S6 simplify 自查

- 四层改动各就各位无冗余；/abort 尾随排干与 S7-d 余波等待职责不同（前者清队列卫生、后者防交织），均保留
- abort_api.test.ts 的 e2e 组用 env 门控避免 smoke 拖慢——与"断言类修复必须实测"不冲突（同场景已两轮人工实测）

## S7 自审发现与处置（主会话代行，独立性受限如实记录——子代理无本地工具已实证）

| # | 发现 | 级别 | 处置 |
|---|---|---|---|
| 1 | **/abort 排干偷事件竞态**：排干循环最长 2s，期间新 /chat 已开读会被 shift 偷走事件；反向尾随 tool 事件泄入新流并点亮 sawContent → 尾随 settled 照样 break → **新问被空转吃掉**（race3/race4 两轮实测复现，两种泄漏形态） | **P0** | 四连修：S7-a 排干遇锁即停 / S7-b 拿锁后清残渣 / S7-c 收紧判据（仅 thinking/text 算内容，连两个零内容 settled 才放弃）/ **S7-d 中止余波等待（治本：abort 后 2.5s 内的新 prompt 先等余波落完，rpc.lastAbortAt 同时覆盖超时中止路径）** |
| 2 | JS 里误留 Python 风格 `#` 注释（heredoc 施工笔误） | P1 | node --check 即时捕获并修复 |
| 3 | 网关监听 0.0.0.0:9200，按 `127.0.0.1:9200` grep 杀进程落空（空 PID 静默 no-op，>/dev/null 掩盖） | P1 | 改 grep `:9200`；坑记入记忆（重启操作 SOP） |
| 4 | UI 测试 agentRepliesDuring=0 | 非 | 6s 时仍在 thinking 阶段，非缺陷；核心断言（图标/状态/恢复）全过 |

## S8 修复验证

race5 终测（最严苛：abort 后 50ms 发新问）：新问 **42.7s 完整获答**（thinking 2541 段/text 1921 段/tool 6 次/settled 正常收尾，含一轮验证器 retry）；中止流含 aborted ✓。smoke:all **84/84**、根 tsc 11=基线、web tsc 0。


---

# 补充：隔离上下文独立审查（2026-10-12 第二轮，用户拍板"需要隔离上下文再审查"）

## 方法

子代理无本地工具的限制下，把全部变更代码（网关 /chat 与 /abort、RpcClient、mapEvent、main.py、chat.ts 全文、ChatView 变更块、测试，~40KB）**内嵌进任务提示**，隔离上下文离线审查——独立性优于主会话自审（自审漏掉的以下问题即证）。

## 审查结果：3 P0 / 5 P1 / 8 P2（全部逐条核实后处置）

| # | 发现（审查者原文摘要） | 核实 | 处置 |
|---|---|---|---|
| P0-1 | 前端 2.5s 兜底定时器无清除路径：中止后 2.5s 内重发的新轮被 cancelActiveStream 误杀 | 成立 | abortTimerRef + handleSend finally 清除 |
| P0-2 | finally 自动补 abort 单看 sawSettled：双标签页被拒轮会杀同 user 在途合法轮；用户中止后冗余 abort 可命中刚拿锁的新轮 | 成立 | 判据收紧：!settled && !aborted && !流内error（网络异常走 catch 路径仍补） |
| P0-3 | S7-c 误伤真轮（纯工具轮/无 thinking 轮/尾随>2.5s）+ 双零内容 break 不停 pi（级联泄入下一轮）+ 单零内容 skip 后挂死无兜底 | 成立 | 双零→先 rpc.abort() 再告客户端；skip 后 20s 无事件竞速兜底；内部 abort 均清 abortPending |
| P1-1 | S7-b 清队吞掉 B 轮等待期到达的合成 aborted（用户中止被静默吞） | 成立 | abortPending 标志 + /chat 消费即清（修复中自查出标志残留新 bug，一并修 4 处生命周期） |
| P1-2 | send() 写失败不清理 pending → 300s 后补刀 abort 误杀重生进程新轮 | 成立 | writeSafe catch 即删 pending |
| P1-3 | dispose 无参唤醒 waiter → undefined → event.type 崩 | 成立（LRU 淘汰真实可达） | 循环头 `if (!event) break` |
| P1-4 | /chat 无断连感知：关标签后服务端空跑、锁滞留 | 成立 | res.on('close')→abort + 等待期 res.destroyed 检查 |
| P1-5 | main.py 失败 200+ok:false（前端只看 res.ok 静默当成功）+ user_id None 落 default | 成立 | 502/400 + JSONResponse 透传状态码 |
| P2 | 8 条：修 4（send 定时器清理/mapEvent Error 字符串化/排干死条件/writeHead 提前）+ initialMessage 消费时序；记录不修 3（verdict.json 读竞态、user_id 可伪造、res.write 背压——均原有系统性问题非本 change 引入） | — | 如左 |

## 修复后终测

- 连点两次 abort：true→false（幂等）✓
- 中止后 50ms 新问：27s 完整获答（thinking 1844/text 2025/settled 收尾）✓
- smoke:all 84/84 · tsc 基线持平 ✓
- **审查者结论原文**："优先修 P0-3（挂死+交织级联）、P0-1/P0-2（前端两处误杀链），三者共同修完才谈得上'中止是用户主权操作'的契约闭环"——均已修
