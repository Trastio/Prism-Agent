# 人工题集转金标 · Step1 explore（2026-10-13）

> 起因：用户交付人工题集 `业务数据/人工题集.xlsx`（34题规格，实交38题）。审查+核库完成，用户拍板按推荐方案执行：**扩 search_cars 筛选能力作为前置，并入本 change 十步走**。
> 本文全部数字为快照 snap-20261012-1222 实测（sha256 见 manifest），防重复推导。

## 1. 题集盘点（Sheet1，38 行 = 表头 1 + 数据 38；Excel 行号 = df 行号 + 2）

| 维度 | 规格 | 实交 | Excel 行 |
|---|---|---|---|
| 销量 | 10 | 12 | 2-13 |
| 配置 | 8 | 11 | 14-24 |
| 口碑 | 10 | 9 | 25-33 |
| 舆情 | 6 | 6 | 34-39 |

- 配比：正向 ~28 / 陷阱 ~5（13%，规格25%）/ 缺口 ~5；"每维至少一道陷阱或缺口"满足（销量:10-12行 / 配置:21行 / 口碑:29行 / 舆情:39行）
- 题集硬伤：**第23行 A 列空**（四车配置对比）；**第21行 A 截断**（保时捷911"①没有这个车的配置，只能通过"）

## 2. 核库硬事实（快照 snap-20261012-1222 直查）

### 销量口径（⚠️ 2026-10-13 更正：初版此处跨年聚合误读，Block1 子代理发现+主会话复验坐实）
- 全库月份范围 2025年1月末→2026年9月末（market_source.json），但 **2026年9月末零售全空**（月末批零售滞后，与 CAM SOP 记忆一致，初版"9月末批剧变/部分覆盖"结论作废）；month='9月末' 有零售值的 862 车系全部是 **year=2025 历史数据**
- **零售口径最新有值月=2026年8月末**：E5 4,436 / 零跑 B10 6,790 / MG 4X 3,427 / 零跑 A10 25,084（2026 单年值；初版"E5 9月末10,377/8月末15,210"系 2025+2026 混合，作废）
- **查询纪律：sales_trim 聚合必须带 year 维度**（同名字月跨年并存：8月末 2025 有 841 车系 188万、2026 有 1140 车系 151万）
- **风云T7 库内零售全空**（结论不变）：仅 9月中/9月末行且 retail 全 NULL，8月末无行；launch_date 2026/08/26
- 用户原期望"最新8月数据"本来就对，第2行无需按"过时"改写（仅补"2027款无销量行，占比取在售版型"事实）

### 车名在库情况（autohome.db series_summaries / 舆情库 vehicles）
- 在库：银河E5(7650)、零跑B10(7877)、零跑A10(8433)、零跑B01(8006)、风云T7(8660)、风云A9(7853)+**风云A9L(7225) 双车系并存**、MG 4X(8564)、海狮05 EV(7982)、海狮06(8087)、星愿(7806)、QQ3 EV(8499)
- **不在库：零跑B1（B10/B01 并存，天然红线#7 考点）、风云T1000、腾势N9、保时捷911**
- sales_trim 车系串形态：'零跑 B10'（带空格）、'比亚迪 海狮05 EV'/'比亚迪 海狮06 EV'/'比亚迪 海狮06 DM-i'（带品牌+纯电/DM-i 拆串）——与 series_summaries 名不一致，keyword 匹配须去空格（既有惯例）
- 海狮05：series_summaries 只有'海狮05 EV'（口碑 634），sales 有 EV+DM-i 两串 → 第25行"海狮05 2026款口碑"需消歧 EV/DM-i

### 口碑/舆情覆盖量（判分样本守卫依据）
- 口碑 review_count：星愿 2380 > 银河E5 1261 > 零跑B10 1020 > 零跑B01 949 > 海狮05 EV 634 > 海狮06 543 > MG 4X 255 > 零跑A10 187 > **风云T7 40（薄样本）**；QQ3 EV 无口碑（0）
- 舆情帖量（analyzed_posts）：星愿 1263 > 风云A9 718 > 风云T7 630 > 海狮06 554 > 银河E5 604 > QQ3 398；**更正：舆情库含 MG4X（车名无空格 'MG4X'，298 原帖，初版按 'MG 4X' 查漏报无）**；舆情库无：海狮05/腾势N9/保时捷911/风云T1000
- 零跑A10：series_summaries.review_count=187 系摘要层缓存值，**review_tags 实际 0 行、config_snapshots 无行（四维仅销量有数）**→ Excel 24 实为缺口题
- 舆情快照 as_of：2026-10-07 16:48（raw_posts 最新）

## 3. 工具能力审计（读 .pi/extensions/prism-guardrails/index.ts 注册代码，非文档）

