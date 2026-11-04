/**
 * 质量层 LLM 评审 · 纯函数+注入口单测（不外呼真实 API——工单硬约束）
 *
 * 覆盖：parseJudgeJson 鲁棒解析与 schema 非法路径（含 P2-1 强转洞封堵）/ mapToFive 映射 /
 *      judgeTask 真路径（第 4 参注入口 stub callFn：confidence 闸 / P1-3 解析失败重试 /
 *      API 耗尽 / P2-2 $ 模式注入封堵）/ Spearman 已知序列断言（含并列平均秩）/
 *      addrOf 寻址键（P1-2）/ selectGaps 按行谓词 / v3-v6 正文留档指纹复算（fingerprintOf）/
 *      v7① buildUserText 模板分型（单轮=v6 逐字节/多轮三段式）/
 *      v7② 资格硬锁（QUALIFIED 过滤/探测全败硬错/校准例外/限流退避不降级/预算耗尽）/
 *      v7③ 后置只读聚合（collectScoredRowsFromSidecar：有效行/缺判分账/槽缺失）。
 * 契约：eval/quality_judge.mjs（改实现必须先改测试）。
 * 运行：node --test eval/quality_judge.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  parseJudgeJson, mapToFive, spearman, rankAvg, selectGaps, judgeTask, addrOf,
  PROMPT_VERSION, PROMPT_FINGERPRINT, CONF_MIN, JUDGE_SYSTEM_PROMPT, USER_TEMPLATE, PROMPT_ARCHIVE,
  MULTI_USER_TEMPLATE, buildUserText, fingerprintOf, QUALIFIED_MODELS,
  selectJudge, callJudgeOnce, collectScoredRowsFromSidecar, _setTestHooks, _resetProbeCache, parseAnthropicResponse, calibrationAlignment,
} from './quality_judge.mjs';

const OK = '{"d1":2,"d2":2,"d3":2,"d4":2,"d5":2,"d6":2,"confidence":0.9,"one_line_reason":"结论先行口径完整"}';

// judgeTask 注入口公用件：stub 裁判调用（零外呼），可编排返回序列与捕获 userText。
const STUB_JUDGE = [{ name: 'stub', model: 'stub-m' }];
const stubReply = (content) => ({ content, usage: { prompt_tokens: 10, completion_tokens: 5 }, used: 'stub/stub-m' });
const okJson = (confidence, d5 = 2) => JSON.stringify({
  d1: 2, d2: 2, d3: 2, d4: 2, d5, d6: 2, confidence, one_line_reason: 'ok',
});
const ITEM = { task: 't1', dimension: '销量', question: 'q', reply_full: 'r' };

// ── prompt 固件 ─────────────────────────────────────────────────────────
test('prompt 固件：版本号格式、指纹 sha256 前 8 位、模板占位齐全', () => {
  assert.match(PROMPT_VERSION, /^v\d+$/); // 值随校准轮次递增（v1→v2…），契约=格式而非具体值
  assert.match(PROMPT_FINGERPRINT, /^[0-9a-f]{8}$/);
  assert.ok(JUDGE_SYSTEM_PROMPT.includes('D6'));
  assert.ok(/泄漏扫描|泄漏/.test(JUDGE_SYSTEM_PROMPT), '裁判 prompt 必须含泄漏扫描纪律');
  // v4 起 D5 为三级泄漏分级（G-5 Step8 拍板）：主体多处/关键位置=0；口径小节/尾部单处轻度=1；无=2
  assert.ok(JUDGE_SYSTEM_PROMPT.includes('泄漏分级'), 'D5 必须是分级语义而非"任一泄漏=0"');
  assert.ok(JUDGE_SYSTEM_PROMPT.includes('辅助位置'), 'D5=1 档须有辅助位置定义');
  for (const ph of ['{dimension}', '{question}', '{reply}']) assert.ok(USER_TEMPLATE.includes(ph));
  // v7① 多轮三段式模板占位
  for (const ph of ['{dimension}', '{n}', '{turns}', '{reply}']) assert.ok(MULTI_USER_TEMPLATE.includes(ph), `多轮模板缺占位 ${ph}`);
  assert.ok(MULTI_USER_TEMPLATE.includes('最后一轮'), '多轮模板必须显式标注最后一轮');
  // v7② 资格链非空且形如 Provider/model
  for (const q of QUALIFIED_MODELS) assert.match(q, /^[\w-]+\/[\w.-]+$/);
});

test('fingerprintOf：空多轮=旧公式（3 段拼接）逐字节一致——归档复算的唯一入口', () => {
  // 旧公式直算（v3 首轮曾用的形态）与 fingerprintOf 空多轮必须同值
  const a = PROMPT_ARCHIVE.v5;
  const manual = createHash('sha256')
    .update('v5\n' + a.system + '\n---USER---\n' + a.user_template)
    .digest('hex').slice(0, 8);
  assert.equal(fingerprintOf('v5', a.system, a.user_template, ''), manual);
  assert.equal(fingerprintOf('v5', a.system, a.user_template), manual, 'multiTpl 缺省=空串同值');
  // 追加多轮段=不同指纹（v7 起第 4 段入指纹输入）
  assert.notEqual(fingerprintOf('v5', a.system, a.user_template, 'X'), manual);
});

test('PROMPT_ARCHIVE：v3-v6 正文留档指纹可复算；v1/v2 如实声明不可复算（不事后重构）', () => {
  const expect = { v3: '03786cb8', v4: '4bcfbcdf', v5: '1f1c63e0', v6: '8b7c7620' };
  for (const [v, fp] of Object.entries(expect)) {
    const a = PROMPT_ARCHIVE[v];
    assert.ok(a && typeof a.system === 'string' && a.system.length > 500, `${v} 全文必须留档`);
    assert.equal(fingerprintOf(v, a.system, a.user_template, ''), fp, `${v} 留档正文按现行哈希输入必须复算出指纹（留档保真的机械验证）`);
    assert.equal(fp, a.fingerprint, `${v} 归档指纹字段与期望值一致`);
  }
  // 审查 P2-⑧：v7 承诺"单轮模板/系统提示词与 v6 不动"的最强机械钉死——现行正文 ≡ v6 归档逐字一致
  assert.equal(USER_TEMPLATE, PROMPT_ARCHIVE.v6.user_template, '现行单轮模板必须与 v6 归档逐字一致（v7① 只加多轮分型）');
  assert.equal(JUDGE_SYSTEM_PROMPT, PROMPT_ARCHIVE.v6.system, '现行系统提示词必须与 v6 归档逐字一致');
  assert.equal(PROMPT_ARCHIVE.v6.fingerprint, '8b7c7620', 'v6 指纹与重判前 sidecar 现存值一致（归档锚）');
  for (const lost of PROMPT_ARCHIVE.lost) {
    assert.match(lost.version, /^v\d+$/);
    assert.match(lost.fingerprint, /^[0-9a-f]{8}$/);
    assert.ok(!('system' in lost), 'v1/v2 正文未留档——不许事后重构伪造（红线#1）');
    assert.ok(/不可复算/.test(lost.note));
  }
});

// ── v7① buildUserText 模板分型 ──────────────────────────────────────────
test('buildUserText 单轮：与 v6 replace 链输出逐字节一致（含 $ 模式与回退路径）', () => {
  // 常规行：与 v6 的三段 replace 链逐字节一致（ρ 连续性的机械前提）
  const item = { task: 't9', dimension: '配置', question: 'q1', reply_full: 'r1' };
  const expected = USER_TEMPLATE
    .replace('{dimension}', () => item.dimension || '-')
    .replace('{question}', () => item.question || item.task)
    .replace('{reply}', () => item.reply_full || '');
  assert.equal(buildUserText(item), expected);
  // question 缺省回退 item.task；dimension 缺省 '-'
  const item2 = { task: 't8' };
  const expected2 = USER_TEMPLATE
    .replace('{dimension}', () => '-')
    .replace('{question}', () => 't8')
    .replace('{reply}', () => '');
  assert.equal(buildUserText(item2), expected2);
  // $ 模式注入防护保留（P2-2）
  const item3 = { task: 't7', dimension: '口碑', question: 'a$&b$`c', reply_full: "x$'y$&z" };
  assert.ok(buildUserText(item3).includes('a$&b$`c') && buildUserText(item3).includes("x$'y$&z"));
  // turnMessages 缺失或单轮 → 回退单轮形态（旧报告兼容）
  assert.equal(buildUserText({ ...item, turnMessages: undefined }), expected);
  assert.equal(buildUserText({ ...item, turnMessages: ['只有一轮'] }), expected);
  assert.equal(buildUserText({ ...item, turnMessages: null }), expected);
});

test('buildUserText 多轮（v7① 冤案根治）：三段式——各轮消息+末轮标注+指向声明', () => {
  const item = { task: 'multi-02', dimension: '口碑', turnMessages: ['轴距2700最畅销的BEV？', '低配高配差多少钱？', '车主最满意哪方面？'], reply_full: '车主最满意"好开好停"。' };
  const text = buildUserText(item);
  assert.ok(text.includes('多轮对话，共 3 轮'), '维度行标注轮数');
  assert.ok(text.includes('第1轮：轴距2700最畅销的BEV？'));
  assert.ok(text.includes('第2轮：低配高配差多少钱？'));
  assert.ok(text.includes('第3轮（最后一轮）：车主最满意哪方面？'), '末轮显式标注');
  assert.ok(text.includes('只需回答「最后一轮」的问题'), '指向声明——裁判 D1 判末轮问题');
  assert.ok(text.includes('（针对最后一轮问题的回复）'));
  assert.ok(text.includes('车主最满意"好开好停"。'), '末轮回复入文');
  for (const ph of ['{dimension}', '{n}', '{turns}', '{reply}', '{question}']) {
    assert.ok(!text.includes(ph), `占位符 ${ph} 必须全部替换`);
  }
  // 两轮题：退化为首轮+末轮（拍板三段式的最小形态）
  const two = buildUserText({ task: 'm2', dimension: '销量', turnMessages: ['问A', '问B'], reply_full: 'r' });
  assert.ok(two.includes('共 2 轮') && two.includes('第1轮：问A') && two.includes('第2轮（最后一轮）：问B'));
  // 非字符串轮项被剔除后不足 2 → 回退单轮（脏数据不炸）
  assert.ok(buildUserText({ task: 'm3', dimension: '-', question: 'q', reply_full: 'r', turnMessages: ['问A', 42] }).startsWith('【用户问题】（维度：-）'));
});

test('judgeTask 多轮行：captured userText 走三段式（末轮指向，非首轮 40 字截断题面）', async () => {
  let captured = '';
  const item = { task: 'multi-12', dimension: '销量', question: '首轮流速快不快？（40字截断形态）', turnMessages: ['首轮流速快不快？', '海豚8月销量多少？'], reply_full: '16,879 辆。' };
  await judgeTask(STUB_JUDGE, item, null, async (_j, text) => { captured = text; return stubReply(OK); });
  assert.ok(captured.includes('第2轮（最后一轮）：海豚8月销量多少？'), '末轮问题必须入题面');
  assert.ok(captured.includes('只需回答「最后一轮」'), '指向声明必须入题面');
  assert.ok(!captured.includes('【用户问题】（维度：销量）\n首轮流速快不快？（40字截断形态）'), '不得再用首轮 question 单轮形态');
});

// ── parseJudgeJson ──────────────────────────────────────────────────────
test('parseJudgeJson: 标准 JSON 直解', () => {
  const r = parseJudgeJson(OK);
  assert.deepEqual(
    { d1: r.d1, d2: r.d2, d3: r.d3, d4: r.d4, d5: r.d5, d6: r.d6 },
    { d1: 2, d2: 2, d3: 2, d4: 2, d5: 2, d6: 2 },
  );
  assert.equal(r.confidence, 0.9);
});

test('parseJudgeJson: 代码栅栏+前后缀散文仍可抽出', () => {
  const text = '好的，评分如下：\n```json\n' + OK + '\n```\n以上。';
  assert.equal(parseJudgeJson(text).d6, 2);
});

test('parseJudgeJson: 纯档位数字串容错（"0"|"1"|"2" 与数字串 confidence）', () => {
  const r = parseJudgeJson('{"d1":"1","d2":2,"d3":0,"d4":1,"d5":2,"d6":0,"confidence":"0.88","one_line_reason":"ok"}');
  assert.equal(r.d1, 1);
  assert.equal(r.confidence, 0.88);
});

test('parseJudgeJson: 维度越界/缺维/非整数 → null（自相矛盾机械弃用）', () => {
  const mk = (o) => JSON.stringify({ d1: 1, d2: 1, d3: 1, d4: 1, d5: 1, d6: 1, confidence: 0.9, one_line_reason: 'r', ...o });
  assert.equal(parseJudgeJson(mk({ d3: 3 })), null);   // 越上界
  assert.equal(parseJudgeJson(mk({ d3: -1 })), null);  // 越下界
  assert.equal(parseJudgeJson(mk({ d3: 1.5 })), null); // 非整数
  assert.equal(parseJudgeJson('{"d1":1,"confidence":0.9}'), null); // 缺多维
  // 多余键容忍（宽松解析）：六维齐全+confidence 合法即接受，d9 不参与
  assert.notEqual(parseJudgeJson(mk({ d9: 1 })), null);
  assert.equal(parseJudgeJson(''), null);
  assert.equal(parseJudgeJson(null), null);
});

test('parseJudgeJson: P2-1 强转洞封堵——null/true/空串不再被 Number 收编成合法分', () => {
  const mk = (o) => JSON.stringify({ d1: 1, d2: 1, d3: 1, d4: 1, d5: 1, d6: 1, confidence: 0.9, one_line_reason: 'r', ...o });
  // 旧洞：Number(null)=0 / Number(true)=1 / Number('')=0 —— 曾被静默收作合法 0/1 分
  assert.equal(parseJudgeJson(mk({ d3: null })), null);
  assert.equal(parseJudgeJson(mk({ d3: true })), null);
  assert.equal(parseJudgeJson(mk({ d3: '' })), null);
  assert.equal(parseJudgeJson(mk({ d3: '2 ' })).d3, 2); // 纯档位串容忍（前后空白）
  // confidence 旧洞：true→1 过闸、null→0、''→0
  assert.equal(parseJudgeJson(mk({ confidence: null })), null);
  assert.equal(parseJudgeJson(mk({ confidence: true })), null);
  assert.equal(parseJudgeJson(mk({ confidence: '' })), null);
  assert.equal(parseJudgeJson(mk({ confidence: '0.8' })).confidence, 0.8); // 非空数字串容忍保留
});

test('parseJudgeJson: confidence 越界/缺失、one_line_reason 缺失 → null', () => {
  const mk = (o) => JSON.stringify({ d1: 1, d2: 1, d3: 1, d4: 1, d5: 1, d6: 1, one_line_reason: 'r', ...o });
  assert.equal(parseJudgeJson(mk({ confidence: 1.2 })), null);
  assert.equal(parseJudgeJson(mk({ confidence: 'high' })), null);
  assert.equal(parseJudgeJson(mk({ confidence: 0.9, one_line_reason: '' })), null);
});

// ── mapToFive ───────────────────────────────────────────────────────────
test('mapToFive: 0-12 线性映射 0-5 保留一位小数', () => {
  assert.equal(mapToFive(0), 0);
  assert.equal(mapToFive(12), 5);
  assert.equal(mapToFive(6), 2.5);
  assert.equal(mapToFive(10), 4.2);   // 10/12*5=4.1667 → 4.2
  assert.equal(mapToFive(11), 4.6);   // 4.5833 → 4.6
  assert.equal(mapToFive(1), 0.4);
  assert.equal(mapToFive(9), 3.8);    // 3.75 → 3.8（round 半进位）
});

// ── judgeTask 真路径（第 4 参注入口，stub 零外呼；P2-4 修复：不再用假脚手架空转断言）──
test('judgeTask 真路径：confidence<0.75 → mapped null + null_reason 带置信值（恰好 1 次调用）', async () => {
  const calls = [];
  const res = await judgeTask(STUB_JUDGE, ITEM, { prompt_tokens: 0, completion_tokens: 0, requests: 0 },
    async (_j, text) => { calls.push(text); return stubReply(okJson(0.6)); });
  assert.equal(calls.length, 1, '解析成功不触发重试');
  assert.equal(res.task, 't1');
  assert.equal(res.mapped, null);
  assert.equal(res.total, 12, 'total 仍算出（供弃用诊断）');
  assert.equal(res.null_reason, 'confidence 0.6 < 0.75');
  assert.equal(res.judge_model, 'stub/stub-m');
  assert.ok(calls[0].includes(ITEM.question) && calls[0].includes(ITEM.reply_full), 'userText 含题面与回复');
});

test('judgeTask 真路径：有效回复 → mapped=mapToFive(total) 且 usage 计数', async () => {
  const usage = { prompt_tokens: 0, completion_tokens: 0, requests: 0 };
  const res = await judgeTask(STUB_JUDGE, ITEM, usage, async () => stubReply(OK));
  assert.equal(res.mapped, 5);
  assert.equal(res.null_reason, null);
  assert.deepEqual(usage, { prompt_tokens: 10, completion_tokens: 5, requests: 1 });
});

test('judgeTask 真路径：API 耗尽 → null 形态（对函数输出断言，非手写字面量）', async () => {
  const res = await judgeTask(STUB_JUDGE, ITEM, null, async () => null);
  assert.equal(res.mapped, null);
  assert.equal(res.dims, null);
  assert.equal(res.total, null);
  assert.equal(res.null_reason, '解析失败/API 耗尽');
  assert.equal(res.judge_model, null);
});

test('judgeTask 真路径：P1-3 非法 JSON 同候选链重试一次成功 → 有效分且恰好 2 次调用', async () => {
  const replies = ['抱歉，我认为这份回复整体不错，无法给出结构化打分。', okJson(0.9, 1)];
  let i = 0;
  const res = await judgeTask(STUB_JUDGE, ITEM, { prompt_tokens: 0, completion_tokens: 0, requests: 0 },
    async () => stubReply(replies[i++]));
  assert.equal(i, 2, '首答非法 JSON 后必须重试恰好一次');
  assert.equal(res.mapped, mapToFive(11));
  assert.equal(res.dims.d5, 1);
});

test('judgeTask 真路径：重试后仍非法 JSON → null 且 null_reason 如实声明（不再有第三次调用）', async () => {
  let i = 0;
  const res = await judgeTask(STUB_JUDGE, ITEM, null, async () => { i++; return stubReply('垃圾回复' + i); });
  assert.equal(i, 2);
  assert.equal(res.mapped, null);
  assert.equal(res.null_reason, '解析失败（重试一次后仍非法 JSON）');
});

test('judgeTask 真路径：P2-2 $ 模式注入封堵——question/reply 含 $& $` $\' 不改写 userText', async () => {
  let captured = '';
  const item = { task: 't2', dimension: '口碑', question: 'a$&b$`c', reply_full: "x$'y$&z" };
  await judgeTask(STUB_JUDGE, item, null, async (_j, text) => { captured = text; return stubReply(OK); });
  assert.ok(captured.includes('a$&b$`c'), 'question 的 $ 序列必须原样保留');
  assert.ok(captured.includes("x$'y$&z"), 'reply 的 $ 序列必须原样保留');
  assert.ok(!captured.includes('{question}') && !captured.includes('{reply}') && !captured.includes('{dimension}'), '占位符全部替换');
});

// ── addrOf（P1-2 寻址键）─────────────────────────────────────────────────
test('addrOf: task#repeat 寻址键（repeat 缺省=1）', () => {
  assert.equal(addrOf({ task: 'a' }), 'a#1');
  assert.equal(addrOf({ task: 'a', repeat: 1 }), 'a#1');
  assert.equal(addrOf({ task: 'a', repeat: 3 }), 'a#3');
  assert.notEqual(addrOf({ task: 'a', repeat: 2 }), addrOf({ task: 'a', repeat: 3 }), '同名不同 repeat 必须不同键');
});

// ── Spearman ────────────────────────────────────────────────────────────
test('spearman: 完全同序=1，完全逆序=-1', () => {
  assert.equal(spearman([1, 2, 3, 4, 5, 6, 7, 8], [10, 20, 30, 40, 50, 60, 70, 80]), 1);
  assert.equal(spearman([1, 2, 3, 4, 5, 6, 7, 8], [80, 70, 60, 50, 40, 30, 20, 10]), -1);
});

test('spearman: 单对相邻换位=0.976（经典值 1-12/504）', () => {
  const rho = spearman([1, 2, 3, 4, 5, 6, 7, 8], [2, 1, 3, 4, 5, 6, 7, 8]);
  assert.ok(Math.abs(rho - 0.976) < 0.001, `got ${rho}`);
});

test('spearman: n=8 时阈值 0.7 对应 Σd² 预算（错 3 位=0.857 仍过，乱序=不过）', () => {
  // 人工序 1..8；judge 把第 1 名放到第 4 位：d=[3,-1,-1,-1,0,0,0,0] Σd²=12 → ρ=1-72/504=0.857 过
  const rho3 = spearman([1, 2, 3, 4, 5, 6, 7, 8], [4, 1, 2, 3, 5, 6, 7, 8]);
  assert.ok(rho3 > 0.7, `错3位应仍过阈 got ${rho3}`);
  const rho4 = spearman([1, 2, 3, 4, 5, 6, 7, 8], [5, 1, 2, 3, 4, 6, 7, 8]); // Σd²=20 → ρ=0.762 仍过阈
  assert.ok(Math.abs(rho4 - 0.762) < 0.001, `Σd²=20 应=0.762 got ${rho4}`);
  const rhoBad = spearman([1, 2, 3, 4, 5, 6, 7, 8], [5, 6, 7, 8, 1, 2, 3, 4]);
  assert.ok(rhoBad < 0.7, `半数翻转应不过阈 got ${rhoBad}`);
});

test('spearman: 并列平均秩（tie 处理）与非单调已知值', () => {
  // x 无并列、y 有并列 [1,1,3]：y 秩=[1.5,1.5,3]
  assert.deepEqual(rankAvg([1, 1, 3]), [1.5, 1.5, 3]);
  assert.deepEqual(rankAvg([3, 1, 2]), [3, 1, 2]);
  // x=[1,2,3] y=[1,1,3]：秩 y=[1.5,1.5,3]，Pearson-on-ranks=1.5/√3=0.866（并列须用一般定义，非 1-6Σd² 公式）
  const rho = spearman([1, 2, 3], [1, 1, 3]);
  assert.ok(Math.abs(rho - 0.866) < 0.001, `tie Spearman 应=0.866 got ${rho}`);
});

test('spearman: 退化输入 → null', () => {
  assert.equal(spearman([1], [1]), null);
  assert.equal(spearman([2, 2, 2], [1, 2, 3]), null); // 常数序列
  assert.equal(spearman([], []), null);
});

// ── --find-gap 谓词（验收#3：主分≥4 且质量分<3 清单能力；P1-2 按行寻址）─────
test('selectGaps: 只捞"主分≥4 且质量分<3"；null 质量分与低主分不计入（键=task#repeat）', () => {
  const q = [
    { task: 'a', repeat: 1, mapped: 2.5 },  // 命中（主5 质量2.5）
    { task: 'b', repeat: 1, mapped: 3.0 },  // 不命中（质量=3 非小于3）
    { task: 'c', repeat: 1, mapped: 2.0 },  // 不命中（主分2<4）
    { task: 'd', repeat: 1, mapped: null }, // 不命中（弃用≠低质量）
    { task: 'e', repeat: 1, mapped: 2.9 },  // 命中（主4 边界含）
    { task: 'f', repeat: 1, mapped: 1.0 },  // 不命中（主分缺失）
    { task: 'g', repeat: 2, mapped: 2.0 },  // 命中（同名 repeat2 行各有主分，互不串）
    { task: 'g', repeat: 3, mapped: 2.0 },  // 不命中（repeat3 主分=2，不受 repeat2 干扰）
  ];
  const main = new Map([
    ['a#1', { score: 5 }], ['b#1', { score: 5 }], ['c#1', { score: 2 }],
    ['d#1', { score: 5 }], ['e#1', { score: 4 }], ['f#1', {}],
    ['g#2', { score: 4 }], ['g#3', { score: 2 }],
  ]);
  assert.deepEqual(selectGaps(q, main).map((r) => `${r.task}#${r.repeat}`), ['a#1', 'e#1', 'g#2']);
});

// ── Anthropic 兼容路由（2026-10-29 路由切换：5.3-flash 走 /api/anthropic，套餐内可用）──
test('parseAnthropicResponse：thinking 块剥离、text 块拼接、usage 映射；空文本如实返回', () => {
  const data = {
    content: [
      { type: 'thinking', thinking: '推理中...' },
      { type: 'text', text: '{"d1":2' },
      { type: 'text', text: ',"d2":1}' },
    ],
    usage: { input_tokens: 1234, output_tokens: 567 },
  };
  const { text, usage } = parseAnthropicResponse(data);
  assert.equal(text, '{"d1":2,"d2":1}');
  assert.deepEqual(usage, { prompt_tokens: 1234, completion_tokens: 567 });
  // 只有 thinking 块（预算被推理吃光）→ 空文本（上层归"空回复"）
  assert.equal(parseAnthropicResponse({ content: [{ type: 'thinking', thinking: 'x' }] }).text, '');
  // 容错：content 缺失/非数组
  assert.equal(parseAnthropicResponse({}).text, '');
  assert.equal(parseAnthropicResponse(null).usage, null);
});

test('callJudgeOnce anthropic 形态：x-api-key 头 + system 顶层字段 + messages 单 user 轮 + text 块答案', async () => {
  const realFetch = global.fetch;
  try {
    const seen = [];
    global.fetch = async (url, init) => {
      seen.push({ url: String(url), headers: init.headers, body: JSON.parse(init.body) });
      return {
        ok: true, status: 200,
        json: async () => ({ content: [{ type: 'thinking', thinking: '...' }, { type: 'text', text: 'ANSWER' }], usage: { input_tokens: 10, output_tokens: 5 } }),
      };
    };
    const cand = { name: 'GLM', model: 'glm-5.3-flash', apiStyle: 'anthropic', endpoint: 'https://open.bigmodel.cn/api/anthropic/v1/messages', key: 'kk', maxTokens: 8000 };
    const r = await callJudgeOnce([cand], '判分文本');
    assert.equal(r.content, 'ANSWER', 'text 块拼接为答案');
    assert.equal(r.used, 'GLM/glm-5.3-flash');
    assert.deepEqual(r.usage, { prompt_tokens: 10, completion_tokens: 5 });
    const [call] = seen;
    assert.match(call.url, /\/api\/anthropic\/v1\/messages$/, '必须打 Anthropic 兼容端点');
    assert.equal(call.headers['x-api-key'], 'kk');
    assert.equal(call.headers['anthropic-version'], '2023-06-01');
    assert.equal(call.body.system.length > 100, true, 'system 提示词走顶层字段');
    assert.equal(call.body.messages.length, 1);
    assert.equal(call.body.messages[0].role, 'user', 'messages 只含 user 轮（system 不混入）');
    assert.equal(call.body.max_tokens, 8000);
  } finally { global.fetch = realFetch; }
});

// ── 校准对齐剔除（2026-10-29 用户拍板：混层锚剔出对齐、锚文件原样）────────────
test('calibrationAlignment：剔除项不入门禁但全锚 rho 照算；null 传播如实', () => {
  // 构造：人工序 1-4，其中 rank2=混层锚（judge 给满分反转）——剔掉后其余完美对齐
  const ranked = [{ rank: 1, task: 'a' }, { rank: 2, task: 'mix' }, { rank: 3, task: 'b' }, { rank: 4, task: 'c' }];
  const byId = new Map([
    ['a', { total: 9 }], ['mix', { total: 12 }], ['b', { total: 7 }], ['c', { total: 5 }],
  ]);
  const r = calibrationAlignment(ranked, byId, ['mix']);
  assert.equal(r.gate_n, 3);
  assert.deepEqual(r.excluded, ['mix']);
  assert.equal(r.rho_gate, 1, '剔混层锚后 a>b>c 与人工序完美一致');
  assert.ok(r.rho_all < 1 && r.rho_all != null, '全锚 rho 含反转锚必低于门禁集');
  // 无剔除：门禁=全锚
  const r2 = calibrationAlignment(ranked, byId, []);
  assert.equal(r2.gate_n, 4);
  assert.equal(r2.rho_gate, r2.rho_all);
  // 门禁集内有 null（弃用）→ rho_gate=null 不可算（宁缺毋错）；剔除项 null 不影响门禁
  const byId2 = new Map([['a', { total: 9 }], ['mix', { total: null }], ['b', { total: 7 }], ['c', { total: 5 }]]);
  assert.equal(calibrationAlignment(ranked, byId2, ['mix']).rho_gate, 1, '剔除项弃用不进门禁');
  assert.equal(calibrationAlignment(ranked, byId2, []).rho_gate, null, '门禁内弃用=不可算');
});

// ── v7② 资格硬锁（mock fetch/env；每测试前后清探测缓存与钩子，防串场）──────────
const QUALIFIED_CAND = { name: 'GLM', model: 'glm-5.3-flash', endpoint: 'http://x', key: 'k' };

/** env 卫生存取（审查 P2-⑦）：process.env[k] = undefined 会把字符串 "undefined" 留在环境里——
 *  恢复原值 undefined 时必须 delete。 */
