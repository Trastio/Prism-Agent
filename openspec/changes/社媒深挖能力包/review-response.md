# Review Response · 社媒深挖能力包（Step8）

审查：独立 agent（全量 8 文件逐行，2026-10-12）· 结论：**无 P0，3 P1 + 11 P2；红线专项（fail-closed/自截断/key 不泄漏/防穿越/计数时序）全过**

## P1 全修（3/3）

| # | 发现 | 修法 | 验证 |
|---|---|---|---|
| P1-1 | social-01/02 结构性不可能及格（scoreTask 证据正则只认库行 ID） | 社媒题分支：证据判据=URL 溯源 + 抓取时间/不可复算声明 | runner --check 过（实跑留 M5） |
| P1-2 | time_window 静默失真（douyin 无 month→全时段；weibo 全不支持） | executeAction 显式拒绝不支持组合（fail-closed 列出支持档）+ `_meta.time_window_applied` 随行声明 | 单测 2 case（douyin month 拒/weibo 拒）+ normalize 断言 |
| P1-3 | /export 非法字符（\x0b 等 → IllegalCharacterError 500；表名 [\\/:*?\[\] 抛异常） | 单元格统一 `_cell()` 清洗 + 表名正则替换 `_` | **实机**：含 \x0b + 非法表名导出 200，读回表名已清洗 |

## P2 修 8/11

- URL 正则 `,;` 恢复排除（点号仍放行）三处——逗号分隔 URL 列表不再并成单条
- truncateOutput 截断时末尾显式标记（模型知数据不全）
- 计数器 bump 前置必要参数检查（8 次无效调用不再耗尽预算；block 机制仍在 tool_call 层）
- /export rows_dropped 计数进响应（畸形行不静默丢）
- pi_gateway .env 解析对齐 dotenv 语义（去引号/行内注释，消双源分歧）
- /tikhub/status error 不进 10min 缓存（网络抖动不钉红灯）
- 截断断言收紧（删恒真析取）；无 key 用例 try/finally；tikhub status 测试密封化（强制无 key 态不真实外呼）

## P2 留下一轮（3 条，记录在案）

- manifest 读改写无锁：单 worker uvicorn 下实测原子（await 后无切换点），多 worker 部署前改 jsonl 追加
- SKILLS_ROOT 依赖 process.cwd()：与 index.ts 既有惯例一致（同病），单独修 skills.ts 反而不一致——上云前随全局锚定一并治
- （附带）eval 动态题集合并后的社媒题同样走 skip 分支——设计内行为，非缺陷

## 审查 agent 环境插曲（记录）

首次派发（general-purpose 类型）因子代理会话无任何本地文件读取工具而阻塞，agent 按红线拒绝编造结论（正确行为）；重派 claude 类型（Tools: *）完成全量审查。**教训：派文件审查类子代理须用全工具类型。**
