# Step5 块 A 施工报告（:8000 完整版精简）

> 子代理：c2-blockA（fork 型）· 2026-10-17 · 依据 explore.md 锚点 + proposal.md 块 A 八条
> 红线遵守：只改 frontend/index.html + static/js/app.js 两文件；零 commit；零服务重启（静态直读即生效）；零后端改动；零付费 API

## 一、改动清单（八条全落地）

| # | 拍板项 | 落点 |
|---|---|---|
| 1 | 删「讨论与传播」卡 | index.html（trend-dual 降单卡）；app.js 删 renderDiscussionChart(2707字符)/discussionVolume computed/实例+resize+调用三处；**trendData/discussion_volume 数据链保留**（sparseSince 顶部黄字与热度分仍消费） |
| 2 | 2.2 副标题 | "搜索热度 · 平台分布 · 热帖" |
| 3 | 并₁ 情感趋势⇄负面趋势 | renderSentimentChart 重写：堆叠柱保留 + 评论级负面占比线（commentSentimentTrendData 同 key 分桶、缺日 null 断点、双 y 轴、自定义 tooltip 帖数+占比）；negative-trend-chart 卡+函数+实例退役 |
| 4 | 并₂ 维度⇄负面TOP5 | renderDimChart 重写为双向图：左=正面得分（蓝，取 dimSentiment），右=评论负面占比（红，取 negativeRadar.negative_dims=原TOP5卡同源）；两源取并集、单侧无数据只画一侧；原TOP5卡删除 |
| 5 | 并₃ 观点标签⇄词云 | opinion-tags-chart 卡+renderOpinionTagsChart+loadOpinionTags（含调用行）删净；词云保留；**缺陷话题簇卡上移入 bottom-dual 格位**（顶替观点卡位，版式维持两列） |
| 6 | 事件归一 | 负面事件TOP3 卡删除；新事件卡降一行数字（kpi-value 同款样式+副标"明细见话题发酵"）；话题发酵=唯一事件列表 |
| 7 | 搜索热度口径注记 | card-sub 尾部追加"平台搜索行为，非讨论量"（R38） |
| 8 | 停采标注+方法论文案 | 新增 platformLabelStopped（仅分布图用，帖chip/采集面板不受污染）；方法论：数据来源改"TikHub 双平台+车质网，微博/快手/新闻 2026-10 起停采存量展示"、评论改"极性直出（正/中/负）"、补"维度轴由帖子侧承载"；**头部 meta 来源行同步改**（"5 平台社媒+新闻"过时表述） |

## 二、自验证据

- `node --check app.js` 三轮全过（每批编辑后）
- curl :8000 → 200；DOM 断言：attention/word-cloud/sentiment/dim/platform 五 id 在位 ✓，discussion/opinion-tags/negative-trend 三 id 零残留 ✓，翻车帖块在位 ✓
- HTML 结构：div 224/224 平衡、section 11/11 平衡（结构编辑无破口）
- app.js 退役引用 grep 零残留（render*/load*/discussionVolume/三实例）

## 三、偏差与决策记录（5 条）

1. **缺陷簇上移**（proposal 未明示落位）：观点标签删除后 bottom-dual 只剩事件卡半宽空格——把原 margin-top 的缺陷话题簇卡移入格位，两列版式保住，无 CSS 改动
2. **并₁ 的 ⚠ 环比标注未保留**：原负面趋势图"环比涨幅≥50% ⚠"标记随卡片退役（tooltip 仍显示占比数值）——信息降级，如需可后续在占比线上加 markPoint（记录不阻塞）
3. **dim 图空态文案**顺带修过时表述（"需本地 ABSA 模型"→"暂无维度数据"，维度本就来自帖子侧 GLM）
4. **热帖 tab 与全部帖子筛选保留停采平台选项**（历史存量可筛，与 D1"保留+标注"一致，30 天线会自然清空它们）
5. **div 平衡用计数法**非 DOM parser（无构建管线）；结构风险已由 curl+计数双验兜底，视觉验收留 tabbit 走查（既有惯例）

## 四、移交

- 块 B（主站轻卡）并行施工中；合并后 tabbit 走查 + agent 6 工具回归
- 并₂ 负侧数据依赖 negativeRadar 已有加载（零新增请求）；轻卡如需"负面维度 top3"同源可复用 negativeRadar.negative_dims
