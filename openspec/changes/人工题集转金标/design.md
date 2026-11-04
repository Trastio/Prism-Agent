# 人工题集转金标 · Step3 design（2026-10-13）

> 依赖：explore.md（事实）+ proposal.md（结构）。用户已拍板：B1 留陷阱、保 38 题。

## Block 0 · search_cars 筛选扩展

### 子服务 prism-dashboards

**`market_data.py` 新函数 `market_series_filter(kw, brand, energy, level, price_min, price_max, wheelbase_min, wheelbase_max, limit=50)`**

> brand 参数为 2026-10-13 拍板B 补入：CAM `sales_trim.brand` 是**子品牌粒度**（风云A9→'风云'/QQ3 EV→'QQ'），集团语义须 OR `manufacturer` 列——过滤=「brand 众数 OR manufacturer 众数，任一去空格 contains」（含合资如 奇瑞捷豹路虎，_meta 注记）。

基础集＝全库车系（同 market_series_all 口径，含无零售车系如风云T7，latest_retail=None）。

每车系两锚分离（关键设计，防 T7 形态丢行）：
- **属性锚月**：该车系自身最新月（按 year + 既有 `_month_key` 排序，'9月末'>'9月中'，无视零售空否）→ 该月行取：energy/level = 非空众数；msrp_min/max = 非空 min/max；wheelbase = 非空众数
- **零售锚月**：自身最新**有零售**月合计（= market_series_all 既有语义，无则 None）

过滤语义（全闭区间，_meta 注明）：
- energy 枚举映射（**写死端点**，agent 只传枚举）：`BEV`={纯电动} / `PHEV`={插电式混合,增程式混合} / `NEV`(电车)={纯电动,插电式混合,增程式混合,燃料电池} / `ICE`(燃油)={传统能源,油电混合}——ICE 语义=用户第9行期望锚
- level：精确匹配（A ≠ A0/A00）
- 价格：车系 [msrp_min, msrp_max] 与查询区间**重叠即命中**（"12万左右±1万"这类容差属题面层，由金标 rubric 定，端点只做通用重叠）
- wheelbase：车系 wheelbase 众数落区间内
- kw：series 名去空格包含匹配（既有惯例）

返回 `{rows:[{series, latest_retail, has_retail, has_weighted, energy, level, msrp_min, msrp_max, wheelbase}], total_matched, total_library, _meta:{source, semantics}}`，latest_retail 降序（None 最后）再按名。

**`market_routes.py`**：`GET /api/series-filter`，参数校验（非法 energy 枚举/非数值 → 400 带提示文案），limit 上限 50，超限截断附 `_truncated` 提示（线B模式）。既有 series-list/series-all **零改动**。

### prism-api

`DASHBOARDS_TOOL_MAP` 加一行：`'series_filter': ('GET', '/dash/market/api/series-filter')`。查询参数自动透传（main.py:768 `dict(request.query_params)` → :786 `params=params`），TTL 缓存键含参数组合（:777）无串味风险。

### extension（.pi/extensions/prism-guardrails/index.ts）

search_cars 参数扩展（全可选）：`energy/level/price_min/price_max/wheelbase_min/wheelbase_max`。**双路径**：任一筛选参数存在 → 调 `${AUTOHOME_BASE}/series_filter`（服务端过滤）；仅 keyword 或无参 → 原 series-list 客户端过滤路径**不动**（既有 agent 行为零回归）。描述更新：跨车系筛选（价格/级别/能耗/轴距+按零售排序）用本工具，找具体车系仍用 resolve_series。

**白名单/截断零改动**：search_cars 已在 ALLOWED_TOOLS；线B 20KB 截断层对 tool_result 自动适用。

### 测试

prism-dashboards 新增 tests（若无目录则建）：in-memory sqlite fixture 造 5 车系——BEV 跨价（msrp 11-15万）、PHEV、ICE 油电混合、无零售有属性（T7 形态）、A0 级（验证 level 精确）；断言：枚举映射、价格重叠（部分重叠命中）、wheelbase 区间、None 零售排序最后、kw 去空格命中、非法枚举 400。

## Block 1 · 金标制备（产出 eval/gold/user-20261013.json）

38 题逐题，每条：`{excel_row, new_id, dimension, 题型[正向|陷阱|缺口|筛选|范式舆情], gold:{numbers, supported_by[]}, expected_evidence, as_of, snapshot_id:'snap-20261012-1222', judge_rubric 草稿, expectation_diffs[], fail_closed[]}`

- 查询规则：销量=月末行 retail（per-series 最新有值月，**月参数形态逐题实测**不假设）；配置=config_snapshots+sales_trim 版型行对齐；口碑=review_tags 聚合（model_full_name LIKE 车系名）；**7 题筛选题=按 design Block0 同一套语义直查**（与端点一致性靠规格钉死，Step9 抽 3 题对活端点核）
- 快照只读（`file:...?mode=ro` URI）
- expectation_diffs：第2/3/10行改写 + 第19/21行补写（proposal 附录草稿为底），**交用户过目后定稿**
- fail_closed：期望断言与库不符清单（explore §7 的核验项），报回不改题
- new_id 段：sales-03..14（12）/ config-03..13（11）/ reviews-03..11（9）/ sentiment-03..08（6）

## Block 2 · 转库与切分

- tasks.json 18→56 题；source='user_20261013'；全字段 schema 对齐既有 18 题；**dimension 映射：金标用英文（sales/config/reviews/sentiment），tasks.json 既有 18 题用中文（销量/配置/口碑/舆情/跨维度/社媒）——转库时统一为中文**
- 切分规则（frozen 目标 ~18-20）：**陷阱5 + 缺口7 → frozen**（红线行为题长期盯）；正向单对象题（~20）按车系聚类对半切（E5 族优先 frozen，保证跨维度长期锚点）；筛选7 + 范式舆情4 + 半支持1（第26行）→ dev（新能力先观察）
- EVAL_STATUS.md：题库 56、切分明细、r3 基线不可直接对比注记

## Block 3 · 判分与 runner

- 排序题 rubric：金标 top3 含 agent 首选（top-3 容差）
- 缺口+web 题：verdict 方向判分（库内声明缺口 + web 数字标不可复算 = 过；编库数字 = 否决）
- 范式舆情题：要素齐全度（声量/情感/负面主题/来源/as_of）
- truth-expectations.json：每题 ≥1 机器断言项
