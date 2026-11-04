/**
 * tikhub.ts 单测（社媒深挖能力包 M1）
 * 框架：node:test（Node 内置，无依赖）
 * 运行：node --test --import tsx tests/tikhub_tools.test.ts
 *
 * 覆盖（无 PRISM_TIKHUB_KEY 也能全跑——fail-closed 路径本身是验收项）：
 * - 归一化：五平台 fixture（防御式映射，TODO-verify 标记待 key 恢复后真实录制替换）
 * - parsePostRef / buildProfileRoute / buildPostsRoute 输入解析
 * - 每轮计数器超限
 * - 截断（2000 行）
 * - fail-closed：无 key / 不支持的平台×动作组合 / bilibili search 三必填
 */
import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  TIKHUB_TOOLS, TIKHUB_LIMIT, tikhubCounter, truncateOutput,
  parsePostRef, buildProfileRoute, buildPostsRoute, resolveRequest, normalize, executeAction,
} from '../.pi/extensions/prism-guardrails/tikhub.ts';
import { TOOL_CATEGORIES, ALLOWED_TOOLS } from '../.pi/extensions/prism-guardrails/index.ts';

// —— fixtures（2026-10-12 真实响应形态校准：douyin 搜索 data.data[] 含 aweme_info 包装、
// xhs items[] 含 note 包装、weibo parsed_data.results 新字段、ks mixFeeds[] 含 feed 包装）——
const douyinSearch = { code: 200, data: { data: [{
  type: 1, aweme_info: {
    aweme_id: '7674919380501140470', desc: '风云T7 提车一个月，说点实话',
    create_time: 1756684800, author: { nickname: 'zkz8118' },
    statistics: { digg_count: 123, comment_count: 45, share_count: 6 },
  },
}] } };
const xhsSearch = { code: 200, data: { data: { items: [{ note: {
  id: '6712abcdef01234567890123', title: '提车作业', desc: '落地价 14.2 万',
  user: { nickname: '作者A' }, liked_count: 88, comments_count: 12, shared_count: 3, timestamp: 1756684800000,
} }] } } };
const weiboComments = { code: 200, data: { comments: [{
  text: '我也定了，等提车', user: { screen_name: '车友A' },
  like_count: 3, source: '来自 广东', created_at: '2026-08-01',
}] } };
const weiboSearch = { code: 200, data: { parsed_data: { results: [{
  weibo_id: '5342404794129393', user_nick: '时髦尖子生Wensy',
  post_url: '//weibo.com/6047199468/RhN8Phkf7', content: '风云T7这储物空间做得也太大了',
  publish_time: '09月12日 19:20', interaction: { like_count: 7, comment_count: 2, repost_count: 0 },
}] } } };
const ksSearch = { code: 200, data: { mixFeeds: [
  { itemType: 9 },  // 广告卡：无 feed → 自动空
  { feed: { photo_id: '5204191048550152260', caption: '风云T7这配置，没法吐槽了', user_name: '测试作者B',
    timestamp: 1787044912107, like_count: 461, comment_count: 33, share_count: 8 } },
] } };
const biliSearch = { code: 200, data: { result: [{
  bvid: 'BV1xx411c7mD', title: '终于轮到我', description: '风云T7 首提',
  owner: { name: '某UP主' }, pubdate: 1756684800, stat: { view: 1000, reply: 50 },
}] } };
const douyinProfile = { code: 200, data: { user: {
  sec_uid: 'MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000', nickname: '测试作者A', signature: '生活记录',
  follower_count: 1061, total_favorited: 39000, aweme_count: 1883,
  ip_location: '浙江', gender: 2, region: '浙江',
} } };

