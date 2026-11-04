# Proposal · 社媒深挖能力包

日期：2026-10-12 · 状态：用户已拍板 6 项决策（见下）

## WHY（一句话）

用户的真实工作流（风云T7 典型用户分析，靠个人 Chrome 登录态 + Claude Code 手工跑）要产品化进 Prism：用 TikHub 付费 API 替代登录态抓取，让 49 人未来都能用"社媒深挖"能力，且全程在既有红线体系内（web tier 降级验证 + 溯源 + fail-closed）。

## WHAT（三件套，互相依赖故合一个 change）

1. **TikHub 工具组**：extension 注册 4 个功能工具（social_search / social_post_comments / social_user_profile / social_user_posts），platform 参数化；归一化输出（每条带 URL）；自截断（50KB/2000 行，第一天就带，不等线 B）；每轮调用上限 8 次（tool_call 护栏）+ 余额探针端点。
2. **用户分析 skill 落地**：`load_skill` 受限读取工具（pi 原生 skill 加载因 read/bash 被排除而断，此为替代）+ `.pi/skills/car-reputation-research/`（SKILL.md 按 Prism 实际改写：TikHub 平台表/画像输出边界/成本纪律/导出对接）。
3. **xlsx 导出**：FastAPI `POST /export`（openpyxl 3.1.5 已在 venv）+ `GET /export/download/{id}` + extension `export_document` 工具 → 交付物闭环（deliverable-spec 模板 B）。

## 已拍板 6 决策（用户 2026-10-12）

| # | 决策 | 内容 |
|---|---|---|
| 1 | 工具切分 | 4 功能工具，platform 参数化，不按平台切 |
| 2 | 分类归属 | 4 工具并入 TOOL_CATEGORIES.web → tier 路由/URL 真值集/白名单派生零新逻辑 |
| 3 | skill 加载 | load_skill 工具（allowlist 目录受限读取，保渐进披露）+ before_agent_start 注入一行指针 |
| 4 | key 策略 | 用户在 TikHub 后台另 mint "Prism" 专用 scoped key（douyin/xhs/weibo/kuaishou/bilibili + tikhub/user）；`prism-api/.env` 单源，网关注入子进程 |
| 5 | 导出形态 | export_document 工具 + /export 端点，xlsx only（docx 二期） |
| 6 | 成本护栏 | 每轮 TikHub 调用 ≤8（tool_call fail-closed）+ 调用留痕走既有 tool_call 事件 + /tikhub/status 余额探针（10min 缓存） |

## 影响范围

- `.pi/extensions/prism-guardrails/index.ts`：+4 tikhub 工具、+load_skill、+export_document、+每轮计数器、collectNameTruth 扩 keyword、TOOL_CATEGORIES.web 扩 4 工具
- `prism-api/main.py`：+/export、+/export/download、+/tikhub/status
- `prism-api/pi_gateway.mjs`：读 prism-api/.env 注入 PRISM_TIKHUB_KEY
- 新增 `.pi/skills/car-reputation-research/`（SKILL.md + references×2）
- `prism-web/vite.config.ts`：/export 代理
- eval：+2 smoke 题（skip-if-no-key）
- 测试：tikhub 工具单测（fixtures）、load_skill 路径守卫、/export API 测试

## 风险

1. **TikHub 响应结构未实测**（key 失效阻塞）——归一化器按 openapi 字段防御式映射，key 恢复后补实测与 fixtures，E2E 前修
2. key 恢复时间不可控——M5 验收（风云T7 重跑）显式依赖 key，其余里程碑不依赖
3. 成本：8 次/轮 × 搜索~$0.01-0.05/次——单轮最坏约 $0.4，护栏内可控；余额黄灯兜底
4. bilibili 端点形态最未验证——social_search/comments 含 bilibili，user_posts 二期

## 验收（Step9 用）

1. smoke:all 全绿（含新增单测）；2. 无 key 时 4 工具 fail-closed 报"未配置"（不静默）；3. 每轮第 9 次 TikHub 调用被 block；4. load_skill 路径穿越被拒；5. /export 往返出合法 xlsx（openpyxl 读回校验）；6. key 恢复后：E2E 风云T7 重跑产出可对照 xlsx + 2 道 smoke 评估题通过。

## 不做边界

- 不做：TikHub 结果落库、MCP 化、docx 导出、bilibili user_posts、跨会话记忆、自动定时采集（那是舆情 Board 的管线）
- 不碰：舆情 Board 12 写端点、其 .env（key 用新 mint 的 Prism key，同账户不同 token）
- 不进 /verify/claim 行 ID 台账（web tier 降级验证本就是为不可复算源设计——已排除路径见 explore）
