# Design · 社媒深挖能力包

## 0 · 架构总览

```
agent(DeepSeek)
  ├─ load_skill('car-reputation-research')   ← extension 工具，读 .pi/skills/（allowlist）
  ├─ social_search / social_post_comments / social_user_profile / social_user_posts
  │     └─ extension makeTikhubTool → fetch api.tikhub.dev（Bearer PRISM_TIKHUB_KEY）
  │          归一化 + truncateHead(50KB/2000行) + _meta{source:tikhub, as_of, 不可复算}
  ├─ export_document(title, sheets) → POST prism-api /export → xlsx 落 exports/
  │     └─ 返回 {url:'/export/download/{id}', filename} → agent 在回复里给链接
  └─ tool_call 护栏：每轮 tikhub 调用计数 >8 → block（fail-closed）
验证：4 工具 ∈ TOOL_CATEGORIES.web
  → decideTier：纯社媒轮=web / 混合轮=mixed（零新验证器）
  → collectWebUrlsThisTurn 自动收集归一化输出里的 URL 进真值集
  → verifyNames web 豁免 + 数字走 web 降级告警（既有机制）
```

## 1 · TikHub 工具组（extension，照 makeSentimentTool 工厂模式）

### 1.1 端点映射表 ENDPOINT_MAP（action × platform）

| action | douyin | xiaohongshu | weibo | kuaishou | bilibili |
|---|---|---|---|---|---|
| search | POST `/douyin/search/fetch_video_search_v1` {keyword,cursor,sort_type,publish_time} | GET `/xiaohongshu/app_v2/search_notes` {keyword,page,sort_type,time_filter} | GET `/weibo/web_v2/fetch_advanced_search` {q,page} | GET `/kuaishou/app/search_comprehensive` {keyword,publish_time} | GET `/bilibili/web/fetch_general_search` {keyword} |
| comments | GET `/douyin/app/v3/fetch_video_comments` {aweme_id,cursor,count} | GET `/xiaohongshu/app_v2/get_note_comments` {note_id} | GET `/weibo/web_v2/fetch_post_comments` {id,count} | GET `/kuaishou/app/fetch_video_comment` {photo_id} | GET `/bilibili/web/fetch_video_comments` {video_id} |
| profile | GET `/douyin/web/handler_user_profile_v4` {sec_user_id} 或 v2 {unique_id} | GET `/xiaohongshu/app_v2/get_user_info` {user_id 或 share_text} | — | — | — |
| posts | GET `/douyin/web/fetch_user_post_videos` {sec_user_id,max_cursor,count} | GET `/xiaohongshu/app_v2/get_user_posted_notes` {user_id,cursor} | — | — | — |

- weibo/kuaishou 时间窗参数沿用舆情侧枚举换算（xhs time_filter 中文枚举 / ks publish_time 英文枚举，抄 tikhub_collector.py:116-128）
- profile 的 douyin 双入口：`user_id` 参数带 `sec_uid:` 前缀走 v4，纯数字抖音号走 v2
- bilibili profile/posts 二期不做（形态未验证）

### 1.2 归一化输出（grounding + token 经济的关键）

统一信封：`{items:[...], _meta:{source:'tikhub', as_of:<now ISO>, endpoint, 不可复算:true, cost_note}}`

- search items：`{platform, url, title, text(≤300字), author, published_at, stats:{likes,comments,shares?}}`
- comments items：`{author, text(原话，≤300字), likes, ip_location?, published_at, url}`
- profile：单对象 `{platform, user_id, nickname, signature, follower_count, total_favorited, posts_count, ip_location, gender?, age?, region?}`
- posts items：`{platform, url, title, published_at, stats:{likes,comments}}`
- **URL 构造规则**（进 URL 真值集的唯一入口）：douyin 视频 `https://www.douyin.com/video/{aweme_id}`；xhs `{share_url 或 https://www.xiaohongshu.com/explore/{note_id}}`；weibo `https://m.weibo.cn/status/{wid}`；ks/哔哩用响应自带 url，无则省略
- 字段映射防御式：每字段候选名数组（openapi 字段名 → 实测可能漂移），全部未命中时该字段置 null 不报错——key 恢复后实测校准
- 中文枚举/时区换算集中在 normalizer，工具层不复用舆情侧代码（Python→TS 重写，~80 行/平台）

