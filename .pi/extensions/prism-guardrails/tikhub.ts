/**
 * TikHub 社媒工具组核心模块（社媒深挖能力包 M1）
 *
 * 纯逻辑独立于 index.ts：端点映射 / 归一化 / 信封 / 重试 / 截断 / 每轮计数器，
 * 供 extension 注册 4 个 social_* 工具（social_search / social_post_comments /
 * social_user_profile / social_user_posts）与单测直接引用。
 *
 * 红线落点：
 * - 自截断（pi 规范 50KB/2000 行，extensions.md:2170-2197）——本地实现防包解析依赖
 * - fail-closed：key 未配置/网络失败/信封失败 → 明确错误，绝不返回编造的空数据
 * - 输出带 _meta{source:'tikhub', as_of, 不可复算}——web tier 降级验证的口径声明
 * - 每条 item 带 url（进 URL 真值集的唯一入口）
 *
 * 响应结构按 openapi + 舆情侧采集器防御式映射（TODO-verify：key 恢复后实测校准，M5 T5.1）
 */

// ---------------------------------------------------------------------------
// 常量与计数器
// ---------------------------------------------------------------------------

export const TIKHUB_TOOLS = new Set([
  'social_search', 'social_post_comments', 'social_user_profile', 'social_user_posts',
]);

export const TIKHUB_BASE = (process.env.TIKHUB_BASE_URL || 'https://api.tikhub.dev').replace(/\/$/, '');
export const TIKHUB_LIMIT = 20;
export const TIKHUB_LIMIT_MSG =
  '本轮 TikHub 调用已达上限（20 次，成本护栏）。请基于本轮已获取的数据继续分析；' +
  '数据不足处如实声明数据缺口并走假设清单范式（gap_assumption_pattern），不要硬凑。';

// 每轮调用计数（before_agent_start 清零；回灌轮算新轮）
let callCount = 0;
export const tikhubCounter = {
  reset() { callCount = 0; },
  /** +1 并返回是否超限（超限即 block） */
  bump(): boolean { callCount += 1; return callCount > TIKHUB_LIMIT; },
  get count() { return callCount; },
};

// 截断（pi 规范：50KB / 2000 行，取头）
const MAX_BYTES = 50 * 1024;
const MAX_LINES = 2000;
export function truncateOutput(s: string): { text: string; truncated: boolean } {
  let lines = s.split('\n');
  let truncated = false;
  if (lines.length > MAX_LINES) { lines = lines.slice(0, MAX_LINES); truncated = true; }
  let text = lines.join('\n');
  if (Buffer.byteLength(text, 'utf8') > MAX_BYTES) {
    // 按字节截断；残缺尾字节由 toString 替换为 U+FFFD（可接受）
    text = Buffer.from(text, 'utf8').subarray(0, MAX_BYTES).toString('utf8');
    truncated = true;
  }
  return { text, truncated };
}

// ---------------------------------------------------------------------------
// 端点映射（openapi 2026-10-12 核对；bilibili search 三必填 order/page/page_size）
// ---------------------------------------------------------------------------

export type SocialPlatform =
  | 'douyin' | 'xiaohongshu' | 'weibo' | 'kuaishou' | 'bilibili';

export type TikhubAction = 'search' | 'comments' | 'profile' | 'posts';

interface EndpointSpec {
  method: 'GET' | 'POST';
  path: string;
  build: (p: Record<string, any>) => { query?: Record<string, any>; body?: Record<string, any> };
}

export const TIME_WINDOW_MAP = {
  // xhs time_filter 中文枚举（契约）/ ks publish_time 英文枚举（契约）/ douyin publish_time 数字
  xiaohongshu: { day: '一天内', week: '一周内', halfyear: '半年内' } as Record<string, string>,
  kuaishou: { day: 'one_day', week: 'one_week', month: 'one_month' } as Record<string, string>,
  douyin: { day: 1, week: 7, halfyear: 182 } as Record<string, number>,
};

