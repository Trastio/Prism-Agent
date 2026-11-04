# verification · harness 登记收敛（Step9，2026-10-13 深夜）

对 proposal.md 验收 7 条逐条复核：

## 1. 自检 fail-loud ✅
注入演练：白名单一项临时改名（submit_conclusion_DRILL）+ 临时技能目录 → 重启 + 触发一轮 → 网关日志精准告警 `登记漂移: 业务白名单缺注册:submit_conclusion_DRILL`；还原后零告警。stderr 管道实证（gateway.log 带 [pi:usr] 标签）。

## 2. 真值信封 ✅
- 三形态（compare/get_config_detail/get_trims）harvestTruth 单测覆盖（含 cells 字符串数字、"15.4英寸"前导、diff 段金额、区间价两端、千分位）
- **模型上下文零增量**：剥离在最外层（解析出 _truth 即剥）；轨迹层 _truth 不出现（采集先于截断的顺序契约 + 单测顺序断言）
- E2E：金额题 submit 通过且金额（-4300/+5700/4260/1.62万）全部来自工具/工具真值派生，无"不在工具真值集"误拒

## 3. 保底③喂源 ✅
两轮真实会话（含此前必误触发的追问轮"主力版型是怎么界定的？"）**零保底触发**；resolve 成功写账（series_id 且非 ambiguous）；空 series_key 守卫（P2-2）。

## 4. 回灌契约 ✅
ChatView 前缀过滤（对账单测断言两侧字面量一致）+ 空气泡过滤；guidance 三处统一追加"重述最小化"话术；五问复跑未再出现"结论重述两遍"。

## 5. 技能目录动态生成 ✅
listSkills 扫描（容错单目录失败）；演练：临时技能目录被扫到、删除后消失；load_skill 描述注册时动态拼装。

## 6. 提示词受众分层 ✅
SYSTEM.md 第 9 条改写为总则（工具名/表名/字段名/引用格式禁入正文+转译义务+例外阀）；AGENTS.md 纪律 1 澄清半句落盘；SKILL.md 第 7 条同步。E2E 实证：两轮对比问答正文**零内部名泄漏**（get_trims/sales_trim/tp/msrp/is_main/config_diff 全查无）。

## 7. 回归 ✅
门禁 E1-E9 **9/9**（exit 0）；smoke:verify **107/0**、guard 15/0、value_diff 37/0；tsc 零新增（TS5097+datasource.ts 历史基线除外）。

## 质量过程

- Step5 fork 子代理施工（8 任务）+ 主会话 M3 提示词
- Step7 隔离审查：0 P0 + 2 P1 + 7 P2 → 修 5（P1-1 diff 收割+去整包 walk、P1-2 matchAll+去逗号、P2-2 空键守卫、P2-3 复核不成立、P2-4 发射方自检）+ 裁决不成立 2（P2-1 外层 catch、P2-3 已置位——均为摘录不全致审查者误报，教训记入 review-response）+ 记录 3（P2-5/6/7）
- E2E 全程五问对照：39→9-14 次工具调用、正文零内部名、submit 1-3 次

## 声明项（非阻塞）

1. P2-5/6/7 记录不修（见 review-response）
2. 名称校验分层（R1-deep）仍在愿望单
3. 浏览器人工走查（手填价+新回答观感）留用户
