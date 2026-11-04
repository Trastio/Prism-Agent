# 人工题集转金标 · Step2 proposal（2026-10-13）

> 目标：38 题人工题集 → 金标准 → eval/tasks.json 转库 → 三分离切分 → 可批跑。
> 前置：search_cars 筛选能力扩展（用户拍板解法1，7 题筛选类题的支撑）。
> 全部事实依据见 explore.md（快照实测，勿重复核）。

## Block 0 · search_cars 筛选扩展（前置，先施工先验收）

**子服务侧（prism-dashboards）**
- 新增 `market_series_filter()`（market_data.py）：基于 sales_trim 聚合出每车系属性行 —— series、latest_retail（沿用 market_series_all 的"自身最新有零售月"口径）、energy（该车系最新月版型行的 energy_type 归一）、level、msrp_min/msrp_max（最新月在售版型）、wheelbase（版型众数）
- 新端点 `GET /dash/market/api/series-filter`（market_routes.py）：查询参数 energy/level/price_min/price_max/wheelbase_min/wheelbase_max/kw/limit，服务端过滤，返回按 latest_retail 降序，附 total_matched/_meta（口径说明）
- **语义映射写死在端点**（agent 只传枚举）：`energy=BEV`→纯电动；`PHEV`→插电式混合+增程式混合；`ICE`→传统能源+油电混合（用户语义锚：第9行期望）；`level=A`→精确 A（A0/A00 不含）
- 既有 series-list/series-all 不动（前端下拉口径不受影响）

**工具侧（extension index.ts）**
- search_cars 参数扩展：keyword + energy + level + price_min/price_max + wheelbase_min/wheelbase_max（可选，全默认不过滤），描述更新为筛选语义；命中超 50 截断提示沿用线B模式
- 描述引导："跨车系筛选（价格/级别/能耗/轴距）用本工具，找具体车系用 resolve_series"

**验收**：单测（值域映射+边界：无结果/单结果/超50截断）+ smoke 回归 + 手动实测三连（12万±1万 BEV / A级 ICE / 轴距 2700±50）+ eval 实例（8100 快照库）同代码验证

## Block 1 · 金标制备（38 题逐题）

- 逐题直查快照库出金标数字 + supported_by 行 ID（格式对齐 submit_conclusion 既有七种引用），全挂 snapshot_id=snap-20261012-1222
- **期望事实断言核验**（explore §7 清单）：E5最高配=TBD核/T7 PTC全系标配/E5全系无PTC/MG4X最低配510半固态自由版/海狮05消歧/零跑A10在库——不符项列 fail-closed 反馈表，报用户改期望或改题，不静默放行
- 3 处过时期望改写（第2/3/10行，按口径A）+ 第19/21行 A 补写（草稿见附录），**一并 diff 交用户过目后**才定稿金标
- 7 题筛选类金标：用 Block 0 新端点的同 SQL 逻辑直查快照，判分容差=金标 top3 含 agent 答案（排序题标准做法）
- 舆情 4 题范式级金标：rubric=声量规模+情感方向+负面主题+来源标注+as_of 声明，不锁数字

## Block 2 · 转库与切分

- tasks.json 追加 38 题：id 段 sales-03..14 / config-03..13 / reviews-03..11 / sentiment-03..08（接既有 18 题，编号从 03 起因 01/02 是模板示例位）
- schema 全字段：question/expected_evidence/as_of（=2026-10-07 快照口径日）/snapshot_id/source='user_20261013'/set/judge_rubric
- **三分离切分建议**（design 定稿）：陷阱+缺口题（~10题）归 frozen（防 dev 过拟合，红线行为题必须长期盯）；正向单对象题（~20题）dev/frozen 对半；开放筛选题（7题）归 dev（依赖 Block 0 新能力，先观察稳定性）；舆情范式题 4 题归 dev
- 陷阱题 judge_rubric 模式复用 trap_check.mjs 既有六类（identity/no_evidence/gap_hard_conclusion/name_grounding/caliber/scope_overreach）

## Block 3 · 判分与 runner 适配

- 新题型 rubric 三类：①排序题（top3 容差）②缺口+web 补充题（verdict=fail 或库声明缺口+web 标不可复算，方向化正则判"是否诚实声明"）③范式级舆情题（要素齐全度）
- truth-expectations.json 扩展：每题至少 1 条机器可断言项（数字精确或区间或行为词）
- EVAL_STATUS.md 更新：题库 18→56、切分明细、待用户拍板残留项

## 十步映射（用户铁律：大 change 严格十步，子代理步骤必须子代理）

- Step1 explore ✅ / Step2 proposal ✅（本文档）
- Step3 design + tasks + self-check（3.5）：待用户确认 §6 两项后落
- **Step5 施工：子代理**（建议两个并行：Block0 代码子代理 + Block1 金标制备子代理；Block2/3 主线串行）
- Step6 simplify / **Step7 code-review：隔离子代理** / Step8 receiving-review / Step9 verification（eval 实例抽查 3-5 题实跑 + smoke 全绿）/ Step10 archive

## 附录 · A 列补写草稿（待用户过目）

- **第21行（保时捷911）**：①库内无此车系配置（resolve_series fail-closed）②如实声明缺口③如需补充只能 web 搜索并标注来源 URL+不可复算（红线#9）
- **第23行（四车配置对比）**：①圈定四车（银河E5/零跑B10/风云T7/MG 4X），各取最高配 ②get_config_detail 分两批（2-6个/批）逐项对比不漏项 ③输出差异表+结论；注意 T7 为 8/26 新上市车系，配置数据完备性需声明
