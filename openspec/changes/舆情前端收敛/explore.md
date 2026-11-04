# 舆情前端收敛 change（change 2）· Step1 explore

> 2026-10-17 · 轻量十步 · 依据：方案 §五（5.1-5.5）+ R17-R21/R34/R38/R46 + change 1 archive §一（新口径）
> 全部锚点为本轮实测（file:line / curl / DB 查询）。

## 一、完整版现状地图（prism-sentiment\frontend）

**文件**：index.html 707 行 / static/js/app.js 1460 行（Vue3 CDN 单页，区块为 `<section class="sec">` + header.pb 页头 :72）。

### 1.1 删/并/归一目标定位（拍板执行面）

| 动作 | 目标 | index.html | app.js |
|---|---|---|---|
| **删** | 讨论与传播图 `discussion-chart` | :174 | 渲染 `renderDiscussionChart()` :968；实例 :117；resize :340；调用 :604；数据 discussion_volume 周桶在渲染函数内（§5.2 已证同源）；**连带 2.2 副标题**（:166 区域"搜索热度 · 讨论声量 · 热帖"→"搜索热度 · 平台分布 · 热帖"） |
| **并₁** | 情感趋势：`sentiment-chart`(:155) ⇄ `negative-trend-chart`(:333) | 分别在 2.1 区块与 3.4 风险区块 | renderSentimentChart :1019 / renderNegativeTrendChart :857（P3-4 resize :351）；合并=堆叠柱+负面占比叠加线，删 negative-trend-chart 独立卡 |
| **并₂** | 维度轴：`dim-chart`(:159) ⇄ 风险信号「负面维度TOP5」卡片 | 风险区块 :262 段内 | renderDimChart :1059；负面TOP5 卡片数据来自 negativeRadar（:798 拉 /negative-radar） |
| **并₃** | 词频：`opinion-tags-chart`(:417) ⇄ `word-cloud-main`(:459) | 3.2 内容洞察区 | renderOpinionTagsChart :674（数据 :740 /api/analysis/top-opinions）/ renderWordCloud :1116（数据 :786 /word-cloud）；**留词云删标签TOP10** |
| **归一** | 事件三处→「话题发酵」列表唯一出口 | ①风险信号「负面事件 TOP3」卡 :316-326（数据 negativeRadar.negative_events）；②话题发酵列表 :385-412（eventTimeline :746 拉 /events）；③本周增量「新事件」卡 :232-239（incrementOverview :847） | ③降为一行数字（increment-overview.new_events.length），①删卡 |
| **保留+口径注记** | 搜索热度图 `attention-chart` :170 | renderAttentionChart :912 | R38：保留，卡片需加"平台搜索行为，非讨论量"标注 |
| **保留不动** | 翻车帖 :337 / 护车帖 :359（comment-sentiment-diff :793）；周报月报 :465/:549；采集进度面板 :86-105（progress :576）；6 浮层（全部帖子 :491 / 历史报告 :542 / 帖子详情 / 添加车型 / 关注列表 / 车队总览 openFleet :46） | | |

**8 主区块 section 行号**：:87 采集进度 / :105 热度全景 / :150 情感趋势(2.1) / :165 声量分布(2.2) / :215 本周增量(2.x) / :262 风险信号(2.3) / :384 话题发酵(3.1) / :454 内容洞察(3.2) / :479 方法论(4)。

## 二、轻卡数据面（6 端点实测全通，风云T7, 30 天窗）

| 端点（/api/dashboard/） | 实测返回 | as_of |
|---|---|---|
| `overview/{id}?start&end` | total/positive/negative/neutral/week_total/week_change_rate/**health_score**/peak_date/best_dim/worst_dim/sample_insufficient/comment_model_available/degraded[] | ❌ 无 as_of 字段 |
| `sentiment-trend/{id}` | [{date,positive,negative,neutral}] 日序列 | — |
| `dim-sentiment/{id}` | [{dim,score,count}] 帖子侧 GLM 维度（**新口径不受影响**） | — |
| `increment-overview/{id}` | {new_negative_count, new_events[]}（归一③取数点） | — |
| `vehicles/{id}/events` | [{id,event_tag,source,start_date,end_date,post_count,sentiment_distribution}] | — |
| `fleet-overview` | [{name,health_score,week_change_rate,risk_level,...}] | — |

**as_of 缺口**：§5.4 要"数据截至 {as_of}"——舆情侧无现成字段。方案：轻卡用查询窗 end 标注"数据窗截至 {end}"（零后端改动）或主站补"舆情库 max(collected_at)"一行（荐前者）。

**车质网可达性（R46）**：库内 active 池车质网帖仅 **11 条**（Model Y 4 / T11 2 / A9 1 等，T7 无 seriesId 映射=0）；platform-distribution 实测**不含 chezhwang 档**（T7 窗内 5 档=dy/ks/news/wb/xhs，车质网帖量太小未成档或平台过滤口径）；posts 端点 `/api/dashboard/posts/{id}?platform=chezhiwang` 可查。**落位评估：量级撑不起缺陷簇主视图，荐"健康分卡·本月投诉 N 条"行式**（取数=posts 端点 platform 过滤 count，或后端 overview 加一字段）。

