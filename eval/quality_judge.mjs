/**
 * 质量层 LLM 评审（G-5 proposal-mini W1）· 后置重放式质量裁判
 *
 * 语义：读既有评估报告的 results[].reply_full + 题目元数据，交异源 LLM 裁判
 *   （agent=DeepSeek → 裁判=GLM，Kimi 兜底）按 rubric 六维打质量分。
 *   纯观测维度，不进及格线、不改 runner 主链（proposal 验收#4）。
 *   与 replay_check 同为后置重放形态：零 agent 重跑。
 *
 * rubric 六维（各 0-2，总分 12 线性映射 0-5 保留一位小数）：
 *   D1 直接回答 / D2 结构可读 / D3 口径与 caveats / D4 冗长度（显式惩罚）
 *   / D5 专业语气（泄漏分级——G-5 Step8 拍板：正文主体多处或关键位置泄漏=0；
 *     口径小节/尾部单处轻度泄漏=1；无泄漏=2。替代 v3"任一泄漏=0"）
 *   / D6 可操作性
 * 防病三件（proposal #4）：
 *   ①judge prompt 固定文本+版本号，指纹=sha256 前 8 位随结果落盘（同 prompt_files_hash 范式）；
 *     历史版本正文留档 PROMPT_ARCHIVE（v3 起逐版全文可复算；v1/v2 未入案卷，如实声明不可复算）；
 *   ②confidence<0.75 或输出 schema 非法（含维度间自相矛盾的机械形态）→ 该题质量分 null
 *     （不计均值，计入弃用率）——LLM 裁判噪声不污染任何汇总；
 *   ③红绿校准集 eval/quality_calibration.json（人工锚 8 题不许改），
 *     Spearman(judge, 人工序) ≥0.7 才准用。
 *
 * CLI：
 *   node eval/quality_judge.mjs <report.json>                  # 全量判质量（写 sidecar 缓存；资格链硬锁）
 *   node eval/quality_judge.mjs <report.json> --calibrate      # 只跑校准 8 题并算 Spearman（例外：允许全候选链试新裁判）
 *   node eval/quality_judge.mjs <report.json> --find-gap       # 后置只读：打印"主分≥4 且质量分<3"清单（零 LLM、不写 sidecar）
 *   node eval/quality_judge.mjs <report.json> --post           # 后置只读：质量分写 langfuse（quality-score，environment=eval）
 * 寻址（P1-2 修复）：报告行按 task#repeat 寻址——runner --repeat=k 产同 task 名多行，
 *   缓存键 / --post 幂等 id / traceId 绑定均按行取（与 runner 的 runId|taskId|repeat 口径对齐）。
 * 资格硬锁（v7②，2026-10-29 凌晨两起夜跑事故根治）：判分链锁死 QUALIFIED_MODELS
 *   （资格=当前 prompt 版本下校准 ρ≥0.7）——HTTP 429/5xx=限流类→指数退避等待重试（15→300s，
 *   单题墙钟预算默认 10min，env PRISM_QJ_ROW_BUDGET_MS 覆盖），**绝不降级到链外模型**
 *   （宁缺毋错：被否裁判的废数据比没数据危险——污染过 sidecar 的 4-flash 前车之鉴）。
 *   后置 --post/--find-gap 只读 sidecar 资格槽：不触发重判、不写 sidecar（教训②"后置读模式只读不写"）。
 * fail-soft（限资格链内）：单题裁判失败（限流等待耗尽/传输重试耗尽/解析失败重试一次后仍非法/
 *   confidence 不足）= 该题 null，不中断整轮。
 *
 * langfuse 写入形态复刻 langfuse_writer.postEvalScore（Basic pk:sk / api/public/scores /
 * 幂等 id / environment 顶层字段）——该导出内部固定 name='eval-score' 不可复用，故同形态复刻。
 *
 * 单测契约：eval/quality_judge.test.mjs（rubric 解析/映射/judgeTask 注入口真路径/Spearman；不外呼真实 API）。
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, dirname, basename } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const IS_MAIN = (() => {
  // Windows 盘符大小写不一致坑（同 replay_check P2-5）
  try {
    return Boolean(process.argv[1])
      && import.meta.url.toLowerCase() === pathToFileURL(process.argv[1]).href.toLowerCase();
  } catch { return false; }
})();

// ── ① 固定 prompt（版本号递增才许改；指纹随结果落盘）──────────────────────
// 版本史（校准轮次记录见 sidecar rounds；人工锚不许改）：
//   v1：首轮基线。实录 ρ=-0.733 FAIL——glm-4-flash 漏扫实锤泄漏（降级模式/别名表、as_of），
//       D4 全 2 零长度惩罚，前 6 名坍缩 11/12 同分。（正文未留档，不可复算，见 PROMPT_ARCHIVE.lost）
//   v2：+泄漏扫描显式步骤 +D4 长度锚 +"先找扣分点再给2"。实录 ρ=-0.732 FAIL——
//       抓到 sentiment-05/skill-01/social-01 泄漏但 sales-09 尾部列表项泄漏仍漏扫；
//       顶部 5 题仍坍缩（11×5），人工 6 名 multi-07 与人工 1-4 名同分=ρ 负主因。（正文未留档）
//   v3：①扫描结果进 JSON 且字段序在 d1..d6 之前（自回归生成顺序=扫描真正条件化打分），
//       leak_scan 须抄命中词原文、扫到文末最后一行；②D3 收紧=时点+口径+边界三项齐才给 2；③D4 锚量化。
//       实录 ρ：GLM-4-flash=-0.491 / Kimi-k2.6=-0.546，均 FAIL——Kimi 泄漏全抓对但中段坍缩
//       （2/3/4/5/7/8 名六题同分 10）：人工锚把埋藏式轻泄漏当小扣，"任一泄漏=0"语义结构性失配。
//       （正文全文留档 PROMPT_ARCHIVE.v3，指纹 03786cb8 可复算）
//   v4：D5 泄漏三级分级（主会话拍板，G-5 Step8 修复#7）——
//       2=零泄漏；1=恰单处轻度泄漏且在辅助位置（口径小节/尾部小字/列表项末尾提醒）；
//       0=两处及以上，或单处在正文主体（开篇结论/主段论述/标题/表格主体）。
//       实录：GLM 漏扫依旧（sales-09 实锤泄漏仍给 D5=2，GLM 不配当裁判的结论再+1）；
//       Kimi 8/8 判齐后 ρ=-0.709 FAIL——D5 分级本身生效（config-05 得 D5=1 教科书案例），
//       但 D4 长度锚未被执行（social-01 3.2K/skill-01 3.4K 仍 D4=2 → 五题同分 10 坍缩）。
//       副产：位置标注使推理链变长，Kimi maxTokens 4000 被挤爆 4/8 空回复→8000 基建修复。
//       （正文全文留档 PROMPT_ARCHIVE.v4，指纹 4bcfbcdf 可复算）
//   v5：D4 与 length_scan 机械绑定（字数落档即定分，不许因内容详实上调）+ 评分纪律加
//       d4 自检行——解 v4 实录的"扫描与打分不一致"。D5 分级措辞不变（工单仅许一次措辞调整）。
//       实录：v5·Kimi ρ=0.761 PASS（exit 0，资格坐实）；2026-10-28 GLM-5.3-flash 接棒后 ρ=0.672 FAIL——
//       失分集中在 config-05/sales-09：辅助位（口径小节/尾部/列表项）两处泄漏被判 D5=0，
//       而 v5 正文"两处及以上=0"未限定位置——与 Step8 拍板原文"**正文主体**多处或关键位置=0"及
//       人工锚判分习惯（config-05 辅助位多处仍 rank2、skill-01 主体单处 rank7）冲突：位置主导在 v5 丢字。
//       （正文全文留档 PROMPT_ARCHIVE.v5，指纹 1f1c63e0 可复算）
//   v6：D5 找回位置主导（丢字修正，非新分级）——辅助位置不论一处还是多处=D5=1，
//       正文主体（开篇结论/主段论述/标题/表格主体）任一命中=D5=0。
//       实录：v6·glm-5.3-flash ρ=0.73 PASS（资格坐实；v5 轮 0.672 FAIL 对照留档 sidecar）。
//       （正文全文留档 PROMPT_ARCHIVE.v6，指纹 8b7c7620 可复算）
//   v7（当前）：多轮逐轮口径（multi 族 12 行 D1=0 冤案根治）——报告行 question=首轮消息截断
//       40 字（runner 落盘语义）而 reply_full=末轮回复，单轮模板判多轮=题面错位天然冤案；
//       多轮行（turnMessages≥2）改用 MULTI_USER_TEMPLATE 三段式：各轮用户消息依序给全
//       （runner 只落逐轮问题+末轮回复，中间轮回复不可得，如实声明）+ 末轮指向声明 + 末轮回复。
//       单轮模板与 v6 逐字节一致（校准集 8 题全单轮，ρ 连续性）；JUDGE_SYSTEM_PROMPT 不动。
//       同版落地判分链资格硬锁（v7②）与后置只读（v7③），见文件头 CLI 节。
export const PROMPT_VERSION = 'v7';

export const JUDGE_SYSTEM_PROMPT = `你是汽车行业产品交付的质量评审员。你将看到一封数据助手回复（面向汽车产品经理）。你只评价它作为「交付给汽车产品经理的答案」的质量：不评价数据真伪（另有验证层负责），也不要求它包含任何内部验证标识。

评分程序（严格执行）：先完成两项扫描并把结果写进 JSON 的 leak_scan / length_scan 字段，然后再填 d1..d6——扫描结论必须与打分一致。

【泄漏扫描】从第一个字逐句扫到文末最后一行（含列表项、小字提醒、口径说明——泄漏常藏在这些位置）：找"系统内部词汇/过程性自述/内部 ID"。三类目标：①工具/接口/字段/机制/表名（supported_by、as_of、series_id、retail_sum、降级模式、别名表、skill、工作流、工具调用、快照、数据集、可打标等任何系统内部词汇）；②过程性自述（"我将加载…""我先核验…""本轮不引用…"式自我报告）；③内部数字 ID 出现在正文。每处命中都把词原文抄进 leak_scan 并标注位置——位置分两类：主体=开篇结论/主段论述/标题/表格主体；辅助=口径小节/尾部小字/列表项末尾提醒——多处用分号分隔。零命中写"无"。
【长度扫描】估算正文字符量写进 length_scan（如"约1450字，跨维度题，合适"）。

六维打分（每维 0/1/2；每一维先找扣分证据，有证据才降档；两维之间不许互相迁就）：
D1 直接回答：2=开门见山给出明确结论，正对用户所问；1=有回答但结论含糊或只答了一部分；0=答非所问或没有结论。
D2 结构与可读性：2=结论先行、分层展开、表格只用于对比性信息；1=有结构但局部难读（大段堆砌、表格过密）；0=表格墙或无结构。
D3 口径与不确定性叙述：2=数据时点、统计口径、对比边界三项都交代且自然融入行文（缺任一项=1）；1=只交代其中一两项，或交代生硬；0=不做任何口径说明就下结论。
D4 冗长度（显式惩罚，防长度偏差——与 length_scan 机械绑定）。长度参照锚：简短事实题（如"哪个卖得最好"）约 500 字内合适；单一维度分析约 800-1500 字；跨两三维度综合约 1500-2500 字。定档规则（机械执行）：约 2500-3500 字 → D4=1（偏长）；约 4000 字以上或大量重复堆砌 → D4=0；长度与题型复杂度匹配 → D4=2。字数落在哪一档就给哪一档的分，不许因内容详实、结构好而上调——内容质量由 D1/D2/D6 承担，长度惩罚不与内容抵消。宁可精炼，不以长度充质量。
D5 专业语气（泄漏分级，位置主导）：2=泄漏扫描零命中，通篇像资深同行写给 PM 的分析；1=命中的泄漏全部位于辅助位置（口径小节/尾部小字/列表项末尾提醒），不论一处还是多处，正文主体干净；0=任一命中出现在正文主体（开篇结论、主段论述、标题、表格主体），不论处数。
D6 可操作性：2=结论+关键取舍或建议，PM 可直接拿去决策或汇报；1=有结论但下一步含糊；0=无法直接采用。

评分纪律：
- 回复中的数字本身不在评价范围（真伪由验证层负责）；数字怎么呈现（口径交代、结构）在范围。
- 按看到的文本如实评：不脑补没写的内容，也不放过真实存在的缺陷。
- 自检：d4 必须落在 length_scan 所记字数对应的档位——若 length_scan 记"约3200字"而 d4=2，视为自相矛盾，须改 d4。
- one_line_reason 写最强扣分点（若无扣分写最强优点），格式如"D5=1：尾部口径句带 as_of；D4=1：超长"。
- 只输出一个 JSON 对象，字段顺序必须如下（扫描字段在前），不要输出任何其他文字：
{"leak_scan":"命中词原文+位置（主体/辅助），分号分隔，或'无'","length_scan":"约X字+判断","d1":0,"d2":0,"d3":0,"d4":0,"d5":0,"d6":0,"confidence":0.90,"one_line_reason":"一句话理由（不超过60字）"}
- confidence 是你对本次评分的自评把握：评分标准与文本对应明确给 0.9 以上；模棱两可给 0.5 左右。`;

export const USER_TEMPLATE = `【用户问题】（维度：{dimension}）
{question}

【助手回复全文】
{reply}`;

// 多轮三段式（v7①）：turnMessages≥2 的报告行专用——各轮用户消息依序给全（"逐轮问答对"里的
// 问全给、答只有末轮——runner 只落末轮回复，中间轮回复不可得，如实声明不脑补），
// 末轮显式标注并声明回复只须回答末轮问题（裁判 D1 不再拿首轮题面判末轮回复）。
export const MULTI_USER_TEMPLATE = `【用户问题】（维度：{dimension}；多轮对话，共 {n} 轮）
本题是同一会话里的连续对话。各轮用户消息依序如下：
{turns}
下面的助手回复只需回答「最后一轮」的问题；前几轮问题仅供上下文。

【助手回复全文】（针对最后一轮问题的回复）
{reply}`;

/** 指纹复算（v7 公式化）：multiTpl 为空串=旧公式（3 段拼接）逐字节一致——v3-v6 归档指纹可复算；
 *  非空则追加多轮模板段（第 4 段），当前指纹=四段输入。 */
