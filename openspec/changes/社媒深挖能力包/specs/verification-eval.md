# Spec 4 · 验证层接线与评估（零新验证器原则）

## 待办

- T1 tier 路由确认：纯社媒轮=web / 社媒+库轮=mixed（decideTier 既有逻辑，只验证不新增）；**显式验证数值台账不误收 social_* 数字**（L885 采集仅 business 类——mixed 轮后台账不得含 tikhub 来源数值，self-check Gap3）
- T2 collectWebUrlsThisTurn 验证：social_* 归一化输出的 url 字段进真值集（实测一轮对话后 webUrls 含 douyin/xhs 链接）
- T3 collectNameTruth 扩 keyword（Spec 1 T2 内实现，此处验证：keyword"风云T7"出现在 prism-name-truth 真值集）
- T4 工具描述与出口闸一致性：tikhub 数字结论走 web 降级（web_downgrade 告警不误伤）；社媒轮不触发 resolve_series 强制（身份强制只管 library tier——验证既有判据不被破坏）
- T5 eval 2 题：social-01（小红书引语 3 条带 URL）/social-02（抖音画像数字+不可复算标注）；无 key skip 不计分母
- T6 基线回归：既有 55 smoke + 16 题不回归（trap 6 题行为不变）

## 设计细节

- social-01 断言：回复含 ≥3 条 URL 且 URL ∈ 本轮 tool_result 真值集（复用 runner 的证据检查模式）；引语可在对应工具结果中找到（子串）
- social-02 断言：粉丝/获赞/作品数与工具结果一致（数值台账 web 降级路径）+ 出现"不可复算"或"抓取时间"标注
- 评估题 JSON 落 eval/tasks 现有集；runner 改动=skip-if-no-key 探测（调 /tikhub/status configured 判断）

## 验收

1. 一轮真实社媒对话后 verdict.json 无 tikhub 相关误拒（web tier 生效）
2. 社媒+query_* 混合轮：库侧严格验证照常、社媒侧降级告警照常（mixed tier 既有行为）
3. social-01/02 有 key 时通过、无 key 时自动 skip（runner 输出可见 skip 标记）
4. 16+2 题全量跑：既有 16 题分数不因本 change 漂移（±1 分内）

## 依赖

- Spec 1（工具就位才有真值集可采）；T5 依赖 key（无 key 验证 skip 路径）