- **query_sales**(series_key, year?, group_by=month|spec, month?) ✓ / **query_reviews**(series_key, tag_category?) ✓ / **query_config**(series_key) ✓
- **sentiment_*×6**(vehicle_name) ✓（resolveVehicleId 精确+模糊；未收录返回 unavailable 语义）
- **search_cars**：**仅 keyword 车系名包含匹配（去空格）**，客户端过滤，返回 series/latest_retail/has_retail/has_weighted，cap 50（index.ts:338-374，线B重写时明确删除 brand/price 参数因端点无字段）
- dashboards 其余 9 工具（get_trims/get_config_detail(sel 2-6)/get_similar_models/get_review_analysis/search_reviews/get_dimension_reviews/get_model_detail/get_sales_detail/score_models）✓
- **7 题不支持**（跨车系筛选/横评类）：第7行(轴距2700最好BEV)、第8行(奇瑞最好电车)、第9行(A级最好燃油)、第18行(12万BEV配置最好)、第22行(15万以下续航600+配置推荐)、第32行(10万电车口碑最好)、第33行(轴距2700燃油口碑最好)
- 半支持 1 题：第26行"海狮06哪个**版本**口碑最好"——工具均为车系级聚合，版型级仅 search_reviews(kw=版型名) 近似

### 筛选数据源实况（prism-dashboards/src/api/market_data.py）
- `market_series_list()`（:103）＝最新有零售月车系+零售合计，按零售降序；`market_series_all()`（:139）＝全库车系+自身最新有零售月——**两者均无 energy/level/price/wheelbase 字段**
- sales_trim 可筛选列（值域实测）：energy_type{传统能源 94,644 / 纯电动 56,850 / 插电式混合 29,821 / 油电混合 10,718 / 增程式混合 9,967 / 燃料电池 114}；fuel{汽油/柴油/…}；level{A 71,787 / B 63,769 / C 43,238 / A0 9,570 / D 8,627 / A00 4,727 / Light Bus 210 / Mini Bus 168 / E 18}；msrp 数值元（如 112800.0）；wheelbase_mm 整数（如 2750）
- 用户语义锚：第9行期望"燃油=传统能源+油电混合"；第19行期望"区分海狮06纯电和DMI"

## 4. 评估基建现状（转库落点）

- **eval/tasks.json：18 题唯一机器源**（cross-01..10 + trap-01..06 + social-01..02），全 dev set；schema：id/dimension/question/expected_evidence/as_of/source/snapshot_id/set/judge_rubric
- 既有 id 段：cross-/trap-/social-；人工题应接 sales-/config-/reviews-/sentiment- 段（user-tasks-template.md 既有命名）
- truth-expectations.json 外置断言；snapshot.py create/list 可用；prism.py eval 四实例（8100/8110/8003/9201，子项目零改动——**改 market_data.py 一处，eval 实例同代码跑快照库，自动生效**）
- 评估方案 v3.4.3：三分离 dev/frozen/blind；参数化10题归 frozen（frozen=20）；判分器单测进 smoke

## 5. 用户拍板记录（2026-10-13 本会话）

1. **解法1 采纳**：扩 search_cars 筛选参数（price_min/max、energy、level、wheelbase_min/max + latest_retail 排序），并入本 change 前置
2. **口径A**：销量"最新月"= 每车系最新有值月（当前全库即 2026-8月末；E5 4,436），as_of 如实声明
3. **过时期望 3 处授权我改写**（第2/3/10行），交付时列 diff 用户过目
4. **舆情范式级金标**：判分点=声量/情感分布/负面主题/来源标注，不锁具体数字（快照 as_of 10-07）

## 6. 待用户确认（不阻塞 Block 0 施工，阻塞 Block 1/2）

- **零跑B1（第28行）**：推荐保留为陷阱题（fail-closed：指出库内无 B1、最接近 B10/B01，拒绝脑补对齐）——补足陷阱配比 13%→~16%；若是笔误改 B01 则失一题红线考点
- **题量**：推荐保 38（口碑 9 差 1 题不强制补，dev/frozen 切分时自然处理）
- **第19/21行 A 列补写草稿**（我起草，见 proposal 附录）

## 7. 风险与注意

- **月参数形态**：sales_trim.month='9月末'/'9月中'（字符串）；Block1 实测 /dashboard/sales 两分支均**静默忽略 month 查询参数**（工具描述债已记录）；金标判分锚=2026-8月末且不得把 9月末 NULL 行当销量
- **金标 as_of 锚**：全部挂 snap-20261012-1222（snapshot_id 字段），金标数字与快照哈希绑定，活库后续更新不漂移
- **月口径纪律**：金标锚 2026-8月末（逐车系最新有值月），不得把 2026-9月末 NULL 行当销量，不得跨年混合聚合（初版教训）
- 第2行期望断言"E5最高配=2027款 635 智充激光版"、"T7全系标配PTC"、"E5全系无PTC"、"MG4X最低配=2026款 510半固态自由版"均待金标制备时核库，不符则 fail-closed 报回用户（改期望或改题）