export function fingerprintOf(version, system, userTpl, multiTpl = '') {
  let input = version + '\n' + system + '\n---USER---\n' + userTpl;
  if (multiTpl) input += '\n---USER-MULTI---\n' + multiTpl;
  return createHash('sha256').update(input).digest('hex').slice(0, 8);
}

export const PROMPT_FINGERPRINT = fingerprintOf(PROMPT_VERSION, JUDGE_SYSTEM_PROMPT, USER_TEMPLATE, MULTI_USER_TEMPLATE);

/** 按报告行分型组装裁判 userText（v7①）：
 *  - turnMessages 为数组且 ≥2 轮 → 多轮三段式（{turns} 最后填充——轮消息内文不再被后续占位替换）；
 *  - 否则 → 单轮模板，输出与 v6 replace 链逐字节一致（question 缺省回退 item.task 不变）。
 *  P2-2 注入防护保留：两型填充都用 replace 第二参函数（$&/$`/$' 不当特殊模式解释）。 */
export function buildUserText(item) {
  const turns = Array.isArray(item?.turnMessages)
    ? item.turnMessages.filter((t) => typeof t === 'string')
    : [];
  if (turns.length >= 2) {
    const lines = turns.map((t, i) => `第${i + 1}轮${i === turns.length - 1 ? '（最后一轮）' : ''}：${t}`);
    return MULTI_USER_TEMPLATE
      .replace('{dimension}', () => item.dimension || '-')
      .replace('{n}', () => String(turns.length))
      .replace('{reply}', () => item.reply_full || '')
      .replace('{turns}', () => lines.join('\n')); // {turns} 最后填：插入的轮消息不被再扫描
  }
  return USER_TEMPLATE
    .replace('{dimension}', () => item.dimension || '-')
    .replace('{question}', () => item.question || item.task)
    .replace('{reply}', () => item.reply_full || '');
}

/** 历史版本正文留档（审查 P2-⑩：v1/v2 正文未入案卷——untracked 文件无 git 史、sidecar 只存指纹，
 *  已不可复算，如实声明，不事后重构伪造（红线#1）。v3 起逐版全文留档，指纹按现行哈希输入
 *  （version+'\n'+system+'\n---USER---\n'+user_template 的 sha256 前 8 位）可复算验证（见单测）。 */
