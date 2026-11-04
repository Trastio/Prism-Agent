# 线B-工具截断 · code-review 自审与处置（Step7/8）

## 自审发现（按施工时序）

| # | 发现 | 定级 | 处置 |
|---|---|---|---|
| 1 | dist 分布统计无基数上限——高基数键（每行唯一）会让 dist 自身膨胀超预算（单测首跑抓到） | **P0** | 已修：top-20 + `__other__`/`__distinct__` 降级（回归用例把守） |
| 2 | 预算不记账——多数组各自 ≤ 帽但总和超帽逃过裁剪，落入 headTail 丢 JSON 结构（V4 真实对话抓到：get_review_analysis 12,190 字符非合法 JSON，源=specs 5.7K + provinces 15.7K 均独立放行） | **P0** | 已修：①数组无论裁否累计扣预算 ②收敛循环（超帽压预算重裁 ≤3 轮，≤1.05×帽收敛且保 JSON）。两个回归用例把守 |
| 3 | 长字符串标量 JSON 被 object-spread 成字符索引对象（`{..."abc"}` → `{0:'a',...}`） | P1 | 已修：parse 后非对象直接 headTail |
| 4 | TRUNCATE_DIST_KEYS 的 search_cars: 'brand' 死配置——专用实现裁列后 rows 无 brand 字段，且自带 cap 50 不会触发 hook 截断 | P2 | 已清（simplify） |
| 5 | headTail 字符切边界可能切断 UTF-16 代理对（emoji） | P2 | 不修：载荷为 JSON（ASCII+中文 BMP），风险极低；记档 |
| 6 | 旁路文件无轮转清理 | P2 | 不修（self-check Gap5 已记）：单机 49 人量级增长慢，待加轮转 |
| 7 | full_output_path 把本机绝对路径放进模型上下文 | P2 | 不修：无敏感信息，badcase 归因需要；上线上云时随路径配置一并处理 |
| 8 | 门禁两轮 0/9 均为环境碰撞（并行会话在 02:13/02:17 两次重启网关 + eval_cross 批跑），非本 change 代码问题；V4 真实对话 verdict=pass 已证截断层与出口闸协同正常 | 流程 | 重跑门禁拿真实结果；教训记 archive：**门禁窗口需独占环境（协调并行会话），fetch failed/terminated 全军覆没先查网关日志重启记录再怀疑代码** |

## 结论
两个 P0 均由自动化（单测/真实对话文件级验证）当场抓出并修复+回归把守——十步流程的 3.5 自查 + 施工后验证在此发挥作用。无遗留 P0/P1。

---

# 隔离审查轮（Step7 补做，2026-10-12）

用户拍板补独立审查轮。隔离子代理（不带开发者任何结论，自行读 pi 文档/后端源码/实跑复现）报告：**P0 零、P1×2、P2×9**。

## 处置
| # | 发现 | 处置 |
|---|---|---|
| P1-1 | 顶层数组形态 full_output_path 丢失（JSON.stringify(Array) 忽略实例属性——**审查者实证复现**；舆情主力端点是顶层数组且 sentiment_posts 21.3KB 必超帽） | ✅ 修：路径经 TruncateOptions.bypassPath 写进 _truncated marker（对象/数组统一 + 计入收敛预算，连带消 P2-3 注入后置越帽）；单测加顶层数组 bypassPath 回归断言 |
| P1-2 | truncate 单测未进 smoke:verify 文件清单——门禁不执行本 change 单测，回归会绿灯放行 | ✅ 修：package.json smoke:verify 追加（98 tests/0 fail 实证） |
| P2-1 | 截断器异常逃逸无兜底（fail-open 风险） | ✅ 修：handler 整体 try/catch 退化 head/tail |
| P2-2 | 并行工具同毫秒旁路文件名碰撞 | ✅ 修：文件名追加 toolCallId（防字符清洗） |
| P2-3 | full_output_path 注入在尺寸收敛之后（越帽） | ✅ 随 P1-1 消除 |
| P2-4 | 保底 2000×多兄弟数组/单超大元素形态落 headTail（尺寸达标但丢 JSON 结构） | 记录：真实端点形状实证收敛正常；headTail 切 JSON 边界留待需要时 |
| P2-5 | `_truncated` 键撞名覆盖（当前无此形状） | 记录 |
| P2-6 | tikhub r2（daily_usage）失败静默盲区 | 记录：并行会话活跃区，不越界修 |
| P2-7 | dist 机制生产不可达 + 不在门禁 | 部分处置：P1-2 修后进门禁；dist 代码保留待按需配置 |
| P2-8 | content 非 text 块丢失/代理对/旁路内容非最原始载荷 | 记录（archive 归因须知已补 d 项） |
| P2-9 | 无 handler 层测试/边界值/Unicode 缺口 | 部分处置：P1-1 回归断言已补；其余记录 |

## 修复后验证
- 单测 11/11（含 P1-1 回归）；tsc 11=基线；smoke:verify **98 tests 0 fail**（含 truncate 套件）
- 重启后真实对话：sentiment_posts（顶层数组）verdict=pass——当前数据 14.8K<帽未触发截断，数组形态 marker 注入的保障=单测断言（与对象形态共用同一 marker 构造，仅包装两行不同）+ 对象形态端到端实证（V4）

## 审查轮结论
红线（先抽后截/台账全量/名称真值/_meta 保真/_truncated 可复算）经审查者三重独立核实（文档+代码+实测）全部成立。P0 零。两条 P1 修复+回归把守后合档条件达成。
