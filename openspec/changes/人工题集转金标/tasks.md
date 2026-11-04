# 人工题集转金标 · tasks（2026-10-13）

## Block 0（子代理A · 施工）
- [x] T0.1 market_data.py：market_series_filter（:189 两锚分离+ENERGY_ENUMS:181+重叠语义）
- [x] T0.2 market_routes.py：GET /api/series-filter（:106 参数校验 400/limit 收敛[1,50]/截断提示）
- [x] T0.3 prism-api/main.py：DASHBOARDS_TOOL_MAP **:885**（原记 :731 系并行会话改动前行号，10-13 北极星 change 后漂移，已核）加 series_filter 行
- [x] T0.4 extension index.ts：search_cars 双路径参数扩展+描述更新（筛选参数→series_filter，原路径逐字未动）
- [x] T0.5 tests/test_market_series_filter.py：12 测试过（主会话亲跑复现 1.26s→0.56s）
- [x] T0.6 验证：单测 12/12 + tsc 新增 0 错（历史基线 11 不变）+ 真实库只读三连实测（12万BEV 83 命中/A级ICE 276/轴距区间 330，T7 形态不丢行）——**活端点+eval 实例留 Step9**
  - 施工方报 3 处加固偏差（数据层 ValueError 兜底/错误响应体回流/limit 下限钳 1），均在界内，主会话采信

## Block 1（子代理B · 施工，与A并行）
- [x] T1.1 快照只读逐题查数：38 题金标 + supported_by 全部在库核验（_verify_user_gold.py 128/128，主会话亲跑复现）
- [x] T1.2 fail_closed 5 条：PTC 两题库内无字段不可核验（真差项候选已扫出：温度分区控制/方向盘加热）/ A10 四维仅销量（Excel24 转缺口题）/ MG4X 最低配核验通过 / 海狮05 消歧更重（DM-i 口碑 0 条）/ E5 最高配核验通过（14.78万）
- [x] T1.3 diff 表 7 行（第2行保留+补充/第3/10/12行改写/第19/21/23行补写）
- [x] T1.4 产出 eval/gold/user-20261013.json + 报告.md + _gen/_verify 复跑脚本
- [x] **重大纠错（已主会话复验坐实）**：初版"9月末批已导入"系跨年聚合误读，2026-9月末零售全空，最新=2026-8月末；explore.md 已更正；用户原"最新8月"期望本来就对
- [x] 遗留决策（2026-10-13 用户拍板）：**PTC 两题保留原题不走改题**——混合语义（库内声明无字段→红线#9 web 补充→佐证方向 T7有/E5无→URL+不可复算→纠正命题；web 无果如实"无法核验"亦合格；eval 期 web 不可用按 social 条件题不计分母）。config-03/04 金标已改写，128 断言复检过，报告.md 已附裁决记录
- [x] brand 参数小补+拍板B **收口（10-13）**：market_data.py brand/manufacturer 双路径任一 contains（:279-306）；tests 18/18（主会话亲跑复现）；真实库两连精确命中——BEV top3=QQ3 EV 12,129/风云A9 5,796/iCAR V23 2,479（与金标一致），NEV top3=QQ3 EV/智界V9 增程 8,213/风云A9（集团语义生效，口径差异非 bug）；tsc 新增 0。**Block 0 全部收口（T0.1-T0.5+brand+拍板B），活端点/eval 实例验证仍留 Step9**

## Block 2（主线，Block1 产出用户过目后）
- [x] T2.1 tasks.json 20→**58**（并行会话先加到 20，以盘面为准；schema 对齐/dimension 中文映射/快照绑定；**diff 7 行用户 2026-10-13 确认定稿**）
- [x] T2.2 切分落库：frozen 19（陷阱4+缺口7+E5族正向8，规则执行逐条审计过）/ dev 19 + EVAL_STATUS 题库状态节 + truth-expectations 锚点键

## Block 3（主线）
- [x] T3.1 truth-expectations 扩展（smoke 级锚点键；逐题全量断言在 _verify_user_gold.py 131 条——超配部分记录于 archive 留下一轮）
- [x] T3.2 rubric：judge_rubric 全量入 tasks.json（verdict 判分可用已实证）；三类机器判分（top3 容差/缺口 web 方向/舆情范式）归 P1 scorer 抽取

## Step6-10
- [x] Step6 simplify（并入 Step7 审查 simplification 节处置：修 1 死行/记 3）
- [x] Step7 code-review **隔离子代理**（无 P0/2 P1/8 P2/4 简化；关键面全核实：筛选金标与端点语义独立复刻吻合/两锚分离三重验证/零回归/无注入面）
- [x] Step8 receiving-review（P1 全修：金标 5 处文本修 + 生成器裁决覆盖层（重跑幂等，diff 唯一差异为措辞改进采纳生成器版）；P2 修 4 记 4；review-response.md 落盘；**终验：pytest 20/20 + 断言 131/131 + 生成器重跑后复验 131/131**）
- [x] Step9 verification（10-13 全绿）：活端点两连+T7形态+400 / eval 快照实例 G9 坐实 / 真实 agent E2E（奇瑞题 31s verdict=pass 首选=硬锚）/ trap01-06 全5分（07/08=并行会话新题已知未完成项）/ smoke:all 链贯通 / pytest 20/20 / 断言 131/131 + **金标 diff 7 行用户确认单 ✅**
- [x] Step10 archive（archive.md 落盘 2026-10-13，change 关闭）