export const PROMPT_ARCHIVE = {
  lost: [
    { version: 'v1', fingerprint: 'c456c44a', note: '正文未留档不可复算（ρ=-0.733：漏扫泄漏+D4 全 2+前 6 名坍缩）' },
    { version: 'v2', fingerprint: '80f86d81', note: '正文未留档不可复算（+泄漏扫描步骤+D4 长度锚，ρ=-0.732）' },
  ],
  v3: { system: "你是汽车行业产品交付的质量评审员。你将看到一封数据助手回复（面向汽车产品经理）。你只评价它作为「交付给汽车产品经理的答案」的质量：不评价数据真伪（另有验证层负责），也不要求它包含任何内部验证标识。\n\n评分程序（严格执行）：先完成两项扫描并把结果写进 JSON 的 leak_scan / length_scan 字段，然后再填 d1..d6——扫描结论必须与打分一致。\n\n【泄漏扫描】从第一个字逐句扫到文末最后一行（含列表项、小字提醒、口径说明——泄漏常藏在这些位置）：找\"系统内部词汇/过程性自述/内部 ID\"。命中任何一处：D5=0，并把命中的词原文抄进 leak_scan。三类目标：①工具/接口/字段/机制/表名（supported_by、as_of、series_id、retail_sum、降级模式、别名表、skill、工作流、工具调用、快照、数据集、可打标等任何系统内部词汇）；②过程性自述（\"我将加载…\"\"我先核验…\"\"本轮不引用…\"式自我报告）；③内部数字 ID 出现在正文。零命中写\"无\"。\n【长度扫描】估算正文字符量写进 length_scan（如\"约1450字，跨维度题，合适\"）。\n\n六维打分（每维 0/1/2；每一维先找扣分证据，有证据才降档；两维之间不许互相迁就）：\nD1 直接回答：2=开门见山给出明确结论，正对用户所问；1=有回答但结论含糊或只答了一部分；0=答非所问或没有结论。\nD2 结构与可读性：2=结论先行、分层展开、表格只用于对比性信息；1=有结构但局部难读（大段堆砌、表格过密）；0=表格墙或无结构。\nD3 口径与不确定性叙述：2=数据时点、统计口径、对比边界三项都交代且自然融入行文（缺任一项=1）；1=只交代其中一两项，或交代生硬；0=不做任何口径说明就下结论。\nD4 冗长度（显式惩罚，防长度偏差）。长度参照锚：简短事实题（如\"哪个卖得最好\"）约 500 字内合适；单一维度分析约 800-1500 字；跨两三维度综合约 1500-2500 字。约 2500-3500 字且属上述题型=1（偏长）；约 4000 字以上或大量重复堆砌=0；长度与复杂度匹配=2。宁可精炼，不以长度充质量。\nD5 专业语气（内部泄漏=0）：2=泄漏扫描零命中，通篇像资深同行写给 PM 的分析；1=零命中但个别措辞生硬；0=泄漏扫描命中任何一处。\nD6 可操作性：2=结论+关键取舍或建议，PM 可直接拿去决策或汇报；1=有结论但下一步含糊；0=无法直接采用。\n\n评分纪律：\n- 回复中的数字本身不在评价范围（真伪由验证层负责）；数字怎么呈现（口径交代、结构）在范围。\n- 按看到的文本如实评：不脑补没写的内容，也不放过真实存在的缺陷。\n- one_line_reason 写最强扣分点（若无扣分写最强优点），格式如\"D5=0：降级模式；D4=1：超长\"。\n- 只输出一个 JSON 对象，字段顺序必须如下（扫描字段在前），不要输出任何其他文字：\n{\"leak_scan\":\"命中的泄漏词原文或'无'\",\"length_scan\":\"约X字+判断\",\"d1\":0,\"d2\":0,\"d3\":0,\"d4\":0,\"d5\":0,\"d6\":0,\"confidence\":0.90,\"one_line_reason\":\"一句话理由（不超过60字）\"}\n- confidence 是你对本次评分的自评把握：评分标准与文本对应明确给 0.9 以上；模棱两可给 0.5 左右。", user_template: "【用户问题】（维度：{dimension}）\n{question}\n\n【助手回复全文】\n{reply}", fingerprint: "03786cb8" },
  v4: { system: "你是汽车行业产品交付的质量评审员。你将看到一封数据助手回复（面向汽车产品经理）。你只评价它作为「交付给汽车产品经理的答案」的质量：不评价数据真伪（另有验证层负责），也不要求它包含任何内部验证标识。\n\n评分程序（严格执行）：先完成两项扫描并把结果写进 JSON 的 leak_scan / length_scan 字段，然后再填 d1..d6——扫描结论必须与打分一致。\n\n【泄漏扫描】从第一个字逐句扫到文末最后一行（含列表项、小字提醒、口径说明——泄漏常藏在这些位置）：找\"系统内部词汇/过程性自述/内部 ID\"。三类目标：①工具/接口/字段/机制/表名（supported_by、as_of、series_id、retail_sum、降级模式、别名表、skill、工作流、工具调用、快照、数据集、可打标等任何系统内部词汇）；②过程性自述（\"我将加载…\"\"我先核验…\"\"本轮不引用…\"式自我报告）；③内部数字 ID 出现在正文。每处命中都把词原文抄进 leak_scan 并标注位置——位置分两类：主体=开篇结论/主段论述/标题/表格主体；辅助=口径小节/尾部小字/列表项末尾提醒——多处用分号分隔。零命中写\"无\"。\n【长度扫描】估算正文字符量写进 length_scan（如\"约1450字，跨维度题，合适\"）。\n\n六维打分（每维 0/1/2；每一维先找扣分证据，有证据才降档；两维之间不许互相迁就）：\nD1 直接回答：2=开门见山给出明确结论，正对用户所问；1=有回答但结论含糊或只答了一部分；0=答非所问或没有结论。\nD2 结构与可读性：2=结论先行、分层展开、表格只用于对比性信息；1=有结构但局部难读（大段堆砌、表格过密）；0=表格墙或无结构。\nD3 口径与不确定性叙述：2=数据时点、统计口径、对比边界三项都交代且自然融入行文（缺任一项=1）；1=只交代其中一两项，或交代生硬；0=不做任何口径说明就下结论。\nD4 冗长度（显式惩罚，防长度偏差）。长度参照锚：简短事实题（如\"哪个卖得最好\"）约 500 字内合适；单一维度分析约 800-1500 字；跨两三维度综合约 1500-2500 字。约 2500-3500 字且属上述题型=1（偏长）；约 4000 字以上或大量重复堆砌=0；长度与复杂度匹配=2。宁可精炼，不以长度充质量。\nD5 专业语气（泄漏分级）：2=泄漏扫描零命中，通篇像资深同行写给 PM 的分析；1=恰好一处轻度泄漏，且只出现在辅助位置（口径小节/尾部小字/列表项末尾提醒），正文主体干净；0=泄漏两处及以上，或只有一处但出现在正文主体（开篇结论、主段论述、标题、表格主体）。\nD6 可操作性：2=结论+关键取舍或建议，PM 可直接拿去决策或汇报；1=有结论但下一步含糊；0=无法直接采用。\n\n评分纪律：\n- 回复中的数字本身不在评价范围（真伪由验证层负责）；数字怎么呈现（口径交代、结构）在范围。\n- 按看到的文本如实评：不脑补没写的内容，也不放过真实存在的缺陷。\n- one_line_reason 写最强扣分点（若无扣分写最强优点），格式如\"D5=1：尾部口径句带 as_of；D4=1：超长\"。\n- 只输出一个 JSON 对象，字段顺序必须如下（扫描字段在前），不要输出任何其他文字：\n{\"leak_scan\":\"命中词原文+位置（主体/辅助），分号分隔，或'无'\",\"length_scan\":\"约X字+判断\",\"d1\":0,\"d2\":0,\"d3\":0,\"d4\":0,\"d5\":0,\"d6\":0,\"confidence\":0.90,\"one_line_reason\":\"一句话理由（不超过60字）\"}\n- confidence 是你对本次评分的自评把握：评分标准与文本对应明确给 0.9 以上；模棱两可给 0.5 左右。", user_template: "【用户问题】（维度：{dimension}）\n{question}\n\n【助手回复全文】\n{reply}", fingerprint: "4bcfbcdf" },
  v5: { system: "你是汽车行业产品交付的质量评审员。你将看到一封数据助手回复（面向汽车产品经理）。你只评价它作为「交付给汽车产品经理的答案」的质量：不评价数据真伪（另有验证层负责），也不要求它包含任何内部验证标识。\n\n评分程序（严格执行）：先完成两项扫描并把结果写进 JSON 的 leak_scan / length_scan 字段，然后再填 d1..d6——扫描结论必须与打分一致。\n\n【泄漏扫描】从第一个字逐句扫到文末最后一行（含列表项、小字提醒、口径说明——泄漏常藏在这些位置）：找\"系统内部词汇/过程性自述/内部 ID\"。三类目标：①工具/接口/字段/机制/表名（supported_by、as_of、series_id、retail_sum、降级模式、别名表、skill、工作流、工具调用、快照、数据集、可打标等任何系统内部词汇）；②过程性自述（\"我将加载…\"\"我先核验…\"\"本轮不引用…\"式自我报告）；③内部数字 ID 出现在正文。每处命中都把词原文抄进 leak_scan 并标注位置——位置分两类：主体=开篇结论/主段论述/标题/表格主体；辅助=口径小节/尾部小字/列表项末尾提醒——多处用分号分隔。零命中写\"无\"。\n【长度扫描】估算正文字符量写进 length_scan（如\"约1450字，跨维度题，合适\"）。\n\n六维打分（每维 0/1/2；每一维先找扣分证据，有证据才降档；两维之间不许互相迁就）：\nD1 直接回答：2=开门见山给出明确结论，正对用户所问；1=有回答但结论含糊或只答了一部分；0=答非所问或没有结论。\nD2 结构与可读性：2=结论先行、分层展开、表格只用于对比性信息；1=有结构但局部难读（大段堆砌、表格过密）；0=表格墙或无结构。\nD3 口径与不确定性叙述：2=数据时点、统计口径、对比边界三项都交代且自然融入行文（缺任一项=1）；1=只交代其中一两项，或交代生硬；0=不做任何口径说明就下结论。\nD4 冗长度（显式惩罚，防长度偏差——与 length_scan 机械绑定）。长度参照锚：简短事实题（如\"哪个卖得最好\"）约 500 字内合适；单一维度分析约 800-1500 字；跨两三维度综合约 1500-2500 字。定档规则（机械执行）：约 2500-3500 字 → D4=1（偏长）；约 4000 字以上或大量重复堆砌 → D4=0；长度与题型复杂度匹配 → D4=2。字数落在哪一档就给哪一档的分，不许因内容详实、结构好而上调——内容质量由 D1/D2/D6 承担，长度惩罚不与内容抵消。宁可精炼，不以长度充质量。\nD5 专业语气（泄漏分级）：2=泄漏扫描零命中，通篇像资深同行写给 PM 的分析；1=恰好一处轻度泄漏，且只出现在辅助位置（口径小节/尾部小字/列表项末尾提醒），正文主体干净；0=泄漏两处及以上，或只有一处但出现在正文主体（开篇结论、主段论述、标题、表格主体）。\nD6 可操作性：2=结论+关键取舍或建议，PM 可直接拿去决策或汇报；1=有结论但下一步含糊；0=无法直接采用。\n\n评分纪律：\n- 回复中的数字本身不在评价范围（真伪由验证层负责）；数字怎么呈现（口径交代、结构）在范围。\n- 按看到的文本如实评：不脑补没写的内容，也不放过真实存在的缺陷。\n- 自检：d4 必须落在 length_scan 所记字数对应的档位——若 length_scan 记\"约3200字\"而 d4=2，视为自相矛盾，须改 d4。\n- one_line_reason 写最强扣分点（若无扣分写最强优点），格式如\"D5=1：尾部口径句带 as_of；D4=1：超长\"。\n- 只输出一个 JSON 对象，字段顺序必须如下（扫描字段在前），不要输出任何其他文字：\n{\"leak_scan\":\"命中词原文+位置（主体/辅助），分号分隔，或'无'\",\"length_scan\":\"约X字+判断\",\"d1\":0,\"d2\":0,\"d3\":0,\"d4\":0,\"d5\":0,\"d6\":0,\"confidence\":0.90,\"one_line_reason\":\"一句话理由（不超过60字）\"}\n- confidence 是你对本次评分的自评把握：评分标准与文本对应明确给 0.9 以上；模棱两可给 0.5 左右。", user_template: "【用户问题】（维度：{dimension}）\n{question}\n\n【助手回复全文】\n{reply}", fingerprint: "1f1c63e0" },
  v6: { system: "你是汽车行业产品交付的质量评审员。你将看到一封数据助手回复（面向汽车产品经理）。你只评价它作为「交付给汽车产品经理的答案」的质量：不评价数据真伪（另有验证层负责），也不要求它包含任何内部验证标识。\n\n评分程序（严格执行）：先完成两项扫描并把结果写进 JSON 的 leak_scan / length_scan 字段，然后再填 d1..d6——扫描结论必须与打分一致。\n\n【泄漏扫描】从第一个字逐句扫到文末最后一行（含列表项、小字提醒、口径说明——泄漏常藏在这些位置）：找\"系统内部词汇/过程性自述/内部 ID\"。三类目标：①工具/接口/字段/机制/表名（supported_by、as_of、series_id、retail_sum、降级模式、别名表、skill、工作流、工具调用、快照、数据集、可打标等任何系统内部词汇）；②过程性自述（\"我将加载…\"\"我先核验…\"\"本轮不引用…\"式自我报告）；③内部数字 ID 出现在正文。每处命中都把词原文抄进 leak_scan 并标注位置——位置分两类：主体=开篇结论/主段论述/标题/表格主体；辅助=口径小节/尾部小字/列表项末尾提醒——多处用分号分隔。零命中写\"无\"。\n【长度扫描】估算正文字符量写进 length_scan（如\"约1450字，跨维度题，合适\"）。\n\n六维打分（每维 0/1/2；每一维先找扣分证据，有证据才降档；两维之间不许互相迁就）：\nD1 直接回答：2=开门见山给出明确结论，正对用户所问；1=有回答但结论含糊或只答了一部分；0=答非所问或没有结论。\nD2 结构与可读性：2=结论先行、分层展开、表格只用于对比性信息；1=有结构但局部难读（大段堆砌、表格过密）；0=表格墙或无结构。\nD3 口径与不确定性叙述：2=数据时点、统计口径、对比边界三项都交代且自然融入行文（缺任一项=1）；1=只交代其中一两项，或交代生硬；0=不做任何口径说明就下结论。\nD4 冗长度（显式惩罚，防长度偏差——与 length_scan 机械绑定）。长度参照锚：简短事实题（如\"哪个卖得最好\"）约 500 字内合适；单一维度分析约 800-1500 字；跨两三维度综合约 1500-2500 字。定档规则（机械执行）：约 2500-3500 字 → D4=1（偏长）；约 4000 字以上或大量重复堆砌 → D4=0；长度与题型复杂度匹配 → D4=2。字数落在哪一档就给哪一档的分，不许因内容详实、结构好而上调——内容质量由 D1/D2/D6 承担，长度惩罚不与内容抵消。宁可精炼，不以长度充质量。\nD5 专业语气（泄漏分级，位置主导）：2=泄漏扫描零命中，通篇像资深同行写给 PM 的分析；1=命中的泄漏全部位于辅助位置（口径小节/尾部小字/列表项末尾提醒），不论一处还是多处，正文主体干净；0=任一命中出现在正文主体（开篇结论、主段论述、标题、表格主体），不论处数。\nD6 可操作性：2=结论+关键取舍或建议，PM 可直接拿去决策或汇报；1=有结论但下一步含糊；0=无法直接采用。\n\n评分纪律：\n- 回复中的数字本身不在评价范围（真伪由验证层负责）；数字怎么呈现（口径交代、结构）在范围。\n- 按看到的文本如实评：不脑补没写的内容，也不放过真实存在的缺陷。\n- 自检：d4 必须落在 length_scan 所记字数对应的档位——若 length_scan 记\"约3200字\"而 d4=2，视为自相矛盾，须改 d4。\n- one_line_reason 写最强扣分点（若无扣分写最强优点），格式如\"D5=1：尾部口径句带 as_of；D4=1：超长\"。\n- 只输出一个 JSON 对象，字段顺序必须如下（扫描字段在前），不要输出任何其他文字：\n{\"leak_scan\":\"命中词原文+位置（主体/辅助），分号分隔，或'无'\",\"length_scan\":\"约X字+判断\",\"d1\":0,\"d2\":0,\"d3\":0,\"d4\":0,\"d5\":0,\"d6\":0,\"confidence\":0.90,\"one_line_reason\":\"一句话理由（不超过60字）\"}\n- confidence 是你对本次评分的自评把握：评分标准与文本对应明确给 0.9 以上；模棱两可给 0.5 左右。", user_template: "【用户问题】（维度：{dimension}）\n{question}\n\n【助手回复全文】\n{reply}", fingerprint: "8b7c7620" },
};

