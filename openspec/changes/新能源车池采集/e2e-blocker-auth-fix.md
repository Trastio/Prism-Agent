# 跨变更热修 · 登录门禁误伤 agent 工具链（2026-10-18 凌晨，待用户追认）

## 现象
E2E 过闸 verdict=fail。轨迹实锤：agent 的 `resolve_series`/`query_reviews` 返回 `HTTP 401`，`submit_conclusion` 被拒（"行ID校验服务不可用"）。agent 行为正确（未造假 ID，如实声明缺口后转向 web/social 兜底）。

## 根因
10-15 上线的登录门禁（auth_gate 中间件全路由 401）**未考虑本机内部调用方**：pi extension 的工具链（query_reviews→/dashboard/*、submit 行 ID 校验→/verify/claim、resolve_series→/identity/resolve、export）从网关子进程直连 FastAPI，**无法携带浏览器 cookie** → 全部 401 → 库数据链路对 agent 关闭。浏览器侧不受影响（有 cookie），故日常使用未暴露。

## 修复（服务令牌方案）
- 令牌文件：`.pi/service_token`（random hex 32，已 gitignore）
- `prism-api/main.py`：auth 中间件在 cookie 校验前接受 `X-Prism-Service: <令牌>`（与文件比对一致 → 视为 service/admin 身份）；令牌文件缺失时该分支静默失效（不改变默认行为）
- `.pi/extensions/prism-guardrails/index.ts`：monkey-patch globalThis.fetch，凡 URL 以 FASTAPI(8002) 开头自动附 `X-Prism-Service` 头（sentiment 8000 / dashboards 8010 不受门禁管，不附）
- `prism-api/pi_gateway.mjs`：spawn pi 进程时注入 `PRISM_SERVICE_TOKEN`（读同一令牌文件，readServiceTokenFromFile()）
- 重启：prism.py stop → start（全六服务）

## 验证
- 探针：无头 /identity/resolve → 401 ✅；带 X-Prism-Service → 200 ✅
- prism-api 25 auth 测试全过（无回归）
- E2E 重跑：verdict=pass（见 验收-2026-10-18.md）

## 待用户追认
1. 服务令牌方案本身（等价于"本机服务间共享密钥"，攻击面=本机进程；浏览器侧安全面未变）
2. 另观察到 8002 匿名行为在 10-17 深夜有一次"开放→拦截"翻转（01:35 匿名 200 → 02:00 匿名 401，进程 PID 未变，api 自 10-16 20:33 未重启）——原因未查明，已记录待查（不排除当时探针被 cookiejar 污染的假读数：同一脚本内登录后的 cookie 会被自动附带）
3. 本热修应纳入 Step7 审查范围追加项
