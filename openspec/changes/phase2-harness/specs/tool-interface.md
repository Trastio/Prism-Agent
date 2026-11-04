# Spec · 2.2 工具接口层【红线核心】

> 阶段2 · 6 待办（原 5 + 阶段1 复审新增对象身份映射层）
> 依赖：`prompt-context.md`（2.1）
> 解锁：`verification.md`（2.3）

---

## 待办清单

| ID | 待办 | 优先级 | 依赖 |
|---|---|---|---|
| 2.2.0 | 对象身份映射层 + 覆盖率守卫（新增） | P0 | — |
| 2.2.1 | 数据源注册表 | P0 | — |
| 2.2.2 | 口径视图 v1（物化视图 + 运行时聚合） | P0 | 2.2.1 |
| 2.2.3 | 3 核心语义工具 query_sales/reviews/config | P0 | 2.2.0, 2.2.2 |
| 2.2.4 | tool_call 护栏（cc-safety-net + 自建红线拦截） | P0 | — |
| 2.2.5 | tool_result grounding（数值 + 名称维度） | P0 | 2.2.3 |

---

## 2.2.0 对象身份映射层 + 覆盖率守卫

### 设计
`resolve_series(user_input: string) → IdentityResult`
```typescript
type IdentityResult = {
  series_key: string;              // 库内唯一键，如 '铂智7'（用于 sales_trim.series）
  series_id: string;               // model_id，如 '7650'（用于 config_snapshots.series_id / owner_reviews.model_id）
  canonical_name: string;          // 官方备案名
  aliases: string[];               // 市场名/别名 ['铂智7X']
  source: 'alias_table' | 'online_verify';
  coverage: {
    sales_trim: { hit: boolean, rows?: number, as_of?: string };
    owner_reviews: { hit: boolean, count?: number };
    config_snapshots: { hit: boolean, version?: number };
    series_summaries: { hit: boolean };
  };
  needs_online_verify: boolean;    // alias 未命中 OR 命中但数据表无行 OR 覆盖不全 → true
  ambiguous: boolean;              // 歧义词命中多个候选时 true
  candidates?: string[];           // 歧义时的候选列表
  warnings: string[];              // 缺数据维度声明
}
```

### 流程
1. 库内查 `series_alias`（series_key / source / raw_name）
2. **多命中（歧义）** → `ambiguous=true` + `candidates=[...]`，agent 调 **rpiv-ask-user-question 插件**让用户澄清
3. **alias 命中但数据表无行**（如铂智7X 在 alias 表有、weighted 表 0 行）= **覆盖率缺失** → `needs_online_verify=true`，agent 调 web-access skill 核验同车两名关系，核验通过后用真实 series_key 重查
4. **alias 完全未命中** → `needs_online_verify=true`，联网核验是否存在该车；不存在 → fail-closed
5. 覆盖率守卫：检查 series_key 在 4 个数据源的覆盖情况，缺数据维度进 `warnings`，agent 必须在报告声明
6. **series_id 解析**：alias 表若不含 series_id，从 series_summaries 或 sales_trim 反查 model_id；都查不到时 config_snapshots 用 series_name 模糊匹配 + 人工确认

### 验收
- "铂智7X" → series_key='铂智7', series_id 查 series_summaries 不收录→needs_online_verify=true，联网核验同车两名
- "银河E5" → series_key='银河E5', series_id='7650', coverage 全 true
- "不存在的车" → fail-closed
- "7X"（歧义）→ ambiguous=true, candidates=[铂智7X, 乐道L7X, 一汽奥迪 E7X, ...]，触发 rpiv-ask-user-question

---

## 2.2.1 数据源注册表

### 设计
`src/registry/datasource.ts`，注册 Atuohome SQLite + 舆情 REST + RAG（预留第四口）：
```typescript
{ name, type: 'sqlite'|'http', connection, as_of, coverage_guard, health_check }
```
- Atuohome: `C:\...\autohome.db`（只读直连 immutable=1）
- 舆情: `127.0.0.1:8000`（21 dashboard GET 分 6 工具组）
- RAG: 预留

### 验收
- 启动时健康检查全 pass
- 任一数据源 down → 降级声明，不 crash

---

## 2.2.2 口径视图 v1

### 设计（决策①：物化视图 + 运行时聚合 混合）

**物化视图表**（Prism 侧 `prism_views.db`，与生产库隔离）：
- `mv_sales_monthly`：`series × year × month × retail_sum × tp_avg`（只取月末行预聚合）
- `mv_reviews_dim`：`model_id × tag_category × sentiment × count × coverage_rate`
- `mv_config_spec`：`series_id × spec_id × 年款 × key_config_items`（展平嵌套 dict）
- 每表配 `_meta`：`as_of / 数据源 / 覆盖率 / 口径说明`

**运行时聚合**（TS 工具内）：跨时段对比、版型筛选、竞品池动态构造 → 走 `sales_trim` 直查，强制 `month LIKE '%月末'` + `year+month` 分组。

### 刷新机制（Gap 6 补）
- **开发期**：手动触发 `npm run refresh-views`（命令读 autohome.db 重算三表 + 更新 _meta.as_of）
- **上线期**：轮询 `autohome.db` 的 `config_snapshots.fetched_at` / `sales_trim` 最新行 mtime，变化时触发刷新；兜底每日 cron 一次
- 不依赖 Atuohome 主动通知（黑盒供给端，不进其内部）

