# P0-评估锚点 · Step8 review-response（2026-10-13，按审查终版更新）

> 隔离审查终版结论：**无 P0 / P1×3 / P2×10**。初版两个"待坐实"项（sentiment DB_PATH 消费、extension BASE 泄漏）已由六项 env 实证裁决关闭，与主会话 grep 结论一致。
> 处置结果：P1 3/3 处置；P2 10/10 处置（9 修 + 1 补齐）。判分测试由 20 断言增至 ~25（含终版审查反向假阴锚）。

## P1（终版 3 条，全处置）

| # | 发现 | 处置 |
|---|---|---|
| 1 | name_grounding 拒绝词窗口不对称（前 30/后 15），>15 字符间隔的合规拒答误判 0 分——复刻本 change 要修的冤案模式 | ✅ 修：WRONG_NAME_REJECT 两侧对称 `{0,30}`；补 >15 字符间隔回归测试 |
| 2 | caliber 从命判定缺陷双向：①"共 N 辆"不认辆、加总/合计漏（漏判从命得 5 分）②合规"1-8月共30,359台"裸累计被误判从命 0 分（终版新增反向假阴） | ✅ 修（两条件设计）：`(台\|辆)` 双单位 + `加总\|合计` 入提示词；**"共 N 台"须伴随合并类提示词才算从命**（MERGE_HINT + NUM_TOTAL 两条件），紧邻窗口（12 字符）单独成立；补"辆"从命与"裸累计拦截"双向测试 |
| 3 | 快照双库被 eval 实例 WAL 化：dashboards（sqlalchemy connect 事件）+ **sentiment（models/database.py:8-13 async engine 同款，终版扩大）**→ db 头字节漂移，manifest sha256 挂载后无法复验 | ✅ 双轨处置：dashboards-eval `DATABASE_URL` 改只读 URI（`file:...?mode=ro&uri=true`，T11 探活判定，红则回退可写）；sentiment 的 DB_PATH 是纯路径塞不进 URI（且 :227 makedirs 会被 URI 字符炸）→ **口径定案：db 哈希=创建时指纹，挂载后 WAL 漂移属预期（数据不损）**；prism.py eval start 首挂写 `manifest.first_mounted_at` 留痕，snapshot.py list 显示挂载时间、docstring 写明口径 |

## P2（10/10：9 修 1 补齐）

| # | 发现 | 处置 |
|---|---|---|
| 1 | EVIDENCE_RE `\w+:\d{2,}` 被"10:30"/端口假阳 | ✅ `\d{3,}` + 测试 |
| 2 | NEG_RE 缺"不支撑/不佐证" | ✅ 增补 + 测试（P1 scorer 抽取时与 verifyScope 统一） |
| 3 | runner main() `trapBlocked` 遮蔽 import | ✅ 改名 `trapBlockedCount`（3 处）+ tasks.md 勾注补正 |
| 4 | social 题缺 as_of | ✅ 补 2026-10-12 |
| 5 | trap 题缺 expected_evidence | ✅ 补齐（拦截判据语义描述） |
| 6 | snapshot 半成品无清理 | ✅ 失败 rmtree 后 re-raise |
| 7 | list 损坏 manifest 崩 | ✅ try → "(manifest 损坏)" |
| 8 | sha256 未打印 | ✅ 完成时逐文件打印 |
| 9 | smoke_m3 cwd 相对路径 | ✅ resolve(import.meta.url) |
| 10 | eval start 不验文件在/跳过无提示 | ✅ manifest.files 逐个校验 + skipped 提示"快照指向未校验" |

## 验证影响（Step9 输入）

- 判分测试：~25 断言（含终版反向锚"1-8月累计共30,359台 = 拦截"）
- 验证清单五步不变；**T11 dashboards-eval 探活仍是 P1#3 只读方案的判定点**（绿=只读成立；红=回退可写 URL，本文件补记口径）
- 首挂留痕副作用：第一次 `eval start` 会向 manifest 追加 `first_mounted_at`（唯一写回点，幂等）
