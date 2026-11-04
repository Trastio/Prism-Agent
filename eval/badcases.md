# badcase 台账（轮 2 主数据入口，2026-10-13 初始化；2026-11-01 补全机制设计）

> 来源三通道：①北极星看板四象限（verdict×点踩，pass+点踩=假阴性优先）②trajectories verdict=fail 每周翻（终轮归一后）③人工抽检（沉默的坏例子只有抽样能发现）。
> 立骨架不填种子——2026-10-13 前的 fail 多为开发期测试会话，无分析价值；首条正式记录从真实用户流量起。
>
> 口径：只做两轮——轮 1 上线前评估（题集跑分→改→复跑判显著），轮 2 上线后 badcase 回流（真实坏例→转题→复跑防复发）。

---

## 一、采集通道（三路，含实测状态）

| 通道 | 数据源 | 读取方式 | 状态 |
|---|---|---|---|
| **机器 A：verdict=fail** | `.pi/sessions/trajectories.jsonl` 的 `verdict/verdict_reason` | `node eval/dynamic-tasks.ts --collect` | ✅ 已实现（2026-10-31） |
| **用户 B：👎 点踩** | `prism_events.db` 的 `feedback` 事件（ChatView 按钮已埋点） | `node eval/feedback_collect.mjs`（并 `chat_settled` 兜底 verdict） | ✅ 已实现（2026-11-01） |
| **隐式 C：行为信号** | 轨迹 `conversation` 同 session 多轮 | `collectBadcases` 内联判定 | ✅ 已实现（重问/纠正/无应答） |
| 人工 D：抽样 | 报告与真实对话人工翻 | 人工 | 按需 |

**四象限**（verdict × 👎，终轮归一后）：

| | 👎 有点踩 | 无反馈 |
|---|---|---|
| **verdict=fail** | 双确认（最高优先） | 机器自报（次优先） |
| **verdict=pass** | **假阴性（最优先——规则层漏掉的坏例）** | 正常，不动作 |

> 代码现状更正（2026-11-01 实测）：`/badcases/quadrant` 端点**存在**——`prism-ops/ops_server.py:306`（GET /badcases/quadrant?days=14，四象限+终轮明细）；早前「未找到」记录有误，系查错位置。另：通道 B 读取器 `eval/feedback_collect.mjs` 已落地（本地实跑过，四象限并轨三数据源）。

**隐式信号判据**（可复算，见 `eval/dynamic-tasks.ts`）：

| 信号 | 判据 |
|---|---|
| `user_rephrase` | 同 session 相邻人类提问，字符二元组 Jaccard ≥ 0.6（用户重问） |
| `user_correct` | 用户末条含「不对/错了/我是说/不是这个/重新查…」 |
| `no_answer` | conversation 末尾是 user 消息（问了没答） |

系统注入的续跑消息（`[完成验证器] …`）**不作为题面**，回溯上一条人类消息（实测 L4 误收，已修 + 单测锁）。

---

## 二、判断三问（每条入账前过一遍）

1. **谁说了算**：机器 verdict=fail 或用户 👎 即算候选；两者都有=双确认最高优先。
2. **可复现吗**：复现成功的才转正式题（eval/tasks.json）；不可复现的记"偶发"观察。
3. **红线级吗**：编数字/越权/裸SQL 类——**不等轮次，任何时刻 hotfix + 冻结集回归**。

---

## 三、去重与归一

- **同 session 合并**：重问/纠正信号指向上一轮（`ref_line`），台账只记一条并在"现象"里写明第几轮。
- **同题多次**：同一 `question` 只保留一次（`generateDynamicTasks` 已有 50 字前缀去重）。
- **终轮归一**：一行=一次交互（带截至该轮完整历史），判定取末条 assistant 与末条 verdict。
- **反复出现才升级**：同一问题在不同 session 出现 ≥2 次 → 从"观察"升为"转题"。

---

## 四、归因五维（对齐 /attribution）

对象理解 / 能力选择 / 工具调用顺序 / 权限与确认边界 / 业务结果

> 机器只能给初判（工具轨迹可看出"没查库/查错库/编数字"），**最终归因由人填**。

---

## 五、处置四态与回流路径

处置枚举：**修复**（代码）/ **转题**（进 eval/tasks.json 或 dynamic-tasks.json）/ **误报**（判分器问题，修判分）/ **观察**（偶发不动作）。

```
① node eval/dynamic-tasks.ts --collect
     └→ eval/badcases.json（四件套留档：question/answer/tools/verdict_reason/sessionId/source_line）
② 人工裁决：过判断三问 + 五维归因 + 填处置 → 本台账
③ 转题：node eval/dynamic-tasks.ts → dynamic-tasks.json（set=dynamic，--set=all 不含）
     判据（judge_rubric/truth）**人工补，绝不自动生成**——真实 badcase 是新场景，无原题可继承
④ 回跑：node eval/runner.mjs --set=dynamic → 对比原判因是否修复
⑤ 复发防护：修复后涉题进 frozen 复跑，确认不回归
```

**分工**：机器负责收集、去重、初判、留档；人负责裁决、归因、定判据、拍板发布。

---

## 六、记录格式

| 日期 | 来源 | session_id | 现象 | 归因（五维） | 处置 | 状态 |
|---|---|---|---|---|---|---|
| （示例）2026-10-20 | 四象限·pass+点踩 | 01a1xxxx | 用户点踩但 verdict=pass：结论正确但未回用户实际问的版型 | 对象理解 | 转题 tasks.json（trap） | 已转 |

---

## 七、节奏与退出条件

- **节奏**：轮 1 批跑后翻一次报告（score≤2 + trap 未拦截）；上线后每次发版前翻一次新增 fail + 👎。
- **退出条件**：每条记录必须有处置，无"待定"过夜；"观察"类 30 天内未复发 → 归档，不占台账。
- **不做**：周报、月度金标重算、自动归因生成（与两轮口径一致）。
