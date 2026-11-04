# OneAPI（getoneapi.com）接口需求与缺口清单

> 2026-09-09 初测 + 2026-09-10 快手补测定稿。累计 12 次计费成功 + 若干次不计费失败，总花费 ≈0.6 元。
> **结论先行（2026-09-10 用户决策）：取消 CDP，四平台全部走 OneAPI。**
> 09-09 曾判"快手不可用"，09-10 补测推翻：**挂起的只是 v1 端点，`search_video_v3` 一次即通**；快手评论/批量详情也全通。唯一遗留是快手搜索无时间窗（靠 photo_id 截断增量）。

## 〇、API 基础与已确认端点

Base：`https://api.getoneapi.com`。全部 **POST + JSON body（必须 UTF-8）** + 头 `Authorization: Bearer <ONEAPI_KEY>`。key 在项目 `.env`（ONEAPI_KEY / ONEAPI_BASE_URL）。

| 平台 | 用途 | 路径 | body 要点 | 状态 |
|---|---|---|---|---|
| 抖音 | 搜索 | `/api/douyin/search_video` | `{"keyword","page"}`；文档另有 publish_time(0/1天/7天/180天)+sort_type(2=最新发布) | ✅ 09-10 复测 661KB/12 条 |
| 抖音 | 评论 | `/api/douyin/fetch_video_comment` | count 3-30 + cursor | ✅ 09-09 |
| 快手 | 搜索 | `/api/kuaishou/search_video_v3` | `{"keyword","pcursor":""}`，翻页回传 `data.pcursor` | ✅ 09-10，453KB/19 条每页 |
| 快手 | ~~搜索 v1~~ | `/api/kuaishou/search_video` | — | ❌ 服务端 90s 挂起，**弃用**（ASCII/中文关键词均挂） |
| 快手 | 评论 | `/api/kuaishou/fetch_video_comment` | `{"id":"<photo_id>","pcursor":""}` | ✅ 09-10，2 个真实 photoId 验证 |
| 快手 | 批量详情 | `/api/kuaishou/fetch_multiple_video_detail` | `{"id":[...≤50]}` | ✅ 09-10（热度刷新用） |
| 小红书 | 搜索/评论 | `/api/xiaohongshu/...`（精确路径待从文档回填） | noteTime 时间窗 + sort=new | ✅ 09-09 |
| 微博 | 搜索/评论 | 同上待回填 | type=61 实时；flow=1 按时间 | ✅ 09-09 |

⚠️ **编码坑（09-10 实测）**：git-bash 直接 curl 传中文会发 GBK → 服务端秒回 `{"code":0,"message":"error"}`（不计费）。Python `requests/json=` 天然 UTF-8 无此问题；curl 必须用 `--data-binary @file`。09-09 的"快手挂起"部分混杂了此因素，但 v1 挂起用 ASCII 关键词复现过，是真挂。

## 一、四平台实测结果

| 平台 | 搜索 | 评论 | 返回质量 | 采集路径决策 |
|---|---|---|---|---|
| 抖音 | ✅ 615KB / 11 条 | ✅ 10 条 | 四平台最好：完整 aweme_detail（~190 key）、`create_time` Unix 秒、赞/评/转全、评论带 IP 省级 + 楼中楼数 | OneAPI（自家 CDP 同关键词 81 字节风控空） |
| 小红书 | ✅ 156KB / 20 条 | ✅ 15 条 | 好：Unix 秒、扁平计数 liked/collected/comments/shared_count、`xsec_token` 20/20 有值（**必须入库**，抓详情凭证） | OneAPI（CDP 退役） |
| 微博 | ✅ 83KB / 10 条 | ✅ 3 条 | 可用，需 3 项清洗（见下）；评论 text_raw 干净是亮点 | OneAPI（CDP 退役） |
| 快手 | ✅ v3 453KB / 19 条每页 | ✅ 10 条 + 翻页游标 | 可用，需注意毫秒时间戳 + 跨页去重（第 1/2 页 photo_id 重叠 12/19） | OneAPI（CDP 退役；v1 弃用） |

### 微博接入的 3 项清洗（建 adapter 时照做）
1. `created_at` 是字符串 `'Wed Sep 09 12:29:43 +0800 2026'`，非 Unix 时间戳 → strptime 解析
2. 搜索正文 `text` 带 HTML 标签（`<a href=...#话题#</a>`）→ 剥标签；长文 `isLongText` 标记，需另抓全文（样例全短文，深采时再处理）
3. IP 属地：帖子在 `region_name`（'发布于 广东'）✅；评论无独立字段，藏在 `source`（'来自 格鲁吉亚'），且语义有歧义（设备来源或 IP 属地）→ 只信帖子的

### 快手接入要点（09-10 v3 实测）
- 搜索 `data.mixFeeds[].feed`：id=`photo_id`、正文=`caption`、时间=`timestamp`（**Unix 毫秒，÷1000 入库**）、互动 `like_count`/`comment_count`/`share_count`+`forward_count`/`view_count`/`collect_count`、作者 `user_id`/`user_name`/`headurls[].url`
- 评论 `data.rootComments[]`：id=`comment_id`、正文=`content`、赞=`likedCount`、时间=`timestamp`(毫秒)、作者=`author_name`、**IP=`authorArea`（省级）**；汇总 `data.commentCount`、翻页 `data.pcursor`
- 批量详情 `data.photos[]`：计数 + `timestamp`(ms) 全
- **跨页必须按 photo_id 去重**，连续重叠率过高应停止翻页（防空转）
- ⚠️ DB 存量快手帖的 platform_post_id 疑似 UUID 非真实 photo_id（09-10 测试代理观察）——建 collector 时需核对 cdp_collector 的存储语义；若为 UUID，旧帖无法回填 OneAPI 评论，新采必须存真实 photo_id

