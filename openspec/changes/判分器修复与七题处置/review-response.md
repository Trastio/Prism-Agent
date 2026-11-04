# review-response · Step8 处置表（对 审查报告.md 的 P1×4 + P2×9）

> 主会话处置（2026-10-27）。修=代码已改并过测试；记=不改，理由入档。

| 项 | 处置 | 落点/理由 |
|---|---|---|
| P1-1 NEG_RE 三层漂移 | **修（深修）** | 补"不把"形态入 completion.ts NEG_RE 后红测仍红——实证发现**窗口判定只看归因词前 14 字不含词本身**，"不把X归因"类否定短语的词尾=被检词，窗口内永远拼不完整（晨间已加的不将/不对…归因形态在本层同为此因是死代码）。修法=窗口延伸至含被检词（`slice(i-14, i+hit.length)`），否定短语跨词匹配成立；completion.test 补 v1.2 cross-02 实录句回归锁；真违规句三例抽查仍全判越界（方向未松）。**副产物：晨间死代码形态被本修复激活** |
| P1-2 rescore 不认"命中禁项" | **修** | rescore.mjs 条件扩 `(r.includes('缺要素') \|\| r.includes('命中禁项'))`，同 cap 语义 |
| P1-3 sales-03 pp 改动漏账 | **修** | scoring-rules.json calibration_log 补记账（六字段，evidence 指审查报告 P1-3+施工报告注⑥）；truth_check.test 同步改断言"末三条" |
| P1-4 abort e2e 双断言活栈必红 | **修** | drainStream/drainStreamFull 补 authHeaders；rawFile 与 /session/messages 改用登录身份 `smoke_test` 定位（resolve_user_id 覆盖 body uid 的既有事实，注释留痕） |
| P2-1 replay 用截断 tools 判工具类 trap | **记+注** | 当前题库决定性工具全在 index 0（审查实证）；replay_check 头部"已知不等价边界"三条注明（触发形态出现时须先更新） |
| P2-2 replay 不豁免 error/timeout 行 | **修** | CLI 主循环跳过 error/timeout 行，汇总单列"基建行跳过 N" |
| P2-3 replay 对无效报告给偏高读数 | **修** | run_valid=false 时打印警示行（"不可作基线证据"） |
| P2-4 replay 末轮 truth 未做 branch 解析 | **记+注** | 当前 75 题零 branch_on；同入"已知不等价边界" |
| P2-5 IS_MAIN 盘符大小写 + rescore 默认参 | **修** | 两文件 IS_MAIN 小写化比对；rescore taskById 去默认值（必传） |
| P2-6 网关 catch 注释失实 | **修（注释）** | 注释改为"防御性归还；catch 覆盖 prompt 后流错时冗余无害；disposed 随对象丢弃" |
| P2-7 中止标记一次性消费未声明完整 | **修（注释）** | 消费点补注释：跨会话消费即作废、回原会话不补=设计取舍 |
| P2-8 单源测试锁不住 runner 回归 | **修** | replay_check.test 增静态位锁：runner.mjs 源码不得含内联 `/销量\.\*印证/` 且必须含 checkOverreach |
| P2-9 "锚点全中(0)"读感 | **修（注释）** | truth_check checkTruth 注明空数组=合法零锚形态 |

**修 9 / 记 2（均加边界注明）/ 全部 13 项有去处。**
