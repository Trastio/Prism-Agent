# 线B-工具截断 · proposal

## WHY
自建工具结果不截断（100KB series-list 全量入上下文），后果三连：长会话越聊越慢（事发会话 446KB）、compaction 压力大、pi 规范（extensions.md 自截断要求）未遵守。同时 explore 挖出三个工具层 bug（search_cars 参数失效 / sentiment_trend 必 422 / tikhub 状态 429 盲区），同属工具接口层，并入本 change 一次收口。

## WHAT

### 1. 统一截断层（核心）
- **挂载点**：extension 内注册**第二个** `tool_result` handler（在现有采集 handler 之后注册）——pi 链式中间件语义保证：台账/名称/_meta 先看全量 → 截断 handler 后跑 → `{content}` 补丁即进上下文与会话文件。"台账先抽后截"由注册顺序结构性保证
- **覆盖集 TRUNCATABLE（23 个数据工具）**：query_* 3 + sentiment 6 + dashboards 10 + social_* 4。**流程/交互工具不截**（resolve_series / submit_conclusion / load_skill / export_document / ask_user / web 插件 4 个）
- **算法（一套，非按工具定制）**：
  1. JSON parse 成功 → 保真名单字段永不截（`_meta`、`as_of`、`url`、行 ID 类键）→ 长数组裁到总额 ≤20KB → 尾附 `_truncated {total_rows, kept_rows, dist?, hint}`
  2. parse 失败 → head 8000 + tail 4000 字符 + 标记
  3. 分布摘要（dist）：确定性 groupby（纯代码可复算，非 LLM 摘要）；按工具白名单配置分组键，第一期仅 search_cars 配 `brand`
- **旁路文件**：全量原文落 `logs/tool-outputs/{ts}-{tool}.json`，截断载荷带 `full_output_path`；写盘 best-effort（失败静默，不影响工具结果）
- **总帽 20KB**（正当载荷上限 query_config 15KB + 25% 余量）

### 2. search_cars 客户端过滤（B2）
专用实现替换通用透传：拿到全量后按 keyword（去空格 contains）/brand/min_price/max_price 过滤 + 只回 `[series_id, name, level, price]` 列 + cap 50 行 + 命中数。100KB → 典型 <2KB。只选行不改数，红线#1 无涉。

### 3. 工具层 bug 三修
- **sentiment_trend**：extension 侧把可选 `days`（默认 30）换算为 `start/end`（YYYY-MM-DD）传真实端点——工具描述不变，PM 仍然只说"最近 30 天"
- **/tikhub/status 429 盲区**：`http_info != 200` 时写 `out.error`（前端状态灯现成显示"异常"）；error 不进缓存已有逻辑兜住
- ~~tikhub data1~~：已先行修复（2026-10-12，见 verification）

### 4. 不做清单
- pi-web-access 4 个插件工具不截（URL 真值集风险，观察一版）
- tikhub.ts 内部 truncateOutput 不收编替换（并行会话活跃开发区，双道防线职责不同）
- LLM 语义摘要（数字红线天敌）；分页/游标（行为风险）；结果老化/compaction 定制（B3 测量后再定）；数据面分离（远期）
- compaction 参数不动（keepRecentTokens 30000 保持；B3 仅测量）

## 决策记录
| # | 决策 | 理由 |
|---|---|---|
| D1 | 截断=第二 tool_result handler，非改现有分支 | 链式语义结构性保证"先抽后截"；零侵入并行会话共享的采集逻辑 |
| D2 | 一套算法覆盖 23 工具，组级只有截/不截开关 | 验证矩阵 1 份（E1-E9 一次覆盖）；模型看到的截断格式全站一致 |
| D3 | 20KB 总帽 | v1.5 纸面值 × 实测正当上限 15KB 校准 |
| D4 | dist 只做确定性 groupby | 摘要数字也必须可复算（红线#1 同源逻辑） |
| D5 | 社交包区域不改，双道防线 | 并行开发冲突风险 > 代码统一收益 |

## 影响范围
- 新增：`src/shared/truncate.ts`（纯函数）+ `tests/truncate.test.ts`
- 修改：`.pi/extensions/prism-guardrails/index.ts`（截断 handler + search_cars 专用实现 + trend 参数换算）、`prism-api/main.py`（tikhub 429 一行）
- 不碰：verify/* 逻辑、工具白名单/tier 定义、tikhub.ts、前端、子服务

## 验收
1. 单测：真实 series-list 100KB 样本 → 截断输出 ≤20KB、`_meta`/行ID/url 完整、`_truncated` 结构正确；非 JSON 路径；保真名单路径
2. `npm run smoke:all` 50/50
3. **E1-E9 出口闸门禁全绿**（`node eval/runner.mjs --gate`）——截断不得破坏台账完整性（漏真值 → 出口闸红）
4. 实测：跑一次真实 E5 分析对话，session JSONL 中工具结果条目全部 ≤20KB；台账（prism-numeric-truth）数字完整；回复正文仍含行 ID+SQL
5. 根 tsc 零新增（11=基线）；web tsc/build 不涉（无前端改动）
6. search_cars：keyword=银河 → 过滤后小载荷；trend 修复后 200
