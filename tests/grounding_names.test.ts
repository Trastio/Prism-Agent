/**
 * verifyNames R1-deep 分层单测（尾巴包 change，2026-10-16）
 * 拍板方案落地：车系名/版型名（含字母数字、版/型转置）保 hard 拒；
 * ≤3 字纯 CJK 的 findClosest 命中（d<3 零区分度）降 soft——散文普通词告警不拒，
 * 消除 R1-deep 自纠 1-3 次的耗 token。
 * token 化事实（extractNameTokens）：版型后缀正则（含字母数字+版/型）与纯中文连续段；
 * 数字/标点是天然边界——真实 R1-deep 误报即"销量 4436 辆"式切出的 2 字段。
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { verifyNames } from '../src/verify/grounding.ts';

describe('verifyNames · R1-deep 分层', () => {
  it('回归锁：含字母数字的错版名仍 hard 拒（转写错误检测不伤）', () => {
    // '610KM星舰版' 对 truth '610km星舰版'：版型后缀 token，findClosest 命中，含字母 → hard
    const r = verifyNames('610KM星舰版卖得好', new Set(['610km星舰版']));
    assert.equal(r.pass, false, JSON.stringify(r));
    assert.ok(r.mismatches.some((m) => m.includes('610KM星舰版')), '应 hard 拒错转写版名');
  });

  it('回归锁：版/型后缀转置错误仍 hard 拒', () => {
    const r = verifyNames('530Km探索型优惠中', new Set(['530Km探索版']));
    assert.equal(r.pass, false, JSON.stringify(r));
    assert.ok(r.mismatches.some((m) => m.includes('转写错误') || m.includes('530Km探索型')));
  });

  it('新增：≤3 字纯 CJK 的近真值命中降 soft（不拒、进 softs 告警）', () => {
    // '魅蓝'（数字边界切出 2 字段）对 truth '海豚'：d=2<3 恒命中——旧版误报拒，现在 soft；
    // truth 含文本可命中词（海豚）→ 全局兜底不触发（真实 claim 场景总有车系名命中）
    const r = verifyNames('魅蓝 100 分好评，海豚也行', new Set(['海豚', '星际魅族']));
    assert.equal(r.pass, true, JSON.stringify(r));
    assert.equal(r.mismatches.length, 0, 'soft 不进 mismatches');
    assert.ok(r.softs.some((s) => s.includes('魅蓝')), 'softs 应留告警记录');
  });

  it('回归锁：前缀简称放行（风云 → 风云T7），不产生 mismatch', () => {
    const r = verifyNames('风云 4436 辆', new Set(['风云T7']));
    assert.equal(r.pass, true, JSON.stringify(r));
    assert.equal(r.mismatches.length, 0);
  });

  it('回归锁：truth 精确命中直接通过', () => {
    const r = verifyNames('海豚 4436 辆', new Set(['海豚']));
    assert.equal(r.pass, true);
  });
});
