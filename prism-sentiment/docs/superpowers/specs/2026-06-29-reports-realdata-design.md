# 主题 C：reports 真实数据 + LLM 配置统一 — 设计文档

> 日期：2026-06-29
> 治根主题 C（共 7 主题）：deep-report 接真实数据源 + reports LLM 双 provider + 清理失效 brief

## 1. 背景与根因

reports.py 内部实现**不一致**——同为报告端点，数据来源却分两派：

| 端点 | 前端调用 | 数据来源 | 状态 |
|------|---------|---------|------|
| `/dashboard-summary` | ✅ generateReport | 从 DB 取（sentiment/event/dim/post）| ✓ 正确 |
| `/weekly-digest` | ✅ createReport | 从 DB 取（sentiment/event/top_posts）| ✓ 正确 |
| `/deep-report` | ✅ createReport | **硬编码 `sentiment_data={}, event_data=[], anomaly_data=[]`**（266）| ✗ 占位 |
| `/brief` | ❌ 前端不用 | **硬编码 `volume_change=1.5, top_posts=[]`**（233）| ✗ 占位+失效 |

**deep-report 是用户可见 bug**：前端 `createReport('deep_report')` 实际调用，但 `generate_deep_report_content` 收到空数据 → 生成的深度报告**无任何真实数据支撑**（情感分布全 0、无事件）。

**brief 是失效死代码**：数据源 `anomaly`（AnomalyEvent）已在 2026-06 分析重设计删除（记忆 [[analysis-redesign-2026-06-17]]），`volume_change=1.5` 是无源之水；前端无调用入口（仅 `test_report_api`/`test_e2e` 用）。

**LLM 配置层**：`reports._call_llm`（43-63）硬编码 `model="glm-4-flash"` + 只读 `config["glm"]`，不支持 deepseek。而 `analyzer.AnalysisPipeline`（104-122）已实现双 provider 路由（glm 优先 → deepseek 备选）+ retry。全栈 LLM 调用散落 6 处（reports/keyword_expander/relevance_filter/event_tracker/batch_runner/analyzer），各自 `load_api_config + httpx.post`，细节各异，**无共享 client**。

**共同根因**：
- deep-report/brief 没接 DB 数据源（不像 weekly-digest/dashboard-summary 那样查询）
- reports LLM 配置硬编码，没复用 analyzer 的双 provider 逻辑
- 全栈无共享 LLM 调用层 → 每处各写各的，provider/retry/错误处理不一致

## 2. 目标

1. **deep-report 接真实数据**：sentiment 分布、事件、维度从 DB 取（参考 dashboard_summary 已有查询）。
2. **brief 清理**：删除失效端点（anomaly 数据源已删 + 前端不用）—— *产品决策项，见 §5*。
3. **reports LLM 双 provider**：支持 glm 优先 + deepseek 备选，复用共享逻辑。
4. **抽共享 LLM helper** `utils/llm_client.py`：双 provider 路由 + httpx + retry；reports 复用（其他模块的 _call_llm 统一留作后续主题，避免范围爆炸）。
5. **治根判据**：deep-report 内容有真实数据支撑；新增/切换 LLM provider 只改共享 helper 一处。

## 3. 设计

### 3.1 `utils/llm_client.py` — 共享 LLM 调用

置信度：高（复用 analyzer 104-122 已验证的路由逻辑）。

```python
async def call_llm(prompt: str, timeout: int = 60) -> str:
    """双 provider 路由（glm 优先 → deepseek 备选）+ httpx + retry。
    无配置返回友好错误串（不 raise，匹配 reports 现有契约）。"""
    config = load_api_config()
    glm_cfg, ds_cfg = config.get("glm", {}), config.get("deepseek", {})
    if glm_cfg.get("api_key"):
        api_key, base = glm_cfg["api_key"], glm_cfg.get("base_url", "...paas/v4")
        model = glm_cfg.get("model", "glm-4-flash")
    elif ds_cfg.get("api_key"):
        api_key, api_url = ds_cfg["api_key"], ds_cfg.get("api_url", "...deepseek.com/v1/chat/completions")
        model = ds_cfg.get("model", "deepseek-chat")
    else:
        return "API 未配置..."
    # httpx.post + retry（参考 analyzer._call_api 的 @retry）
```