### 1.3 信封/重试/超时/截断（红线：自截断第一天就带）

- 信封：HTTP 200 且 JSON `code==200` 才算成功（抄舆情侧规则）；`401` → "TikHub key 失效，请管理员更新"；`402` → "TikHub 余额不足"；其余业务失败原文透传前 200 字
- 重试：仅 5xx/网络错误重试 1 次；401/402/404 不重试（确定性失败）
- 超时：单请求 30s（AbortController）
- **截断**：`truncateHead(JSON.stringify(result), {maxBytes:DEFAULT_MAX_BYTES, maxLines:DEFAULT_MAX_LINES})`（pi 规范 extensions.md:2170-2197）；另 items 硬上限 30 条（max_results 默认 20）
- fetch 失败 fail-closed：返回 `{error, guidance}` 不编造空数据

### 1.4 每轮调用上限（成本护栏核心）

- extension 模块级 `tikhubCallCount`，`before_agent_start` 置 0（验证器回灌轮算新轮，合理）
- `tool_call` 处理器：toolName ∈ tikhub 4 工具 → count+1；`>8` → `{block:true, reason:'本轮 TikHub 调用已达上限(8)，请基于已获取数据继续分析或如实声明数据缺口'}`（fail-closed，含缺口声明引导——与 gap_assumption_pattern 呼应）

### 1.5 key/env 管理（决策 4）

- 新建 `prism-api/.env`（gitignore）：`TIKHUB_KEY_PRISM=<用户 mint 的 Prism key>`
- `pi_gateway.mjs` spawn 时读该文件注入 env `PRISM_TIKHUB_KEY`（缺文件/缺 key → 不注入，工具运行时报"未配置"，不崩网关）
- `main.py`（python-dotenv）读同一 key 供 /tikhub/status 用；单源无双份维护
- 用户操作项：TikHub 后台 mint "Prism" key，scope 勾 douyin(web/app/search)、xiaohongshu(app_v2/web)、weibo(web_v2)、kuaishou(app)、bilibili(web)、tikhub/user——**记入 tasks M0 用户项**

## 2 · load_skill 工具 + skill 落地（决策 3）

### 2.1 load_skill（受限读取，替代被排除的 read）

```
参数：{name: string, file?: string}   // file 省略 = SKILL.md
校验：name /^[a-z0-9-]+$/；file /^[a-z0-9/_.-]+$/ 且 resolve 后必须仍在 <PROJECT_ROOT>/.pi/skills/ 内（防穿越）
读取：utf-8，truncateHead 50KB
返回：文件原文 + 目录内其他文件清单（提示 agent 可继续 load references/*）
```

- 注册 1 个工具 `load_skill`；**不依赖** pi 原生 skill 发现（trust/发现与否不影响可用性）
- `before_agent_start` 注入系统提示词追加一行：`可用技能：load_skill("car-reputation-research")——车型社媒口碑调研/典型用户深挖工作流（何时用/怎么用见 skill 内）。read 工具不可用，技能一律经 load_skill 加载`（~50 token 常驻成本，渐进披露；明示 read 不可用防 pi 原生发现教坏，见 self-check Gap1）

### 2.2 skill 内容（`.pi/skills/car-reputation-research/`，Prism 版改写）

- **SKILL.md**（~60 行）：触发词保留（口碑/舆情/车主反馈/提车作业/典型车主/KOC）；铁律=原文 6 条 + 新增 2 条（画像输出边界：人群理解颗粒度、不输出可定位个人的信息组合、溯源 URL 对管理者可见；成本纪律：TikHub 8 次/轮内工作、超限触发缺口声明范式）；流程 5 步保留，平台表换 TikHub 版；交付改为"调 export_document 出 xlsx（模板见 references/deliverable-spec.md）"
- **references/deliverable-spec.md**：模板 A/B 保留，对接 export_document 的 sheets 结构（headers/rows 对应）
- **references/platform-notes.md**：按 Prism 实际重写——抖音/小红书/微博/快手/哔哩=social_* 工具（免登录）；汽车之家=web fetch 游客全通（URL 格式 `{hash}/{topicid}-1.html` 实测）；删 CDP/MediaCrawler/3388 等全部 Claude Code 依赖；陷阱清单保留（媒体循环转载/上市初期真车主极少/口述日期以页面为准/评论区金矿）

