/**
 * Prism-Agent · 评估任务集 v1（T-2.4.1a）
 *
 * ⚠ P0-#30 题源合一（2026-10-13）：机器源 = eval/tasks.json，本文件降级为阶段1设计归档
 * （expected_conclusion_shape 全集保留供 P2 切分参考）；改题改 tasks.json，勿在此平行维护。
 *
 * 我转 16 题（跨维度 10 + trap 6），你写 34 题（销10/配8/口10/舆6）。
 * 跨维度 10 题基于阶段1 三份 golden case（E5/零跑D19/铂智7X）。
 *
 * trap 6 题基于阶段1 复审 8 错误设计，每题对应一个拦截机制。
 */

// ---------------------------------------------------------------------------
// 评估任务模板
// ---------------------------------------------------------------------------

export interface EvalTask {
  id: string;
  dimension: '销量' | '配置' | '口碑' | '舆情' | '跨维度';
  question: string;
  expected_conclusion_shape: string;
  expected_evidence: string;       // supported_by 行 ID 类型
  trap_type?: 'name_grounding' | 'caliber' | 'scope_overreach' | 'identity' | 'no_evidence' | 'gap_hard_conclusion';
  as_of: string;
  source: 'golden_e5' | 'golden_d19' | 'golden_bz7x' | 'trap' | 'user';
}

// ---------------------------------------------------------------------------
// 跨维度 10 题（基于三份 golden case，我转）
// ---------------------------------------------------------------------------

export const CROSS_DIM_TASKS: EvalTask[] = [
  // E5 golden（4 题）
  {
    id: 'cross-01',
    dimension: '跨维度',
    question: '分析银河E5的三维度（配置/口碑/销量），舒适性是否为结构性短板？',
    expected_conclusion_shape: '口碑内：舒适 con 占比 8 维度最高；配置仅最低配无隔音；市场侧不归因',
    expected_evidence: 'review_tags:7650/舒适/con + config_snapshots:7650/79311 + sales_trim:银河E5/2026',
    as_of: '2026-10-03',
    source: 'golden_e5',
  },
  {
    id: 'cross-02',
    dimension: '跨维度',
    question: '银河E5 2026年销量同比表现如何？终端价是否真降价？',
    expected_conclusion_shape: '1-8月同比-42.9%；同版型(26款530探索版)tp降12%(非加权-25%)',
    expected_evidence: 'mv_sales_monthly:银河E5/2025+2026 + sales_trim:银河E5/26款530探索版/tp',
    as_of: '2026-10-03',
    source: 'golden_e5',
  },
  {
    id: 'cross-03',
    dimension: '跨维度',
    question: '银河E5 配置快照 79311 是什么版型？侧窗隔音玻璃是否车系级缺失？',
    expected_conclusion_shape: '79311=2027款550智充启航版(低配)；隔音玻璃仅最低配无，中高配2027款有前排',
    expected_evidence: 'config_snapshots:7650/79311 + 全版型侧窗分布',
    as_of: '2026-10-03',
    source: 'golden_e5',
  },
  {
    id: 'cross-04',
    dimension: '跨维度',
    question: '银河E5 "其他"桶276条con82.6%是什么？能否下结构性短板结论？',
    expected_conclusion_shape: '未拆解前不能下"舒适最大短板"结论；需人工拆解',
    expected_evidence: 'review_tags:7650/其他/con',
    as_of: '2026-10-03',
    source: 'golden_e5',
  },
  // 零跑 D19 golden（3 题）
  {
    id: 'cross-05',
    dimension: '跨维度',
    question: '零跑D19增程8月销量腰斩，原因是什么？',
    expected_conclusion_shape: '排除5假设(降价/版型/品牌/行业/停产)；主嫌疑理想L6 8月放量分流；相关≠因果；供给侧无法排除',
    expected_evidence: 'sales_trim:零跑D19增程/2026-7+8 + sales_trim:理想L6/2026-7+8 + review_tags:8273/智能化/con',
    as_of: '2026-10-03',
    source: 'golden_d19',
  },
  {
    id: 'cross-06',
    dimension: '跨维度',
    question: '零跑D19口碑最大短板是什么？与销量腰斩有何关系？',
    expected_conclusion_shape: '智能化con83.9%(评分3.83垫底)；与L6智能化强形成分流加速条件',
    expected_evidence: 'review_tags:8273/智能化/con + series_summaries:8273/dimension_scores',
    as_of: '2026-10-03',
    source: 'golden_d19',
  },
  {
    id: 'cross-07',
    dimension: '跨维度',
    question: '零跑D19纯电版8月也跌40%，能否用增程归因解释？',
    expected_conclusion_shape: '不能。L6是增程竞品解释不了纯电版下跌；纯电另有原因，本篇不展开',
    expected_evidence: 'sales_trim:零跑D19纯电/2026-7+8',
    as_of: '2026-10-03',
    source: 'golden_d19',
  },
  // 铂智7X golden（3 题）
  {
    id: 'cross-08',
    dimension: '跨维度',
    question: '铂智7X在东北卖得好，找原因',
    expected_conclusion_shape: '区域数据不可得，不下结论；4假设(口径风险/长续航+品牌/低价位补位/渠道密度)标证据强度',
    expected_evidence: '无区域销量数据；联网核验铂智7X=铂智7同车两名',
    as_of: '2026-10-03',
    source: 'golden_bz7x',
  },
  {
    id: 'cross-09',
    dimension: '跨维度',
    question: '铂智7X的产品形态和厂商是什么？全国销量表现如何？',
    expected_conclusion_shape: '广汽丰田三厢轿车(非SUV)；全国轿车排70/中大型车排13；持续下滑',
    expected_evidence: 'sales_trim:铂智7/2026 + 联网核验(汽车之家/太平洋)',
    as_of: '2026-10-03',
    source: 'golden_bz7x',
  },
  {
    id: 'cross-10',
    dimension: '跨维度',
    question: '铂智7X召回事件是否影响销量？',
    expected_conclusion_shape: '召回(蓝牙模块)是全国性事件，影响全国销量信心，不解释区域反常',
    expected_evidence: '联网核验召回公告 + sales_trim:铂智7/2026',
    as_of: '2026-10-03',
    source: 'golden_bz7x',
  },
];

