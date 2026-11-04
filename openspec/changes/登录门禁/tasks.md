# 登录门禁 · 任务单（2026-10-15 十步走完归档）

- [x] T1 api：auth 块 + /auth/login + /auth/me + auth_gate 中间件全路由拦截（豁免 login/health/OPTIONS）+ PRISM_ENV=prod 无密钥拒启（P1-1 修复）
- [x] T2 api：resolve_user_id token 优先覆盖 6 处调用点；users.json scrypt 盐哈希+自动 bootstrap+**原子写+mtime 热生效**（P2-1 修复）
- [x] T3 api：eval 通道 PRISM_EVAL_USER/PASS（无后门，同 login 流程）
- [x] T4 web：LoginGate（400/401 文案区分，P2-8 修复）+ App 三态门控 + lib/auth.ts 全局 401 拦截 + **vite proxy 补 /auth**（审查⑤实锤修复）
- [x] T5 单测：test_auth.py 10 例 + conftest 旁路 + 既有 15 例零回归 → 25/25
- [x] T6 验证：tsc 0 错 + build + 401 逐路由抽验 ×8 + 登录链路 + vite 代理链路 + E2E + user_id 防冒用实证
- [x] T7 Step7 隔离审查（auth-gate-review：P0=0/P1=2/P2=10）→ review-response（修4+实锤1/化解1/记录6+）
- [x] T8 Step8 修复：vite /auth / prod 拒启断言 / 原子写+缓存失效 / LoginResult 文案 / 测试加固
- [x] T9 verification.md（浏览器渲染走查降级：Tabbit 实例故障，API+代理层全验）
- [x] T10 归档（上云必须清单随 verification 落档）
