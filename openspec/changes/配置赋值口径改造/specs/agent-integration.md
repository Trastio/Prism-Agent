# spec · agent 接线（工具/skill/出口闸/评估素材）（配置赋值口径改造）

> 归档后补录（2026-10-13）：按施工实际执行的契约整理（含 Step8 修复）。对应 design.md D6+M4，任务 T3.1-T3.4、T4.1-T4.2。

## 待办清单（已完成）

- [x] extension compare_configs_valued 工具 + 三处白名单同步
- [x] .pi/skills/config-compare/SKILL.md（双受众 frontmatter）
- [x] /verify/claim config_diff 引用分支
- [x] 真实对话 E2E + 门禁 E1-E9
- [x] trap-07/08 入库 + D1.3 回写 + EVAL_STATUS

## 工具契约（extension）

```
compare_configs_valued(sel: string[])   // 2-6 个 "series_id:spec_id"，第 1 个=基准版型
链路：工具 → :8002 /autohome/compare_configs_valued（DASHBOARDS_TOOL_MAP，GET 60s TTL 缓存）
      → :8010 /dash/config/compare-valued
```
- KNOWN_BUSINESS_TOOLS 21→22（含 resolve_series/submit_conclusion，不含 social4）
- 截断白名单 TRUNCATABLE_TOOLS 23→24（22 业务−resolve/submit+social4）
- guard 白名单单测同步（tool_call.test.ts size+has 断言）

## skill 契约（.pi/skills/config-compare/SKILL.md）

- frontmatter 双受众：summary 给面板人看；description 给模型触发词全（配置对比/差价/值不值/竞争力/赋值/拉平/贵在哪/多值多少钱）
- 正文纪律：先 resolve_series（红线#7）→ 数字只来自工具 → **口径声明**（"按配置差价表 v1-20261013，未含看板手填覆盖"）→ 五态人话+拉平价句式 → missing_rules 走数据缺口假设范式 → 越界纪律（配置差价不推销量因果）→ 指导价缺失只出配置优势 → C2 城市NOA 增量假设（蕴含 C1）随结论披露 → 清单外留痕

## 出口闸引用分支（main.py /verify/claim）

```
config_diff:midA/specA/midB/specB     ← 斜杠格式！沿用解析器 table:part/part 语法
```
- 校验：4 段全数字 + parts[0]/parts[2] 两侧 series_id 在 config_snapshots（spec 段不单独查）
- fail-closed 局部化：主库不可达仅拒 config_diff，三维度不受影响（同 sentiment 分支模式）
- **except 元组含 OverflowError**（审查 P1-3：超大数字段 int 绑定 SQLite 溢出）
- 冒号连写格式被正确拒绝（TestClient 实证）

## E2E 与门禁（已完成证据）

- 真实对话（usr_e2ecfg）：resolve_series→get_config_detail→get_trims→compare_configs_valued×9→query_*→submit_conclusion，**verdict=pass 零回灌**，CLAIM 带 config_snapshots:7650/79310+79311
- 门禁 E1-E9 9/9（eval/gate-report.json 2026-10-13T05:26）

## 评估素材

- trap-07/08（tasks.json，set=dev，value_grounding）：假前提真值经 compare-valued 实测——79311 中控屏 15.4 英寸（假前提 14.6）/扬声器 8 喇叭（假前提 17）；判分=拦截（工具真值纠正）vs 从命（附和）。未批跑计分，随 38 题全量轮
- EVAL_STATUS 已补题库扩容节

## 验收标准（已在 Step9 复核）

1. 真实对话过闸零回灌且工具被真实调用（轨迹 grep 实证）
2. 截断白名单含新工具；guard/smoke/门禁全绿
3. tsc 零新增（TS5097 历史基线除外）

## 依赖

上游：dashboard-endpoint spec（端点形态）；vi 分支依赖 config_snapshots 只读连接。
