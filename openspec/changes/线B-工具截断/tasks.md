# 线B-工具截断 · tasks

## Step1-3.5
- [x] T0 explore 实测（体积表/hook 现状/链式语义/bug 三连/门禁定位）→ explore.md
- [x] T1 proposal（D1-D5 决策）→ proposal.md
- [x] T2 tasks（本文档）
- [x] T3 self-check 自查收敛（见 self-check.md，Gap 全修后进施工）

## Step5 施工
- [x] T4 `src/shared/truncate.ts`：truncateToolResult(text, opts) 纯函数
  - JSON 路径：parse → 保真名单（_meta/as_of/url/id 类键）→ 找长数组递归裁到 ≤MAX → 重组 + `_truncated`
  - 非 JSON 路径：head 8000 + tail 4000 + 标记
  - dist：可选分组键的确定性 groupby（仅被裁数组）
- [x] T5 `tests/truncate.test.ts`：真实样本断言（100KB→≤20KB、_meta/url 完整、_truncated 结构、非 JSON、不触发路径 <20KB 原样返回）
- [x] T6 extension：import truncate + TRUNCATABLE 集合 + **第二个 tool_result handler**（采集 handler 之后注册；旁路文件写盘 best-effort；截断标记含 hint）
- [x] T7 extension：search_cars 专用实现（keyword 客户端过滤 + 裁列到真实字段 + cap 50；brand/price 参数删除——端点无此字段）
- [x] T8 extension：sentiment_trend 参数换算（days 默认 30 → start/end YYYY-MM-DD）
- [x] T9 main.py：/tikhub/status `http_info != 200` → out.error（429 盲区）
- [x] T10 静态验证：根 tsc（11=基线）+ node --check extension（tsx 编译路径走单测）+ py_compile main.py

## Step5 验收
- [x] V1 单测：node --test tests/truncate.test.ts 全绿
- [x] V2 smoke:all 50/50
- [x] V3 服务重启（prism.py）→ 端点级实测：search_cars keyword 过滤后小载荷 / sentiment_trend 200 / tikhub 429 显异常
- [x] V4 真实对话实测：E5 分析一轮 → session JSONL 工具结果条目 ≤20KB + 台账完整 + 正文含行 ID/SQL
- [x] V5 **E1-E9 出口闸门禁全绿**（runner --gate）

## Step6-10
- [x] T11 simplify（死配置清理：DIST_KEYS search_cars 条目——专用实现自带截断后失效）（自查新增代码死区/重复）
- [x] T12 code-review（自审 + 用户抽查）
- [x] T13 receiving-review（修 P0/P1）
- [x] T14 verification（验收记录 → verification.md）
- [x] T15 archive（归档 + 记忆更新）
