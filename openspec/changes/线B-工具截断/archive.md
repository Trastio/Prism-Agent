# 线B-工具截断 · archive（2026-10-12 十步走完归档）

## 交付
1. **统一截断层**：`src/shared/truncate.ts` 纯函数 + extension 第二个 `tool_result` handler（注册在采集 handler 之后，"台账先抽后截"由注册顺序结构性保证）。覆盖 23 个数据工具（query 3 + sentiment 6 + dashboards 10 + social 4）；20KB 总帽；JSON 感知递归裁数组保头；`_truncated` 计数+hint+可选 dist（确定性 groupby，top-20 降级）；旁路文件 `logs/tool-outputs/`；流程工具（resolve_series/submit_conclusion/load_skill/export_document）与 web 插件 4 个不截
2. **search_cars 重写**：专用实现（keyword 客户端过滤 + 裁列 + cap 50 + total_matched）——修掉"参数透传给无参端点、100KB 全量入上下文、描述与真实字段不符"三合一问题。100KB → 典型 <1KB
3. **sentiment_trend 修复**：days→start/end 日期换算（端点必填，原实现 agent 调必 422）
4. **/tikhub/status 429 盲区**：非 200 写 error（前端状态灯显异常）；data1 未定义 bug 已先行修复
5. 单测 11 条（3 条真实缺陷回归）

## 实测效果（V4 真实对话）
search_cars 100KB→914B；get_review_analysis 37.9KB→19.5KB（JSON 合法+_truncated+旁路）；全部条目 ≤20K；**两轮 verdict=pass（出口闸台账完整性实战验证）+ 门禁 E1-E9 9/9**

## 持久事实（勿重复推导）
- **pi tool_result 链式中间件**：同扩展多 handler 按注册顺序执行，后注册者见前者改写后结果，返回 `{content}` 补丁即进上下文与会话文件（extensions.md:842-858）——截断层靠此实现零侵入
- **截断算法两难点的解**：①预算必须**累计记账**（数组无论裁否都扣，否则多数组各自 ≤ 帽、总和逃逸）②超帽走**收敛循环**（压预算重裁 ≤3 轮）而非 headTail 兜底（丢 JSON 结构破坏下游）
- **dist 摘要只能确定性 groupby + 基数上限**（高基数键会让摘要自身膨胀）——LLM 摘要是数字红线天敌，永不可用于数字
- **search_cars 的真实后端**是市场口径 series-list（`{series, latest_retail, has_retail, has_weighted}`，1149 行）——找 series_id/model_id 一律走 resolve_series
- 旁路文件 agent 读不到（无文件工具），防绕过；full_output_path 进载荷供人归因
- MAX_POOL=12 软顶在门禁+并行批跑同时跑时被突破（spawn 到 12+），两批跑可共存但互抢资源

## 教训
- **门禁 0/9 全军覆没先查网关日志重启记录再怀疑代码**：fetch failed + terminated 的组合 = 并行会话重启了网关（本轮两次碰撞实锤）；门禁窗口应协调独占环境
- 单测首跑和 V4 真实对话各抓到一个 P0（dist 基数 / 预算记账）——纯函数也要用**真实载荷形态**做单测（specs+provinces 形态是真实 koubei data 复刻）
- 十步的 3.5 自查 Gap3（裁哪头）当时定"保头=服务端原序"，施工中被证明是对的（选样规则必须等于服务端排序，可复算）

## 留下一轮（非阻塞）
- headTail 代理对边界（P2 不修）；旁路文件轮转（Gap5）；full_output_path 上云时的路径策略（P2）
- 34 题用户题（接入位就绪）；40 并发压测（上线前 gate）；Langfuse Prism 层 observation
- 观察项：20KB 帽下模型"带窄参数重查"行为率（trajectories 统计）；compaction 参数是否需要随截断调整（B3 测量：本轮未动）

## 补：隔离审查轮（Step7 补做，用户拍板）
隔离子代理独立审查抓到自审漏掉的 **P1×2**（顶层数组形态 full_output_path 被 JSON.stringify(Array) 丢弃——审查者实证复现；单测未进 smoke:verify 门禁）+ P2×9，全部处置（修 4/记 5）。修复要点：bypassPath 经 TruncateOptions 进 _truncated marker（对象/数组统一+计入收敛预算）；handler 整体 try/catch fail-closed 兜底；旁路文件名加 toolCallId。**再次印证：自审+自动化抓算法缺陷，独立审查抓"注入路径/门禁接入"这类系统集成缺陷——两者互补不可互代**。
