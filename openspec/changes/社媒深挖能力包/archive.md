# Archive · 社媒深挖能力包

日期：2026-10-12 · 十步流程：Step1 explore → Step2 propose（四件套）→ Step3.5 自查（7 Gap）→ Step5 施工（M1-M4）→ Step6 simplify → Step7 code-review → Step8 修复 → Step9 verification → Step10 archive

## 一句话

把用户的"风云T7 典型用户分析"个人工作流（Claude Code skill + CDP 登录态抓取）产品化进 Prism：TikHub 付费 API 包装成 4 个 social_* 工具（免登录、可上云、web tier 降级验证），skill 方法论经 load_skill 受限读取落地，xlsx 导出闭环（export_document + /export）。

## 交付物

| 层 | 物件 |
|---|---|
| 工具 | `.pi/extensions/prism-guardrails/tikhub.ts`（端点映射 5 平台×4 动作/归一化/信封/截断/每轮计数器）+ index.ts 注册 4 工具 |
| 技能 | `.pi/extensions/prism-guardrails/skills.ts`（load_skill 防穿越双闸）+ `.pi/skills/car-reputation-research/` 三件套（Prism 版：TikHub 平台表/画像边界铁律/成本纪律/分轮推进）|
| 导出 | prism-api main.py `/export` + `/export/download/{id}` + `/tikhub/status`；extension export_document |
| 接线 | TOOL_CATEGORIES.web+4 工具、utility+load_skill/export_document；before_agent_start 计数清零+技能指针行；tool_call 8 次/轮 block；tool_result social_* keyword 名称真值 |
| 评估 | eval 2 题（social-01/02，requires_tikhub skip-if-no-key）+ tests/social_wiring.test.ts 6 锚 |
| 前端 | KanbanView 社媒API 黄灯 chip；vite /export、/tikhub 代理 |
| 配置 | prism-api/.env.example（TIKHUB_KEY_PRISM 单源两用）+ pi_gateway env 注入链 + 根 .gitignore |

## 关键决策（拍板记录）

6 项用户拍板（2026-10-12）：工具按功能切 4 个 platform 参数化 / tikhub 归 web 类（零新验证器）/ load_skill 方案 A / 另 mint "Prism" 专用 scoped key / xlsx only / 8 次每轮+$5 黄灯+调用留痕。

## 意外收获（存量 bug 治本）

URL 真值集正则在第一个 `.` 截断（collectWebUrlsThisTurn + verifyWeb 双侧对称掩盖，防编造 URL 检查实际失效）——由 social_wiring 单测打出，本 change 一并修复。

## Step7 code-review 结论

独立 agent 全量审查（重派一次：首个子代理无文件读取工具阻塞，换全工具型完成）：**无 P0；3 P1 + 11 P2；红线专项全过**。P1=社媒评估题判据（已修：社媒题证据=URL+抓取时间）/time_window 静默失真（已修：不支持显式拒+生效过滤进 _meta）/export 非法字符（已修：清洗+实测 200）。

## Step8 修复记录

P1 3/3 + P2 8/11 修复（明细见 review-response.md）；修后 smoke:all **83/0** + tsc 基线 + pytest 全过 + 全栈重启实测（含控制字符导出/表名清洗复验）。P2 留 3 条：manifest 锁（单worker原子，多worker前改jsonl）/SKILLS_ROOT cwd 锚定（与既有惯例同病，上云前统一治）/动态题集社媒 skip（设计内）。

## M5 验收实录（2026-10-12 深夜，key 就位后）

- **key 决策反转**：用户拍板不 mint 专用 key，复用舆情同串（prism-api/.env 已填）
- **401 乌龙结案**：全程是我方提取 bug——bash `cut -d= -f2` 吃掉 Base64 key 尾部 `==`（58≠60），拿截断 key 测 6 轮全 401；"token 作废/到期"推断全错，key 从未失效（get_user_info 200/"舆情项目"/70 scopes）。教训：含 `=` 的值禁用 cut -d= 解析
- **七端点全弹校准**（实测响应驱动 5 处修正）：douyin search POST body 须全字符串（数字 422）；douyin 作品列表 web 版恒 400（TikHub 侧坏）→ app/v3 版；列表路径 douyin=xhs/ks/weibo 各自包装层（aweme_info/note/feed）+ 归一化根是剥信封对象（单段 'data'）；weibo 用 parsed_data.results 新字段 + post_url 协议相对补 https；广告卡空项过滤；`interaction.like_count` 候选补齐。修后 7/7 全通（profile 1/posts 5/xhs 20/douyin 7/weibo 24/ks 10/bili 20，全带 URL）
- **E2E 风云T7 闭环**（33s 单轮零回灌）：load_skill→resolve_series(8660)→social_search×2→social_post_comments×2→再载技能取交付规范→export_document；xlsx 实测合格（双 sheet 含"说明与来源"/表头 平台·作者·引语·URL·抓取时间/真实车主引语"我要上岸""枕着清风"等 6 URL+时间戳）；信源分级生效（过滤经销商内容）；发现短板=正文不带 URL → 工具描述加"回复正文逐条附 URL"强约束，修后 social-01/02 双 5 分
- **T5.4 混合轮**：query_reviews（行ID+as_of 严格）与 social_search（URL 降级）同轮并存，出口闸 4 次提交后过闸零回灌
- **fixtures 真实化**：raw+归一化双份落 eval/artifacts/tikhub-raw|tikhub-fixtures/，单测 fixture 全部换真实形态，TODO-verify 清零
- 18 题全量回归：后台跑（logs/eval_full_20261012.log），前 4 题（cross-01~03）满分

## 留下一轮（非阻塞）

- 18 题全量回归分数归档（跑完后记入 EVAL_STATUS.md）
- 余额字段形态：get_user_info 的 data 空对象，余额疑在 get_user_daily_usage——/tikhub/status 黄灯阈值待接真实字段
- bilibili user profile/posts 二期；docx 导出二期；KS 深翻页（overlap 停止条件抄舆情侧）二期
- 正文口径声明措辞（"不可复算"字样 agent 常省略）——观察项，暂不加硬约束

## 运维必记

- key 配置：`prism-api/.env` → `TIKHUB_KEY_PRISM=`（.env.example 有 scope 勾选清单）；网关重启后生效（读文件一次缓存）
- 工具上限：8 次/轮是 fail-closed block（tool_call 层），agent 提示词与技能铁律双教
- 新工具全景：21 业务 + social_* 4（web）+ load_skill/export_document（utility）+ web 4 + ask_user