const setEnv = (k, v) => { if (v === undefined) delete process.env[k]; else process.env[k] = v; };

test('selectJudge 硬锁：非资格模型可用也不入链/不被探测；资格探测全败 → 宁缺毋错硬错', async () => {
  const realFetch = global.fetch; const envGlm = process.env.GLM_api; const envKimi = process.env.Kimi_api;
  process.env.GLM_api = 'k'; process.env.Kimi_api = 'k';
  const probed = [];
  global.fetch = async (_url, init) => {
    const model = JSON.parse(init.body).model; probed.push(model);
    if (model === 'glm-5.3-flash') return { ok: false, status: 429, text: async () => 'rate limited' };
    return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: 'pong' } }] }) };
  };
  try {
    _resetProbeCache();
    // 锁定模式：资格模型 429 → 硬错（绝不降级组链），链外模型连探测都不发生
    await assert.rejects(selectJudge(null, {}), /宁缺毋错/);
    assert.ok(probed.includes('glm-5.3-flash'), '资格模型必须被探测');
    assert.ok(!probed.includes('glm-4-flash') && !probed.includes('kimi-k2.6'), '链外模型在锁定模式不得被探测');
    // 资格模型可用 → 链=[资格模型]，非资格不入链
    _resetProbeCache(); probed.length = 0;
    global.fetch = async (_u, init) => {
      const model = JSON.parse(init.body).model; probed.push(model);
      return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: 'pong' } }] }) };
    };
    const chain = await selectJudge(null, {});
    assert.deepEqual(chain.map((c) => `${c.name}/${c.model}`), QUALIFIED_MODELS, '锁定链=QUALIFIED 声明序');
    // --judge kimi（无资格且非校准）→ 拒绝并提示先过校准
    await assert.rejects(selectJudge('kimi', {}), /需先 --calibrate 过阈才有资格/);
    // 校准例外：全候选链探测（试新裁判是校准本职），429 者剔除其余保留
    _resetProbeCache(); probed.length = 0;
    global.fetch = async (_u, init) => {
      const model = JSON.parse(init.body).model; probed.push(model);
      if (model === 'glm-5.3-flash') return { ok: false, status: 429, text: async () => 'rl' };
      return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: 'pong' } }] }) };
    };
    const calChain = await selectJudge(null, { calibrate: true });
    assert.ok(probed.includes('glm-4-flash') && probed.includes('kimi-k2.6'), '校准模式允许全候选链探测');
    assert.ok(calChain.some((c) => c.model === 'glm-4-flash') && !calChain.some((c) => c.model === 'glm-5.3-flash'), '校准链按可用性组链（429 剔除）');
  } finally {
    global.fetch = realFetch; _resetProbeCache();
    setEnv('GLM_api', envGlm); setEnv('Kimi_api', envKimi); // P2-⑦：原值 undefined 必须 delete（赋值会强转 "undefined" 留环境）
  }
});

