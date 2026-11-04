# Verification · 社媒深挖能力包（Step9）

日期：2026-10-12 · 验证人：施工会话 · code-review 结论：见文末补记

## Proposal 验收 6 条对照

| # | 验收条 | 结果 | 证据 |
|---|---|---|---|
| 1 | smoke:all 全绿（含新增单测） | ✅ | 82 pass / 0 fail（tikhub 15 + load_skill 4 + social_wiring 6 新增，既有 57 不回归）；根 tsc 11=历史基线零新增；web tsc 0 错 build 2.28s |
| 2 | 无 key 时 4 工具 fail-closed 报"未配置" | ✅ | 单测（executeAction 无 key 路径）+ **实机**：真实会话调 social_search 返回 `{"status":"unavailable","reason":"TikHub 未配置（PRISM_TIKHUB_KEY 缺失，请联系管理员在 prism-api/.env 配置）"}`（session jsonl 实录） |
| 3 | 每轮第 9 次调用被 block | ✅（代码+单测）| tikhubCounter bump 第 9 次返回超限（单测）；tool_call hook block 文案含缺口声明引导；**回灌轮清零**：before_agent_start 每次 agent run 触发（既有身份判据同路径佐证）+ 单测 reset 后恢复；RPC 实机回灌轮验证留 M5（key 后 E2E 顺带） |
| 4 | load_skill 路径穿越被拒 | ✅ | 单测 4 case：`../secrets`、`../../prism-api/.env`、大写名、绝对路径 `C:/Windows/win.ini` 全拒；正则+resolve 前缀双闸 |
| 5 | /export 往返出合法 xlsx | ✅ | pytest 5 case（openpyxl 读回单元格一致/filename 白名单/rows 超限 422/404）+ **实机**：POST /export → GET download 200 xlsx MIME 4969B |
| 6 | key 恢复后 E2E 风云T7 重跑 + 2 道 smoke 题 | ⏸ blocked-pending-key | M5 显式依赖 U0.1（用户 mint Prism key）；runner skip 逻辑已实测就位（/tikhub/status configured:false → SKIP 不计分母） |

## Spec 级补充验证

- **Spec1（工具）**：ENDPOINT_MAP 参数按 2026-10-12 openapi 全核对（bilibili search 三必填 order/page/page_size 进单测断言）；归一化五平台 fixture 过；信封 401/402 语义化文案；自截断 50KB/2000 行（>2000 行 fixture 验 truncated 标记）
- **Spec2（技能）**：load_skill 实机返回完整 SKILL.md（agent 回复引用五步流程表）；技能指针行进系统提示词（before_agent_start 实机生效）；三文件无 Claude Code 残留（grep 仅命中来源标注元数据）
- **Spec3（导出）**：见验收 5；/tikhub/status 实机 {configured:false} 不报错；鉴权中间件只拦 /autohome/ 前缀写端点 → /export/download 浏览器直链可下载（Gap4 解除实测）
- **Spec4（验证接线）**：decideTier 纯社媒=web/混合=mixed（单测+回归锚纯库=library 不变）；collectWebUrlsThisTurn 收 social_* 输出 URL 进真值集（单测）；数值台账隔离（social_* ∉ business 类，单测）；名称真值 keyword 分支（代码路径+实机无 name 误报：实机会话 settled=1 零回灌）

## 意外收获：存量 URL 正则 bug 治本

写 social_wiring 单测时打出：`collectWebUrlsThisTurn`/`verifyWeb` 的 URL 正则把 `.` 列入排除集——**真值集与回复 URL 双侧都在第一个点截断**（`https://www`），对称掩盖使检查从不误报但也几乎无区分度（同主域任意 URL 可互相冒充）。本 change 一并修复（URL 内允许点号，尾缀清理保留），web tier URL 防编造检查自此真正生效。已记入 EVAL_STATUS.md。

## Step7 code-review 补记

独立 agent 全量审查（8 文件逐行）：**无 P0；3 P1 + 11 P2；红线专项全过**（fail-closed 处处成立/自截断落地/key 无泄漏路径/防穿越三重闸/计数器时序正确）。P1：①social 评估题判据结构性不及格 ②time_window 静默失真（口径红线贴脸）③/export 非法字符 500。

## Step8 修复复验

P1 3/3 全修（P1-3 实机复验：含控制字符+非法表名导出 200、表名已清洗、rows_dropped 正确）；P2 8/11 修（见 review-response.md）；留 3 条记录在案。修后全量：**smoke:all 83/0** + tsc 11 基线零新增 + pytest 全过 + 全栈重启五服务绿 + 实机 /export 往返复验。

## 留下一轮 / blocked

- M5 三项全量（fixtures 真实化/风云T7 重跑/social 题+回灌轮实跑）——blocked on U0.1 key
- TikHub 余额字段形态（/tikhub/status 的 balance 捞取键名 + 前端黄灯阈值）——key 后实测校准
- 归一化字段映射 TODO-verify 清账——同上（fixtures 手造已标）
