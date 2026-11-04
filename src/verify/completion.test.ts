/**
 * T-9.2 单测骨架 · completion 验证器
 * 框架：node:test（Node 内置，无依赖）
 * 运行：node --test --import tsx src/verify/completion.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { verifyCompletion, type Claim } from './completion.ts';

describe('verifyCompletion', () => {
  it('缺 supported_by → fail', () => {
    const claim: Claim = {
      conclusion_text: '银河E5舒适性好',
      supported_by: [],
      as_of: '2026-10-05',
      scope: '口碑内',
    };
    const r = verifyCompletion('test-session-1', claim);
    assert.equal(r.pass, false);
    assert.ok(r.failures.some(f => /supported_by/.test(f)));
  });

  it('口碑结论越界市场侧 → fail', () => {
    const claim: Claim = {
      conclusion_text: '舒适性短板被销量同比下滑印证',
      supported_by: ['review_tags:7650/舒适/con'],
      as_of: '2026-10-05',
      scope: '口碑内',
    };
    const r = verifyCompletion('test-session-2', claim);
    assert.equal(r.pass, false);
    assert.ok(r.failures.some(f => /越界/.test(f)));
  });

  it('max 1 次 continuation（attempt 2 后 can_continue=false）', () => {
    const claim: Claim = {
      conclusion_text: '结论',
      supported_by: [],
      as_of: '2026-10-05',
      scope: '口碑内',
    };
    const r1 = verifyCompletion('test-session-3', claim);
    const r2 = verifyCompletion('test-session-3', claim);
    assert.equal(r1.can_continue, true);
    assert.equal(r2.can_continue, false);
  });

  it('明确声明“不归因/不对…做归因” → 不判越界（cross-02 假阳性回归）', () => {
    const claim: Claim = {
      conclusion_text: '销量同比 -42.9%，终端价下行；市场侧不归因：以上只描述销量与价格结果，'
        + '不对下滑原因做产品力归因；若要判断是产品力、竞品还是渠道问题，需另做交叉核验。',
      supported_by: ['sales_trim:银河E5/2026/8'],
      as_of: '2026-10-11',
      scope: '市场侧不归因',
    };
    const r = verifyCompletion('test-session-4', claim);
    assert.equal(r.failures.some(f => /越界/.test(f)), false, r.failures.join('; '));
  });

  it('明确声明"不把…归因到产品力" → 不判越界（Step8 P1-1：v1.2 cross-02 实录句，验证层曾漏此形态）', () => {
    const claim: Claim = {
      conclusion_text: '银河E5 2026年1-8月零售同比 -42.9%，终端价下行。'
        + '边界声明：以上为市场侧结果，不把销量下滑归因到产品力（配置/口碑是另一条线，需要可另做交叉）。',
      supported_by: ['sales_trim:银河E5/2026/8'],
      as_of: '2026-10-11',
      scope: '市场侧',
    };
    const r = verifyCompletion('test-session-5', claim);
    assert.equal(r.failures.some(f => /越界/.test(f)), false, r.failures.join('; '));
  });
});