export const ENDPOINT_MAP: Record<string, EndpointSpec> = {
  // —— search ——
  // douyin：POST body 须全字符串（数字会 422；board 同款实测 2026-10-12）
  'search:douyin': {
    method: 'POST', path: '/api/v1/douyin/search/fetch_video_search_v1',
    build: p => ({ body: { keyword: String(p.keyword), cursor: String(p.cursor ?? 0), sort_type: '0', publish_time: String(TIME_WINDOW_MAP.douyin[p.time_window] ?? 0), search_id: '' } }),
  },
  'search:xiaohongshu': {
    method: 'GET', path: '/api/v1/xiaohongshu/app_v2/search_notes',
    build: p => ({ query: { keyword: p.keyword, page: p.page || 1, sort_type: 'general', ...(p.time_window && TIME_WINDOW_MAP.xiaohongshu[p.time_window] ? { time_filter: TIME_WINDOW_MAP.xiaohongshu[p.time_window] } : {}) } }),
  },
  'search:weibo': {
    method: 'GET', path: '/api/v1/weibo/web_v2/fetch_advanced_search',
    build: p => ({ query: { q: p.keyword, page: p.page || 1 } }), // timescope 格式未验证，默认不限
  },
  'search:kuaishou': {
    method: 'GET', path: '/api/v1/kuaishou/app/search_comprehensive',
    build: p => ({ query: { keyword: p.keyword, sort_type: 'all', ...(p.time_window && TIME_WINDOW_MAP.kuaishou[p.time_window] ? { publish_time: TIME_WINDOW_MAP.kuaishou[p.time_window] } : {}) } }),
  },
  'search:bilibili': {
    method: 'GET', path: '/api/v1/bilibili/web/fetch_general_search',
    build: p => ({ query: { keyword: p.keyword, order: 'totalrank', page: p.page || 1, page_size: 20 } }), // 三必填
  },
  // —— comments ——
  'comments:douyin': {
    method: 'GET', path: '/api/v1/douyin/app/v3/fetch_video_comments',
    build: p => ({ query: { aweme_id: p.post_id, cursor: p.cursor || 0, count: Math.min(p.max || 20, 50) } }),
  },
  'comments:xiaohongshu': {
    method: 'GET', path: '/api/v1/xiaohongshu/app_v2/get_note_comments',
    // note_id 或 share_text 二选一（端点原生契约）；短链形态直接吃 share_text
    build: p => ({ query: p.share_text ? { share_text: p.share_text } : { note_id: p.post_id, cursor: p.cursor || '' } }),
  },
  'comments:weibo': {
    method: 'GET', path: '/api/v1/weibo/web_v2/fetch_post_comments',
    build: p => ({ query: { id: p.post_id, count: Math.min(p.max || 20, 50) } }),
  },
  'comments:kuaishou': {
    method: 'GET', path: '/api/v1/kuaishou/app/fetch_video_comment',
    build: p => ({ query: { photo_id: p.post_id, pcursor: p.cursor || '' } }),
  },
  'comments:bilibili': {
    method: 'GET', path: '/api/v1/bilibili/web/fetch_video_comments',
    build: p => ({ query: { bv_id: p.post_id, pn: p.page || 1 } }),
  },
  // —— profile（douyin 双入口由 buildProfileRoute 决定）——
  'profile:douyin:sec': {
    method: 'GET', path: '/api/v1/douyin/web/handler_user_profile_v4',
    build: p => ({ query: { sec_user_id: p.user_id } }),
  },
  'profile:douyin:unique': {
    method: 'GET', path: '/api/v1/douyin/web/handler_user_profile_v2',
    build: p => ({ query: { unique_id: p.user_id } }),
  },
  'profile:xiaohongshu': {
    method: 'GET', path: '/api/v1/xiaohongshu/app_v2/get_user_info',
    build: p => (p.share_text ? { query: { share_text: p.share_text } } : { query: { user_id: p.user_id } }),
  },
  // —— posts（作品列表）——
  // douyin：web 版 fetch_user_post_videos 实测恒 400（TikHub 侧坏，不扣费）→ 用 app/v3 版（2026-10-12 实测 200）
  'posts:douyin': {
    method: 'GET', path: '/api/v1/douyin/app/v3/fetch_user_post_videos',
    build: p => ({ query: { sec_user_id: p.user_id, max_cursor: p.cursor || 0, count: Math.min(p.count || 20, 30) } }),
  },
  'posts:xiaohongshu': {
    method: 'GET', path: '/api/v1/xiaohongshu/app_v2/get_user_posted_notes',
    build: p => ({ query: { user_id: p.user_id, cursor: p.cursor || '' } }),
  },
};

