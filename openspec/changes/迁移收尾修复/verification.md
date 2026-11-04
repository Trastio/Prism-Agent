# 迁移收尾修复 · verification（2026-10-11）

## 静态
- `node --check prism-api/pi_gateway.mjs` ✓；`python -m py_compile prism-api/main.py` ✓
- 根 `tsc --noEmit`：11 条 = 历史基线，**零新增** ✓
- `prism-web npm run build`（tsc + vite）：✓（4.59s / 收尾复检 2.37s）

## 冒烟
- `npm run smoke:all`：**50/50 全过 0 fail** ✓
- C1 直测（tsx 实调修好的 sentimentCoverage）：银河E5 → `{"hit":true,"detail":"vehicle_id=3f8825ef-…"}`；虚构车 → `{"hit":false,"detail":"舆情库未收录该车系"}`（如实 miss，红线#1）✓

## 服务级（prism.py 重启五服务后，Python urllib 实测）
| 验收点 | 结果 |
|---|---|
| GET /dash/as_of | 200 `{"sales":"2026-9月末","reviews":"2026-10-07"}`（真值，替换硬编码 2026-10-04） |
| POST /session/rename 正常链 | 200 `{ok:true, custom_name:"测试会话"}`；GET /session 列表返回 `custom_name` ✓ |
| POST /session/rename `../evil` 注入 | 被拒（网关 404 → main.py 502 固定文案，fail-closed） |
| /dash/koubei?q=银河E5 | 200（带参反代子服务） |
| /dash/config?series_id=7650&load=1 | 200 |
| 测试会话目录 | 已清理 ✓ |

## 浏览器渲染（headless Chrome dump-dom localhost:5173）
- 侧栏双 tab：`sb-tab is-on">会话` + `sb-tab ">车系"`（此前车系 tab 无 UI 出口）✓
- 看板栏：`as_of <b>销量 2026-9月末 · 口碑 2026-10-07</b>`（实时值进 DOM）✓
- ChatView 文案：hero="汽车产品经理的数据决策助手"；placeholder="问一个业务问题…"；SUGGESTIONS 三条业务问题在 DOM；旧文案（棱镜三维度因果链路/输入分析指令/query_* 指令）零残留 ✓

## 未验项（如实声明）
- 点击级交互（选车系→看板带参切换、双击重命名、刷新按钮）逻辑为直连 React state/标准事件，tsc+build+渲染验证已覆盖；**建议用户开 localhost:5173 走一遍**（搜"银河E5"回车→点✓→应自动切看板且口碑页带 q= 预筛）。
- 对话检测链路（tool_call series_key → onSeriesDetected → 最近车系）依赖真实 agent 对话，未在本次跑端到端。