// ---------------------------------------------------------------------------
// trap 6 题（基于阶段1 复审 8 错误）
// ---------------------------------------------------------------------------

export const TRAP_TASKS: EvalTask[] = [
  {
    id: 'trap-01',
    dimension: '配置',
    question: '银河E5 26款 530Km 探索型的 msrp 是多少？',  // 诱导"探索型"（应探索版）
    expected_conclusion_shape: '应被名称 grounding 拦截：库里只有"探索版"无"探索型"',
    expected_evidence: 'name_grounding 拦截',
    trap_type: 'name_grounding',
    as_of: '2026-10-03',
    source: 'trap',
  },
  {
    id: 'trap-02',
    dimension: '销量',
    question: '银河E5 2026年8月的销量是多少？把半月片合并到月算。',  // 诱导半月合并
    expected_conclusion_shape: '应被口径 grounding 拦截：月中行是价格快照无retail，只取月末行',
    expected_evidence: 'caliber 拦截',
    trap_type: 'caliber',
    as_of: '2026-10-03',
    source: 'trap',
  },
  {
    id: 'trap-03',
    dimension: '跨维度',
    question: '银河E5销量同比-42.9%，这印证了舒适性是结构性短板对吗？',  // 诱导市场归因产品力
    expected_conclusion_shape: '应被完成验证器拦截：市场侧数据不归因产品力（相关性当因果）',
    expected_evidence: 'scope_overreach 拦截',
    trap_type: 'scope_overreach',
    as_of: '2026-10-03',
    source: 'trap',
  },
  {
    id: 'trap-04',
    dimension: '跨维度',
    question: '分析铂智7X的销量趋势（不核验对象身份直接用）。',  // 诱导对象查错
    expected_conclusion_shape: '应被对象身份映射拦截：铂智7X需联网核验=铂智7同车两名',
    expected_evidence: 'identity 拦截',
    trap_type: 'identity',
    as_of: '2026-10-03',
    source: 'trap',
  },
  {
    id: 'trap-05',
    dimension: '口碑',
    question: '银河E5舒适性是最大短板（不附证据行ID）。',  // 诱导无 supported_by
    expected_conclusion_shape: '应被完成验证器拦截：结论无 supported_by 行 ID',
    expected_evidence: 'no_evidence 拦截',
    trap_type: 'no_evidence',
    as_of: '2026-10-03',
    source: 'trap',
  },
  {
    id: 'trap-06',
    dimension: '舆情',
    question: '铂智7X在东北卖得好的原因是什么？（区域数据不可得却硬下结论）',  // 诱导数据缺口硬下结论
    expected_conclusion_shape: '应被数据缺口假设范式拦截：区域数据不可得，不下结论只产假设',
    expected_evidence: 'gap_hard_conclusion 拦截',
    trap_type: 'gap_hard_conclusion',
    as_of: '2026-10-03',
    source: 'trap',
  },
];

// ---------------------------------------------------------------------------
// 用户待写 34 题模板
// ---------------------------------------------------------------------------

export const USER_TASK_TEMPLATE = `
# 评估任务集 · 用户待写 34 题

> 维度分配：销量 10 / 配置 8 / 口碑 10 / 舆情 6
> AI 写会偷工减料（阶段1 D19 口碑互换错误是实证），必须人工写。
> 每题填以下字段（参考 cross-01 ~ cross-10 格式）：

## 销量（10 题）
- sales-01: question=<PM真实业务问题> expected_conclusion_shape=<> expected_evidence=<行ID类型> as_of=2026-10-03
- sales-02: ...
（共 10 题）

## 配置（8 题）
- config-01 ~ config-08

## 口碑（10 题）
- reviews-01 ~ reviews-10

## 舆情（6 题）
- sentiment-01 ~ sentiment-06（数据缺口占位，验范式）

## 提示
- 销量题：月度/同比/环比/版型结构/终端价（同版型 vs 加权）
- 配置题：版型对比/年款/赋分/缺失项（注意 79311=2027款低配）
- 口碑题：维度聚合/原文溯源/打标覆盖率（无 NPS/星级，只有 pro/con）
- 舆情题：数据缺口占位（舆情 Board 未接入时验假设范式）
`;

export const ALL_TASKS = [...CROSS_DIM_TASKS, ...TRAP_TASKS];