test('callJudgeOnce 限流退避（v7②）：429×2→200 同模型重试成功；预算耗尽→null；非限流错快重试 3 次', async () => {
  const realFetch = global.fetch;
  try {
    // 退避等待压 0 + 时钟冻结（预算永不耗尽路径）
    _setTestHooks({ sleep: async () => {}, now: () => 0 });
    let n = 0; const models = [];
    global.fetch = async (_u, init) => {
      const model = JSON.parse(init.body).model; models.push(model); n++;
      if (n <= 2) return { ok: false, status: 429, text: async () => 'rl' };
      return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '{"d1":1}' } }] }) };
    };
    const r = await callJudgeOnce([QUALIFIED_CAND], 'u');
    assert.ok(r?.content, '退避后重试同模型成功');
    assert.deepEqual(models, ['glm-5.3-flash', 'glm-5.3-flash', 'glm-5.3-flash'], '只调链内模型，429 不降级不换模型');
    // 预算耗尽：时钟每次退避后推进 20_000_000ms > 默认 10min 预算 → null（1 次调用后即断）
    let t = 0;
    _setTestHooks({ sleep: async () => { t += 1; }, now: () => t * 20_000_000 });
    let calls = 0;
    global.fetch = async () => { calls++; return { ok: false, status: 429, text: async () => 'rl' }; };
    assert.equal(await callJudgeOnce([QUALIFIED_CAND], 'u'), null, '限流等待耗尽 → null（不降级）');
    assert.equal(calls, 1);
    // 非限流错（HTTP 400）：快重试恰好 ATTEMPTS 次后链耗尽 → null
    _setTestHooks({ sleep: async () => {}, now: () => 0 });
    calls = 0;
    global.fetch = async () => { calls++; return { ok: false, status: 400, text: async () => 'bad' }; };
    assert.equal(await callJudgeOnce([QUALIFIED_CAND], 'u'), null);
    assert.equal(calls, 3, '非限流错=3 次快重试');
  } finally {
    global.fetch = realFetch; _setTestHooks(null);
  }
});