export const CONF_MIN = 0.75;

// ── 裁判提供方（异源：GLM 优先，Kimi 兜底；模型名探测确认）─────────────────
// 2026-10-27 探测实证（施工报告 W1 节）：
//   glm-4.7-flash=思考型（max_tokens 400 全被 reasoning 吃光→content 空），须 thinking:disabled；
//   且高负载时段 429 频发 → 必须候选链降级；kimi-k2-0905-preview 已退役（404），
//   /v1/models 实际可用=kimi-k2.6/k3 系；kimi-k2.6 仅允许 temperature=1（省略参数）。
const PROVIDERS = [
  {
    name: 'GLM', endpoint: 'https://open.bigmodel.cn/api/paas/v4/chat/completions', keyEnv: 'GLM_api',
    models: [
      // 2026-10-29 路由切换（用户指路）：原生 v4 端点对 glm-5.3-flash=付费档（账户无余额→429/1113
      // "余额不足或无可用资源包"）；**Anthropic 兼容端点 /api/anthropic 含在现行套餐内可用（探针 200 直证，
      // 判分资格模型由此改走该通道——模型 id 不变，QUALIFIED/sidecar 槽键均不受影响）**。
      // 仍是强制思考型（content 含 thinking 块，text 块才是答案——parseAnthropicResponse 剥离），
      // 8000 maxTokens + 240s 超时不变，探测只验 HTTP ok。
      {
        model: 'glm-5.3-flash', apiStyle: 'anthropic',
        endpoint: 'https://open.bigmodel.cn/api/anthropic/v1/messages',
        keyEnvs: ['ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'GLM_api'],
        maxTokens: 8000, timeoutMs: 240000, probeSkipContent: true,
      },
      // glm-5.3（非 flash，套餐内同走 Anthropic 通道）：校准试裁候选——2026-10-29 两轮 5.3-flash
      // 校准 FAIL（0.551/0.469）的稳定反转源=multi-07 锚（裁判满分 vs 人工第 6，内容层缺口六维不测），
      // 试非 flash 版判分习惯是否不同；不入 QUALIFIED（资格只由 --calibrate 过阈产生）。
      { model: 'glm-5.3', apiStyle: 'anthropic', endpoint: 'https://open.bigmodel.cn/api/anthropic/v1/messages', keyEnvs: ['ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'GLM_api'], maxTokens: 8000, timeoutMs: 240000, probeSkipContent: true },
      { model: 'glm-4.7-flash', extra: { thinking: { type: 'disabled' } } },
      { model: 'glm-4-flash', extra: {} },
    ],
  },
  {
    name: 'Kimi', endpoint: 'https://api.moonshot.cn/v1/chat/completions', keyEnv: 'Kimi_api',
    models: [
      // 推理重型：判分实测 reasoning≈3.2K token（v3）——须大 maxTokens+长超时，否则 content 恒空。
      // v4 实测（10-27）：泄漏位置标注使推理链更长，maxTokens=4000 被 reasoning 挤爆→
      // 4/8 题"空回复"弃用（成功请求 completion≈3.5K 贴顶）→ 提到 8000（2× 余量）。
      // v5 实测（10-27 晚）：Kimi 高负载时段（k3.1 持续 429）最长回复（3.4K）150s 超时×3 弃用→240s。
      // probeSkipContent：小预算探测下 reasoning 吃光是预算伪影非不可用——探测只验 HTTP ok。
      { model: 'kimi-k2.6', extra: {}, noTemperature: true, maxTokens: 8000, timeoutMs: 240000, probeSkipContent: true },
      { model: 'kimi-k3.1-pro-highspeed', extra: {}, noTemperature: true, maxTokens: 8000, timeoutMs: 240000, probeSkipContent: true },
    ],
  },
];
// ── 资格硬锁（v7②）：链锁死过校准模型，链外模型任何路径不可达 ────────────────
// 资格=当前 prompt 版本下 --calibrate ρ≥0.7 过阈。2026-10-29 凌晨两起夜跑事故根治：
// 限流期 fail-soft 逐题降级把 189 行全落到校准已否的 glm-4-flash（敷衍量级废值）并写回污染
// sidecar——降级无资格约束=设计缺陷。Kimi（v5 轮 ρ=0.761 曾过阈）未在 v6+ prompt 校准且账户
// 余额停机，不入 v7 资格链；扩链唯一途径=--calibrate 过阈后改此常量（资格由校准产生）。
export const QUALIFIED_MODELS = ['GLM/glm-5.3-flash'];

const ATTEMPTS = 3;        // 非限流错每候选 1+2 次快重试（工单口径）
const MAX_TOTAL_ATTEMPTS = 8; // 链级快重试总预算（防多候选连环 flake 跑飞；限流退避不占此预算）
const TIMEOUT_MS = 30000;
const PROBE_MAX_TOKENS = 256; // 推理型模型探测须留 reasoning 预算（8 会恒空回复误降级——10-27 实测坑）
const BACKOFF_STEPS_S = [15, 30, 60, 120, 240, 300]; // 限流退避阶梯（秒）——末位=BACKOFF_CAP_S（审查 P2-①：cap 必须在阶梯内可达，走完后稳态 300s 循环）
const BACKOFF_CAP_S = 300;

/** 单题墙钟预算（限流等待的硬边界）：默认 10 分钟，env PRISM_QJ_ROW_BUDGET_MS 覆盖。 */
function rowBudgetMs() {
  const v = Number(process.env.PRISM_QJ_ROW_BUDGET_MS);
  return Number.isFinite(v) && v > 0 ? v : 10_000_000;
}

/** 行间限速（2026-10-29 重判事故：anthropic 通道一小时 fetch failed 中断窗，疑似速率敏感）：
 *  默认 0（不限），env PRISM_QJ_ROW_GAP_MS 覆盖——批跑建议 3000（与用户交互会话共享通道，让速）。 */
function rowGapMs() {
  const v = Number(process.env.PRISM_QJ_ROW_GAP_MS);
  return Number.isFinite(v) && v >= 0 ? v : 0;
}

function flattenCandidates() {
  const list = [];
  for (const p of PROVIDERS) {
    for (const m of p.models) {
      // key 解析按模型级 keyEnvs 优先（5.3-flash 走 Anthropic 通道用 AUTH_TOKEN，2026-10-29 路由切换）
      const key = (m.keyEnvs || [p.keyEnv]).map((e) => process.env[e]).find(Boolean);
      if (!key) continue;
      list.push({ name: p.name, endpoint: m.endpoint || p.endpoint, key, ...m });
    }
  }
  return list;
}

const _probeCache = new Map(); // `${name}/${model}` → {ok,why} 模块级探测缓存（同进程一次，按候选缓存）

/** 清空探测缓存（仅单测用——测试里 mock fetch 后须重置，避免上一测试的探测结果串场）。 */
export function _resetProbeCache() { _probeCache.clear(); }

// 测试钩子（仅单测用，生产恒为默认实现）：sleep 供退避等待压 0，now 供预算耗尽路径的时钟推进。
const _defaultHooks = { sleep: (ms) => new Promise((res) => setTimeout(res, ms)), now: () => Date.now() };
let _hooks = _defaultHooks;
/** 注入/恢复测试钩子：_setTestHooks({sleep,now}) 部分覆盖；_setTestHooks(null) 恢复默认。 */
export function _setTestHooks(h) {
  _hooks = h ? { ..._defaultHooks, ...h } : _defaultHooks;
}

// ── 双协议适配（2026-10-29 路由切换）：apiStyle='anthropic' 走 Anthropic 兼容端点，默认 v4 原生 ──
const ANTHROPIC_HEADERS = (key) => ({ 'x-api-key': key, 'anthropic-version': '2023-06-01', 'Content-Type': 'application/json' });

/** Anthropic 兼容响应解析（导出供单测）：content 数组里 type='text' 块拼接为答案（thinking 块剥离），
 *  usage 映射 input_tokens/output_tokens → prompt_tokens/completion_tokens。空文本→上层归"空回复"。 */
export function parseAnthropicResponse(data) {
  const blocks = Array.isArray(data?.content) ? data.content : [];
  const text = blocks.filter((b) => b?.type === 'text').map((b) => b.text ?? '').join('').trim();
  const u = data?.usage;
  const usage = u ? { prompt_tokens: u.input_tokens ?? 0, completion_tokens: u.output_tokens ?? 0 } : null;
  return { text, usage };
}

/** 单候选探测（结果按候选缓存）。要求 HTTP ok 且 content 非空（思考模型空回复在探测即淘汰）。 */
async function probeCandidate(c) {
  const cacheKey = `${c.name}/${c.model}`;
  if (_probeCache.has(cacheKey)) return _probeCache.get(cacheKey);
  const isAnth = c.apiStyle === 'anthropic';
  let r;
  try {
    const res = await fetch(c.endpoint, {
      method: 'POST',
      headers: isAnth ? ANTHROPIC_HEADERS(c.key) : { Authorization: 'Bearer ' + c.key, 'Content-Type': 'application/json' },
      body: JSON.stringify(isAnth
        ? { model: c.model, max_tokens: PROBE_MAX_TOKENS, messages: [{ role: 'user', content: 'ping' }] }
        : { model: c.model, messages: [{ role: 'user', content: 'ping' }], max_tokens: PROBE_MAX_TOKENS, ...c.extra, ...(c.noTemperature ? {} : { temperature: 0 }) }),
      signal: AbortSignal.timeout(c.timeoutMs ?? TIMEOUT_MS),
    });
    if (res.ok) {
      const data = await res.json();
      const contentOk = isAnth
        ? parseAnthropicResponse(data).text !== ''
        : typeof data?.choices?.[0]?.message?.content === 'string' && data.choices[0].message.content.trim();
      r = contentOk || c.probeSkipContent ? { ok: true, why: '' } : { ok: false, why: '空回复' };
    } else r = { ok: false, why: `HTTP ${res.status}` };
  } catch (e) { r = { ok: false, why: (e)?.message ?? String(e) }; }
  _probeCache.set(cacheKey, r);
  return r;
}

/** 启动探测+组链（v7② 硬锁语义）：
 *  - 默认（全量判/后置）：只在 QUALIFIED_MODELS 内组链，按资格声明序（探测只验证可用、失败剔除，
 *    不按可用性重排）；资格候选探测全败 → 抛"宁缺毋错"硬错退出，**绝不降级到链外模型**。
 *  - opts.calibrate=true（--calibrate）：例外允许全候选链按可用性组链——试新裁判是校准的本职，
 *    否则永远无法扩链。
 *  - only='GLM'|'Kimi' 限定提供方：锁定模式下该提供方无资格模型 → 抛错提示先过校准。 */
export async function selectJudge(only = null, opts = {}) {
  const want = only ? String(only).toUpperCase() : null;
  const wantModel = only ? String(only) : null; // 精确模型 id（如 glm-5.3，2026-10-29 校准试裁用）
  const calibrate = Boolean(opts?.calibrate);
  let pool;
  if (calibrate) {
    // --judge 支持提供方名（大小写不敏感）或精确模型 id（全等）——试新裁判必须能点名到具体模型，
    // 否则链头（5.3-flash）永远挡在前面，非 flash 版永远试不到。
    pool = flattenCandidates().filter((c) => !want || c.name.toUpperCase() === want || c.model === wantModel);
    if (!pool.length) return []; // 该提供方/模型无 key/无候选——交由调用方报 "--judge X 探测不可用"
  } else {
    pool = flattenCandidates()
      .filter((c) => QUALIFIED_MODELS.includes(`${c.name}/${c.model}`))
      .filter((c) => !want || c.name.toUpperCase() === want);
    if (!pool.length) {
      if (want) throw new Error(`--judge ${only}：该提供方无资格模型（资格链=${QUALIFIED_MODELS.join(' > ')}）——需先 --calibrate 过阈才有资格（宁缺毋错）`);
      throw new Error(`资格链为空：QUALIFIED_MODELS(${QUALIFIED_MODELS.join(',')}) 不在 PROVIDERS 候选中（配置漂移，拒绝判分）`);
    }
    const qIdx = new Map(QUALIFIED_MODELS.map((m, i) => [m, i])); // 按资格声明序，不按探测可用性重排
    pool.sort((a, b) => (qIdx.get(`${a.name}/${a.model}`) ?? 99) - (qIdx.get(`${b.name}/${b.model}`) ?? 99));
  }
  const ok = [], bad = [];
  for (const c of pool) {
    const r = await probeCandidate(c);
    if (r.ok) ok.push(c);
    else bad.push(`${c.name}/${c.model}: ${r.why}`);
  }
  if (!ok.length) {
    if (calibrate) throw new Error(`GLM/Kimi 均不可用（探测全败：${bad.join('；') || '无候选'}）`);
    throw new Error(`宁缺毋错：资格链探测全败，拒绝判分（${bad.join('；')}）——稍后重试（判分中途限流会预算内退避等待，不降级）`);
  }
  for (const b of bad) console.error(`[probe] ${b} → 剔除${calibrate ? '（校准模式：其余候选仍全链可用）' : '（资格链硬锁：链外模型永不入链）'}`);
  return ok;
}

/** 单候选单次裸调用。返回 {content, usage} 或 {err, rateLimited}（429/5xx=限流类）。
 *  apiStyle='anthropic'：/v1/messages 协议（system 顶层字段 + x-api-key 头），text 块拼接为答案。 */
async function rawCall(c, userText) {
  const isAnth = c.apiStyle === 'anthropic';
  try {
    const res = await fetch(c.endpoint, {
      method: 'POST',
      headers: isAnth ? ANTHROPIC_HEADERS(c.key) : { Authorization: 'Bearer ' + c.key, 'Content-Type': 'application/json' },
      body: JSON.stringify(isAnth
        ? {
          model: c.model, max_tokens: c.maxTokens ?? 700, system: JUDGE_SYSTEM_PROMPT,
          messages: [{ role: 'user', content: userText }],
          ...(c.noTemperature ? {} : { temperature: 0 }),
        }
        : {
          model: c.model,
          messages: [
            { role: 'system', content: JUDGE_SYSTEM_PROMPT },
            { role: 'user', content: userText },
          ],
          max_tokens: c.maxTokens ?? 700,
          ...c.extra,
          ...(c.noTemperature ? {} : { temperature: 0 }),
        }),
      signal: AbortSignal.timeout(c.timeoutMs ?? TIMEOUT_MS),
    });
    if (res.ok) {
      const data = await res.json();
      if (isAnth) {
        const { text, usage } = parseAnthropicResponse(data);
        if (text) return { content: text, usage };
        return { err: '空回复' };
      }
      const content = data?.choices?.[0]?.message?.content;
      if (typeof content === 'string' && content.trim()) return { content, usage: data?.usage ?? null };
      return { err: '空回复' };
    }
    const status = res.status;
    return { err: `HTTP ${status}: ${(await res.text()).slice(0, 120)}`, rateLimited: status === 429 || status >= 500 };
  } catch (e) { return { err: (e)?.message ?? String(e) }; }
}

/** 候选链裁判调用（传输层，v7② 退避语义）：
 *  - 限流类（HTTP 429/5xx）：指数退避 15→300s 等待重试，受单题墙钟预算约束——**等待不降级**
 *    （链已锁死资格模型，链外模型任何路径不可达）；预算耗尽 → null（审查 P2-④：检查点在调用前，
 *    墙钟可越界一个退避段（≤300s），有界无害）。
 *  - 其他传输错（超时/网络/4xx）：每候选快重试 ATTEMPTS 次（链级 MAX_TOTAL_ATTEMPTS 预算）。
 *  预算口径（审查 P2-③）：每次调用独立窗口——judgeTask 的解析层重试（P1-3）再调本函数会新开预算，
 *  单题最坏 ≈2×行预算；仍是"等待不降级"语义，只是窗口按传输调用计（记录，不额外收敛）。
 *  只负责"拿到 HTTP 200 且非空回复"；解析层（200 但非法 JSON）的重试在 judgeTask（P1-3）。 */
export async function callJudgeOnce(judge, userText) {
  const budget = rowBudgetMs();
  const start = _hooks.now();
  let quickTotal = 0; let lastErr = '';
  for (const c of judge) {
    let quickTries = 0; let rlStep = 0;
    while (true) {
      if (_hooks.now() - start >= budget) {
        console.error(`[judge] 单题墙钟预算耗尽（限流等待不降级，${Math.round((_hooks.now() - start) / 1000)}s）：${lastErr}`);
        return null;
      }
      const r = await rawCall(c, userText);
      if (!r.err) return { content: r.content, usage: r.usage, used: `${c.name}/${c.model}` };
      lastErr = `${c.name}/${c.model} ${r.err}`;
      if (r.rateLimited) {
        const waitS = Math.min(BACKOFF_STEPS_S[Math.min(rlStep, BACKOFF_STEPS_S.length - 1)], BACKOFF_CAP_S);
        rlStep++;
        console.error(`[judge] ${lastErr} → 限流退避 ${waitS}s 后重试（资格链内不降级）`);
        await _hooks.sleep(waitS * 1000);
        continue; // 退避不占快重试预算，只受墙钟预算约束
      }
      quickTries++; quickTotal++;
      if (quickTries >= ATTEMPTS || quickTotal >= MAX_TOTAL_ATTEMPTS) break;
      await _hooks.sleep(1000 * quickTries);
    }
  }
  console.error(`[judge] 候选链耗尽（${lastErr}）`);
  return null;
}

// ── ② 输出解析与 null 路径 ───────────────────────────────────────────────
const DIM_KEYS = ['d1', 'd2', 'd3', 'd4', 'd5', 'd6'];

/** 鲁棒 JSON 抽取：直解 → 剥代码栅栏 → 首个配平大括号子串。schema 非法返回 null。
 *  维度只收真数或纯档位数字串（P2-1：null/true/'' 不再被 Number 强转收编成 0/1）；
 *  confidence 只收有限数 0-1（数字或非空数字串，true/null/'' 同样拒绝）。 */
export function parseJudgeJson(text) {
  if (typeof text !== 'string' || !text.trim()) return null;
  const tryParse = (s) => {
    try { return JSON.parse(s); } catch { return null; }
  };
  let obj = tryParse(text.trim());
  if (!obj) obj = tryParse(text.replace(/```(?:json)?/gi, '').replace(/```/g, '').trim());
  if (!obj) {
    const start = text.indexOf('{');
    if (start >= 0) {
      let depth = 0;
      for (let i = start; i < text.length; i++) {
        if (text[i] === '{') depth++;
        else if (text[i] === '}') { depth--; if (depth === 0) { obj = tryParse(text.slice(start, i + 1)); break; } }
      }
    }
  }
  if (!obj || typeof obj !== 'object') return null;
  const dims = {};
  for (const k of DIM_KEYS) {
    const raw = obj[k];
    let v;
    if (typeof raw === 'number') v = raw;
    else if (typeof raw === 'string' && /^(?:0|1|2)$/.test(raw.trim())) v = Number(raw.trim());
    else return null; // 缺维 / null / true / '' / 其他形态——不静默强转（P2-1）
    if (!Number.isInteger(v) || v < 0 || v > 2) return null; // 维度越界=自相矛盾形态，弃
    dims[k] = v;
  }
  const cRaw = obj.confidence;
  let confidence;
  if (typeof cRaw === 'number') confidence = cRaw;
  else if (typeof cRaw === 'string' && cRaw.trim() !== '' && Number.isFinite(Number(cRaw))) confidence = Number(cRaw);
  else return null; // 缺失 / true / null / ''（P2-1）
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) return null;
  if (typeof obj.one_line_reason !== 'string' || !obj.one_line_reason.trim()) return null;
  return { ...dims, confidence: Math.round(confidence * 100) / 100, one_line_reason: obj.one_line_reason.trim().slice(0, 200) };
}

/** 总分 0-12 → 0-5 线性映射，保留一位小数。 */
export function mapToFive(total) {
  return Math.round((total / 12) * 5 * 10) / 10;
}

/** 单题裁判（P1-3 修复）：传输层重试/候选降级在 callJudgeOnce 内；HTTP 200 但非法 JSON
 *  在本层同候选链重召一次，仍非法才弃。confidence<CONF_MIN → null（total 仍算出，供诊断）。
 *  fail-soft 不抛。callFn 仅为单测注入口（默认真实调用），生产路径不传。 */
export async function judgeTask(judge, item, usage, callFn = callJudgeOnce) {
  // v7①：模板分型（多轮三段式/单轮 v6 形态）；P2-2 注入防护在 buildUserText 内保留
  const userText = buildUserText(item);
  const addUsage = (r) => {
    if (usage && r?.usage) {
      usage.prompt_tokens += r.usage.prompt_tokens ?? 0;
      usage.completion_tokens += r.usage.completion_tokens ?? 0;
      usage.requests += 1;
    }
  };
  let r = await callFn(judge, userText);
  if (!r) return { task: item.task, dims: null, total: null, mapped: null, null_reason: '解析失败/API 耗尽', one_line_reason: null, judge_model: null };
  addUsage(r);
  let parsed = parseJudgeJson(r.content);
  if (!parsed) {
    r = await callFn(judge, userText); // P1-3：200 但非法 JSON → 同候选链重试一次再弃
    if (!r) return { task: item.task, dims: null, total: null, mapped: null, null_reason: '解析失败（重试调用耗尽）', one_line_reason: null, judge_model: null };
    addUsage(r);
    parsed = parseJudgeJson(r.content);
    if (!parsed) return { task: item.task, dims: null, total: null, mapped: null, null_reason: '解析失败（重试一次后仍非法 JSON）', one_line_reason: null, judge_model: r.used };
  }
  const total = DIM_KEYS.reduce((a, k) => a + parsed[k], 0);
  if (parsed.confidence < CONF_MIN) {
    return { task: item.task, dims: parsed, total, mapped: null, null_reason: `confidence ${parsed.confidence} < ${CONF_MIN}`, one_line_reason: parsed.one_line_reason, judge_model: r.used };
  }
  return { task: item.task, dims: parsed, total, mapped: mapToFive(total), null_reason: null, one_line_reason: parsed.one_line_reason, judge_model: r.used };
}

/** 报告行寻址键：task#repeat（P1-2）。runner --repeat=k 产同 task 名多行，repeat 缺省按 1。 */
export function addrOf(row) {
  return `${row.task}#${row.repeat ?? 1}`;
}

// ── Spearman（一般定义=秩的 Pearson，含并列平均秩）────────────────────────
export function rankAvg(arr) {
  const idx = arr.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
  const ranks = new Array(arr.length);
  let i = 0;
  while (i < idx.length) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1].v === idx[i].v) j++;
    const avg = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) ranks[idx[k].i] = avg;
    i = j + 1;
  }
  return ranks;
}

