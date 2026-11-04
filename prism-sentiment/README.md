# 车型舆情分析看板

汽车舆情监控系统：采集多平台社媒帖+评论 → LLM 分析情感/事件/缺陷 → 看板呈现。

## 快速启动

```bash
# 1. 环境：conda base（必须用全路径 python，勿用 hermes venv）
conda activate base

# 2. 配置凭证
cp .env.example .env          # 填 TIKHUB_KEY
# .secrets 填 glm/deepseek/local_model 的 LLM 配置（字段见 utils/config.py）

# 3. 启动服务（默认 127.0.0.1:8000）
python start.py

# 4. 打开看板
# 浏览器访问 http://127.0.0.1:8000/
```

## 技术栈

- **后端**：FastAPI + SQLAlchemy(async) + SQLite
- **采集**：TikHub API（微博/小红书/抖音/快手）+ 车质网 HTML 直采 + 新闻源
- **分析**：LLM（GLM-4-Flash 主力/DeepSeek 备选）+ 本地 ABSA（Qwen3-4B 微调）
- **前端**：Vue 3 + ECharts（CDN，无构建步骤）

## 项目结构

```
api/routes/       # FastAPI 路由（dashboard/collection/analysis/reports/watchlist）
pipeline/         # 采集（collectors/）+ 分析（analysis/）
models/           # SQLAlchemy 模型 + 迁移
frontend/         # Vue 看板（index.html + static/js/app.js + static/css/）
scripts/          # 运维脚本（daily_update/refresh_engagement/llm_qa_sample）
docs/             # 设计文档
tests/            # pytest（719+ 用例）
```

## 测试

```bash
PYTHONPATH=. python -m pytest -q
```

## 配置

- `.env`：TikHub key + 服务 HOST/PORT
- `.secrets`：LLM 配置（glm/deepseek/local_model）
- 环境变量详见 `utils/config.py` + `pipeline/collectors/platform_strategy.py`

## 安全

- 默认监听 127.0.0.1（仅本机访问），需局域网访问设 `HOST=0.0.0.0`
- 无鉴权（内部工具），上线需自行加 auth middleware