### 微博可用字段亮点
`user.verified / verified_type / verified_reason / followers_count` 齐全（蓝V/营销号过滤可用）；`ad_marked` 可辨广告帖；评论 `text_raw` 纯文本无需剥 HTML。

## 二、接口需求矩阵（P0 核心）

| 需求 | 抖音 | 小红书 | 微博 | 快手 |
|---|---|---|---|---|
| 帖子搜索 | `search_video`：publish_time 0/1天/7天/180天 + sort_type 2=最新发布，**唯一有完整时间窗+排序**，增量最友好 | `search_note`：noteTime one_day/one_week/half_year + sort=new | `search`：type=61 实时 / 60 热门，**无时间窗** → 增量靠 type=61 + 命中已入库 id 截断 | `search_video_v3`：**无时间窗** → 增量靠 photo_id 截断 + 跨页去重 |
| 一级评论 | `fetch_video_comment`（count 3-30 + cursor） | `fetch_video_comment`（noteId + cursor，sort 1=最新） | `fetch_post_comment`（**flow=1 按时间** + max_id 翻页） | `fetch_video_comment`（id + pcursor） |
| 楼中楼/子评论 | ✅ 有子评论接口 | ✅ 有子级评论接口 | ✅ 有子评论接口 | ❌ subCommentsMap 首屏为空，基本拿不到（影响小——`fetch_top_comments` 本来主要吃一级评论） |
| 详情 / 热度刷新 | 视频详情 + 批量（≤50） | 笔记详情 V2 系列 | 微博详情 | `fetch_multiple_video_detail` ≤50 ✅ |

调用约束（全部接口通用）：HTTP 恒 200，业务 `code` 200=成功计费 / 0=失败不计费 / 401=key 无效 / 403=账户不可用 / 301=余额不足；**失败重试 ≤5 次否则触发它家风控标记账户**；建议超时 60s（实测耗时 3-13s，快手 v1 挂起除外）。

## 三、缺口清单

| # | 缺口 | 影响 | 处置 |
|---|---|---|---|
| 1 | ~~快手搜索接口服务端挂起~~ → **已解决**：v1 挂起弃用，`search_video_v3` 可用（09-10） | 无 | collector 快手搜索一律 v3 |
| 2 | 微博/快手搜索无时间窗参数 | 增量多花 1-2 页调用（翻到已入库 id 即停） | 可接受 |
| 3 | 快手楼中楼无接口 | 楼中楼观点缺失 | 影响小——`fetch_top_comments` 本来主要吃一级评论 |
| 4 | 抖音播放量不在搜索/详情响应里 | 热度分暂缺播放维度 | 可选增强：Douyin-App 作品统计接口（批量 ≤50）；现热度分用赞/评/转已够。**快手 v3 直接带 view_count，无此问题** |
| 5 | 长微博正文需另抓全文 | 长文分析不完整 | 深采时对 isLongText 帖调详情接口 |
| 6 | 新闻 / 百度指数 / 车型联想 OneAPI 不覆盖 | 无 | 继续用 bocha/anspire + gopup + autohome，与 OneAPI 互补不冲突 |

## 四、成本估算（单价未核实，按混合均价估）

- 已花：09-09 ≈0.3 元 / 6 次 + 09-10 ≈0.3 元 / 6 次 → 混合均价 **≈0.05 元/次**
- 四平台全切（2 车型日级增量）：≈ 40-60 次/天 ≈ **2-3 元/天 ≈ 60-90 元/月**
- 周深采 + 月回溯另加 30-50% → **上限 ≈110-130 元/月**

成本两个数量级低于人工监控，**不构成决策约束**；真正的约束是下面的合规。

## 五、可选扩展（产品决策，非欠缺）

- **B 站**：OneAPI 有综合搜索 + 视频评论——汽车评测重镇，若扩平台首选
- **视频号 + 公众号**：OneAPI 有搜索/文章/评论/阅读数——覆盖大龄用户群
- **热榜对齐**：OneAPI 快手 `fetch_hot_billboard` 等热榜接口（09-10 文档盘点确认存在）——可做"舆情 vs 平台大盘"对照
- 用户此前已明确反对 KOL/作者维度方向，不列入

## 六、合规定位（不变）

OneAPI 属逆向接口池转售（同 TikHub 类），平台方有起诉数据公司胜诉先例。**个人调研/演示可用；公司生产管线接入前必须过公司合规确认**。抖音官方开放平台（video.search 特殊权限）申请继续并行，作为合规正道。

## 附：实测原始数据

`logs/oneapi_test/`：dy_search.json(615KB) / dy_comments.json(69KB) / xhs_search.json(156KB) / xhs_comments.json(17KB) / wb_search.json(83KB) / wb_comments.json(9.5KB)；09-10 快手：ks_search_v3_utf8.json(453KB) / ks_search_v3_page2.json / ks_comments_5206161368980153357.json / ks_comments_5196591194977260534.json / ks_multi_detail.json / dy_search_sanity.json；请求体样例 `_body_ks_*.json`；过程记录 `ks_timeout_note.md`。