export function spearman(a, b) {
  const n = Math.min(a.length, b.length);
  if (n < 2) return null;
  const ra = rankAvg(a), rb = rankAvg(b);
  const ma = ra.reduce((x, y) => x + y, 0) / n, mb = rb.reduce((x, y) => x + y, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) {
    num += (ra[i] - ma) * (rb[i] - mb);
    da += (ra[i] - ma) ** 2;
    db += (rb[i] - mb) ** 2;
  }
  if (da === 0 || db === 0) return null; // 常数序列无相关
  return Math.round((num / Math.sqrt(da * db)) * 1000) / 1000;
}

/** 校准对齐计算（纯函数，2026-10-29 用户拍板"剔除对齐+分层声明"）：
 *  门禁集 = 人工锚 − quality_calibration.json 的 alignment_exclusions（混层锚：其排名理由属内容层，
 *  质量层六维按设计不测，任何 LLM 裁判结构性不可对齐）。人工排序文件原样保留；
 *  全锚 ρ 同时算出仅作透明度参考，PASS/FAIL 只看门禁集。符号契约同下（取负=+1 对齐人工序）。 */
export function calibrationAlignment(ranked, byId, exclusions = []) {
  const exSet = new Set(exclusions);
  const totalsOf = (list) => list.map((x) => byId.get(x.task)?.total);
  const ranksOf = (list) => list.map((x) => x.rank);
  const rhoOf = (list) => {
    const t = totalsOf(list);
    return list.every((_, i) => t[i] != null) ? -spearman(t, ranksOf(list)) : null;
  };
  const gateRanked = ranked.filter((x) => !exSet.has(x.task));
  return {
    rho_gate: rhoOf(gateRanked), gate_n: gateRanked.length,
    rho_all: rhoOf(ranked), all_n: ranked.length,
    excluded: ranked.filter((x) => exSet.has(x.task)).map((x) => x.task),
  };
}