## 3 · xlsx 导出（决策 5）

### 3.1 FastAPI（main.py）

- `POST /export`：body `{title, filename?, sheets:[{name, headers, rows, note?}]}` → openpyxl 生成（表头加粗+冻结首行+列宽自适应）→ 落 `prism-api/exports/{file_id}.xlsx` + manifest.json 登记 → 返回 `{file_id, filename, url:'/export/download/{file_id}', sheets:n}`
  - 校验：sheets≤20、每 sheet rows≤5000、cell ≤3000 字截断、filename 白名单 `[A-Za-z0-9_\-一-龥.]{1,60}`（不合法自动改 `export-{ts}`）
- `GET /export/download/{file_id}`：FileResponse（xlsx MIME），file_id 必须命中 manifest（防目录穿越）
- `GET /tikhub/status`：代理 `/tikhub/user/get_user_info` + `get_user_daily_usage`，10min 内存缓存；无 key → `{configured:false}`（不报错）

### 3.2 extension export_document 工具

- 参数：`{title, filename?, sheets:[{name, headers, rows, note?}]}` → POST /export → 返回 `{url, filename, sheets}`；**工具描述明确教**："在回复正文中用 markdown 链接给用户 url"
- vite.config.ts 加 `/export` 代理（与 /dash 同模式）；前端不改组件（markdown 链接渲染已有）

## 4 · 验证层接线（决策 2，零新验证器）

- `TOOL_CATEGORIES.web` 扩为 `{web_search, fetch_content, source_check, get_search_content, social_search, social_post_comments, social_user_profile, social_user_posts}`——decideTier/collectWebUrlsThisTurn/EXTRA_TOOLS 白名单派生三处自动生效
- 出口闸：**tikhub 数字不进 /verify/claim 台账**（无本地库）；agent 教学放在工具描述里："引用 TikHub 数据时标注 来源平台+URL+抓取时间+不可复算"（web tier 降级链路既有）
- `collectNameTruth` 扩：tikhub 工具的 `keyword` 参数值加入名称真值集（agent 引用的车系名来自查询词，天然可对齐）；_meta 校验仍仅 query_*（tikhub 无此协议，与舆情同）
- 社媒轮无 resolve_series 强制（对象是"车型社媒口碑"非库内分析）——身份强制移除 change 已定执行层判据只管 library tier，天然不触发

## 5 · 评估（2 道 smoke 题，skip-if-no-key）

- `social-01`：搜小红书"风云T7 提车"，给 3 条带 URL 引语 → 验 URL 真值集命中 + 引语可溯源
- `social-02`：抖音查作者A（sec_uid 已知）画像，输出粉丝数/获赞/作品数并标注不可复算+抓取时间 → 验 web 降级路径不误伤
- 进 eval 任务集（runner 16→18），无 key 自动 skip 不计入分母

## 6 · 测试设计

| 层 | 文件 | case |
|---|---|---|
| 单测 node:test | tests/tikhub_tools.test.ts | 归一化（fixtures 5 平台）、信封 401/402/5xx、items 上限、每轮计数 block（导出计数器函数直接测） |
| 单测 node:test | tests/load_skill.test.ts | 合法加载/穿越拒绝（../、绝对路径、大写）/file 参数合法引用加载 |
| API 测试 pytest | prism-api/tests/test_export_api.py | POST /export 往返（openpyxl 读回校验单元格）、下载命中 manifest、filename 白名单、rows 超限 422 |
| smoke 集成 | 既有 smoke:all | 无 key 时工具 fail-closed 文案（mock env 缺失路径） |
| E2E | 手工 | M5 风云T7 重跑（依赖 key） |

fixtures 来源：key 恢复前用 openapi 字段名手造最小样例（标 TODO-verify）；key 恢复后真实调用录制替换。

## 7 · 前端改动（最小）

- vite.config.ts：+/export、+/tikhub/status 代理
- 余额黄灯：状态栏 chip（KanbanView statusbar 数据源加 /tikhub/status，configured && balance<$5 黄点）——P2 优先级，M4 内做，若挤则挪二期不阻塞