### 口径坑 10 条内化
（见 design.md §1.4，全部写进视图层 SQL 与 _meta 声明）

### 验收
- 物化视图三表可通过 `refresh-views` 刷新，_meta.as_of 更新
- 报告 v0.3 的 E5 真实序列通过 `mv_sales_monthly` 复现（3028/1823/6508/5950/5203/7218/5162/4436）
- 查询返回结果必带 _meta（as_of + 覆盖率 + 口径）

---

## 2.2.3 3 核心语义工具

### query_sales
```typescript
pi.registerTool({
  name: 'query_sales',
  description: '查询车系销量/终端价。expected: retail 来自月末行(非月中价格快照); 必须按 year+month 分组; 返回带 as_of+覆盖率; 名称字段从库源直取禁止改写',
  parameters: Type.Object({
    series_key: Type.String(),
    year: Type.Optional(Type.Number()),
    month: Type.Optional(Type.String()),
    group_by: Type.Optional(Type.Union([Type.Literal('month'), Type.Literal('spec')])),
    metric: Type.Optional(Type.Union([Type.Literal('retail'), Type.Literal('tp')]))
  }),
  execute: async (id, params, signal, onUpdate, ctx) => {
    const identity = await resolve_series(params.series_key);  // 前置身份映射
    // identity.series_key 用于 sales_trim；identity.series_id 用于 config/owner_reviews
    // 走 mv_sales_monthly 或运行时聚合
    // ctx.sessionId / ctx.userId 用于多租户隔离（L3 工具侧 per-user 白名单）
    // 返回 { rows, _meta: {as_of, coverage, 口径} }
  }
});
```

### query_reviews
- 输入 series_key（→ resolve_series 得 model_id）, tag_category?, sentiment?, with_samples?
- 走 mv_reviews_dim + owner_reviews（原文样本时查 source_text）
- 返回维度聚合 + 可选原文 + _meta（含打标覆盖率）

### query_config
- 输入 series_key（→ resolve_series 得 series_id）, spec_id?, 年款?, key_items?
- 走 mv_config_spec（展平嵌套 dict）
- 返回配置项 + 年款标注 + _meta

### ctx 用法（Gap 7 补）
所有 query_* 工具的 ctx 字段：
- `ctx.sessionId`：会话隔离（L2 pi SessionManager per-user）
- `ctx.userId`：用户级工具白名单（L3 工具侧，普通用户锁只读、管理者解锁采集触发）
- `ctx.callStack`：工具调用计数（状态栏 hook 用，≥3 同维度告警）

### discover_tools 按需包
能耗/评分/事件/缺陷 + 6 sentiment_*（舆情外挂第四组），棱镜三维度查完后解锁。

### 验收
- 3 工具可被 agent 调用
- 返回结果必带 _meta
- 名称字段精确来自 DB（测试：调用 query_sales('银河E5') 返回 model_name 含"探索版"非"探索型"）
- ctx.userId 可用于 per-user 白名单切换

---

## 2.2.4 tool_call 护栏

### 设计
- **cc-safety-net@2.4.15**（全局已装）：GitHub 读写拦截
- **自建红线拦截**（pi.on('tool_call')）：返回 `{block:true, reason, terminate}` 拦截
  - 禁裸 SQL（参数化语义工具）
  - 禁触发表写（仅 query_*，无 mutate_*）
  - 禁越权（管理者操作需密码弹窗确认）
- fail-closed：工具抛错 = 拦截

### 验收
- 裸 SQL 调用被拦
- 写操作被拦
- 护栏失效时 fail-closed（不静默放行）

---

## 2.2.5 tool_result grounding（数值 + 名称维度）

### 设计（教材 §3.1 chapter1/grounding.py 照抄 + 名称扩展）

**数值维度**（销量/配置）：
- `QUANTITY_FLOOR=1000`，`_SCALES` 加"万/亿"
- 工具返回数值与模型回复数值做容差比对，超阈值 fail-closed

**名称维度（新增，修阶段1 复审 8 个名称错误）**：
- 工具返回的 `series / brand / model_name / tag_category / manufacturer` 字段进真值集
- 模型最终回复里的车系/版型/品牌/维度名/厂商做精确匹配
- 不一致 → fail-closed

**名称 grounding 测试集（8 条，明确清单）**：
| # | 错误名（模型输出） | 库源真值 | 来源 |
|---|---|---|---|
| 1 | 26款 530Km 探索型 | 26款 530Km 探索版 | 报告① |
| 2 | 530km 启航型 | 530km 公务版 | 报告① |
| 3 | 全域精灵版 | 全球精灵版 | 报告① |
| 4 | 铂智7 是 SUV | 三厢轿车 | 报告③ |
| 5 | 星纪元 ET 08 EV | 比亚迪 海豹08 EV | 报告③ |
| 6 | 蔚来 Z9 GT | 腾势 Z9 GT | 报告③ |
| 7 | 智驾版 | 激光雷达版 | 报告③ |
| 8 | 一汽丰田 GAC | 广汽丰田 | 报告③ |

### 实现
`src/verify/grounding.ts`，接 `pi.on('tool_result')` 改写 + `agent_settled` 终验。

### 验收
- 8 条名称错误样本 100% 被拦截
- 数值容差比对通过