/** --find-gap 谓词（纯函数）：主分≥4 且质量分<3 的行（"对但不好"候选；质量分 null 不计入——
 *  弃用≠低质量）。mainByAddr 键=addrOf 形态（task#repeat，P1-2 口径）。 */
export function selectGaps(qualityResults, mainByAddr) {
  return qualityResults.filter((r) => {
    const main = mainByAddr.get(addrOf(r))?.score;
    return main != null && main >= 4 && r.mapped != null && r.mapped < 3;
  });
}

// ── langfuse 写入（复刻 langfuse_writer.postEvalScore 形态；本工单不实际调用）──
function loadLangfuseCreds() {
  try {
    const file = JSON.parse(readFileSync(resolve(ROOT, '.pi/agent-minimal/langfuse.json'), 'utf-8'));
    return {
      publicKey: process.env.LANGFUSE_PUBLIC_KEY?.trim() || file.publicKey,
      secretKey: process.env.LANGFUSE_SECRET_KEY?.trim() || file.secretKey,
      baseUrl: process.env.LANGFUSE_BASE_URL?.trim() || file.baseUrl,
    };
  } catch { return null; }
}

export async function postQualityScore(runId, taskId, repeat, traceId, value, comment, metadata) {
  const creds = loadLangfuseCreds();
  if (!creds?.secretKey || !creds.baseUrl) throw new Error('langfuse 凭证缺失');
  const id = 'qj-' + createHash('sha256').update(`${runId}|${taskId}|${repeat}|quality-score`).digest('hex').slice(0, 32);
  const res = await fetch(`${creds.baseUrl}/api/public/scores`, {
    method: 'POST',
    headers: {
      Authorization: 'Basic ' + Buffer.from(`${creds.publicKey}:${creds.secretKey}`).toString('base64'),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      id, traceId, name: 'quality-score', value, dataTypes: ['NUMERIC'],
      environment: 'eval', // 顶层字段才进 scores.environment（langfuse_writer 实测口径）
      comment: String(comment).slice(0, 500),
      metadata,
    }),
    signal: AbortSignal.timeout(10000),
  });
  if (res.status !== 201 && res.status !== 200) {
    throw new Error(`api/public/scores HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  return id;
}

// ── sidecar 缓存（同指纹条目复用，换 prompt 版本自动失效重判）────────────────
function sidecarPath(reportPath) {
  return resolve(ROOT, 'eval/reports', 'quality-' + basename(reportPath));
}

function loadSidecar(reportPath) {
  const p = sidecarPath(reportPath);
  if (!existsSync(p)) return null;
  try { return JSON.parse(readFileSync(p, 'utf-8')); } catch { return null; }
}

function saveSidecar(reportPath, data) {
  writeFileSync(sidecarPath(reportPath), JSON.stringify(data, null, 1), 'utf-8');
}

/** 后置只读聚合（v7③，纯函数——零 LLM、零 sidecar 写）：从 sidecar 资格链槽按报告行序取有效分。
 *  rows=槽内 mapped 非 null 的行（形态与判分结果兼容，可直接喂 selectGaps/--post）；
 *  missing=报告有而槽缺（或 mapped null）的行——后置模式报数不补判（先跑全量判）。
 *  槽键=QUALIFIED_MODELS 全链串（判定型链锁死后键稳定；缺槽=从未全量判过或链已换血）。
 *  指纹闸（审查 P1-1）：只认槽键不认指纹=读路径漏洞——历史 v6 跑批若可用链恰好只剩单资格模型
 *  （限流夜窗合理产物），槽键与 v7 资格槽逐字撞名，--post 会把 v6 口径分打成 v7 标签入库。
 *  写路径有"指纹变更清空 by_judge"，读路径必须对偶：指纹不匹配一律按 stale 拒读。 */
export function collectScoredRowsFromSidecar(sidecar, report) {
  const chainKey = QUALIFIED_MODELS.join(' > ');
  const entries = report.results.map((r) => ({ task: r.task, repeat: r.repeat ?? 1 }));
  if (!sidecar) return { rows: [], missing: entries, chainKey, slotMissing: true, why: 'sidecar 不存在（从未全量判过）' };
  if (sidecar.prompt_fingerprint !== PROMPT_FINGERPRINT) {
    return { rows: [], missing: entries, chainKey, slotMissing: true, why: `sidecar 指纹过期（${sidecar.prompt_fingerprint ?? '无'} ≠ 现行 ${PROMPT_FINGERPRINT}）——旧口径的分不许打现行标签，先重跑全量判` };
  }
  const slot = sidecar.by_judge?.[chainKey];
  if (!slot) return { rows: [], missing: entries, chainKey, slotMissing: true, why: '资格链槽缺失（从未全量判过或链已换血）' };
  const rows = [], missing = [];
  for (const e of entries) {
    const cached = slot.items[`${e.task}#${e.repeat}`];
    if (cached && cached.mapped != null) rows.push({ ...cached, repeat: e.repeat });
    else missing.push(e);
  }
  return { rows, missing, chainKey, slotMissing: false, why: '' };
}

