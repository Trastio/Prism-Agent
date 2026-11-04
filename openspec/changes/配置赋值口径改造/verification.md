# verification · 配置赋值口径改造（Step9，2026-10-13）

对 proposal.md 验收 7 条逐条复核：

## 1. parity：compute_value_diff 与 JS 公式一致 ✅
- 单测 legacy_mode 锁公式（presence±1/数值差/文本跳/相等跳/双无跳/缺采跳/未定价计数/手填覆盖/3列逐列/文案四态），期望值公式手工推导
- parity 疑点追加核查：原 JS `_unitPrice`（snapshots/dash_config.html:509-513）对 price=0 **计入**计算（仅显示空串），Python legacy 一致——无 0 价行分歧
- 注意：parity 锁**公式**不锁单价源（生产单价源已按拍板切 diff_pricing，见 design D2/self-check Gap1）

## 2. 新规则单测正反例全过 ✅
- band 文本档（F1/E1 含子串序防误命中/G3/M2 组合枚举/H6 fallback0）、band 数值档（B1/G4→改flat见下）、数量差（G5）、threshold（G1 正反）、○=无、缺采跳过、missing 拒绝汇总、未知 pricing fail-closed
- 36/36 passed（含 Step8 审查回归 5 条）

## 3. 端点真实数据 ✅
- TestClient 7650:79311 vs 79310 → 逐项判定+config_adv=-4300+flat_adv=+5700（guide 11.78/10.78 万）
- manual POST 覆盖生效（source=manual）；get_trims 失败 monkeypatch → 200 降级（guide None/flat_adv None/差价照常）
- 缺快照/非法 sel 错误信封正确；Infinity 手填 → 200（P0-1 修复实证）

## 4. 看板 ✅（附边界声明）
- 活页面检查（8010 重启后）：新 hint 五规则在 / refreshDiffFromServer 在 / 旧 _computeDiffCells 无 / renderDiffFoot 在
- 手填→POST→tfoot 更新：代码链路+TestClient 实证；**浏览器人工点按未走查**（tabbit 不在本轮），留用户走查——不阻塞归档的声明项

## 5. agent 端到端 ✅
- 真实对话（usr_e2ecfg）："79311 和 79310 配置差价多少，值不值？" → resolve_series→get_config_detail→get_trims→**compare_configs_valued×9**→query_*→submit_conclusion → **verdict=pass 零回灌**，CLAIM 带 config_snapshots 行 ID
- 截断白名单 24 工具确认（index.ts:65）；guard 白名单单测同步（smoke:guard 15/15）
- 缺规则场景：单测覆盖（missing→blocked→拒绝汇总）；skill 写明缺口范式

## 6. 门禁与 smoke ✅
- 门禁 E1-E9 **9/9**（eval/gate-report.json，2026-10-13T05:26）；smoke:all 全绿（含 smoke:value_diff 36）

## 7. trap 素材入库 ✅
- tasks.json 18→20 题：trap-07/08（value_grounding 假前提，真值经 compare-valued 实测：79311 中控 15.4 英寸/8 喇叭）；EVAL_STATUS 已记录

## 附加完成
- 旧链路收敛：fold_prices 删除（墓碑注释保留）；/config trim 视图 raw 行结构保留
- guide_diff/_diff_vs_min 死代码清除（Step6）
- D1.3 任务清单回写（重述为 61 项差价链路 agent 化）；EVAL_STATUS 补记

## 声明项（非阻塞）
1. 浏览器人工走查手填交互未做（留用户）
2. trap-07/08 与 runner --only=trap 兼容性未实跑（随下轮批跑）
3. 生产 9200 网关已重启加载 extension 新代码；若与其他会话并行，重启记录见 logs/
