# 人工题集转金标 · Step10 archive（2026-10-13 归档）

> 十步全走完：explore→proposal→design+tasks→self-check（3.5）→Step5 施工（双子代理并行）→Step6（并入审查处置）→Step7 隔离审查→Step8 修→Step9 验证→Step10 归档。
> 金标 diff 7 行 + fail_closed 5 条经用户 2026-10-13 逐项确认定稿。

## 交付物

**代码（Block 0，block0-coder 子代理，三轮）**
- `prism-dashboards/src/api/market_data.py`：market_series_filter（两锚分离/ENERGY_ENUMS/价格重叠/brand=子品牌 OR 集团 manufacturer 拍板B/limit 钳位）
- `prism-dashboards/src/api/market_routes.py`：GET /api/series-filter（400 校验/limit [1,50]/_truncated）
- `prism-api/main.py:885`：TOOL_MAP series_filter 行
- `.pi/extensions/prism-guardrails/index.ts`：search_cars 双路径参数扩展（brand/energy/level/price/wheelbase）
- `prism-dashboards/tests/test_market_series_filter.py`：20 测试（含跨年锚月/平票升序回归保护）

**金标（Block 1，block1-gold 子代理 + 主会话两轮拍板改写）**
- `eval/gold/user-20261013.json`（38 题终态）+ 报告.md（38 条可复算 SQL/diff 表/裁决记录）
- `_gen_user_gold.py`（**裁决覆盖层**，重跑幂等）+ `_verify_user_gold.py`（131 断言）

**转库（Block 2/3，主线）**
- `eval/tasks.json` 20→**58**（新 38：frozen 19 = 陷阱4+缺口7+E5族正向8；dev 19 = 筛选8+范式舆情5+正向6）
- `eval/EVAL_STATUS.md` 题库状态节 + `truth-expectations.json` 锚点键（smoke 级；全量断言在 _verify）

## 关键裁决记录（防重复推导）

1. **跨年聚合误读纠错**：初版"9月末批已导入/部分覆盖862车系"系漏 year 维度（'9月末'有值全在 2025）；真值=2026-9月末零售全空，最新有值月 2026-8月末（E5 4,436/B10 6,790/MG4X 3,427/A10 25,084）。用户原期望"最新8月"本来就对。**sales_trim 聚合必须带 year**。
2. **PTC 两题**：库内无 PTC 字段（两车零命中）；用户裁决保留原题→混合语义（库声明缺口→红线#9 web 佐证方向 T7有/E5无→URL+不可复算；web 无果"无法核验"亦合格；eval 期 web 不可用不计分母）。
3. **brand 拍板B**：CAM brand 列=子品牌粒度，"奇瑞"类问题是集团语义→brand=子品牌 OR manufacturer contains；BEV（用户"纯电车"）top3=QQ3 EV 12,129/风云A9 5,796/iCAR V23 2,479。
4. **零跑B1 留陷阱**（fail-closed 拒绝脑补对齐 B10/B01）；**保 38 题**不删。
5. 零跑A10 在库但四维仅销量→Excel 24 转缺口题；风云A9/A9L 双车系=天然身份核验考点。

## Step9 验证（全绿）

- 活端点（8002→8010）：BEV/NEV 两连与金标分毫不差；T7 两锚分离生效；400 在位
- eval 快照实例（8003）：同代码自动生效，21/1472 精确命中（G9 坐实）
- **真实 agent E2E**（奇瑞原题打活网关）：31s verdict=pass 出口闸；首选 QQ3 EV 12,129（硬锚）+双口径声明齐全
- 回归：trap-01..06 全 5 分（extension 零回归；trap-07/08 0 分=并行会话新题已知未完成项，非本 change）；smoke:all 链式贯通；pytest 20/20；断言 131/131（生成器重跑后复验）

## 留下一轮（记录不阻塞）

- 排序 top3 容差/缺口 web 方向正则/舆情范式的机器判分接入 → **P1（scorer 抽取）**，verdict 判分已可用
- P2-3 剩余断言（筛选输入属性完备性/站方口径）随 P2 首跑并入 truth-expectations
- market_series_filter 与 market_series_all 去重抽函数；nan/inf 收紧；缓存键 quote；query_sales month 参数描述债（端点静默忽略）
- 58 题首跑 v1 基线（批跑纪律：冻结服务/单进程）；既有 20 题 frozen 化随基线定
- 筛选题 Step9 抽核清单已列 sales-08/10（审查者同算法代查吻合可对照）