### 3.2 reports._call_llm 改用共享

置信度：高。

- 删 reports.py 自己的 httpx 实现（43-63），改为 `from utils.llm_client import call_llm`
- 保留 `reports._call_llm` 名作薄包装（`return await call_llm(prompt, timeout)`），使 `test_report_api` 的 `patch("api.routes.reports._call_llm")` 继续生效，测试无需改路径

### 3.3 deep-report 接真实数据

置信度：高（直接复用 dashboard_summary 333-367 的查询模式）。

`create_deep_report` 改为查询 DB 填充，删硬编码 `{}`/`[]`：
- `sentiment_data`：`AnalyzedPost` 按 sentiment group_by count（SELF_ONLY + 时间窗）
- `event_data`：`EventGroup` 按 post_count desc top N
- 维度：复用 `_compute_dim_sentiment`（reports.py 已有，184-219）
- `anomaly_data`：anomaly 已删，**移除该参数**及 prompt 中"异常事件数"段

`generate_deep_report_content` 签名相应调整（去 anomaly_data，sentiment/event/dim 从调用方传入）。

### 3.4 brief 删除（决策项 §5）

若确认删除：
- 删 `create_brief`/`BriefRequest`/`generate_brief_content`（66-81, 222-252）
- 删 `test_report_api` 的 brief 测试 + `test_e2e` brief 用例
- 理由：anomaly 数据源已删，语义失效，前端无入口

## 4. 改造范围

| 文件 | 改动 |
|------|------|
| `utils/llm_client.py`（新） | 共享 call_llm（双 provider + retry） |
| `utils/test_llm_client.py`（新） | provider 路由 + 无配置 + mock 调用测试 |
| `api/routes/reports.py` | _call_llm 改共享；deep-report 接 DB 数据；删 brief（若确认） |
| `tests/test_report_api.py` | deep-report 验证 prompt 含真实数据；删 brief 测试（若确认） |
| `tests/test_e2e.py` | 删 brief 用例（若确认） |

## 5. 决策项（需用户确认 — 产品范畴）

**brief 删除 vs 基于 EventGroup 重写**：
- **推荐删除**：anomaly 数据源已删、前端不用、是死代码。删除=治根（消除失效代码）。
- 备选重写：若产品想保留"事件简报"功能，改为基于 EventGroup（取最大事件 + 其热帖）。但前端无入口，需同时加前端入口（扩范围）。
- *这是产品决策（保留与否），非纯技术，故列出请你定。*

## 6. 验证

pytest（mock LLM）：
1. `test_llm_client`：glm 配置→走 glm；仅 deepseek→走 deepseek；都无→错误串；mock httpx 验证请求
2. `deep-report`：传入含数据的 DB fixture → 断言传给 LLM 的 prompt 含真实 sentiment 计数 + 事件名（mock call_llm 捕获 prompt）
3. 现有 weekly-digest/dashboard-summary 测试不受影响

## 7. 涉及文件

- 新增：`utils/llm_client.py`、`tests/test_llm_client.py`
- 修改：`api/routes/reports.py`、`tests/test_report_api.py`、（`tests/test_e2e.py`）

## 8. 非目标（YAGNI）

- **不统一全栈 6 处 _call_llm**（analyzer/keyword_expander/relevance_filter/event_tracker/batch_runner）——范围爆炸，留作独立后续主题；本主题只建共享 helper + reports 接入
- 不改前端报告调用（createReport/generateReport 不变）
- 不改 weekly-digest/dashboard-summary（已正确）
- 不做 LLM 流式/SSE（当前同步够用）
