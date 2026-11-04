# Step7 隔离审查处置记录（登录门禁 · 2026-10-15）

> 审查者：auth-gate-review 子代理（代码磁盘提取内嵌）｜ 结论：**P0=0 / P1=2 / P2=10**
> 处置：修 4 + 实锤修 1 / 化解 1 / 记录上云清单 6+ ｜ 修后 pytest 25/25 + tsc 0 错 + build ✓

## P1 处置

| # | 发现 | 处置 |
|---|---|---|
| P1-1 | dev 固定密钥回落可离线伪造含 admin 的合法 token（源码内公开串） | **修**：`PRISM_ENV=prod` 且无 `PRISM_AUTH_SECRET` → **启动 raise 拒启**（fail-closed 入执行层，红线#5 精神）；本地 dev 保留回落+WARN |
| P1-2 | 门禁覆盖面疑虑（/dash 反代归属 + iframe 直连子服务） | **核实化解**：iframe src 全走 `/dash/*` 相对路径（vite→8002 反代→gate 覆盖），8010 不直接暴露浏览器；/dash 反代在 api 层（dash_as_of 注释实证）。**附带发现**：舆情 board 静态资源 `/static` `/api/dashboard` 走 vite 直连 8000（无门禁）——静态 JS/CSS 无业务数据，属"子服务本地不拦"拍板边界，记录 |

## 审查"需人工确认"六项核实结果（主会话）

1. manager_auth 在 :62 `@app.middleware` 注册、auth_gate 在 :154 后注册=外层先执行 ✓ 声明正确
2. `app.state` 全文件唯一读点=gate 内 getattr，无写点（写点仅 conftest）✓ 旁路安全坐实
3. iframe 全走反代 ✓（P1-2 化解）
4. `validate_user_id` 消费点已全部收敛进 `resolve_user_id`，无第 7 处 ✓
5. **vite proxy 枚举表无 `/auth` —— 实锤 P1 修复**：单测/runner 直连 8002 全绿掩盖了浏览器登录 404；vite.config.ts 补 `/auth` 转发
6. 浏览器登录链路人工走查 → Step9（tabbit）

## P2 处置

| # | 发现 | 处置 |
|---|---|---|
| P2-1 | users.json 非原子写+损坏静默重置回默认密码+缓存永不失效 | **修**：tmp+os.replace 原子写；mtime 失效缓存（改密/白名单热生效）；损坏重置前显式 WARN |
| P2-2 | token 无吊销/logout/jti（登出=等 7 天） | 记录上云清单（/auth/logout+短 TTL+token_ver） |
| P2-3 | login 无速率限制（10^6 密码空间可穷举） | 记录上云清单（失败锁定+IP 限速） |
| P2-4 | 共享密码下 admin 白名单无独立凭证（分层装饰性） | 记录（拍板形态已知；上云 per-user 或 admin 二次凭证） |
| P2-5 | cookie 无 secure 标志 | 记录环境分叉（HTTPS 时 secure=True） |
| P2-6 | runner PRISM_EVAL_PASS 缺省 '666666' 明文 | 记录（与 main.py bootstrap 字面量同源，本地便利；改密时同步改 env） |
| P2-7 | web 拦截器盲区（绝对 URL/EventSource/iframe 内 401 不冒泡） | 记录（全站相对路径为既有约定；iframe 面已由反代+gate 覆盖） |
| P2-8 | LoginGate 400 与 401 混同一文案 | **修**：login() 返回 LoginResult{user,error}，400"用户名或密码格式不合法"与 401"密码错误"分开展示 |
| P2-9 | 明文断言测试单跑脆弱+未断言哈希形态 | **修**：先 _users() 再读文件 + pwhash `[0-9a-f]{128}`/salt `{32}` 断言（审查猜的 96 hex 有误，scrypt dklen 默认 64→128 hex，已按实际断言） |
| P2-10 | gated fixture 无 try/finally | 不修（pytest teardown 语义保证 yield 后执行，纯防御） |

## 验证

pytest 25/25（含 P2-9 加固）/ tsc 0 错 / build 6.52s ✓。冷重启全链验证与浏览器走查见 verification.md（Step9）。
