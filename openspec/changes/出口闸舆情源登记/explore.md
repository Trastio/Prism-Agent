# Explore · 出口闸舆情源登记

日期：2026-10-11 · 触发：用户前端问"最近风云T7有什么舆情么"，出现"完成验证器重试"免责文案。

## 事发轨迹（usr_6dwyu5ca / session 01a12b68）

[83] 用户提问 → [84-101] resolve_series(8660) + 4 个 sentiment 工具取数（515帖/负面23/健康分88.2）→ [102-106] submit_conclusion **4 连拒** → [107] 首答交付 → [108] 轮末验证器 fail"漏提交" → [109] 保底回灌 → [110-117] 重试轮改用 review_tags 口碑源过闸 → [118] 二答 + 前端免责框（ChatView.tsx:260）。

## 根因三层（实测确证）

1. **主因·结构性**：`/verify/claim`（prism-api/main.py:772-816）的 supported_by 行 ID 校验只认 `review_tags|mv_reviews_dim` / `sales_trim|mv_sales_monthly` / `config_snapshots|mv_config_spec` 三族，**其余一律"库中无对应数据"**。舆情数据在另一库（prism-sentiment/data/vehicle_sentiment.db），闸完全不知道 → 任何带数字的舆情结论必被拒 → 必触发保底重试。数字本身没问题（数值台账 tool 真值集已采集 sentiment 数值，515/23/88.2 全过）——卡死的是行 ID 溯源。
2. **次因·verifyNames 误报**：`findClosest` 阈值 editDistance<3，"风云"（2字）vs"空间"（2字）d=2 恒命中 → "疑似人工转写错误"。真值集（prism-name-truth）里有"风云T7"但精确匹配不看前缀包含。已知遗留 R1。
3. **表现层**：重试轮免责文案"不是对上一句提问的直接回答"读起来像故障告警。

## 关键代码坐标（全部已读）

- 出口闸工具：`.pi/extensions/prism-guardrails/index.ts:355-467`（submit_conclusion；描述 L359 只教三维度格式；拒绝提示 L462-463 同）
- 行 ID 查库：`prism-api/main.py:772-816`（`/verify/claim`，`_open_live()` 只开 AUTOHOME_DB）
- 名称校验：`src/verify/grounding.ts:112-172` verifyNames + `findClosest`(L142-151, d<3) + `editDistance`
- 名称真值采集：extension L604+ collectNameTruthFromEntries（prism-name-truth entries）
- 舆情工具：extension L177-280 makeSentimentTool（vehicle_name → resolveVehicleId 经 fleet-overview 精确/包含匹配 → UUID）
- 前端免责：`prism-web/src/components/ChatView.tsx:251-260`（isRetry 标签 + retryReason）
- 测试基建：node:test；活服务模式 tests/identity_api.test.ts（服务不可达自动 skip）；smoke:all 5 组（package.json:12）

## 舆情库可校验面（vehicle_sentiment.db，75MB WAL）

- `vehicles(id UUID, name, brand, status)` —— 23 车，name 如"风云T7"
- `raw_posts(id, vehicle_id, platform, ...)` —— 帖行（post uuid 可精确命中）
- `analyzed_posts(id, post_id, vehicle_id, sentiment, dim_sentiment JSON)` —— 维度情感 JSON 含维度名
- `event_groups(id, vehicle_id, event_tag, ...)`

## 约束回顾

- pi.exe(Bun) 进程内禁原生 SQLite → 查库必须走 HTTP（/verify/claim 既有模式）
- 舆情库只读；fail-closed：库不可达时仅 sentiment_* 引用判失败，三维度不受影响
- verifyNames 8 条阶段1测试集（grounding.test.ts）不得回归

## 已排除的替代路径

- 在 sentiment 服务加 /verify 端点：多一跳、多一个服务依赖，prism-api 直读 sentiment DB 与直读 autohome DB 同模式（服务端真值、只读），无新增暴露
- 舆情数字按 web tier 降级：不当——舆情是自有库数据、可复算，红线#1 的"库数据"待遇
