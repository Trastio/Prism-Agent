# Step5 · 块 B 施工报告（主站舆情轻卡替换 iframe）

> 子代理：c2-blockB（fork）· 2026-10-17 · 依据 explore.md §2/§3 + proposal.md 块 B 设计
> 红线遵守：只改 prism-web 下文件（SentimentBoard.tsx 重写 + KanbanView 一行传参 + styles.css 追加 sc-* 段）；零 commit；未重启服务（vite 热更）；后端零改动；未调付费 API（端点实测走本地 :8000）

## 一、改动清单

| 文件 | 改动 |
|---|---|
| `prism-web/src/components/dashboards/SentimentBoard.tsx` | **76 行 iframe 壳整体重写为原生轻卡（~300 行）**：三概念（①最近热度=30 天声量 Sparkline+平台占比条/②健康分=分数+负面维度 top3+车质网投诉行/③正在发酵=事件 top3+本周负面帖）＋翻车帖/护车帖固定块＋搜索热度小卡＋口径两行脚注＋「查看完整看板→」新窗 :8000。header.pb 隐藏 hack 随 iframe 一并退役（§5.4"看不懂"根因拔除） |
| `prism-web/src/components/KanbanView.tsx:82` | 一行：`<SentimentBoard seriesKey={seriesKey} ...>`（seriesKey 由 App→KanbanView 既有链路下传，此前舆情 tab 不接） |
| `prism-web/src/styles.css` | 追加 `.sc-*` 段（~30 条：网格/占比条/维度胶囊/翻车帖条目/空态等，全借既有 VS 令牌）+ 补 `.chart-area-xt`（Spark 紫调面积类此前不存在） |

## 二、实现要点与裁决

1. **series 联动（D3）**：fleet-overview 取全车池 → 名匹配（去空格精确→双向包含）；命中→9 端点并行 allSettled；无 seriesKey→空态卡；未命中→"车池未收录「X」"卡+当前 8 台名单
2. **窗口**：30 天（end=今天本地时区、start=−29d）；本周=−6d（increment-overview）
3. **降级规则执行**：车质网行=posts?platform=chezhiwang&start&end（**端点可用**，T7 实测 total=0 → 显示"投诉 0 条"诚实零而非隐藏；fetch 失败才隐藏）；搜索热度=/trend 的 search_index 序列（null 日过滤，<2 点整块隐藏）
4. **翻车帖方向语义**：pos2neg=post:positive∧comment:negative，neg2pos 反向，"mixed" 排除（实测首条即 mixed，正确不入选）；各取点赞 top2；点击→完整版（按任务书）
5. **停采档（D1）**：weibo/kuaishou/news 档保留渲染+灰化+"已停采"标（占比条段灰+图例 em 标）
6. **as_of（D4）**：标题行"数据窗截至 {end}"；刷新=reloadKey 重拉全部端点

## 三、端点实测记录（直连 :8000，T7=306be9ad-…530d）

| 端点 | 结果 |
|---|---|
| /fleet-overview | ✓ [{id,name,brand,health_score,…}]——series 反查数据源 |
| /overview/{id}?start&end | ✓ health_score 84.1/worst_dim 售后服务/week_total 75（**无 as_of 字段→D4 查询窗标注**） |
| /sentiment-trend/{id}?start&end | ✓ 日序列（**start&end 必填**——explore 表未标注，422 实测补记） |
| /dim-sentiment/{id} | ✓ [{dim,score,count}]，T7 多为正值→负面 top3 取**分数升序前三**（含 -0.08 售后） |
| /increment-overview/{id}?start&end | ✓ {new_negative_count:7,…}（start&end 必填同上） |
| /vehicles/{id}/events | ✓ [{event_tag,post_count,…}]（tag 有"01"类噪声→post_count≥2 过滤+降序列 top3，数据质量属上游遗留） |
| /platform-distribution/{id}?start&end | ✓ 5 档含停采档（dy75/ks5/news36/wb69/xhs144） |
| /comment-sentiment-diff/{id} | ✓ post_sentiment/comment_sentiment/genuine_themes（R44 链）——翻车帖数据源 |
| /trend/{id}?start&end | ✓ {data:[{search_index:76.8| null,…}]}——搜索热度块⑤数据源 |
| /posts/{id}?platform=chezhiwang&start&end | ✓ {total:0}（T7 无车质网映射）——车质网行数据源 |

## 四、验证

- **tsc**：`npx tsc --noEmit` → 11 错全部位于根项目 `src/registry/*`+`src/verify/*`（**项目已知历史基线**，见 phase3 记忆"root tsc 11=基线"）；prism-web/本轮三文件**零错误**
- **vite 5173 探活**：200（热更已载入新组件）
- 渲染逻辑层：组件内各块均有空态/降级分支（见实现要点 3/5 + nomatch/empty/error/loading 五态）

## 五、偏差与移交

1. 翻车帖条目点击行为=打开完整版（按任务书字面）；帖子的原始平台 URL 已在 title 悬浮可复制——若 PM 想直接跳原帖，改一行 onClick 即可，移交验收时问
2. events tag 噪声（"01"/"2014" 类）属上游事件聚类质量，轻卡已用 post_count≥2 兜底；根治归舆情侧 v2
3. 轻卡取数 9 请求/次刷新——量级可接受（GET 轻端点）；若后续卡顿可合并（后端 overview 加字段，explore §六-2 同源建议）
4. **块 A（完整版精简）为并行任务不在本报告范围**；验收=tabbit 走查+完整版过目+agent 6 工具回归（后端零改动，工具回归预期天然绿）
