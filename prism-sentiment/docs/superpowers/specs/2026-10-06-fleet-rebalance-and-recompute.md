# 车队调整 + HeatMetric 重算 — 设计文档（superpowers 简化版）

> 日期：2026-10-06
> 状态：执行中
> 流程：superpowers 简化版（用户显式豁免 10 步流程）

## 背景

1. v1+v2 清理脚本盲区：只改 `raw_posts.analysis_status='irrelevant'`，没级联重算预计算表（HeatMetric 1708 行 + defect_themes 14 行 + AnalyzedPost 473 行冗余）。前端实时数据正确，但热度类指标基于旧数据。
2. 用户要求删 4 车（零跑A10、元PLUS、元UP、华境s）从车队总览，加 2 车（QQ3、风云A9L）采集。

## 任务

### 任务 B：删 4 车
- 4 车都 0 帖，设 `status='inactive'`（软删可恢复，比物理删安全）
- 华境s 是 brand 空的占位车也一并 inactive
- 车队总览 `Vehicle.status == "active"` 过滤自动排除

### 任务 C：加 2 车
- QQ3（奇瑞）：INSERT + search_keywords `["QQ3","奇瑞QQ3","Chery QQ3"]`
- 风云A9L（奇瑞）：INSERT + search_keywords `["风云A9L","奇瑞风云A9L","风云 A9L"]`
- 后续触发 daily_update 采集

### 任务 A：HeatMetric 重算
- 删 23 车 HeatMetric 1708 行（created_at=2026-10-04 早于 10-06 清理，基于含混入帖旧数据）
- 跑 `calculate_range` 重算（RELEVANT_ONLY 口径自动排除 irrelevant）
- 删 defect_themes 14 行（TTL 24h 已过期，下次访问端点自动重算）
- 清 AnalyzedPost 关联 irrelevant 的 473 行冗余（让表干净）

## 非目标

- 不改 HeatMetric 计算逻辑（只重算数据）
- 不改 fleet-overview 端点代码（status 过滤已正确）
- 不补 _KNOWN 别名（QQ3/风云A9L 走 fallback aliases=[name] 即可，新车型无已知元数据）

## 流程豁免说明

用户显式要求走 superpowers 简化版（规模小、纯数据修复 + 配置变更无代码逻辑）。不写 OpenSpec 四件套，不归档到 openspec/archive/。spec 文档保留在 docs/superpowers/specs/ 作为决策记录。