// 平台 × action 支持矩阵（profile/posts 二期只开 douyin/xhs）
export const SUPPORTED: Record<SocialPlatform, Partial<Record<TikhubAction, boolean>>> = {
  douyin: { search: true, comments: true, profile: true, posts: true },
  xiaohongshu: { search: true, comments: true, profile: true, posts: true },
  weibo: { search: true, comments: true },
  kuaishou: { search: true, comments: true },
  bilibili: { search: true, comments: true },
};

// ---------------------------------------------------------------------------
// 输入解析（URL 或裸 ID → 平台内 ID）
// ---------------------------------------------------------------------------

export function parsePostRef(input: string): { id: string } | { error: string } {
  const s = String(input || '').trim();
  if (!s) return { error: 'post_url_or_id 为空' };
  // 常见 URL 形态抽 ID；裸 ID 原样透传（平台无关，由调用方交给对应端点）
  const patterns: Array<[RegExp, string]> = [
    [/douyin\.com\/video\/(\d+)/, 'id'],
    [/xiaohongshu\.com\/(?:explore|discovery\/item)\/([0-9a-f]{24})/, 'id'],
    [/xhslink\.com\/[A-Za-z0-9]+/, 'share'], // xhs 短链：整链作 share_text 交给端点
    [/weibo\.(?:cn|com)\/(?:status|detail)\/(\d+)/, 'id'],
    [/kuaishou\.com\/short-video\/([0-9A-Za-z]+)/, 'id'],
    [/bilibili\.com\/video\/(BV[0-9A-Za-z]+)/, 'id'],
  ];
  for (const [re, kind] of patterns) {
    const m = s.match(re);
    if (m) return kind === 'share' ? { id: s } : { id: m[1] };
  }
  if (/^https?:\/\//.test(s)) return { error: '无法从该 URL 解析出帖子 ID，请传平台标准链接或裸 ID' };
  return { id: s };
}

/** douyin profile 双入口路由：sec_uid: 前缀 → v4；纯数字抖音号 → v2；URL 内嵌 MS4wLjAB… → v4 */
export function buildProfileRoute(platform: SocialPlatform, userInput: string):
  { key: string; user_id: string; share_text?: string } | { error: string } {
  const s = String(userInput || '').trim();
  if (!s) return { error: 'user_id 为空' };
  if (platform === 'xiaohongshu') {
    if (/^https?:\/\//.test(s) || s.includes('xhslink')) return { key: 'profile:xiaohongshu', user_id: '', share_text: s };
    return { key: 'profile:xiaohongshu', user_id: s };
  }
  // douyin
  const secFromUrl = s.match(/douyin\.com\/user\/(MS4wLjAB[A-Za-z0-9_-]+)/);
  if (secFromUrl) return { key: 'profile:douyin:sec', user_id: secFromUrl[1] };
  if (s.startsWith('sec_uid:')) return { key: 'profile:douyin:sec', user_id: s.slice('sec_uid:'.length) };
  if (/^MS4wLjAB/.test(s)) return { key: 'profile:douyin:sec', user_id: s };
  if (/^\d{6,20}$/.test(s)) return { key: 'profile:douyin:unique', user_id: s };
  return { error: '抖音用户标识须为 sec_uid（MS4wLjAB…）、sec_uid: 前缀、用户主页链接或纯数字抖音号' };
}

/** posts 的用户标识：douyin 需 sec_uid（同上规则，去掉抖音号分支） */
export function buildPostsRoute(platform: SocialPlatform, userInput: string):
  { key: string; user_id: string } | { error: string } {
  const s = String(userInput || '').trim();
  if (!s) return { error: 'user_id 为空' };
  if (platform === 'xiaohongshu') return { key: 'posts:xiaohongshu', user_id: s };
  const secFromUrl = s.match(/douyin\.com\/user\/(MS4wLjAB[A-Za-z0-9_-]+)/);
  if (secFromUrl) return { key: 'posts:douyin', user_id: secFromUrl[1] };
  if (s.startsWith('sec_uid:')) return { key: 'posts:douyin', user_id: s.slice('sec_uid:'.length) };
  if (/^MS4wLjAB/.test(s)) return { key: 'posts:douyin', user_id: s };
  return { error: '抖音作品列表须用 sec_uid（MS4wLjAB…）或用户主页链接（可先用 social_user_profile 查抖音号对应的 sec_uid）' };
}

// ---------------------------------------------------------------------------
// 归一化（防御式字段映射：候选名链；全部未命中 → null，绝不 throw）
// ---------------------------------------------------------------------------

function pick(o: any, ...names: string[]): any {
  if (!o || typeof o !== 'object') return undefined;
  for (const n of names) {
    const v = n.split('.').reduce((acc: any, k) => (acc == null ? undefined : acc[k]), o);
    if (v !== undefined && v !== null && v !== '') return v;
  }
  return undefined;
}

function pickList(o: any, ...paths: string[]): any[] {
  for (const p of paths) {
    const v = p.split('.').reduce((acc: any, k) => (acc == null ? undefined : acc[k]), o);
    if (Array.isArray(v) && v.length > 0) return v;
  }
  return [];
}

function ts2iso(v: any): string | null {
  if (v === undefined || v === null || v === '') return null;
  const n = Number(v);
  if (Number.isFinite(n) && n > 1e9) {
    const ms = n > 1e12 ? n : n * 1000; // 秒/毫秒自适应
    const d = new Date(ms);
    return isNaN(d.getTime()) ? null : d.toISOString().replace('T', ' ').slice(0, 16) + 'Z';
  }
  return String(v).slice(0, 32); // 非数字时间原样保留（字符串日期）
}

function clip(v: any, n: number): string | null {
  if (v === undefined || v === null || v === '') return null;
  return String(v).replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '').slice(0, n);
}

const NUM = (v: any): number | null => (Number.isFinite(Number(v)) && v !== '' && v !== null ? Number(v) : null);

/** weibo 评论 source 属地语义："来自 广东" → "广东"（抄舆情侧 _WEIBO_IP_RE 惯例） */
function weiboIp(s: any): string | null {
  const m = String(s || '').match(/来自\s*(.+)$/);
  return m ? m[1].trim().slice(0, 20) : null;
}

const URL_BUILDERS: Record<string, (it: any) => string | null> = {
  douyin: it => { const id = pick(it, 'aweme_id', 'awemeId', 'id'); return id ? `https://www.douyin.com/video/${id}` : (pick(it, 'share_url') || null); },
  xiaohongshu: it => pick(it, 'share_url', 'shareUrl') || (pick(it, 'note_id', 'noteId', 'id') ? `https://www.xiaohongshu.com/explore/${pick(it, 'note_id', 'noteId', 'id')}` : null),
  // weibo：post_url 协议相对（//weibo.com/...）→ 补 https:；无则用 weibo_id 构造
  weibo: it => {
    const pu = pick(it, 'post_url');
    if (pu) return String(pu).startsWith('//') ? 'https:' + pu : String(pu);
    const id = pick(it, 'weibo_id', 'id', 'wid', 'mid');
    return id ? `https://m.weibo.cn/status/${id}` : null;
  },
  kuaishou: it => pick(it, 'share_url', 'shareUrl', 'photo_url') || (pick(it, 'photo_id', 'photoId') ? `https://www.kuaishou.com/short-video/${pick(it, 'photo_id', 'photoId')}` : null),
  bilibili: it => { const bv = pick(it, 'bvid', 'bvid_str'); return bv ? `https://www.bilibili.com/video/${bv}` : null; },
};

function normalizeSearchItem(platform: SocialPlatform, it: any) {
  // 包装层解开（2026-10-12 实测）：douyin 搜索项在 aweme_info、xhs 在 note、ks 在 feed；
  // weibo/bilibili 无包装。无对应键时原样（|| it 兜底）。
  const src = it?.aweme_info || it?.note || it?.feed || it;
  const url = URL_BUILDERS[platform]?.(src) || null;
  return {
    platform,
    url,
    title: clip(pick(src, 'title', 'display_title', 'desc', 'caption', 'text', 'name'), 120) || null,
    text: clip(pick(src, 'desc', 'description', 'content', 'text', 'caption'), 300),
    author: clip(pick(src, 'author.nickname', 'author.nick_name', 'user.screen_name', 'user.nickname', 'user_info.nickname', 'user.nick', 'user_nick', 'user_name', 'uname', 'owner.name'), 40) || null,
    published_at: ts2iso(pick(src, 'create_time', 'createTime', 'created_at', 'time', 'timestamp', 'pubdate', 'publish_time')),
    stats: {
      likes: NUM(pick(src, 'statistics.digg_count', 'liked_count', 'attitudes_count', 'like_count', 'diggCount', 'interaction.like_count', 'stat.like')),
      comments: NUM(pick(src, 'statistics.comment_count', 'comment_count', 'comments_count', 'commentCount', 'interaction.comment_count', 'stat.reply', 'reply')),
      shares: NUM(pick(src, 'statistics.share_count', 'share_count', 'shareCount', 'shared_count', 'interaction.repost_count', 'reposts_count', 'stat.share')),
    },
  };
}

function normalizeCommentItem(platform: SocialPlatform, it: any) {
  const raw = it || {};
  return {
    platform,
    author: clip(pick(raw, 'user.nickname', 'user.screen_name', 'user_info.nickname', 'user_name', 'uname', 'member.uname', 'author.nickname'), 40) || null,
    text: clip(pick(raw, 'text', 'content', 'comment_content', 'content.message'), 300),
    likes: NUM(pick(raw, 'digg_count', 'liked_count', 'like_count', 'like', 'likes')),
    ip_location: platform === 'weibo' ? weiboIp(pick(raw, 'source')) : clip(pick(raw, 'ip_label', 'ip_info.ipLabel', 'ip_location'), 20),
    published_at: ts2iso(pick(raw, 'create_time', 'createTime', 'create_date', 'time', 'comment_time')),
    url: URL_BUILDERS[platform]?.(raw) || null,
  };
}

function normalizeProfile(platform: SocialPlatform, data: any) {
  const u = pick(data, 'data.user', 'user', 'data') || {};
  return {
    platform,
    user_id: pick(u, 'sec_uid', 'secUid', 'uid', 'user_id', 'user.UserInformationVO.userId', 'id') || null,
    nickname: clip(pick(u, 'nickname', 'nick_name', 'name', 'user.UserInformationVO.nickname'), 40) || null,
    signature: clip(pick(u, 'signature', 'desc', 'user.UserInformationVO.desc'), 120),
    follower_count: NUM(pick(u, 'follower_count', 'followerCount', 'fans', 'fansCount', 'user.UserInformationVO.fansCount')),
    total_favorited: NUM(pick(u, 'total_favorited', 'totalFavorited', 'user.UserInformationVO.totalLikeCount')),
    posts_count: NUM(pick(u, 'aweme_count', 'awemeCount', 'notesCount', 'notes')),
    ip_location: clip(pick(u, 'ip_location', 'ipLocation', 'ip_location_format'), 20),
    gender: pick(u, 'gender') === 1 ? '男' : pick(u, 'gender') === 2 ? '女' : null,
    region: clip(pick(u, 'region', 'city', 'province', 'country_code'), 20),
  };
}

// 列表路径（2026-10-12 实测校准；normalize 收到的是已剥信封对象——单段 'data' 是 douyin 搜索原生形态）
const SEARCH_LIST_PATHS: Record<string, string[]> = {
  douyin: ['data', 'data.data', 'data.aweme_list', 'aweme_list'],  // 原生 data 直挂列表 / 缓存层 data.data
  xiaohongshu: ['data.items', 'data.data.items', 'data.notes'],    // items[] 含 note 包装
  weibo: ['parsed_data.results', 'data.posts', 'data.data.posts'], // parsed_data.results（新形态）
  kuaishou: ['mixFeeds', 'data.mixFeeds'],                          // mixFeeds[] 含 feed 包装（广告卡无 feed 自动空）
  bilibili: ['result', 'data.result', 'data.data.result'],
};
const COMMENT_LIST_PATHS: Record<string, string[]> = {
  douyin: ['data.comments', 'data.data.comments', 'comments'],
  xiaohongshu: ['data.comments', 'data.data.comments', 'data.data.list'],
  weibo: ['data.comments', 'data.data.comments', 'data'],
  kuaishou: ['data.comments', 'data.data.comments', 'data.visionCommentPanel.rootComments'],
  bilibili: ['data.replies', 'data.data.replies', 'replies'],
};
const POSTS_LIST_PATHS: Record<string, string[]> = {
  douyin: ['data.aweme_list', 'data.data', 'aweme_list'],  // app/v3 版两种形态都收
  xiaohongshu: ['data.notes', 'data.data.notes', 'notes'],
};

/** 统一出口：items 上限 30 + _meta 口径声明（keyword 进 _meta 供名称真值采集；生效时间窗随行声明） */
export function normalize(action: TikhubAction, platform: SocialPlatform, data: any, ctx: { keyword?: string; time_window?: string } = {}) {
  let listPath: string[], mapper: (it: any) => any;
  if (action === 'search') { listPath = SEARCH_LIST_PATHS[platform]; mapper = it => normalizeSearchItem(platform, it); }
  else if (action === 'comments') { listPath = COMMENT_LIST_PATHS[platform]; mapper = it => normalizeCommentItem(platform, it); }
  else if (action === 'posts') { listPath = POSTS_LIST_PATHS[platform]; mapper = it => normalizeSearchItem(platform, it); }
  else {
    // profile：单对象
    return { ...normalizeProfile(platform, data), _meta: buildMeta(action, platform, ctx) };
  }
  const raw = pickList(data, ...listPath);
  // 空项过滤：广告卡/占位卡（无 url 且无标题正文）不进结果（2026-10-12 实测 ks mixFeeds 混广告卡）
  const items = raw.slice(0, 30).map(mapper).filter((x: any) => x.url || x.title || x.text);
  return {
    items,
    _meta: {
      ...buildMeta(action, platform, ctx),
      total_returned: raw.length,
      truncated_to: items.length,
      has_more: raw.length > 30 ? true : undefined,
    },
  };
}

function buildMeta(action: TikhubAction, platform: SocialPlatform, ctx: { keyword?: string; time_window?: string }) {
  return {
    source: 'tikhub',
    action, platform,
    ...(ctx.keyword ? { keyword: ctx.keyword } : {}),
    ...(ctx.time_window ? { time_window_applied: ctx.time_window } : {}),
    as_of: new Date().toISOString(),
    '不可复算': true,
    note: '外部付费 API 即时快照，引用须标注：来源平台+URL+抓取时间（as_of）',
  };
}

// ---------------------------------------------------------------------------
// 信封 / 请求（key 未配置 fail-closed；401/402 语义化；5xx 重试 1 次）
// ---------------------------------------------------------------------------

export function makeError(tool: string, reason: string) {
  return { status: 'unavailable', tool, reason, fallback: 'none' };
}

/** 实际请求入口：method/path/query/body 已由调用方构建 */
export async function callEndpoint(
  method: 'GET' | 'POST', path: string, query: Record<string, any> | undefined,
  body: Record<string, any> | undefined, key: string | undefined, timeoutMs = 30000,
): Promise<{ ok: true; data: any } | { ok: false; reason: string }> {
  if (!key) return { ok: false, reason: 'TikHub 未配置（PRISM_TIKHUB_KEY 缺失，请联系管理员在 prism-api/.env 配置 TIKHUB_KEY_PRISM）' };
  const url = new URL(TIKHUB_BASE + path);
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined) url.searchParams.set(k, String(v));
  const headers = {
    Authorization: `Bearer ${key}`,
    // Cloudflare 防御：api.tikhub.dev 在 CF 后面，默认 UA（Python-urllib 等）会被 1010 拦
    'User-Agent': 'Prism-Agent/0.3 (+https://localhost:5173)',
    ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}),
  };

  const attempt = async (): Promise<Response> =>
    fetch(url, { method, headers, ...(method === 'POST' ? { body: JSON.stringify(body || {}) } : {}), signal: AbortSignal.timeout(timeoutMs) });

  let resp: Response;
  try {
    resp = await attempt();
  } catch (e1) {
    // 网络错误/超时重试 1 次
    try { resp = await attempt(); }
    catch (e2) { return { ok: false, reason: `TikHub 网络错误：${(e2 as Error).message}` }; }
  }

  const httpStatus = resp.status;
  let json: any = null;
  try { json = await resp.json(); } catch { /* 空体 */ }

  if (httpStatus === 401 || httpStatus === 403) return { ok: false, reason: 'TikHub key 失效或无权限（401/403），请管理员更新 prism-api/.env 的 TIKHUB_KEY_PRISM' };
  if (httpStatus === 402) return { ok: false, reason: 'TikHub 余额不足（402），请管理员充值' };
  if (httpStatus >= 500) {
    // 5xx 重试 1 次
    try {
      resp = await attempt();
      try { json = await resp.json(); } catch {}
      if (resp.status >= 500) return { ok: false, reason: `TikHub 服务错误（HTTP ${resp.status}）` };
    } catch { return { ok: false, reason: `TikHub 服务错误（HTTP ${httpStatus}）` }; }
  }
  if (!resp.ok) return { ok: false, reason: `TikHub HTTP ${resp.status}：${clip(json?.detail?.message || json?.message, 150) || '无错误信息'}` };
  // 信封：HTTP 200 且 code==200 才成功
  if (json && typeof json === 'object' && 'code' in json) {
    if (json.code !== 200) return { ok: false, reason: `TikHub 业务失败 code=${json.code}：${clip(json.message || json.message_zh, 150) || '无信息'}` };
    return { ok: true, data: json.data ?? json };
  }
  return { ok: true, data: json };
}

