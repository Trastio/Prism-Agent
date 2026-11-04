# verification · 登录门禁（2026-10-15）

## 验证矩阵（全部主会话实跑）

| 项 | 结果 | 证据 |
|---|---|---|
| api 单测 | **25/25 绿**（10 auth 例：成功/错密码/非法用户名/无token×3路由/带token含4436锚/过期/伪造/覆盖语义/无明文+哈希形态断言） | pytest |
| tsc + build | 0 错 / 6.52s ✓ | prism-web |
| eval 零回归 | 16/16 + dry-run 正常 | node --test |
| 冷重启 | 六服务全绿（api+web 载入新代码） | prism.py |
| **401 逐路由抽验** | /dashboard /session /dash/as_of /auth/me /export /identity /chat/abort /verify 全 **401**；/health 豁免 200 | httpx 实测 |
| 登录链路 | 错密码 401 固定文案 ✓ → 对密码 200 role=viewer ✓ → /auth/me 恢复 ✓ → 带token业务 200（4436+as_of）✓ | httpx |
| **vite 代理链路** | 5173/auth/me→401；5173/auth/login 对密码→200 错密码→401 文案正确（**Step7 审查⑤实锤修复的闭环验证**） | curl |
| E2E 真对话 | HTTP 200 / settled verdict=pass | user_id=spoofed 自报 |
| **user_id 防冒用实证** | 登录态 tester 查 `?user_id=spoofed_user` → 返回 **tester 的会话列表**（token 覆盖生效，spoof 无效） | httpx |

## Step7 审查

auth-gate-review 子代理：P0=0 / P1=2 / P2=10 → **修 4+实锤修 1 / 化解 1 / 记录上云清单 6+**，见 review-response.md。
- P1-1 dev 密钥回落 → `PRISM_ENV=prod` 无 secret **拒启断言**（fail-closed 入执行层）
- P1-2 iframe 旁路疑虑 → 核实化解（iframe 全走 /dash 反代，gate 覆盖）
- 审查"需人工确认⑤"抓出真雷：**vite proxy 枚举表无 /auth**（单测/runner 直连 8002 全绿掩盖浏览器 404）——已修+闭环验证
- 六项确认全数核毕：中间件顺序正确 / app.state 唯一写点=conftest / 无第 7 处 user_id 消费点

## 偏差与遗留（如实）

- **浏览器渲染走查降级**：Tabbit 浏览器实例 newPage CDP 通道故障（Target.createTarget 无法派发，两 task 复现，与代码无关）——API 层+vite 代理层全验，登录页/主站渲染留用户浏览器一眼（5173 已开）
- 上云必须清单（审查 P2 沉淀）：换强密码+HTTPS+secure cookie / PRISM_AUTH_SECRET 强制 / login 速率限制+失败锁定 / logout+短TTL+token吊销 / admin 独立凭证 / users.json 损坏告警
- 子服务边界（拍板内）：8000/8010/8020 本地不拦；舆情 board 静态资源 /static 走 vite 直连 8000（无业务数据）

## 归档结论

统一口令门上线：进站必过 用户名+密码（666666），全业务路由 token 保护，user_id 服务端签发防冒用，eval 通道自动登录。权限分层 admin/viewer 保持。上云前按清单升级。