## 三、主站接入面（prism-web）

- **SentimentBoard.tsx（76 行，整体替换对象）**：iframe src=/sentiment-board/（:55）+ **header.pb 隐藏 hack :39-48**（§5.4 指认的"看不懂"根因）+ 探活 :17-25 + reloadKey 重载 :29-36。
- **KanbanView.tsx**：看板四 tab（:55 舆情 seg-btn，:82 挂载）；**舆情 tab 当前不接收 seriesKey/seriesId**（:82 只传 reloadKey；config 传了 seriesId）——舆情板内部自己选车。**轻卡需新建 series→vehicle_id 联动**（/api/vehicles/suggest?q= 反查，非迁移现有 q= 机制——app.js 无 URL 参数读取逻辑，:496 suggest 是内部搜索）。
- **_shared.tsx**：现导出仅 Header/Card/GapCard/Loading（:5-:45）——**图表组件（AreaChart/BarChart/HBars）不存在于当前代码**（此前 UI 复审版本的手写 SVG 组件未沉淀到此文件），轻卡图表需自绘（照 ReviewsBoard/MarketBoard 内部实现借令牌）。
- **取数通道**：vite.config :24 `/sentiment-board → 8002`；主站反代 main.py :593 GET-only 转发 8000。**登录门禁影响**：auth_gate（main.py :166）拦所有业务路径（白名单仅 /auth/login+/health :94）——轻卡 fetch '/sentiment-board/api/dashboard/...' 走主站时**浏览器自动带 prism_token cookie**（用户已登录）→ 实际可用，但需注意反代 GET-only（轻卡取数全 GET ✓）与无 cookie 环境（eval/SSR）会 401。

## 四、新数据口径核对

- **前端零直读 dim_sentiment**（app.js 全文无该字段）——评论极性全走三端点：comment-sentiment-overview :721 / trend :730 / diff :793，三端点已极性轨优先（change 1 T4）→ **前端无需适配**。
- 帖子侧 dim 端点（dashboard.py :213 AnalyzedPost.dim_sentiment）= GLM 维度，不受影响。
- 翻车帖链 :305-322 吃 genuine_sentiment（GLM comment_summary），不经 derive（R44）。
- platform-distribution 窗内仍含 news/weibo/kuaishou 档（历史存量帖计入）——**R29 微博口径直接作用于该图**。

## 五、风险与坑

1. **series 联动从无到有**：舆情 tab 无现成联动（config 有），轻卡接 KanbanView 的 seriesKey 需 suggest 反查 vehicle_id + 无映射车系的降级态（如"风云T7"→有；无对应车→显示库内车列表面包屑）。
2. **app.js 删块回归面**：1460 行单页无组件化测试；安全网=①渲染函数调用点集中 :601-610（删一处渲染需同步删实例/resize/数据拉取三处）；②既有 pytest 只测后端；③验收靠 tabbit 走查（项目惯例）。**副标题 :166 连带改**。
3. **微博/停采档展示（R29 待拍板）**：选项 A 保留+档标"已停采"（platform-distribution 返回什么画什么+前端标签表）；B 分布图隐藏停采档（前端过滤 platform in {xhs,dy,chezhiwang}）。数据面影响：A 零改动；B 纯前端过滤但与"全部帖子"浮层的平台筛选一致性要对齐（帖子列表仍可按停采平台筛历史帖）。
4. **反代 GET-only + 鉴权 cookie**：轻卡全部取数 GET ✓；但 401 态需设计（未登录看板=主站本身已拦，低风险）。
5. **iframe 替换不删完整版**：轻卡底部"查看完整看板→"新窗口开 :8000 整页（用户需登录舆情板？——舆情板 :8000 自身无鉴权，直接开即可）。

## 六、Step2 待拍板清单（建议）

1. **R29 微博/停采档口径**：A 保留+标停采（荐——历史可查、零数据改动）vs B 隐藏停采档
2. **车质网落位（R46）**：荐"健康分卡·本月投诉 N 条"行（数据量 11 帖撑不起簇视图）；取数方案：posts 端点 count vs overview 加字段（荐后者，一次请求）
3. **轻卡 series 联动形态**：接 KanbanView seriesKey（suggest 反查）vs 轻卡内嵌车型选择器（完整版同款）；荐前者+降级态
4. **as_of 标注**：查询窗 end 标注（零后端）vs 新增舆情 as_of 端点；荐前者
5. **负面维度 top3 环比箭头**（§5.1 概念 2）：dim-sentiment 无环比字段——用 week_change_rate 类比 or 砍掉箭头；荐砍掉（第一版从简，避免为箭头加后端）

## 七、施工建议（供 Step2 propose）

两个独立块可并行：**块 A 完整版精简**（:8000 侧删/并/归一+副标题+口径标注，纯 app.js/index.html，风险低）∥ **块 B 主站轻卡**（SentimentBoard.tsx 重写+KanbanView 接线+_shared 补图表件，新代码）。验收=tabbit 走查（三概念渲染/完整版入口/as_of 文案/翻车帖在位/搜索热度口径注记）+ agent 6 工具回归（不动后端，跑一遍确认零影响）。