// ── v7③ 后置只读聚合（纯函数边界=零 LLM/零写；rows 形态与 selectGaps 兼容）─────
test('collectScoredRowsFromSidecar：有效行/缺判分账、槽缺失报缺、rows 可直接喂 selectGaps', () => {
  const report = { results: [
    { task: 'a', repeat: 1 }, { task: 'a', repeat: 2 }, { task: 'b', repeat: 1 }, { task: 'c' },
  ] };
  const chainKey = QUALIFIED_MODELS.join(' > ');
  const sidecar = { prompt_fingerprint: PROMPT_FINGERPRINT, by_judge: { [chainKey]: { items: {
    'a#1': { task: 'a', mapped: 4.2, total: 10, dims: { d1: 2 }, one_line_reason: 'r', judge_model: 'GLM/glm-5.3-flash' },
    'a#2': { task: 'a', mapped: null },           // 弃用行 → 缺判（不进 rows）
    'b#1': { task: 'b', mapped: 5, total: 12 },   // 最小形态（老 sidecar 行可能缺可选字段）
    'zz#9': { task: 'zz', mapped: 4 },            // 报告外残留 → 不进 rows（按报告行序聚合）
  } } } };
  const { rows, missing, chainKey: ck, slotMissing } = collectScoredRowsFromSidecar(sidecar, report);
  assert.equal(slotMissing, false);
  assert.equal(ck, chainKey);
  assert.deepEqual(rows.map((r) => `${r.task}#${r.repeat}`), ['a#1', 'b#1'], '按报告行序只取有效行');
  assert.deepEqual(missing.map((e) => `${e.task}#${e.repeat}`), ['a#2', 'c#1'], '缺/null 行入 missing 报数');
  // rows 形态与 selectGaps 兼容（后置 find-gap 不再走判分主链的直接证明）
  const main = new Map([['a#1', { score: 5 }], ['b#1', { score: 4 }]]);
  assert.deepEqual(selectGaps(rows, main).map((r) => `${r.task}#${r.repeat}`), []);
  // 槽缺失（从未全量判/链换血）→ 全量 missing + slotMissing（CLI 层 exit 1）
  const none = collectScoredRowsFromSidecar(null, report);
  assert.equal(none.slotMissing, true);
  assert.equal(none.missing.length, 4);
  assert.deepEqual(none.rows, []);
  // 其他槽（旧链键）不误读——资格槽缺席即缺失（指纹匹配前提下测链键闸）
  const stale = { prompt_fingerprint: PROMPT_FINGERPRINT, by_judge: { 'GLM/glm-5.3-flash > GLM/glm-4.7-flash': { items: { 'a#1': { task: 'a', mapped: 5 } } } } };
  const staled = collectScoredRowsFromSidecar(stale, report);
  assert.equal(staled.slotMissing, true, '旧链槽不得被只读模式误用');
  assert.match(staled.why, /资格链槽缺失/);
  // 指纹闸（审查 P1-1）：槽键逐字撞名但指纹过期（v6 限流夜窗单模型链的合理产物）→ 拒读不许入库
  const fpClash = { prompt_fingerprint: '8b7c7620', by_judge: { [chainKey]: { items: { 'a#1': { task: 'a', mapped: 5 } } } } };
  const fpStale = collectScoredRowsFromSidecar(fpClash, report);
  assert.equal(fpStale.slotMissing, true, '旧口径的分不许打现行标签');
  assert.match(fpStale.why, /指纹过期/);
});
