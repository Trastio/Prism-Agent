# Verification · 中止键与单一在途轮次

## 验收对照（proposal 5 条）

1. **E2E 真流中止 + 锁清 + 续用** ✅ 三轮递进实测：
   - abort_e2e：6s 中止、流即时收尾含 aborted、abort 返回 0.5s
   - abort_race2：abort 响应后 100ms 新问 → 完整获答
   - **abort_race5（终测，最严苛：abort 后 50ms 新问）**：42.7s 完整获答（thinking 2541 / text 1921 / settled 正常收尾）
2. **幂等** ✅ 无在途 `/chat/abort` → `{ok:true,aborted:false}`（fast 组断言）；非法 user_id → 400
3. **UI** ✅ tabbit 浏览器实测：生成中按钮 `#ico-arrow-up`→`#ico-stop`、点击中止、状态"已中止生成"、中止后恢复箭头+输入可用
4. **断线即中止** ✅ 代码路径实证（sawSettled 判据 + 幂等 abortChat）；race 系列即其极端形态验证
5. **回归** ✅ smoke:all **84/84**（+abort fast 组）；根 tsc 11=历史基线；web tsc 0；eval runner 未知 type 忽略（if/else-if 链，核对无需改）

## 竞态修复专项（S7 自审 P0，两轮复现+终测通过）

- race3/race4 复现两种泄漏形态（尾随 settled / 尾随 tool 事件点亮防线）→ S7-a/b/c/d 四连修 → race5 终测全过
- 细节见 review-response.md

## 施工过程中的环境事实

- 网关重启坑：监听 0.0.0.0:9200，grep `127.0.0.1:9200` 落空导致假重启（旧代码仍在跑）——已记入记忆
- heredoc `\\` 折叠坑再次出现（Python 串内 `\\n` 被折成换行）——含反斜杠的代码编辑一律走 Edit 工具

## 环境与产物

- 五服务运行中（gateway 53116 新代码 / api 45224 含 /chat/abort）
- tests/abort_api.test.ts：fast 组进 smoke；e2e 组 PRISM_E2E_ABORT=1 门控
- UI 验证经 tabbit（任务 "Prism abort check" 已 finish）
