# Brainstorming Design Document

Vehicle Sentiment Analysis Agent - Phase 1 技术选型决策

## 决策汇总

| # | 问题 | 决策 | 关键理由 |
|---|------|------|---------|
| 1 | 项目结构 | 根目录重构，清理旧代码 | 简单直接 |
| 2 | MediaCrawler 接入 | 直接集成为子模块 | 复用反爬策略，控制粒度细 |
| 3 | 前端框架 | Vue 3 CDN + ECharts | 组件化开发锚点对话+图表联动，无需构建链 |
| 4 | 后端框架 | FastAPI | 原生异步，SSE/流式输出开箱即用 |
| 5 | 本地模型部署 | Transformers + PEFT | 12GB 够用，LoRA 原生支持，单用户无需 serving |
| 6 | Git | git init + 首次 commit | Superpowers 工作流必需 |
| 7 | gopup Cookie | Playwright 自动获取 | 复用 MediaCrawler 的 Playwright 依赖 |

## 技术栈

```
后端：    Python + FastAPI + LangGraph + SQLite
本地模型： Qwen3-4B-Instruct-2507 + Transformers + PEFT（微调后启用）
API模型：  DeepSeek-V4-Flash（当前主力）
前端：    Vue 3 CDN + ECharts
采集：    gopup + MediaCrawler + Tavily/Bocha/Anspire
工具链：  Git + Superpowers
```

## 项目目录结构

```
pipeline/           # Pipeline 层（确定性数据流）
├── collectors/     # 数据采集器（gopup、MediaCrawler、新闻源）
├── analyzers/      # 分析器（情感、事件、观点）
└── scheduler.py    # 采集调度器
agent/              # Agent 层（LangGraph）
├── research.py     # Research Agent（Reflection Loop）
└── dialog.py       # 锚点对话 Agent
api/                # FastAPI 路由
├── dashboard.py    # 看板 API
├── dialog.py       # 对话 API
├── report.py       # 报告 API
└── vehicle.py      # 车型管理 API
models/             # 数据模型（Pydantic）
db/                 # 数据库（SQLite）
frontend/           # Vue 3 CDN 前端
├── index.html
├── components/     # Vue 3 组件
└── static/         # CSS/JS 静态资源
```