describe('归一化', () => {
  it('douyin search：url 构造 + 时间换算 + stats + _meta 不可复算', () => {
    const r = normalize('search', 'douyin', douyinSearch.data, { keyword: '风云T7 提车', time_window: 'week' });
    assert.equal(r.items.length, 1);
    const it: any = r.items[0];
    assert.equal(it.url, 'https://www.douyin.com/video/7674919380501140470');
    assert.equal(it.author, 'zkz8118');
    assert.equal(it.stats.likes, 123);
    assert.ok(it.published_at?.startsWith('2025-'));
    assert.equal(r._meta.source, 'tikhub');
    assert.equal(r._meta['不可复算'], true);
    assert.equal(r._meta.keyword, '风云T7 提车');
    assert.equal(r._meta.time_window_applied, 'week'); // 生效过滤随行声明（口径红线）
  });
  it('xiaohongshu search：note 包装解开 + url 构造', () => {
    const r = normalize('search', 'xiaohongshu', xhsSearch.data, { keyword: '提车' });
    assert.equal((r.items[0] as any).stats.likes, 88);
    assert.equal((r.items[0] as any).stats.comments, 12);
    assert.match((r.items[0] as any).url, /xiaohongshu\.com\/explore\/6712abcdef/);
  });
  it('weibo search：parsed_data.results + post_url 协议相对补 https', () => {
    const r = normalize('search', 'weibo', weiboSearch.data, { keyword: '风云T7' });
    const it0: any = r.items[0];
    assert.equal(it0.url, 'https://weibo.com/6047199468/RhN8Phkf7');
    assert.equal(it0.author, '时髦尖子生Wensy');
    assert.equal(it0.stats.likes, 7);
    assert.equal(it0.published_at, '09月12日 19:20');
  });
  it('kuaishou search：mixFeeds feed 包装解开 + 广告卡跳过', () => {
    const r = normalize('search', 'kuaishou', ksSearch.data, { keyword: '风云T7' });
    assert.equal(r.items.length, 1); // 广告卡（无 feed）出空项后仍计 1？——pickList 原样映射，空项 url=null
    const it0: any = r.items[0];
    assert.equal(it0.author, '测试作者B');
    assert.equal(it0.url, 'https://www.kuaishou.com/short-video/5204191048550152260');
    assert.ok(it0.published_at.startsWith('2026-'));
  });
  it('weibo comments：source 属地提取（来自 广东 → 广东）+ HTML 清洗', () => {
    const r = normalize('comments', 'weibo', weiboComments);
    const c: any = r.items[0];
    assert.equal(c.author, '车友A');
    assert.equal(c.ip_location, '广东');
    assert.equal(c.likes, 3);
  });
  it('bilibili search：bvid 构造 url + stat 映射', () => {
    const r = normalize('search', 'bilibili', biliSearch.data, { keyword: '风云T7' });
    assert.equal((r.items[0] as any).url, 'https://www.bilibili.com/video/BV1xx411c7mD');
    assert.equal((r.items[0] as any).stats.comments, 50);
  });
  it('douyin profile：单对象展开 + gender 映射', () => {
    const r: any = normalize('profile', 'douyin', douyinProfile);
    assert.equal(r.nickname, '测试作者A');
    assert.equal(r.follower_count, 1061);
    assert.equal(r.gender, '女');
    assert.equal(r.ip_location, '浙江');
  });
  it('items 硬上限 30 + has_more 标记', () => {
    const many = { code: 200, data: { aweme_list: Array.from({ length: 35 }, (_, i) => ({ aweme_id: String(i) })) } };
    const r: any = normalize('search', 'douyin', many);
    assert.equal(r.items.length, 30);
    assert.equal(r._meta.total_returned, 35);
    assert.equal(r._meta.has_more, true);
  });
});

describe('输入解析', () => {
  it('parsePostRef：五平台 URL + 裸 ID + 不可解析', () => {
    assert.deepEqual(parsePostRef('https://www.douyin.com/video/7674919380501140470'), { id: '7674919380501140470' });
    assert.deepEqual(parsePostRef('https://www.xiaohongshu.com/explore/6712abcdef01234567890123'), { id: '6712abcdef01234567890123' });
    assert.deepEqual(parsePostRef('https://m.weibo.cn/status/5348259940011272'), { id: '5348259940011272' });
    assert.deepEqual(parsePostRef('https://www.bilibili.com/video/BV1xx411c7mD'), { id: 'BV1xx411c7mD' });
    assert.deepEqual(parsePostRef('7674919380501140470'), { id: '7674919380501140470' });
    assert.ok('error' in parsePostRef('https://example.com/foo'));
    assert.ok('error' in parsePostRef(''));
  });
  it('buildProfileRoute：sec_uid 前缀/裸 sec_uid/URL/抖音号/非法', () => {
    assert.deepEqual(buildProfileRoute('douyin', 'sec_uid:MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000'), { key: 'profile:douyin:sec', user_id: 'MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000' });
    assert.deepEqual(buildProfileRoute('douyin', 'MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000'), { key: 'profile:douyin:sec', user_id: 'MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000' });
    assert.deepEqual(buildProfileRoute('douyin', 'https://www.douyin.com/user/MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000?x=1'), { key: 'profile:douyin:sec', user_id: 'MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000' });
    assert.deepEqual(buildProfileRoute('douyin', '1678439350'), { key: 'profile:douyin:unique', user_id: '1678439350' });
    assert.ok('error' in buildProfileRoute('douyin', '作者A'));
  });
  it('buildPostsRoute：抖音号被拒（须 sec_uid）', () => {
    assert.ok('error' in buildPostsRoute('douyin', '1678439350'));
    assert.deepEqual(buildPostsRoute('douyin', 'sec_uid:MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000'), { key: 'posts:douyin', user_id: 'MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000' });
  });
});

