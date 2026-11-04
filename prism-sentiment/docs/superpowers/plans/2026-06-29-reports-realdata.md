# 主题 C：reports 真实数据 + LLM 配置统一 Implementation Plan

> **For agentic workers:** superpowers:executing-plans.

**Goal:** deep-report 接 DB 真实数据；抽共享 `utils/llm_client.py`（双 provider + retry）；删除失效 brief。

**Spec:** `docs/superpowers/specs/2026-06-29-reports-realdata-design.md`

**侦察结论（指导实现）：**
- deep-report（前端 createReport 真用）硬编码空数据 → 报告无支撑，**核心 bug**
- brief（前端无入口）+ anomaly 数据源已删 → **死代码，删除**
- dashboard-summary/weekly-digest 已正确，不动
- analyzer 有双 provider 路由（104-122）但私有；全栈 6 处 `_call_llm` 散落 → 抽共享 helper，本主题仅 reports 接入（其余后续）

**决策：brief 删除**（用户授权自主 + 推荐删）。

## Tasks

1. **`utils/llm_client.py` 共享层**（新）+ `tests/test_llm_client.py`
   - `call_llm(prompt, timeout)`: 双 provider 路由（glm 优先 → deepseek）+ tenacity retry + httpx；无配置返友好错误串（不 raise）
   - 复用 analyzer 104-122 的路由逻辑
   - 测：`_select_provider` 三分支（glm/deepseek/none）+ call_llm 无配置 + mock httpx 成功

2. **`api/routes/reports.py` 改造**
   - `_call_llm` 改为 `utils.llm_client.call_llm` 的薄包装（保留名，兼容 test patch 路径）
   - `create_deep_report` + `generate_deep_report_content`：接 DB 取 sentiment/event/dim（复用 `_compute_dim_sentiment` + dashboard_summary 查询模式）；移除 anomaly_data
   - 删 `create_brief`/`BriefRequest`/`generate_brief_content`

3. **测试更新**
   - `test_report_api.py`：deep-report 用 DB fixture 断言 prompt 含真实 sentiment/事件；删 brief 用例
   - `test_e2e.py`：删 brief 用例
   - 新增 `test_llm_client.py`

## 完成标准
- [ ] deep-report 传给 LLM 的 prompt 含真实 sentiment 计数 + 事件名
- [ ] brief 端点及测试删除
- [ ] utils/llm_client 双 provider 路由 + retry
- [ ] pytest test_llm_client + test_report_api + test_e2e 全绿

## 流程纪律（吸取 A/B 教训）
实现后**必做** `/simplify` + `/code-review`，不再跳。
