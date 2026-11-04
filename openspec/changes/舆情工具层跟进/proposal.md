# 舆情工具层跟进 · Step2 proposal（2026-10-20，轻量十步）

## WHY
舆情项目三连改后，Prism 工具层留下一处口径失真（paused 车被误报"未收录"，违反红线#1）+ 一处能力缺口（缺陷簇端点 agent 看不见）+ 一处文案缺注（30 天保留线）。harness 主体（护栏/验证/出口闸协议）经核验不受影响，不动。

## WHAT（4 项，全在 Prism 侧）

### T1 paused/inactive 车口径修正（红线#1）
`resolveVehicleId`（index.ts:333）两级解析：
1. fleet-overview（active 名单）精确→模糊，命中返回 `{id, status:'active'}`
2. miss 后 fallback `GET /api/vehicles`（全量名单，含 status）：
   - 命中 active → 正常查（与现状同）
   - 命中 paused → **继续查询**，响应顶层附 `_meta: {vehicle_status:'paused', note:'该车舆情已停更，以下为停更前冻结数据'}`（PM 看到"数据停在何时"而非"没这车"）
   - 命中 inactive → unavailable，文案改"该车已停用，舆情库内无数据"（真实：inactive 车 0 帖）
   - 全 miss → 现状 unavailable 文案不变（真未收录）
- 6 个既有工具共用此解析，全部受益。

### T2 新工具 sentiment_defects（第 7 个舆情工具）
- 端点 `/defect-themes/{vehicle_id}`；**execute 显式传 30 天权威窗**（`today−29 ~ today` isoformat，复用 `evalToday()` 支持 PRISM_FAKE_TODAY）——与 Phase8 采集行同算法，TTL 字符串精确匹配 → 常态零 LLM；不传窗=回退 7 天默认窗+覆盖权威行=互踩复发（explore 已证，禁止）。
- 描述：口径=近 30 天权威窗（缺陷话题簇=中低互动帖聚类，非热度榜）；引用格式 `sentiment_defects:{车系名}`。
- 配套三处白名单/登记：KNOWN_BUSINESS_TOOLS（22→23）、TRUNCATABLE_TOOLS（+1）、submit_conclusion 描述与拒绝提示补 defects 引用示例（index.ts:619/:725）。
- 名称真值采集（isNameSource index.ts:1467 `startsWith('sentiment_')`）自动覆盖，无需动。

### T3 trend 描述口径注记
sentiment_trend 描述补一句："舆情数据保留线约 30 天，days>30 只返回保留线内数据"。

### T4 出口闸源登记
main.py `_SENTIMENT_TABLES`（:1041）加 `'sentiment_defects'`——default 分支 `_sent_vehicle_exists(parts[0])` 已覆盖车名引用校验，一行改动。tests/verify_claim_api.test.ts 补两用例（真车过/假车拒）。

## 验证（Step9）
1. 单测：resolveVehicleId fallback 三分支（active/paused/inactive/未收录）；verify_claim 新表两用例
2. 活端点：sentiment_defects 真调风云T7；Model Y paused 全链路（工具 execute 层手跑）
3. E2E 真对话两问：①"Model Y 舆情怎么样"（期待冻结口径声明，不误报未收录，过闸）②"风云T7 车主都在吐槽什么缺陷"（期待 defects 工具+库引用过闸）
4. 回归：smoke:all 全绿 + tsc 零新增 + trap/guard 既有测试不回归
5. 重启生产网关 9200（**必须带 PRISM_AUTO_APPROVE_UI=1**）；**eval 网关 9201 不重启**（工具面隔离，见 explore 风险2）

## 不做边界
- 不动舆情仓库任何文件（其工作树有用户未提交改动）
- 不接评论极性三端点（comment-sentiment-*，可选跟进另议）
- 不给 defect 工具暴露时间窗参数（固定权威窗，防互踩+防烧钱）
- 不放 eval defect 题（判分不稳定：LLM 重算路径）

## 工期
轻量：4 文件改动（index.ts/main.py/verify_claim_api.test.ts/新测试）+ 验证，半天内。
