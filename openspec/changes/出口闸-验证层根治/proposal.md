# 出口闸-验证层根治 · proposal

> 2026-10-07 · 依据方案 v1.5 + explore.md（7/7 绿灯）

## WHY

两大症状（回答变慢/收不到回复 + 回答无关消息）的根因是"事后正则验散文 + user 消息回灌"这套补丁架构（G1-G5，详见方案 §一）。四轮审核已收敛的根治方案：**出口闸提交协议**——结论必须走 `submit_conclusion` 结构化提交，验证失败以 tool_result 返回、模型同轮修正；散文退出主验证对象；会话状态落 entry；全部症状转评估回归门 E1-E9。

## WHAT（三线并行）

- **线 A 出口闸**（M1-M2）：submit_conclusion 工具 + 三级数字台账（tool 真值 / declared-derived 弱信任 / 排除项）+ agent_settled 改道为保底①漏提交/②凭空编造
- **线 A 状态台账**（M3）：series_key 非空 append / verifier-state entry / verdict 经 realSessionId 送达 / ctx 首轮时序
- **评估门**（M4）：E1-E9 + trajectory submission 字段 + ci.sh 门槛
- **提示词配套**（M5）：AGENTS/SYSTEM/PRISM_ANALYSIS 教协议
- **线 C 工具层**（并行）：C0 前置（已就位，验收前复查）+ C1 sentiment_events 一处路径 + C2 get_sales_detail 参数语义 + C3 失败语义化
- **线 B 截断**：独立 change 并行（另立目录，不在此 proposal 范围）

## 决策（新增 2 项，D1-D6 见方案 §十一）

| # | 决策点 | 定案 |
|---|---|---|
| D7 | attemptMap 解耦（explore ⑦） | **提取 `verifyClaimChecks` 纯函数**：四件套逻辑零变更；verifyCompletion = 纯函数 + attemptMap（原行为不变）；submit_conclusion 只调纯函数 |
| D8 | E1-E9 存放 | **独立 `eval/tasks_gate.json`** + runner `--gate` 模式；不混入 16 题基线 |

## 影响范围

5 个文件改动 + 1 个新 task 文件（见 explore.md §五）。不碰：verifyCompletion 四件套校验逻辑、web/mixed tier 验证、pi 网关进程模型、上游服务部署。

## 风险（方案 §九 全文有效，此处列施工特有）

- 台账 entry 读取时序：tool_result hook 先于 submit execute（同轮数据已在 entries）——3.5 已核
- 回灌文案对"提交被拒未修正"场景需适配（保底①新语义）
- E2E 依赖网关重启加载新 extension——验收前必须重启 9200

## 验收（方案 §八 N1-N10 全文有效）

N1-N10 + smoke:all（36 单测）不回归 + tsc 零错。E1-E9 不绿不合档。

## 不做

方案 §七 7 条 + 线 B 独立 change。
