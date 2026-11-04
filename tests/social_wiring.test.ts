/**
 * 社媒深挖能力包 M4 · 验证层接线单测
 * 运行：node --test --import tsx tests/social_wiring.test.ts
 *
 * 零新验证器原则的回归锚：social_* 归 web 类后，三处既有机制自动派生——
 * ① decideTier 纯社媒轮=web / 社媒+库=mixed
 * ② collectWebUrlsThisTurn 收集 social_* 结果里的 URL 进真值集
 * ③ 数值台账只采 business 类（social_* 数字不进库真值，self-check Gap3）
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  decideTier, collectWebUrlsThisTurn, TOOL_CATEGORIES,
} from '../.pi/extensions/prism-guardrails/index.ts';

describe('tier 路由（既有 decideTier，social_* 派生验证）', () => {
  it('纯社媒轮 = web', () => {
    assert.equal(decideTier(['social_search', 'social_post_comments']), 'web');
  });
  it('社媒 + 库 = mixed', () => {
    assert.equal(decideTier(['social_search', 'query_reviews']), 'mixed');
    assert.equal(decideTier(['query_sales', 'submit_conclusion', 'social_user_profile']), 'mixed');
  });
  it('纯库轮不受影响（回归锚）', () => {
    assert.equal(decideTier(['query_reviews']), 'library');
    assert.equal(decideTier([]), 'none');
  });
});

describe('URL 真值集（既有 collectWebUrlsThisTurn 派生验证）', () => {
  it('social_search 的归一化输出 URL 进真值集', () => {
    const toolResultText = JSON.stringify({
      items: [
        { platform: 'douyin', url: 'https://www.douyin.com/video/7674919380501140470', text: '提车一个月' },
        { platform: 'xiaohongshu', url: 'https://www.xiaohongshu.com/explore/6712abcdef', text: '提车作业' },
      ],
      _meta: { source: 'tikhub', 不可复算: true },
    });
    const branch: any[] = [
      { type: 'message', message: { role: 'user', content: '搜风云T7' } },
      { type: 'message', message: { role: 'toolResult', toolName: 'social_search', content: [{ type: 'text', text: toolResultText }] } },
    ];
    const urls = collectWebUrlsThisTurn(branch);
    assert.ok(urls.has('https://www.douyin.com/video/7674919380501140470'), `应含 douyin URL，实得 ${[...urls].join(' ')}`);
    assert.ok(urls.has('https://www.xiaohongshu.com/explore/6712abcdef'));
  });
  it('user 消息之前的工具结果不计入（本轮边界回归锚）', () => {
    const branch: any[] = [
      { type: 'message', message: { role: 'toolResult', toolName: 'social_search', content: [{ type: 'text', text: 'https://old.example.com/a' }] } },
      { type: 'message', message: { role: 'user', content: '新问题' } },
    ];
    assert.equal(collectWebUrlsThisTurn(branch).size, 0);
  });
});

describe('数值台账隔离（Gap3）', () => {
  it('social_* 不在 business 类 → 台账不采集', () => {
    for (const t of ['social_search', 'social_post_comments', 'social_user_profile', 'social_user_posts']) {
      assert.ok(!TOOL_CATEGORIES.business.has(t));
    }
  });
});
