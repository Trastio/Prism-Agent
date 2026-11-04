# Phase 4 实施计划：集成与优化

基于 OpenSpec tasks.md T4.1-T4.5，拆解为 TDD 原子任务。

---

## T4.1 端到端流程测试

### T4.1.1 测试：完整 E2E 流程
- **文件**: `tests/test_e2e.py`
- **内容**:
  - 创建车型 → 触发采集（mock 采集器，预设返回数据）→ 触发分析 → 验证 analyzed_posts 有数据
  - 计算热度指标 → 检测异常 → 验证 anomaly_events 有记录
  - 生成简报 → 验证 reports 表有数据
  - Dashboard API 查询 → 验证概览/趋势/分布数据正确
- **TDD**: 先写测试 → 红灯 → 修复各模块集成问题 → 绿灯

### T4.1.2 Commit
- `git commit -m "feat: end-to-end integration test"`

---

## T4.2 生命周期标注

### T4.2.1 测试：生命周期阶段标注
- **文件**: `tests/test_lifecycle.py`
- **内容**:
  - 创建带 lifecycle_anchors 的车型
  - 查询 trend API → 验证返回 lifecycle_phases 数组
  - 验证各阶段日期在趋势数据范围内被正确标注

### T4.2.2 实现：生命周期标注
- **文件**: `api/routes/dashboard.py`（修改 trend 端点）
- **内容**:
  - 从 vehicle.lifecycle_anchors 解析阶段日期
  - 在趋势 API 响应中附加 lifecycle_phases 数组
  - 在 overview 响应中附加 lifecycle_anchors
- **TDD**: 运行 T4.2.1 测试 → 绿灯

### T4.2.3 Commit
- `git commit -m "feat: lifecycle phase annotations in dashboard API"`

---

## T4.3 启动脚本 + 配置

### T4.3.1 测试：启动脚本
- **文件**: `tests/test_startup.py`
- **内容**:
  - 测试 `python -c "from api.main import app"` 成功
  - 测试 app.routes 数量 > 0
  - 测试 data/ 目录在 start.py 中自动创建

### T4.3.2 实现：启动脚本
- **文件**: `start.py`
- **内容**:
  - `uvicorn.run("api.main:app", ...)` 封装
  - 自动创建 data/、data/cookies/、logs/ 目录
  - 支持 HOST/PORT 环境变量
  - DEV 模式热重载
- **TDD**: 运行 T4.3.1 测试 → 绿灯

### T4.3.3 更新 requirements.txt
- 确保所有实际使用的依赖都在 requirements.txt 中

### T4.3.4 Commit
- `git commit -m "feat: startup script and dependency updates"`

---

## T4.4 错误处理与空状态

### T4.4.1 测试：错误处理
- **文件**: `tests/test_error_handling.py`
- **内容**:
  - 测试查询不存在的 vehicle → 404
  - 测试空数据时 dashboard API 返回空列表/零值
  - 测试采集器失败不影响其他采集器

### T4.4.2 实现：错误处理增强
- **文件**: 各模块
- **内容**:
  - Dashboard API 空数据返回合理默认值
  - 前端 empty state 显示
  - 采集器 try/except 隔离
- **TDD**: 运行 T4.4.1 测试 → 绿灯

### T4.4.3 Commit
- `git commit -m "feat: error handling and empty states"`

---

## 任务依赖图

```
T4.1.1 → T4.1.2
         ↘
T4.2.1 → T4.2.2 → T4.2.3
                       ↘
T4.3.1 → T4.3.2 → T4.3.3 → T4.3.4
                                   ↘
T4.4.1 → T4.4.2 → T4.4.3
```

**Phase 4 预计 11 个原子任务，4 个 commit。**