/** collectScoredRowsFromSidecar 的磁盘版：--post/--find-gap CLI 路径用。 */
export function collectScoredRows(reportPath, report) {
  return collectScoredRowsFromSidecar(loadSidecar(reportPath), report);
}

/** 跑一批行（entries=[{task,repeat}]，带 sidecar 增量）：
 *  - 寻址/缓存键=task#repeat（P1-2）；槽键=候选链串（换裁判 GLM↔Kimi 不误用他裁判的分）；
 *  - 指纹匹配且有效分的条目复用；null 条目不缓存（临时故障不当永久结论）；
 *  - P1-1 选型=「指纹变更清空整个 by_judge」而非每槽自存指纹：全局 prompt_fingerprint 是案卷
 *    唯一权威指纹，任一变更即全量失效——只清当前槽会留下"其他槽旧 prompt 的分被新 prompt 复用"
 *    的跨槽缺口（审查 P1-1 复现序列：v3 跑 GLM → 升 v4 只跑 Kimi → 再跑 GLM 即错）。
 *    代价=其他裁判槽的缓存分与 usage 一并作废（本就属旧 prompt，理应重判；顺带修复 P2-⑩
 *    "跨版本混计 token"）。slot.prompt_fingerprint 另记槽内指纹，仅供取证。 */
async function judgeBatch(reportPath, report, entries, judge) {
  const sidecar = loadSidecar(reportPath) || {
    report: report.run_id || basename(reportPath),
    prompt_version: PROMPT_VERSION,
    prompt_fingerprint: PROMPT_FINGERPRINT,
    rounds: [],
    by_judge: {},
  };
  const fresh = sidecar.prompt_fingerprint !== PROMPT_FINGERPRINT;
  if (fresh) sidecar.by_judge = {}; // 指纹变了所有槽旧条目全失效（不同 prompt 的分不许混用）
  const chainKey = judge.map((c) => `${c.name}/${c.model}`).join(' > ');
  const slot = sidecar.by_judge[chainKey] ??= { items: {}, usage: { prompt_tokens: 0, completion_tokens: 0, requests: 0 }, prompt_fingerprint: PROMPT_FINGERPRINT };
  const usage = slot.usage;
  const out = [];
  let reused = 0;
  for (const e of entries) {
    const addr = `${e.task}#${e.repeat}`;
    const item = report.results.find((r) => addrOf(r) === addr); // 按行寻址（P1-2：同名多行各判各的）
    if (!item || !item.reply_full) { out.push({ task: e.task, repeat: e.repeat, dims: null, total: null, mapped: null, null_reason: '报告缺题/缺 reply_full', one_line_reason: null, judge_model: null }); continue; }
    const cached = slot.items[addr];
    if (cached && cached.mapped != null) { out.push({ ...cached, repeat: e.repeat }); reused++; continue; }
    const judged = await judgeTask(judge, item, usage);
    judged.repeat = e.repeat;
    out.push(judged);
    if (judged.mapped != null) slot.items[addr] = judged;
    else delete slot.items[addr]; // 清掉旧失效条目
    if (rowGapMs() > 0) await _hooks.sleep(rowGapMs());
  }
  sidecar.prompt_version = PROMPT_VERSION;
  sidecar.prompt_fingerprint = PROMPT_FINGERPRINT;
  sidecar.judge_provider = judge[0]?.name ?? '';
  sidecar.judge_model = chainKey;
  sidecar.updated_at = new Date().toISOString();
  return { results: out, sidecar, reused, usage, chainKey };
}

