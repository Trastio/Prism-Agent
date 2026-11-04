# 线B-工具截断 · self-check（Step3.5 自查收敛，2026-10-12）

逐 gap 自查（对照提案），全修后进 Step5：

| Gap | 问题 | 处置 |
|---|---|---|
| 1 | 截断 handler 与采集 handler 的顺序靠"注册顺序"隐式保证，未来有人在截断 handler 后再注册采集 handler 就破坏"先抽后截" | 两处加固：①截断 handler 代码内注释声明"必须最后注册"（结构性约束写死）；②tests/truncate.test.ts 加一条集成断言注释说明顺序契约。真要硬保证需 pi API 支持优先级（0.85.1 无），注释+门禁兜底（漏抽真值 E1-E9 必红） |
| 2 | 嵌套 JSON：长数组在子对象里（如 data.rows[].comments[]）而非顶层 | 算法做**递归**裁剪（深度遍历找数组，逐层裁到预算内），非只看顶层 |
| 3 | 裁数组裁哪一头？agent 要"前 N 条"还是"top N"（按热度）？ | 默认保头部（服务端默认排序即业务排序，如 series-list 按销量、posts 按热度）；不做客户端重排序（防引入"截断器选样"的口径争议——选样规则必须等于服务端原序，可复算） |
| 4 | submit_conclusion 的退回修正载荷如果超 20KB 会不会被误截破坏出口闸协议？ | TRUNCATABLE 不含 submit_conclusion（流程工具白名单式排除），结构性免疫 |
| 5 | 旁路文件无限增长（每次截断 100KB，多轮多用户） | 文件名含日期，prism.py 日志目录惯例；首版不做过期清理，archive 记"待加轮转"（低风险：单机 49 人量级，logs/ 已有同类增长先例） |
| 6 | search_cars 过滤后 details/计数语义 | 返回 `{rows, total_matched, truncated, _meta}`——total_matched=过滤后命中数（非全库 221），与 _truncated.total_rows（全库数）区分写清 |
| 7 | sentiment_trend 换算的时区/格式 | start/end 用本地日期 `YYYY-MM-DD`（舆情库按天粒度，端点即此格式——422 报错已示 Query date 类型）；days 默认 30 |
| 8 | `_truncated.dist` 的 groupby 键不存在（如行无 brand 字段）时 | dist 可选生成：无有效分组键则省略 dist 字段（计数+hint 仍在），不硬造 |
| 9 | E1-E9 依赖真实 agent 跑（10+ 分钟），截断对它的破坏面在哪 | 最大破坏面=台账漏抽（Gap1 顺序）与 url 截丢（URL 真值集）——前者门禁直接红，后者保真名单覆盖；V4 再加文件级证据（session 条目 ≤20KB） |
| 10 | tests 目录跑法 | 对齐现有 tests/*.test.ts 的 node:test + assert 风格；truncate 为纯函数无 IO，单测不依赖服务 |

**结论**：spec 无悬空依赖、顺序约束有结构性+门禁双保险、嵌套/边界（Gap2/3/8）有明确规则、可进 Step5。