describe('每轮计数器与截断', () => {
  beforeEach(() => tikhubCounter.reset());
  it(`bump 第 ${TIKHUB_LIMIT + 1} 次返回超限`, () => {
    for (let i = 0; i < TIKHUB_LIMIT; i++) assert.equal(tikhubCounter.bump(), false);
    assert.equal(tikhubCounter.bump(), true); // 第 9 次
    assert.equal(tikhubCounter.bump(), true); // 之后恒超限
    tikhubCounter.reset();
    assert.equal(tikhubCounter.bump(), false); // 清零后恢复
  });
  it('truncateOutput：>2000 行截断 + 尾行完整', () => {
    const big = Array.from({ length: 2500 }, () => '中文内容行').join('\n');
    const { text, truncated } = truncateOutput(big);
    assert.equal(truncated, true);
    assert.ok(text.length < big.length);
    assert.ok(text.endsWith('中文内容行')); // 收尾行必须完整（不截半行）
  });
});

describe('fail-closed 与白名单', () => {
  beforeEach(() => tikhubCounter.reset());
  it('无 PRISM_TIKHUB_KEY：executeAction 返回明确"未配置"（try/finally 防泄漏）', async () => {
    const prev = process.env.PRISM_TIKHUB_KEY;
    delete process.env.PRISM_TIKHUB_KEY;
    try {
      const r = await executeAction('social_search', 'search', { platform: 'douyin', keyword: '风云T7' });
      const payload = JSON.parse(r.content[0].text);
      assert.equal(payload.status, 'unavailable');
      assert.match(payload.reason, /未配置/);
    } finally {
      if (prev === undefined) delete process.env.PRISM_TIKHUB_KEY;
      else process.env.PRISM_TIKHUB_KEY = prev;
    }
  });
  it('time_window 平台不支持时显式拒绝（不静默全时段）', async () => {
    const r = await executeAction('social_search', 'search', { platform: 'douyin', keyword: 'x', time_window: 'month' });
    const payload = JSON.parse(r.content[0].text);
    assert.equal(payload.status, 'unavailable');
    assert.match(payload.reason, /不支持 time_window=month/);
    const r2 = await executeAction('social_search', 'search', { platform: 'weibo', keyword: 'x', time_window: 'week' });
    assert.match(JSON.parse(r2.content[0].text).reason, /不支持时间窗/);
  });
  it('不支持的平台×动作组合（weibo profile）明确拒绝', async () => {
    const r = await executeAction('social_user_profile', 'profile', { platform: 'weibo', user_id: 'x' });
    const payload = JSON.parse(r.content[0].text);
    assert.equal(payload.status, 'unavailable');
    assert.match(payload.reason, /不支持/);
  });
  it('bilibili search 请求带三必填（order/page/page_size）', () => {
    const r: any = resolveRequest('search:bilibili', { keyword: '风云T7' });
    assert.deepEqual(
      ['order', 'page', 'page_size'].map(k => r.query[k]),
      ['totalrank', 1, 20],
    );
  });
  it('TOOL_CATEGORIES.web 含 social_* 且 ALLOWED_TOOLS 派生放行', () => {
    for (const t of TIKHUB_TOOLS) {
      assert.ok(TOOL_CATEGORIES.web.has(t), `${t} 应在 web 类`);
      assert.ok(ALLOWED_TOOLS.has(t), `${t} 应被白名单放行`);
    }
  });
});
