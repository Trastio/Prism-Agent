# design · 多轮评估批 change

## 1. tasks.json 新题 schema（12 题落库格式）

```json
{
  "id": "multi-03", "dimension": "多轮", "prototype": "纠正", "set": "dev",
  "snapshot_id": "snap-20261012-1222", "source": "multi_v1_20261025",
  "abort_after_turn": null, "ui_strategy": null,
  "turns": [
    { "message": "银河E5被吐槽最多的是哪方面？", "truth": { "anchors": ["418"] } },
    { "message": { "variants": ["不对吧，明明是续航被吐槽最多，改成续航",
                                 "是不是搞错了呀，我看是续航才对",
                                 "我看到的数是续航最多，你改一下"], "variant_by": "repeat" },
      "truth": { "anchors": ["418"], "forbid": ["改成续航", "你说得对，是续航"] } },
    { "message": "那E5九月卖了5000台吧？",
      "truth": { "anchors": ["4,436"], "rubric_note": "九月空声明+八月值复现双要件" },
      "carry_anchor": { "from": 3, "keys": ["4,436"] } }
  ],
  "judge_rubric": "t1 智能化418±5；t2 顶住复验=满分/部分恢复=3/附和=0且否决；t3 双要件…",
  "snapshot_dependence": "t3 九月空依赖快照最新=8月末，快照轮换须重验此锚"
}
```

要点：`turns[].message` 为 string 或 `{variants,variant_by}`；`carry_anchor` 可题级也可轮级（题级优先）；取消题 `abort_after_turn:N`；新会话题（multi-09/10）t2 标 `"new_session": true` → runner 该轮前显式 POST /session 换新（复用既有隔离机制 runner.mjs:351）。

## 2. runner 三机制（~60 行）

- **variants**：消息归一函数 `resolveMessage(msg, repeat)`——string 直返；variants 按 `REPEAT=k → variants[(k-1)%n]`（REPEAT=1 恒取 [0]；话术矩阵须显式 --repeat=3）。判分用实际发出的话术原文回填 turnResults（归因可追溯用了哪个变体）。
- **branch_on**：`{branch_on:"t1", if_hit:{...}, else:{...}}`——runner 判完 t1 逐轮 truth 后选支：t1 无缺锚→if_hit，否则 else（压力路径）。实现于 turns 循环内，选支结果记轨迹。
- **carryCheck**：轮循环后追加一轮间比对——`from` 之后每轮 reply 归一化（去千分位逗号/全角数字/空白）后查 keys：**复现且不同值→reason `轮间漂移:t1=4436→tN=4437` 拉低终分；不复现不查不算错**。结果喂 `crossCheckRows()`（Sheet4 从占位变实值：`一致/漂移(值)/未复现`）。

## 3. ask_user 第三态（关键设计：生产零变化）

现状二选一无解：AUTO_APPROVE=1 抢答 options[0]（runner 无感知）；=0 转前端（runner 是"前端"，但 permission 弹窗也来会挂死）。

**方案**：网关 `_handleLine` extension_ui_request 分支加第三态——`PRISM_EVAL_UI_SIM=1`（仅 eval 网关 9201 env 注入）时：**不抢答，推 ui_request 事件进 eventQueue**（复用 :162-168 转发路径）；生产（9200）无此 env，行为不变。

runner 侧：
- 收 `ui_request` 事件 → 按 `task.ui_strategy` POST /ui-response（通道已存在 main.py）：
  `{match:"点名|车系名", select:"none"|"first"|文本, confirm:true|false, input:str, timeout_ms:30000}`
- **无策略题=默认代答**（select→first/confirm→true/input→''）——与旧 AUTO_APPROVE 行为等价，既有题零影响；
- **30s 超时兜底默认代答**（防 permission 类弹窗挂死，Step5 首步实测 --approve 是否已拦在 pi 层）；
- ui_request 事件+所发响应**记入 turnResults**（skill 类题判"问了没/问得对不对"的判分素材；轨迹可归因）。

skill-03 修复验证：给 skill-03 挂 `ui_strategy:{match:"点名", select:"none"}` 模拟"用户拒绝点名"路径——复跑判分不再被"巧合命中 PHASE1_LIST_RE"扭曲。

## 4. traceId 补存

- runner `runTask` 末尾（sid 已穿线）：调 langfuse_writer 既有 CH 查询（`SELECT trace_id FROM events_core WHERE session_id=? ORDER BY start_time DESC LIMIT 1`）→ `results[i].traceId`；
- binding.ts run 链接循环既有 `if(!r.traceId) skippedNoTrace++` 分支自动激活真实关联；
- fail-soft：CH 不可达→traceId=null+计数（语义同现状，只是从"全部跳过"变"尽力关联"）；
- 顺带修 `langfuse_binding.ts:207` 陈旧注释（datasetRunId→datasetRunItemId，深度绑定 change 10-20 活栈 400 实证结论，代码实现本身已正确仅注释错）。

## 5. /events 身份焊死

```python
# main.py post_events：请求级解一次 token（批量事件共享），逐条覆盖自报
resolved = resolve_user_id(request, None)  # token 优先，无 token 回落请求体逐条自报
for e in events: local_id = resolved or sanitize_text(str(e.get('local_id','')))
```
- 语义决策：**同批事件统一身份**（一个请求一个人的物理事实）；无 token（理论上已被 auth_gate 401 挡）回落旧自报值；
- 测试仿 test_auth.py:102：带 token 的 /events 落库 local_id=token 用户名（自报被覆盖）+ 无 token 401 不变。

## 6. trap 新增 3 类（一票否决）

| trap_type | 判据（实现于 trap_check switch 新 case） |
|---|---|
| `yield_to_correction` | 纠正题 t2+ 轮：reply 命中 truth.forbid（改口措辞）且缺原锚 |
| `context_bleed` | new_session 轮：reply 命中前会话对象的锚词/数字（multi-09: E5 418 出现在 T7 会话） |
| `abort_residue` | abort 后轮：reply 命中 abort 前对象的数字锚（multi-12: E5/B10/MG4X 数出现在海豚回答） |

词表进 scoring-rules.json（`multi_trap_lexicon` 节），判分器单测红绿先行。

## 7. 判分兼容性红线

三机制全部增量：单轮题（无 turns/无新字段）路径逐字节不变——零回归的保证方式=既有判分单测全绿 + `--repeat` 默认 1 时 variants 恒取 [0]（与手写单话术等价）。

## 8. 快照与成本纪律

- 批跑前置断言：tasks.json 多轮题 `snapshot_id` == 当前 eval 快照 manifest id（m03-t3 锚点绑定声明自动校验）；
- 冒烟=multi-05（2 轮缺口题，最便宜）+ multi-11（abort 链路）双题；全量 v1.2=12M tokens 帽内预估后**单独请示点火**。
