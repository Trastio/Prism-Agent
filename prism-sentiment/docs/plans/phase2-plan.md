# Phase 2 实施计划：分析能力

基于 OpenSpec tasks.md T2.1-T2.6，拆解为 TDD 原子任务。

---

## T2.1 情感分析 Pipeline + Prompt 工程

### T2.1.1 测试：分析结果解析器
- **文件**: `tests/test_analyzer.py`
- **内容**: 测试 `_parse_response()` 对各种 JSON 格式的解析（正常JSON、带```包裹、非法JSON fallback）
- **TDD**: 先写测试 → 红灯 → 实现 → 绿灯

### T2.1.2 实现：分析 Pipeline 核心
- **文件**: `pipeline/analysis/analyzer.py`
- **内容**:
  - `AnalysisPipeline` 类
  - 事件标签词表（22 个，5 大类 + 1 兜底）
  - 观点标签词表（31 个，4 维度）
  - 三合一 Prompt 模板
  - `_parse_response()` 解析模型输出
  - `_fallback_analysis()` API 不可用时的兜底
  - `analyze_single(text)` 调用 DeepSeek API
  - `analyze_batch(posts)` 批量调用
- **TDD**: 运行 T2.1.1 测试 → 通过

### T2.1.3 测试：批量分析 Runner
- **文件**: `tests/test_batch_runner.py`
- **内容**: 测试批量读取 pending 帖子、分析、写入 analyzed_posts、更新 raw_posts 状态

### T2.1.4 实现：批量分析 Runner
- **文件**: `pipeline/analysis/batch_runner.py`
- **内容**:
  - `BatchAnalysisRunner` 类
  - `run_for_vehicle(vehicle_id)` → 分批读取 → 分析 → 保存 → 标记
  - `run_all_pending()` → 遍历所有有 pending 帖子的车型
- **TDD**: 运行 T2.1.3 测试 → 通过

### T2.1.5 Commit
- `git commit -m "feat: analysis pipeline with TDD tests"`

---

## T2.2 热度指标计算

### T2.2.1 测试：热度指标计算
- **文件**: `tests/test_heat_calculator.py`
- **内容**: 测试 4 层指标计算（注意力指数、讨论声量、媒体声量、互动烈度），测试 upsert 逻辑

### T2.2.2 实现：热度指标计算器
- **文件**: `pipeline/analysis/heat_calculator.py`
- **内容**:
  - `HeatMetricCalculator` 类
  - `calculate_daily(vehicle_id, date)` → 从 raw_posts 计算单日 4 层指标
  - `calculate_range(vehicle_id, start, end)` → 计算日期范围
  - `get_metrics(vehicle_id, start, end)` → 查询已计算指标
  - 指标已存在时 upsert
- **TDD**: 运行 T2.2.1 测试 → 通过

### T2.2.3 Commit
- `git commit -m "feat: heat metric calculator with TDD tests"`

---

## T2.3 异常检测

### T2.3.1 测试：异常检测
- **文件**: `tests/test_anomaly_detector.py`
- **内容**: 测试 ±60% 阈值检测、同日去重、spike/drop 分类

### T2.3.2 实现：异常检测器
- **文件**: `pipeline/analysis/anomaly_detector.py`
- **内容**:
  - `AnomalyDetector` 类
  - `check(vehicle_id, date)` → 对比昨天/今天声量 → 判定异常
  - `check_range(vehicle_id, start, end)` → 批量检测
  - `get_anomalies(vehicle_id, start, end)` → 查询
  - 去重：同一车型同一天只记录一次
  - 记录情感分布变化和 top 帖子
- **TDD**: 运行 T2.3.1 测试 → 通过

### T2.3.3 Commit
- `git commit -m "feat: anomaly detector with TDD tests"`

---

## T2.4 双模型路由器

### T2.4.1 测试：模型路由
- **文件**: `tests/test_model_router.py`
- **内容**: 测试 get_active_model() 在不同环境变量下返回 local/api

### T2.4.2 实现：模型路由器
- **文件**: `pipeline/analysis/model_router.py`
- **内容**:
  - `ModelRouter` 类
  - `check_local_model()` → 检测本地 Qwen3-4B 是否可用
  - `get_active_model()` → 返回当前应使用的模型
  - `get_api_config()` / `get_local_config()` → 返回配置
- **TDD**: 运行 T2.4.1 测试 → 通过

### T2.4.3 Commit
- `git commit -m "feat: model router with TDD tests"`

---

## T2.5 分析 API 路由

### T2.5.1 测试：分析 API
- **文件**: `tests/test_analysis_api.py`
- **内容**: 测试 POST /api/analysis/trigger、GET /api/analysis/heat-metrics 等

### T2.5.2 实现：分析 API
- **文件**: `api/routes/analysis.py`
- **内容**:
  - POST /api/analysis/trigger — 触发分析
  - POST /api/analysis/trigger-all — 全量分析
  - GET /api/analysis/heat-metrics/{id} — 查询热度
  - POST /api/analysis/heat-metrics/{id}/calculate — 计算热度
  - GET /api/analysis/anomalies/{id} — 查询异常
  - POST /api/analysis/anomalies/{id}/check — 检测异常
  - GET /api/analysis/sentiment-summary/{id} — 情感概要
  - GET /api/analysis/top-events/{id} — 事件分布
  - GET /api/analysis/top-opinions/{id} — 观点分布
  - 注册到 `api/main.py`
- **TDD**: 运行 T2.5.1 测试 → 通过

### T2.5.3 Commit
- `git commit -m "feat: analysis API routes with TDD tests"`

---

## 任务依赖图

```
T2.1.1 → T2.1.2 → T2.1.3 → T2.1.4 → T2.1.5
                                        ↘
T2.2.1 → T2.2.2 → T2.2.3                ├→ T2.5.1 → T2.5.2 → T2.5.3
                                        ↗
T2.3.1 → T2.3.2 → T2.3.3
T2.4.1 → T2.4.2 → T2.4.3
```

**Phase 2 预计 16 个原子任务，5 个 commit。**
