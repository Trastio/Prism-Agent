# Step5 施工笔记 · 登录门禁（2026-10-15）

> 施工：auth-gate-build-r2 子代理（fork 型；工具面守卫：正则全量列举漏检文件工具，select: 命中 Bash/Read/Write——与既有教训一致；SubagentHandback 不在本工具面，笔记落盘交付）

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `prism-api/main.py` | ①auth 块（~127-240 行）：AUTH_SECRET（env PRISM_AUTH_SECRET，缺省 dev 回落+启动 WARN）/users.json bootstrap（scrypt 盐哈希 666666）/token 签验（HMAC-SHA256，base64url payload.sig，exp 7d）/`auth_gate` 中间件（豁免 /auth/login /health /OPTIONS 预检；注册于 manager_auth 后=外层先执行；进程内 `app.state.auth_bypass` 仅供离线测试）②`/auth/login`（恒时比较，401 固定文案"用户名或密码错误"，username 白名单 ^[A-Za-z0-9_-]{1,32}$）+`/auth/me` ③`resolve_user_id`（token 优先，自报值仅旁路态回落）④**6 处调用点换血**：/chat/stream、/chat/abort、/session GET+POST、/session/rename、/session/messages（各补 Request 形参） |
| `prism-api/tests/conftest.py` | 新增：import main 前设 PRISM_AUTH_SECRET=pytest-secret；app.state.auth_bypass=True（既有 15 例离线用例零改动通过） |
| `prism-api/tests/test_auth.py` | 新增 10 例：登录成功+cookie 属性/admin 白名单/错密码 401/非法用户名 400/无 token 业务路由 401（dashboard+session+abort）/带 token 200（4436 锚）/过期 token/伪造 token/resolve_user_id 覆盖语义直测/users.json 无明文 |
| `.gitignore` | + `prism-api/data/users.json` |
| `prism-web/src/lib/auth.ts` | 新增：AuthUser 态+subscribe/fetchMe/login/`install401Interceptor`（包装 window.fetch，同源 401→广播 prism:unauthorized；不拦 /auth/*） |
| `prism-web/src/components/LoginGate.tsx` | 新增：登录页（用户名+密码，错密码提示，设计令牌化样式） |
| `prism-web/src/App.tsx` | 三态门控（checking 闪屏→LoginGate→主树）；未登录不挂载 ChatView/埋点/看板 iframe；401 广播→断流+回登录页；initTracker 改为 authUser 就绪才启 |
| `prism-web/src/lib/chat.ts` | getUserId：登录态用户名优先（与后端 resolve_user_id 对齐），legacy localStorage 仅未登录窗口期兜底 |
| `prism-web/src/styles.css` | +登录页样式（--bg/--surface/--accent 令牌，无新依赖） |
| `eval/runner.mjs` | ensureLogin（main() 首步；PRISM_EVAL_USER 缺省 eval/PRISM_EVAL_PASS 缺省 666666；失败 fail-loud exit 1；dry-run 自跳过保持离线可验）+ authHeaders() 挂 4 处 fetch（chat/stream×2、chat/abort、tikhub/status） |

## 验证输出（原样）

- `pytest prism-api/tests/` → **25 passed in 5.15s**（既有 15 零回归 + auth 10 新增）
- `npx tsc --noEmit` → 0 错（修复过 1 处旧名 setAuthUser→setAuthState 后复检）
- `npm run build` → ✓ built in 6.90s
- `node --check eval/runner.mjs` + `--dry-run` → 正常（60 题列出+run_id 元数据）
- `node --test eval/report_lib.test.mjs` → 16/16（runner 改动零回归）

## 设计偏离与理由（供 Step7 审查重点核）

1. **全局 dependency 改为 HTTP 中间件**：指令写"FastAPI Depends 挂 app 级"，但全局 dependencies 无法豁免 /auth/login（循环：登录前无 token）。改用 `@app.middleware('http')` 与既有 manager_auth 同款范式，豁免表清晰；效果等价（全路由拦截）。
2. **app.state.auth_bypass 测试旁路**：非 env/非配置文件，仅同进程可设（conftest 置 True，test_auth 按需关闭）。生产部署无触达路径；比 env 开关安全（无环境变量误配风险）。
3. **/ui-response、/export、/events 等未做 user_id 覆盖**：这些端点不以 user_id 做身份（events 记 session_id/local_id；export 按 user_id 目录只影响归因不影响越权——跨用户读会话的口子在下步网关侧评估）。门禁 401 已保护；user_id 覆盖只做了"身份消费型"6 端点。Step7 可裁。
4. **runner 的 tikhub/status 探测带 cookie**：属门禁后必要适配（GET 也被拦），非设计偏离。

## 需主会话 Step9 验证的事项（本施工未做，按纪律不重启服务）

- 冷重启 api+web 后：未登录 curl 业务路由 401 逐路由抽验（proposal 验收 1）；/auth/login→带 cookie 200 全链
- 浏览器走查：登录页渲染/错密码提示/7 天免登录（cookie）/看板 iframe 正常（同源 /dash 反代带 cookie）
- eval 真跑 1 题（ensureLogin 实链路）
- users.json 已由测试 bootstrap 生成于 prism-api/data/（gitignored，无明文）
