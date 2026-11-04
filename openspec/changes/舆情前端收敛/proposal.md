# 舆情前端收敛 change（change 2）· Step2 proposal + design + tasks（轻量十步）

> 2026-10-17 · 依据：方案 §五（R17-R21/R34/R38/R46）+ explore.md（同目录）· 流程：轻量十步

## 六决策（采 explore 推荐，待用户过目设计稿时一并确认）

| # | 决策 | 依据 |
|---|---|---|
| D1 | R29 微博口径=**保留展示+档标"已停采"**（platform-distribution 档位标签） | 历史可查；零数据损失 |
| D2 | 车质网=**健康分卡行式**（"本月投诉 N 条 · 车质网"） | active 池仅 11 帖（T7 映射 0），撑不起缺陷簇视图（explore 实测） |
| D3 | 轻卡 series 联动=**接 seriesKey**（App 现有 series 状态流；降级态=提示选择车系） | 现状 iframe 无联动（SentimentBoard.tsx:82 只传 reloadKey），从无到有 |
| D4 | as_of 标注=**查询窗 end 日期**（"数据截至 {end}"） | overview 无 as_of 字段，零后端改动 |
| D5 | 负面维度环比箭头**第一版不做** | 无现成环比端点，避免后端加活；v2 视需求补 |
| D6 | **搜索热度纳入轻卡**（第四块小卡，带"搜索行为≠讨论量"口径注记） | R38 用户明确保留——轻卡是主站默认面，不纳入则用户看不到 |

## 块划分（可并行）

**块 A · :8000 完整版精简**（app.js/index.html，纯删/并/归一+文案）
**块 B · 主站轻卡**（SentimentBoard.tsx 76 行整体替换为原生 React 轻卡）

## 块 A 清单（锚点见 explore §1）
1. 删 discussion-chart 卡（index.html:174 + app.js:968 渲染 + discussionVolume 计算段）+ 2.2 副标题改"搜索热度 · 平台分布 · 热帖"
2. 并组一：sentiment-chart + negative-trend-chart → 单图（堆叠柱+负面占比叠加线）
3. 并组二：dim-chart + 风险信号负面TOP5 → 双向维度图（左正右负）
4. 并组三：删 opinion-tags-chart，留 word-cloud-main
5. 事件归一：删风险信号负面TOP3 卡（app.js:316）；本周增量新事件卡（:232）降一行数字；话题发酵=唯一列表
6. attention-chart 加口径注记（"平台搜索行为指数，非讨论量"）
7. platform-distribution 微博/快手档标"已停采"（D1）
8. 方法论文案修正（:483 附近："评论→本地 Qwen3-4B ABSA 15 维"→"评论→极性直出（正/中/负）"+帖子侧 15 维表述）

## 块 B 轻卡设计（wireframe）

```
┌─ 舆情 · {车系名}          数据截至 {end} · 小红书+抖音 ┐
│ ① 最近热度   声量 30 天 sparkline + 平台占比条        │
│ ② 舆情健康分 {分数}/100 · 负面维度 top3 · 本月投诉 N 条(车质网) │
│ ③ 正在发酵   事件 top3 列表 + 本周新增负面帖数        │
│ ④ 翻车帖/护车帖 固定块（2+2 缩略，点击入完整版）      │
│ ⑤ 搜索热度   指数小趋势（口径注记：搜索行为≠讨论量）   │
│ ── 口径两行小字：口碑=车主评价(汽车之家)·舆情=全网讨论 │
│    （小红书+抖音，含非车主）· 健康分已剔除官商账号     │
│ [查看完整舆情看板 →]（新窗 :8000）                    │
└──────────────────────────────────────────────┘
```

- 数据端点：overview（健康分+负面维度）/sentiment-trend（sparkline）/events（发酵）/increment-overview（负面帖数）/platform-distribution（占比+投诉行数据：车质网档帖数）/attention 数据（index 端点？——若无线端点则块⑤降级隐藏，施工时核实）
- 图表：_shared 无现成组件——**自绘轻量 SVG**（sparkline/占比条/小趋势，借 VS 令牌样式，不引依赖）
- series 联动：seriesKey 有值→反查 vehicleId（/identity/resolve 或 fleet-overview 匹配名）；无值→显示"选择车系查看舆情"空态
- 翻车帖：posts 端点过滤 pos2neg/neg2pos（R44：吃 comment_summary.genuine_sentiment）取前 2+2

## 验收
tabbit 走查（轻卡三概念渲染/完整版入口/as_of/删并项单处/搜索热度在位带注记/翻车帖块/车质网行）+ agent 6 工具回归 + 完整版手动过目

## tasks
1. 块 A 施工（子代理 fork）→ 复核
2. 块 B 施工（子代理 fork）→ 复核
3. tabbit 走查 + 归档
