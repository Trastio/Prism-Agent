# review-response · 取代性实验B系列 Step8 处置（对 审查报告.md 的 2P1+14P2）

> 主会话处置 2026-10-27。修=已改并过测试；记=入档不改。

| 项 | 处置 | 落点 |
|---|---|---|
| P1-1 臂纯度 fail-open | **修** | runner：runTask 内断言 allTools ⊆ {run_sql, read_file}，违规收集 ARM_PURITY；runValid=挑战者批纯度断言（取代恒 true）；违规打印栈指向+读数作废；汇总行改打"臂纯度"（顺带修 P2 覆盖率仪表矛盾） |
| P1-2 结构性臂差题 | **修（声明+剔除）** | challenger_check 导出 STRUCTURAL_TOOL_TRAPS=[trap-04/trap-10/skill-01/skill-02]（判定依据注释：工具名判据机械确定分差 ±8pp）；runner 挑战者批增"臂间可比"trap 口径（剔结构题）+ metadata.trap_cmp_*；A0 重放侧同规则对称剔除（写入口径）；单题照判照出 |
| P2 Bun 无 node:sqlite 头注失实 | **修（注释）** | index.ts 头注校正：本机 pi.exe=Bun 1.3.14 实测无 node:sqlite，pi 内实走 spawn 系统 node 兜底（已实证）；20KB=字符数注 |
| P2 SKILL-B E1 口径错（coalesce+方向反） | **修** | E1 改 coalesce(published_at,collected_at)+警示方向修正（45/13014 帖兜底），注明 Step8 修正；B1b 臂不再静默丢帖 |
| P2 C3 as_of 引用错源 | **修** | C3 注明 query_reviews _meta 为准（/dash/as_of 本快照恰同日） |
| P2 db 参数静默回落 | **修** | 非枚举 db 值 fail-loud（error 返回，不静默查主库） |
| P2 buildAuditList 混入未跑题 | **修** | byId 存在时只列实跑题 |
| P2 --challenger --gate 互吞 | **修** | 启动互斥 guard（argv 直判防 TDZ，实测拒） |
| P2 CLI 离线重判无逐轮回复 | **记+声明** | 头注"已知不等价边界"：多轮 trap 题以批内读数为准 |
| P2 multi-09/10 new_session 失 SOP 输入 | **记+声明** | 同上——实验设计固有形态，读数解读注意 |
| P2 challengerScore raw turns（branch 潜伏） | **记** | 当前零 branch_on 题；入库前须先改 |
| P2 manifest rel 标签硬编码 | **记** | 观测项，不影响读数 |
| P2 validateSql 字符串内分号误伤 | **记** | 可用性权衡（宁拒不猜方向一致）；挑战者遇到可加双引号绕开 |
| P2 console.log 噪声 | **记** | 与 guardrails 既有实践一致 |

**修 8 / 记 6；测试：challenger_check+trap+truth+replay 74/74、challenger_ext 10/10、node --check runner/challenger 过。**
TDZ 教训新增：guard 引用后置 const 常量会过 `node --check` 但运行时 ReferenceError——本 change 的互斥 guard 用 argv 直判（已实测拦截）。
