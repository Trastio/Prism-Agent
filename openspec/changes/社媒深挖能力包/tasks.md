# Tasks · 社媒深挖能力包

## M0 前置（用户项，不阻塞施工）

- [x] U0.1 ~~mint Prism 专用 key~~ → 用户拍板改为**复用舆情 key 同串**（2026-10-12），已填 `prism-api/.env`
- [x] U0.2 ~~401 调查~~ → **实为我方提取 bug**（cut -d= 吃掉尾部==），key 从未失效（get_user_info 200/"舆情项目"/70 scopes），舆情采集按周期正常
- [x] U0.3 我：prism-api/.env 模板 + .gitignore 登记（代码部分，M1 内做）

## M1 TikHub 工具组（关键路径）

- [x] T1.1 makeTikhubTool 工厂 + ENDPOINT_MAP 五平台（specs/tools-tikhub T1/T2；施工前重拉 openapi.json 核对五平台**全部**端点参数，bilibili 异常则降四平台，Gap6）
- [x] T1.2 normalizer：统一信封/URL 构造/防御式映射/items≤30 + fixtures（openapi 字段手造，标 TODO-verify）
- [x] T1.3 信封+重试+超时+截断（401/402 语义化；truncateHead）
- [x] T1.4 每轮计数器（可测函数）+ tool_call block>8 + before_agent_start 清零（验收含**回灌轮实测**：连续两轮第二轮第 1 次不被 block，Gap2）
- [x] T1.5 env 注入链：pi_gateway 读 prism-api/.env → PRISM_TIKHUB_KEY；无 key fail-closed
- [x] T1.6 TOOL_CATEGORIES.web 扩 4 工具 + 工具描述教学（引用格式/上限/评论区金矿）
- [x] T1.7 tests/tikhub_tools.test.ts（归一化/信封/计数 block/截断，无 key 可全测）

## M2 技能层

- [x] T2.1 load_skill 工具（allowlist+防穿越+文件清单）+ tests/load_skill.test.ts
- [x] T2.2 before_agent_start 技能指针行（不改 AGENTS.md 文件）
- [x] T2.3 .pi/skills/car-reputation-research/ 三文件 Prism 版改写（SKILL.md 8 铁律/两 references）

## M3 导出

- [x] T3.1 main.py POST /export + GET /export/download/{id}（manifest+校验+openpyxl 样式；确认鉴权中间件范围，download 浏览器直链可下载，Gap4）
- [x] T3.2 GET /tikhub/status（代理+10min 缓存+configured:false 路径；main.py 无 load_dotenv 则补，Gap5）
- [x] T3.3 extension export_document 工具（描述教 markdown 链接）
- [x] T3.4 prism-api/tests/test_export_api.py（往返读回/filename 白名单/超限 422/404）
- [x] T3.5 vite.config.ts +/export +/tikhub/status 代理

## M4 验证接线 + 评估 + 收尾

- [x] T4.1 Spec4 T1-T4 实测验证（tier/URL 真值集/name truth/出口闸一致性）
- [x] T4.2 eval 2 题（social-01/02）+ runner skip-if-no-key
- [x] T4.3 状态栏余额 chip（P2，挤则挪二期）
- [x] T4.4 smoke:all 全绿（55→新增不回归）+ tsc 零新增错

## M5 E2E 验收（依赖 U0.1 key）

- [x] T5.1 fixtures 真实化：5 平台各录一份真实响应，校准 normalizer 字段映射，删 TODO-verify
- [x] T5.2 风云T7 重跑：Prism 独立产出典型用户分析 xlsx（模板 B），与手工版对照（画像字段/引语可溯源/溯源清单完整）
- [x] T5.3 social-01/02 实跑通过；16+2 全量不回归
- [x] T5.4 混合轮实测：社媒+query_reviews 同轮，库侧严格+社媒降级告警并存

## Step6-10

- [x] S6 simplify
- [x] S7 code-review
- [x] S8 receiving-review
- [x] S9 verification（proposal 验收 6 条；key 未恢复则 M5 单列 blocked-pending-key）
- [x] S10 archive

## M6 前端能力可见化（用户追加，2026-10-12）

- [x] T6.1 main.py GET /skills：读 .pi/skills frontmatter（name/description/version/引用文档数），与 load_skill 同源
- [x] T6.2 SkillsPanel：工作流技能区置顶接真数据（GET /skills，fail 落空）+ 原"内置能力"区保留
- [x] T6.3 ChatView SUGGESTIONS 双分支加社媒调研建议词
- [x] T6.4 vite /skills 代理；tsc 0 错 build 过；/skills 实测返回 car-reputation-research
- 注：M6 期间一次纠缠命令链 spawn 了 3 个 runner 进程互相污染 eval 会话——已全杀+清 eval_* 会话目录+单进程重跑（r3）
- [x] T6.5 用户拍板：能力总览移除护栏机制区（内部红线不对用户展示），仅留 工作流技能+数据工具 两区；tsc 0 错 build 过