// ── CLI ──────────────────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2);
  const flags = args.filter((a) => a.startsWith('--'));
  const files = args.filter((a) => !a.startsWith('--'));
  const reportPath = files[0];
  if (!reportPath) {
    console.error('用法：node eval/quality_judge.mjs <report.json> [--calibrate|--post|--find-gap] [--judge glm|kimi]');
    console.error(`  默认=全量判（资格硬锁 ${QUALIFIED_MODELS.join(' > ')}；限流退避等待绝不降级）`);
    console.error('  --calibrate=校准 8 题（例外允许全候选链——资格由校准产生）');
    console.error('  --post/--find-gap=后置只读（读 sidecar 资格槽，零 LLM、不写 sidecar；缺判先跑全量判）');
    process.exit(1);
  }
  const report = JSON.parse(readFileSync(resolve(reportPath), 'utf-8'));
  console.log(`质量裁判 prompt=${PROMPT_VERSION} 指纹=${PROMPT_FINGERPRINT} 报告=${report.run_id || reportPath} 行数=${report.results.length}（题数=${new Set(report.results.map((r) => r.task)).size}）`);

  // ── 后置只读（v7③）：--post/--find-gap 不走判分主链——读 sidecar 资格槽，零 LLM、不写 sidecar。
  //    （--calibrate 与后置并传无意义，校准分支优先；后置模式不依赖裁判可用性。）
  if ((flags.includes('--post') || flags.includes('--find-gap')) && !flags.includes('--calibrate')) {
    const { rows, missing, chainKey, slotMissing, why } = collectScoredRows(reportPath, report);
    if (slotMissing) {
      console.error(`后置只读拒绝：${why || `sidecar 缺资格链槽（${chainKey}）`}——先跑全量判补齐：node eval/quality_judge.mjs ${reportPath}`);
      process.exit(1);
    }
    const mainByAddr = new Map(report.results.map((r) => [addrOf(r), r])); // P1-2：主分/traceId 按行取
    const scored = rows;
    const avg = scored.length ? (scored.reduce((a, b) => a + b.mapped, 0) / scored.length).toFixed(2) : 'n/a';
    console.log(`\n后置只读（v7：零 LLM、不写 sidecar）· 资格槽=${chainKey} · 有效 ${scored.length} 行 · 缺判 ${missing.length} 行`);
    if (missing.length) console.log(`  ⚠ 缺判 ${missing.length} 行未计入——补齐：node eval/quality_judge.mjs ${reportPath}`);
    console.log(`质量分均值（0-5，sidecar ${PROMPT_VERSION} 口径）= ${avg}`);

    if (flags.includes('--find-gap')) {
      const gaps = selectGaps(scored, mainByAddr);
      console.log(`\n--find-gap 清单（主分≥4 且质量分<3，"对但不好"候选）: ${gaps.length} 行`);
      for (const g of gaps) {
        const main = mainByAddr.get(addrOf(g))?.score;
        console.log(`  ${String(g.task).padEnd(14)} #${g.repeat} 主分=${main} 质量分=${g.mapped} (${g.total}/12) ${(g.one_line_reason || '').slice(0, 60)}`);
      }
      if (!gaps.length) console.log('  （无命中）');
    }

    if (flags.includes('--post')) {
      let posted = 0, skippedNoTrace = 0, failed = 0;
      for (const r of scored) {
        const item = mainByAddr.get(addrOf(r));
        if (!item?.traceId) { skippedNoTrace++; continue; }
        try {
          await postQualityScore(
            report.run_id || basename(reportPath), r.task, r.repeat ?? 1, item.traceId, r.mapped,
            `${r.total}/12 · ${r.one_line_reason || ''}`,
            {
              eval_run_id: report.run_id || '', task_id: r.task, repeat: r.repeat ?? 1, environment: 'eval',
              prompt_version: PROMPT_VERSION, prompt_fingerprint: PROMPT_FINGERPRINT,
              dims: r.dims, confidence: r.dims?.confidence ?? null, total: r.total,
              judge: r.judge_model ?? '',
            },
          );
          posted++;
        } catch (e) { failed++; console.warn(`[post] ${r.task}#${r.repeat} 失败: ${(e)?.message ?? e}`); }
      }
      console.log(`\n--post: 写入 ${posted} · 跳过（traceId 缺失）${skippedNoTrace} · 失败 ${failed}（score 名=quality-score, environment=eval, ${PROMPT_VERSION} 口径重发=同幂等 id 覆盖）`);
    }
    process.exit(0);
  }

  const judgeArg = args.find((a) => a.startsWith('--judge'));
  const only = judgeArg ? (judgeArg.includes('=') ? judgeArg.split('=')[1] : args[args.indexOf(judgeArg) + 1]) : null;
  const calibrating = flags.includes('--calibrate');
  // 原文传入（不预 toUpperCase）：selectJudge 内部按"提供方名大小写不敏感 OR 模型 id 全等"双匹配——
  // 预大写会把 glm-5.3 变 GLM-5.3 使模型点名恒失配（2026-10-29 第三轮校准启动失败的根因）
  const judge = await selectJudge(only, { calibrate: calibrating });
  if (!judge.length) { console.error(`--judge ${only}：该提供方探测不可用`); process.exit(1); }
  console.log(`裁判候选链=${judge.map((c) => `${c.name}/${c.model}`).join(' > ')}（${calibrating ? '校准模式：全候选链（试新裁判是校准本职）' : `资格硬锁 ${QUALIFIED_MODELS.join(' > ')}：限流退避等待不降级`}${only ? `，--judge ${only} 限定` : ''}）`);

  // ── --calibrate：8 题人工锚 + Spearman ≥0.7 ──
  if (flags.includes('--calibrate')) {
    const cal = JSON.parse(readFileSync(resolve(ROOT, 'eval/quality_calibration.json'), 'utf-8'));
    const ranked = [...cal.human_ranked].sort((a, b) => a.rank - b.rank);
    const entries = ranked.map((x) => {
      const row = report.results.find((r) => r.task === x.task);
      return { task: x.task, repeat: row?.repeat ?? 1 };
    });
    const { results, sidecar, reused, usage } = await judgeBatch(reportPath, report, entries, judge);
    const byId = new Map(results.map((r) => [r.task, r]));
    // 对齐计算（2026-10-29 分层声明）：门禁集=人工锚−alignment_exclusions（混层锚剔出对齐，锚文件原样）；
    // 全锚 ρ 仅作透明度参考。符号契约不变（取负=+1 对齐人工序，见 calibrationAlignment 注释）。
    const exclusions = Array.isArray(cal.alignment_exclusions) ? cal.alignment_exclusions.map((x) => x.task) : [];
    const { rho_gate: rho, gate_n, rho_all: rhoAll, excluded } = calibrationAlignment(ranked, byId, exclusions);
    const pass = rho != null && rho >= cal.pass_threshold;
    const exSet = new Set(excluded);
    console.log(`\n校准 ${ranked.length} 题（人工序 1=最好${excluded.length ? `；※=分层声明剔除项(${excluded.join(',')})不入门禁` : ''}）:`);
    console.log('  人工序  题目         D1-D6                 总分  映射0-5  一句话理由');
    for (const x of ranked) {
      const r = byId.get(x.task);
      const dims = r?.dims ? DIM_KEYS.map((k) => r.dims[k]).join('') : '------';
      console.log(`  ${String(x.rank).padStart(3)}${exSet.has(x.task) ? '※' : ' '}   ${x.task.padEnd(12)} ${dims}  ${String(r?.total ?? '-').padStart(4)}  ${String(r?.mapped ?? 'null').padEnd(7)} ${(r?.one_line_reason || r?.null_reason || '').slice(0, 60)}`);
    }
    const nulled = results.filter((r) => r.mapped == null).length;
    console.log(`\nSpearman(judge 总分, 人工序) 门禁集(${gate_n}题) = ${rho ?? 'null（有题目弃用，不可算）'}（+1=与人工序完全一致） | 阈值 ${cal.pass_threshold} → ${pass ? 'PASS' : 'FAIL'}${excluded.length ? `\n  参考：全锚(${ranked.length}题) ρ=${rhoAll ?? 'null'}（含混层锚，不入门禁；剔除依据见 quality_calibration.json alignment_exclusions）` : ''}`);
    console.log(`弃用 ${nulled}/${results.length} · 复用缓存 ${reused} · token: prompt=${usage.prompt_tokens} completion=${usage.completion_tokens} requests=${usage.requests}`);
    sidecar.rounds.push({
      mode: 'calibrate', at: new Date().toISOString(),
      prompt_version: PROMPT_VERSION, prompt_fingerprint: PROMPT_FINGERPRINT,
      judge_chain: judge.map((c) => `${c.name}/${c.model}`).join(' > '), rho, pass, nulled,
      rho_all_anchors: rhoAll, alignment_gate_n: gate_n,
      alignment_exclusions: excluded,
      per_task: results.map((r) => ({ task: r.task, repeat: r.repeat, total: r.total, mapped: r.mapped, judge_model: r.judge_model ?? null, null_reason: r.null_reason })),
    });
    saveSidecar(reportPath, sidecar);
    process.exit(pass ? 0 : 2);
  }

  // ── 全量判（默认模式；--post/--find-gap 已提前走只读路径，不再与本主链耦合）──
  const entries = report.results.map((r) => ({ task: r.task, repeat: r.repeat ?? 1 }));
  const { results, sidecar, reused, usage } = await judgeBatch(reportPath, report, entries, judge);
  const scored = results.filter((r) => r.mapped != null);
  const avg = scored.length ? (scored.reduce((a, b) => a + b.mapped, 0) / scored.length).toFixed(2) : 'n/a';
  const nulled = results.length - scored.length;
  sidecar.last_run = {
    mode: 'full',
    at: new Date().toISOString(), avg_quality: scored.length ? Number(avg) : null,
    nulled, total_rows: results.length, distinct_tasks: new Set(results.map((r) => r.task)).size, reused,
  };
  saveSidecar(reportPath, sidecar);

  console.log(`\n判完 ${results.length} 行 / ${new Set(results.map((r) => r.task)).size} 题（复用缓存 ${reused}）· 有效 ${scored.length} · 弃用 ${nulled}${results.length ? `（弃用率 ${(nulled / results.length * 100).toFixed(1)}%）` : ''}`);
  console.log(`质量分均值（0-5）= ${avg} · token: prompt=${usage.prompt_tokens} completion=${usage.completion_tokens} requests=${usage.requests}`);
  console.log(`后置收尾（只读）：node eval/quality_judge.mjs ${reportPath} --post   /   --find-gap`);
  process.exit(0);
}

if (IS_MAIN) {
  main().catch((e) => { console.error('[quality_judge] 致命错误:', e?.message ?? e); process.exit(1); });
}
