# Explore · 社媒深挖能力包

日期：2026-10-12 · 触发：用户提出将个人工作流（风云T7典型用户分析 + car-reputation-research skill）产品化进 Prism，用 TikHub API 替代 CDP 登录态抓取。用户拍板：做 TikHub 工具包 + 用户分析 skill + xlsx 导出三件套（一个 change）。

## 背景资产（已读）

- **skill 源**：`C:\Users\<you>\Desktop\工作\car-reputation-research\`（SKILL.md + references/deliverable-spec.md + references/platform-notes.md，纯方法论无脚本，Claude Code 版）
- **成果样例**：`C:\Users\<you>\Desktop\工作\风云T7典型用户分析.xlsx`（5 sheet：说明与来源/用户对照总览/每用户详解/溯源清单；zkz8118 汽车之家 + 作者A 抖音 双用户跨平台深挖）
- skill 铁律与 Prism 红线同构：每条引用带 URL、未核验不猜测、信源分级（真实车主>意向>媒体>水军）

## E1 · pi skills 机制（实测：原生加载断，需替代设计）

- pi 按 Agent Skills 标准加载：`.pi/skills/`（项目，需 trust）/ agentDir `skills/`（全局）/ settings `skills` 数组 / CLI `--skill`（skills.md Locations 节）
- **断点**：全文加载靠 agent 自己调 `read`（或 `bash` 兜底）（skills.md:37-38）——我们的 EXCLUDE_TOOLS 把 `read`/`bash` 都排除了（pi_gateway.mjs:26-30）→ 描述能进系统提示词，**全文加载不了**
- 替代设计（Step2 拍板）：
  - 方案 A（推荐）：extension 注册 `load_skill(name)` 工具，只读 allowlist 目录内 SKILL.md——保住渐进披露（progressive disclosure），不破红线（不给通用 read）
  - 方案 B：before_agent_start 全文注入——简单但每轮白烧 ~5KB token
- 附注：PI_CODING_AGENT_DIR=.pi/agent-minimal 下放 `skills/` 目录 = 该子进程的全局技能位（描述自动进系统提示词），是否生效施工时验证；最坏情况由 load_skill 工具描述兼任触发入口

## E2 · TikHub 现状（实测：端点/机制全核实；**key 失效+余额耗尽=外部阻塞**）

- **key 状态（实测 2026-10-12）**：`.env` 的 TIKHUB_KEY（nb8p...，58 字符）→ `handler_user_profile_v4` 返回 **401 Invalid API token**；舆情侧日志 svc_err.log 显示 2026-09-22 起采集链路 402 Insufficient balance（小红书评论/快手搜索/抖音指数全停）。**施工不依赖 key 有效，E2E 验收依赖。需用户充值/换 token。**
- **scope 机制（采信 9-11 实测存档 01_get_user_info.json）**：key 按 path 前缀授权，"舆情项目"key 覆盖 douyin(web/app/search/index/douplus)、xiaohongshu(web/app/app_v2/web_v3/pgy)、weibo(web/web_v2)、kuaishou(web/app)、bilibili(web) 等——**所需平台全在 scope 内**；TikHub 支持多 key（可另 mint "Prism" 专用 scoped key，成本审计隔离）
- **账号管理端点（探活+余额监控用）**：`/api/v1/tikhub/user/get_user_info`（key 元数据+scope）、`get_user_daily_usage`（用量）、`get_all_endpoints_info`（**每端点计费单价**，如 endpoint_cost=0.001、rate_limit=10/second）
- **用户侧端点（openapi 1050 paths 中筛选，参数已核实；响应结构待 key 恢复后补验）**：
  - 抖音画像：`douyin/web/handler_user_profile_v4`(GET, sec_user_id，含性别/年龄) + `v2`(GET, unique_id=抖音号)
  - 抖音作品列表：`douyin/web/fetch_user_post_videos`(GET, sec_user_id, max_cursor, count)
  - 小红书画像：`xiaohongshu/app_v2/get_user_info`(user_id|share_text) + `app_v2/search_users` + 作品 `app_v2/get_user_posted_notes`(user_id, cursor)
  - 试调用例 sec_uid（作者A）：MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000
- **内容侧端点（采信舆情侧 14 端点，已实战验证）**：微博/抖音/小红书/快手 搜索+评论+批量统计+指数（tikhub_collector.py ENDPOINTS 表，信封 {code,message,data} 处理、重试护栏、计费上限参数全有现成实现可抄）
- 客户端实现可参照：`舆情Board/pipeline/collectors/tikhub_collector.py`（Bearer auth L239-240、信封 L259-322、计费护栏 env L92-106）

## E3 · 汽车之家论坛（实测：游客全通）

- 完整 URL 格式 `club.autohome.com.cn/bbs/thread/{hash}/{topicid}-1.html` → 200，23KB HTML，真实标题（实测 82aa6935fb2ed361/115718887-1.html → "风云T7立帖为证，所有车友们作证"）
- 注意：**论坛主帖不在我们任何库里**（库里是口碑体系 owner_reviews，33 车系池）——skill 的"平台扫描"汽车之家环节走 web fetch（pi-web-access 既有 web 工具组）
- B站：scope 内有 bilibili/web（TikHub 可查），游客 web fetch 亦可兜底；懂车帝放弃

## E4 · Prism 侧接线点（实测：机制全部现成）

- **工具注册**：`TOOL_CATEGORIES`(business/web/utility) extension L42 + makeSentimentTool 工厂 L198（makeTikhubTool 照抄模式）
- **tier 路由**：decideTier L52 看 calledTools 是否含 web 类——**tikhub 工具归入 web 类 → 纯社媒轮=web tier、混合轮=mixed tier，零新验证器**：URL 进 collectWebUrlsThisTurn L503 真值集、数字走既有 web 降级告警、标注不可复算
- **出口闸**：TikHub 无本地库可复算 → **不进 /verify/claim 台账**（区别于 sentiment_* 直读舆情库模式）——web tier 既有链路即为正确归宿。风险点：出口闸舆情源登记 change 的教训——新数据源必须先想清楚闸怎么接，本方案=不接闸、走 web 通道
- **xlsx 导出**：openpyxl 3.1.5 在 prism-api venv 实测可用；main.py FastAPI 既有 /dash 反代+鉴权中间件模式可挂 /export
- **截断（红线）**：pi extensions.md:2170-2197 要求工具自截断 50KB/2000 行（truncateHead/Tail 从 @earendil-works/pi-coding-agent 导出）——**现有 extension 未截断（已确认缺口，线 B 遗留），新工具第一天就带**；TikHub 搜索结果几十条帖=高危场景
- **成本护栏模板**：舆情侧既有 env 护栏（评论帖数≤5/详情≤5/翻页≤3）参数化模式可抄；轮次上限对标 web 3 轮

## E5 · skill 改写差异（Claude Code 版 → Prism 版）

- 删：web-access skill/CDP/3388 端口/MediaCrawler/uv 命令/xlsx skill 引用、"派子 agent"协作模式
- 换：抖音/小红书/微博/快手→TikHub 工具；汽车之家/B站→web fetch（游客全通）
- 保留：铁律/信源分级/未核验标注/评论区金矿/陷阱清单（媒体循环转载/上市初期真车主极少/口述日期以页面为准）
- 新增：个人画像输出边界（人群理解颗粒度，不输出可定位个人的信息组合，溯源 URL 对管理者可见）+ TikHub 引用格式 + 成本纪律（轮次上限内工作，超限如实声明数据缺口）
- 交付：deliverable-spec 模板 B 对接新 export 工具（溯源清单 sheet = "说明与来源"的既有实践）

## E6 · 验收设计（已与用户对齐）

- 终验：**风云T7 重跑**——Prism 独立产出典型用户分析 xlsx 与手工版对照
- 中间 smoke 评估题 1-2 道（如"搜小红书'风云T7 提车'给 3 条带 URL 引语"——验 URL 真值集命中），进 runner

## 约束回顾

- 红线#1：TikHub 数据=web tier，一律标"不可复算+来源 URL+抓取时间"；红线#4：仅公开内容、学习研究框架（沿用舆情 Board 既有定性）
- 不碰舆情 Board 12 写端点（既有契约）；TikHub 工具=即时查询不落库，与 Board 定期采集管线不冲突
- pi.exe(Bun) 进程内禁原生模块——TikHub 调用是纯 HTTP（fetch），无此限制
- 49 人上线前不设管理者门槛，但调用日志必落（trajectories 现有管道）

## 已排除路径

- **Prism 走 prism-sentiment 代理 TikHub**：多一跳、把即时查询耦合进采集服务的进程模型；直连 api.tikhub.dev 与 sentiment 工具直连 prism-sentiment 同为只读 HTTP，无新增暴露
- **tikhub_* 行 ID 进 /verify/claim**：无本地库可查，硬接=制造新的"库中无对应数据"误拒（舆情源缺口同款事故）；web tier 降级验证本就是为"不可复算源"设计的
- **给 agent 开 read 工具让 pi 原生 skill 生效**：read 可读任意文件，破红线#5（护栏在执行层）+权限分层设计

## Step2 待拍板决策点

1. 工具面切分与命名（4 工具：social_search / social_post_comments / social_user_profile / social_user_posts？还是按平台分？）——倾向功能切分、platform 参数化
2. tikhub 工具归 TOOL_CATEGORIES.web 还是新设 social 类（影响 decideTier/collectWebUrlsThisTurn/白名单派生三处）——倾向并入 web 类（tier 语义就是"不可复算外部源"）
3. load_skill 工具 vs 全文注入（E1 方案 A/B）
4. TikHub key 复用"舆情项目" key vs 另 mint "Prism" 专用 key
5. xlsx 导出：独立 export_document 工具 + FastAPI /export 端点形态
6. 成本护栏参数（每轮 TikHub 调用上限默认值；余额黄灯阈值）