/** 把 spec 的 build 结果落成最终请求参数（供 index.ts 与单测共用） */
export function resolveRequest(routeKey: string, params: Record<string, any>):
  { method: 'GET' | 'POST'; path: string; query?: Record<string, any>; body?: Record<string, any> } | { error: string } {
  const spec = ENDPOINT_MAP[routeKey];
  if (!spec) return { error: `未知 TikHub 路由：${routeKey}` };
  const { query, body } = spec.build(params);
  return { method: spec.method, path: spec.path, query, body };
}

// ---------------------------------------------------------------------------
// 工具执行入口（index.ts 的 4 个 registerTool 全走这里）
// 返回 pi 工具结果形态 {content:[{type:'text',text}]}；一切失败 fail-closed 明示
// ---------------------------------------------------------------------------

export async function executeAction(tool: string, action: TikhubAction, params: any):
  Promise<{ content: [{ type: 'text'; text: string }] }> {
  const key = process.env.PRISM_TIKHUB_KEY;
  const platform = String(params?.platform || '') as SocialPlatform;
  const fail = (reason: string) => ({ content: [{ type: 'text' as const, text: JSON.stringify(makeError(tool, reason)) }] });
  const ok = (payload: any) => {
    // P2 修复：截断时给模型显式标记（静默截断=模型不知数据不全）
    const { text, truncated } = truncateOutput(JSON.stringify(payload));
    const finalText = truncated ? text + '\n【输出超 50KB/2000 行被截断——数据不全；如需更多请缩小范围（更精准关键词/减少条数/分平台轮询）】' : text;
    return { content: [{ type: 'text' as const, text: finalText }] };
  };

  if (!SUPPORTED[platform]?.[action]) return fail(`平台 ${platform} 不支持 ${action}（当前支持：搜索/评论=抖音/小红书/微博/快手/哔哩，用户画像/作品=抖音/小红书）`);

  let routeKey: string, reqParams: Record<string, any> = { ...params };
  if (action === 'search') {
    if (!params?.keyword) return fail('keyword 为空');
    // 口径红线（P1 修复）：time_window 平台不支持时显式拒绝，不静默降级为全时段
    if (params.time_window) {
      const supported = TIME_WINDOW_MAP[platform as keyof typeof TIME_WINDOW_MAP];
      if (!supported || !(params.time_window in supported)) {
        const s = supported ? Object.keys(supported).join('/') : '不支持时间窗过滤';
        return fail(`platform=${platform} 不支持 time_window=${params.time_window}（支持：${s}）。请去掉该参数（全时段）或换用支持的时间窗`);
      }
    }
    routeKey = `search:${platform}`;
    reqParams = { keyword: params.keyword, time_window: params.time_window, page: params.page };
  } else if (action === 'comments') {
    const ref = parsePostRef(params?.post_url_or_id);
    if ('error' in ref) return fail(ref.error);
    routeKey = `comments:${platform}`;
    // xhs 短链：端点原生吃 share_text，比解析 note_id 更稳
    if (platform === 'xiaohongshu' && /^https?:\/\//.test(ref.id)) reqParams = { share_text: ref.id };
    else reqParams = { post_id: ref.id, max: params.max, cursor: params.cursor };
  } else if (action === 'profile') {
    const r = buildProfileRoute(platform, params?.user_id);
    if ('error' in r) return fail(r.error);
    routeKey = r.key;
    reqParams = { user_id: r.user_id, share_text: (r as any).share_text };
  } else {
    const r = buildPostsRoute(platform, params?.user_id);
    if ('error' in r) return fail(r.error);
    routeKey = r.key;
    reqParams = { user_id: r.user_id, cursor: params.cursor, count: params.count };
  }

  const req = resolveRequest(routeKey, reqParams);
  if ('error' in req) return fail(req.error);

  const resp = await callEndpoint(req.method, req.path, req.query, req.body, key);
  if (!resp.ok) return fail(resp.reason);

  const normalized = normalize(action, platform, resp.data, { keyword: params?.keyword, time_window: params?.time_window });
  return ok(normalized);
}
