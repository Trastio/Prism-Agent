# proposal · 多轮评估批 change

## WHY

1. **单轮 90% ≠ 对话可用**：v1.1 基线 4.63 分只证明"一次问对"；真实用户会追问/纠正/换题/中止——多轮扛不扛得住未测（机制 10-15 建好但 0 题，空转）。
2. **上云 Gate G1 需要 72 题口径**（上线方案 §十 G1：v1.2 起含多轮批）；这是上云链第一环。
3. **三个挂账一并清**：ask_user 被网关抢答扭曲（10-20 skill-03 实锤）、traceId 未补存（langfuse run 链接全跳）、/events 身份未焊死（北极星唯一裸奔端点，上云前必须堵）。

## WHAT（七件，explore 已核落点）

| # | 交付 | 落点 | 量级 |
|---|---|---|---|
| 1 | 12 题落库（卷册→tasks.json 60→72）+ 金标 diff 表 | eval/tasks.json | 随卷册 |
| 2 | runner 三机制（branch_on/variants/carryCheck）+ Sheet4 接线 | runner.mjs / report_lib.mjs | ~75 行 |
| 3 | ask_user 模拟应答第三态（eval 网关专用，生产不动） | pi_gateway.mjs + runner | ~50 行 |
| 4 | traceId 补存（run 链接激活）+ binding 陈旧注释修正 | runner.mjs + langfuse_binding.ts:207 | ~20 行 |
| 5 | /events 身份焊死（resolve_user_id 覆盖） | prism-api/main.py:267 | ~5 行+测试 |
| 6 | trap 新增 3 类（附和/串味/残留）+ 判分接线 | trap_check.mjs + scoring-rules.json | ~40 行 |
| 7 | 单测三组+既有 60 题零回归+冒烟 | eval/*.test.mjs | ~10 例 |

## 决策（design.md 详述）

1. 12 题全进 `dev` 集（跑稳后升 frozen 由用户拍板）；
2. ask_user 第三态=`PRISM_EVAL_UI_SIM=1` 仅 eval 网关（9201），生产 9200 零变化；
3. traceId=runner 每题末 CH 查询复用 writer 既有函数，fail-soft 语义不变；
4. 冒烟跑最便宜题（multi-05 缺口双轮），**全量 v1.2 批跑不在本 change 点火**（12M tokens 帽，单独向用户报数）。

## 影响面

- 改：eval/{tasks.json,runner.mjs,report_lib.mjs,trap_check.mjs,scoring-rules.json,langfuse_binding.ts(注释)}、prism-api/{main.py,pi_gateway.mjs}、新增测试
- 不动：生产网关行为、生产 /events 行为语义（只加身份覆盖，响应不变）、判分主干、既有 60 题
- 依赖：快照 snap-20261012-1222 不轮换（m03-t3 锚点绑定其"最新=8月末"）；langfuse 栈在线（traceId 冒烟）

## 验收（方案 §8 六条+追加两条）

1. 12 题入库，金标 diff 表与卷册逐锚一致；
2. 多轮路径单测绿 + 既有 60 题判分零回归；
3. E2E ≥2 题真实双轮 verdict=pass，取消题 abort 链路实测；
4. 四 sheet 产物落地，Sheet4 有实值（非占位注记）；
5. 冒烟批 traceId 非空率>0（run 链接激活实证）；
6. 门禁 prompt-gate 绿 + smoke:all 全绿；
7.（追加）/events 自报被覆盖单测绿；ask_user 模拟应答留痕进轨迹；
8.（追加）skill-03 复跑不再被自动代答（问询事件入轨迹）。

## 不做边界

自适应 LLM 模拟器（v2，须连模拟器质量评估一起上）；完整三层首错归因（L1-2）；多轮 skill 新题（题库演进另批）；生产网关/北极星行为变更；v1.2 全量批跑（另点火）。
