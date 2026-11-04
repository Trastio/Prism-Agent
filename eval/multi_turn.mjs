/**
 * 多轮评估批 change · 多轮机制纯函数（design.md §2 / 方案 v1.1 §10）
 *
 * 三机制都是 runner 增量，不动判分主干；与既有 task.turns=[{message,truth?}] 向后兼容：
 *   - resolveMessage：话术池轮换（variants 按 --repeat=k 取 [(k-1)%n]；string 直返=旧格式照跑）
 *   - selectBranch：条件分支追问（依据引用轮的逐轮 truth 判定选 if_hit/else——τ²-bench known_info 的规则版）
 *   - carryCheck：穿线验证（轮间一致性锚——from 之后各轮查 keys：同值复现=consistent /
 *     近值不同=drift（±2% 窗）/ 不复现=silent 不算错）
 * 纯函数无 IO，正反例契约：eval/multi_turn.test.mjs（改本文件必须先改测试）。
 */
import { normalizeText, extractNumberTokens } from './truth_check.mjs';

/** 机制②：消息归一。string 直返；{variants,variant_by:'repeat'} 按 repeatIdx 取；
 *  畸形（空池/缺 variants）fail-closed 返回空串——不猜话术，空消息会被网关 400 拒（显性失败优于静默错题）。 */
export function resolveMessage(msg, repeatIdx = 1) {
  if (typeof msg === 'string') return msg;
  if (msg && Array.isArray(msg.variants) && msg.variants.length) {
    const n = msg.variants.length;
    return String(msg.variants[(Math.max(1, repeatIdx) - 1) % n]);
  }
  return '';
}

/** 机制①：分支选择。branchTurn={branch_on:'tN', if_hit, else}；turnTruth=[{turn,ok}]
 *  （ok = 该轮 truth 无缺锚无违禁）。引用轮未判分（无 truth）按含糊处理走 else（fail-closed 压力路径）。
 *  返回 {turn: 选中的轮对象（含 message/truth），branch: 'if_hit'|'else'}。 */
export function selectBranch(branchTurn, turnTruth) {
  const m = /^t(\d+)$/.exec(String(branchTurn?.branch_on || ''));
  const refTurn = m ? parseInt(m[1], 10) : null;
  const ref = (turnTruth || []).find((x) => x.turn === refTurn);
  const ok = ref ? ref.ok === true : false; // 未判分=含糊=else
  return ok
    ? { turn: branchTurn.if_hit || {}, branch: 'if_hit' }
    : { turn: branchTurn.else || {}, branch: 'else' };
}

/** 机制③：穿线验证。carry={from:N, keys:['3,427',...]}（from=结论轮，之后各轮才查）。
 *  每轮状态：consistent（同值复现，千分位/全角归一后命中）/ drift（±2% 窗内出现不同值——
 *  4436→4437 式轮间漂移）/ silent（不复现不查不算错）。
 *  返回 {from, keys, results:[{turn,status,found?}], hasDrift}；无 carry → null（单轮题零影响）。 */
export function carryCheck(carry, replies) {
  if (!carry || !Array.isArray(carry.keys) || !carry.keys.length || !Array.isArray(replies)) return null;
  const results = [];
  let hasDrift = false;
  for (const key of carry.keys) {
    for (let i = carry.from; i < replies.length; i++) {
      const tokens = extractNumberTokens(normalizeText(replies[i]));
      // key 自身先归一为数值（"3,427" → 3427；非数字 key 不参与数值穿线——本机制只穿数字锚）
      const nums = extractNumberTokens(normalizeText(String(key)));
      if (!nums.length) continue;
      const keyVal = nums[0].value;
      let exact = false, near = null;
      for (const t of tokens) {
        if (t.percent) continue;
        const diff = Math.abs(t.value - keyVal);
        if (diff < 1e-9) { exact = true; break; }
        // 近值窗：±2% 且非零差（万换算后量级统一在 truth_check 的 canon 之外，这里直接比裸值；
        // 多轮题锚均为同单位裸值，万/台混写场景由题设计规避——记入 design 已知边界）
        if (diff > 1e-9 && diff <= Math.max(2, Math.abs(keyVal) * 0.02)) near = { value: t.value, diff };
      }
      if (exact) results.push({ turn: i + 1, key: keyVal, status: 'consistent' });
      else if (near) { results.push({ turn: i + 1, key: keyVal, status: 'drift', found: near.value }); hasDrift = true; }
      else results.push({ turn: i + 1, key: keyVal, status: 'silent' });
    }
  }
  return { from: carry.from, keys: carry.keys, results, hasDrift };
}

/** P1-2 快照漂移闸（design §8 承诺，Step8 补实装；补审加宽）：**所有绑定快照的题**（snapshot_id
 *  非 any——多轮+单轮一律）锚点都随快照冻结（如 m03-t3 依赖"最新=8月末"，sales-11"九月空"同族），
 *  快照轮换后锚点会静默失效——批跑前必须比"题库 snapshot_id"vs"实际挂载快照"。
 *  activeStamp=eval/snapshots/ACTIVE_SNAPSHOT.txt 内容（prism.py eval start 写入，stop 清除）。
 *  无绑定题→ok 跳过；有题无戳→fail-closed（旧 eval 会话未写戳，重启 eval 或显式放行）；
 *  有戳但题库快照≠挂载→fail-closed 列 mismatch。放行决策在 runner（--allow-snapshot-drift，审计字段进报告）。 */
export function checkSnapshotDrift(tasks, activeStamp) {
  const bound = (tasks || []).filter(t => t.snapshot_id && t.snapshot_id !== 'any');
  if (!bound.length) return { ok: true, mismatches: [], note: '无快照绑定题，跳过' };
  if (!activeStamp) {
    return { ok: false, mismatches: [], note: 'ACTIVE_SNAPSHOT.txt 缺失（由 prism.py eval start 写入）——fail-closed，重启 eval 或 --allow-snapshot-drift 显式放行' };
  }
  const mismatches = [...new Set(bound.map(t => t.snapshot_id).filter(s => s !== activeStamp))];
  return mismatches.length
    ? { ok: false, mismatches, note: `题库快照 ${mismatches.join(',')} ≠ 挂载 ${activeStamp}（锚点绑定声明失效风险，如 m03-t3 九月空 / sales-11 九月空同族）` }
    : { ok: true, mismatches: [], note: `快照一致: ${activeStamp}` };
}
