/**
 * 舆情轻卡（change 2 块 B）：原生 React 三概念主视图，替换 iframe 嵌入壳
 * - 三概念：①最近热度（30 天声量 sparkline+平台占比）②舆情健康分（分数/负面维度top3/车质网投诉行）
 *   ③正在发酵（事件 top3+本周新增负面帖）＋ 翻车帖/护车帖固定块 ＋ 搜索热度小卡（口径注记）
 * - 取数全走 /sentiment-board/ 反代（GET；浏览器自动带 prism_token cookie）
 * - seriesKey 联动：fleet-overview 名匹配 vehicleId；无 series=直嵌完整看板（打开即可看，零点击）；未命中=车池未收录态
 * - as_of：查询窗 end 标注（端点无 as_of 字段，D4 决策零后端）
 * - 图表自绘轻量 SVG（借 styles.css 既有 .chart- 与 .kpi- 令牌，零新依赖；注：勿在块注释里写星杠）
 * - 完整版入口：底部按钮新窗开 :8000 整页（深挖/管理者用；轻卡只是默认面）
 * 降级规则：车质网行 posts 端点失败→隐藏；搜索热度无 search_index 数据→整块隐藏（不造数据）
 */
import { useCallback, useEffect, useState } from 'react';
import { GapCard, Loading } from './_shared';
import EmbedBoard from './EmbedBoard';

const BASE = '/sentiment-board/api/dashboard';
/** 停采平台（R23/R31）——分布图档位标注"已停采"（D1：保留展示不隐藏） */
const STOPPED = new Set(['weibo', 'kuaishou', 'news']);
const PLAT_LABEL: Record<string, string> = {
  xiaohongshu: '小红书', douyin: '抖音', weibo: '微博', kuaishou: '快手',
  news: '新闻', chezhiwang: '车质网', chezhwang: '车质网',
};

type Phase = 'loading' | 'ready' | 'error' | 'empty' | 'nomatch';

interface FleetV { id: string; name: string; brand?: string }
interface Overview {
  health_score?: number; positive?: number; negative?: number; neutral?: number;
  week_total?: number; worst_dim?: string; peak_date?: string; sample_insufficient?: boolean;
}
interface TrendDay { date: string; positive?: number; negative?: number; neutral?: number }
interface DimRow { dim: string; score: number; count: number }
interface EventRow { event_tag: string; post_count: number; start_date?: string; end_date?: string }
interface Incr { new_negative_count?: number }
interface PlatRow { platform: string; count: number }
interface DiffPost {
  title?: string; url?: string; platform?: string; likes?: number;
  post_sentiment?: string; comment_sentiment?: string;
}
interface HeatDay { date: string; attention_index?: number | null }  // 走查修正：端点实为 attention_index（search_index 会让热度块静默隐藏）
interface Bundle {
  overview?: Overview; trend?: TrendDay[]; dims?: DimRow[]; events?: EventRow[];
  incr?: Incr; plat?: PlatRow[]; diff?: DiffPost[]; heat?: HeatDay[]; complaints?: number;
}

/** 本地时区 YYYY-MM-DD（避免 UTC 日界偏移） */
function ymd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

/** 轻量 sparkline：折线+渐隐面积（借 .chart-line/.chart-area 令牌） */
function Spark({ values, tone = 'line' }: { values: number[]; tone?: 'line' | 'xt' }) {
  const w = 120, h = 30, max = Math.max(1, ...values), n = values.length;
  if (n < 2) return <svg className="chart" viewBox={`0 0 ${w} ${h}`}><line className="chart-grid" x1="0" y1={h - 1} x2={w} y2={h - 1} /></svg>;
  const pts = values.map((v, i) => [(i / (n - 1)) * (w - 2) + 1, h - 2 - (v / max) * (h - 6)] as const);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `1,${h - 1} ${line} ${w - 1},${h - 1}`;
  const cls = tone === 'xt' ? 'chart-line-xt' : 'chart-line';
  const areaCls = tone === 'xt' ? 'chart-area-xt' : 'chart-area';
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <polygon className={areaCls} points={area} />
      <polyline className={cls} points={line} />
    </svg>
  );
}

export default function SentimentBoard({ seriesKey, reloadKey }: { seriesKey?: string; reloadKey?: number }) {
  const [phase, setPhase] = useState<Phase>('loading');
  const [vehicle, setVehicle] = useState<FleetV | null>(null);
  const [pool, setPool] = useState<string[]>([]);
  const [end, setEnd] = useState('');
  const [data, setData] = useState<Bundle>({});

  const load = useCallback(async (key?: string) => {
    setPhase('loading');
    try {
      const fleet = await jget<FleetV[]>('/fleet-overview');
      setPool(fleet.map(v => v.name));
      if (!key) { setPhase('empty'); return; }
      const k = key.replace(/\s+/g, '');
      const hit = fleet.find(v => v.name.replace(/\s+/g, '') === k)
        || fleet.find(v => v.name.replace(/\s+/g, '').includes(k) || k.includes(v.name.replace(/\s+/g, '')));
      if (!hit) { setVehicle(null); setPhase('nomatch'); return; }
      setVehicle(hit);

      const now = new Date();
      const e = ymd(now);
      const s = ymd(new Date(now.getTime() - 29 * 864e5));
      const ws = ymd(new Date(now.getTime() - 6 * 864e5));
      setEnd(e);

      const [ov, tr, dim, ev, inc, plat, diff, heat, cz] = await Promise.allSettled([
        jget<Overview>(`/overview/${hit.id}?start=${s}&end=${e}`),
        jget<TrendDay[]>(`/sentiment-trend/${hit.id}?start=${s}&end=${e}`),
        jget<DimRow[]>(`/dim-sentiment/${hit.id}`),
        jget<EventRow[]>(`/vehicles/${hit.id}/events`),
        jget<Incr>(`/increment-overview/${hit.id}?start=${ws}&end=${e}`),
        jget<PlatRow[]>(`/platform-distribution/${hit.id}?start=${s}&end=${e}`),
        jget<DiffPost[]>(`/comment-sentiment-diff/${hit.id}`),
        jget<{ data?: HeatDay[] }>(`/trend/${hit.id}?start=${s}&end=${e}`),
        jget<{ total?: number }>(`/posts/${hit.id}?platform=chezhiwang&start=${s}&end=${e}`),
      ]);
      const val = <T,>(r: PromiseSettledResult<T>) => (r.status === 'fulfilled' ? r.value : undefined);
      setData({
        overview: val(ov), trend: val(tr), dims: val(dim), events: val(ev), incr: val(inc),
        plat: val(plat), diff: val(diff),
        heat: val(heat)?.data,
        complaints: val(cz)?.total, // 车质网行：posts 端点失败→undefined→隐藏（不造数据）
      });
      setPhase('ready');
    } catch {
      setPhase('error');
    }
  }, []);

  useEffect(() => { load(seriesKey); }, [load, seriesKey, reloadKey]);

  const openFull = () => window.open('/sentiment-board/', '_blank', 'noopener');
  /** 用户拍板 B（2026-10-19）：翻车/护车帖点击直跳原帖；无 url 降级进完整版 */
  const openPost = (p: DiffPost) => (p.url ? window.open(p.url, '_blank', 'noopener,noreferrer') : openFull());

  if (phase === 'loading') return <div className="sc-wrap"><Loading /></div>;
  if (phase === 'error') return (
    <div className="sc-wrap">
      <GapCard title="舆情板未连接" miss="经 /sentiment-board/ 反代读取 fleet-overview 失败（:8000 不可达或未登录）。" ask="启动舆情板服务并确认反代 200；已登录主站后重试。" />
      <button className="xt-retry" onClick={() => load(seriesKey)}>重试</button>
    </div>
  );
  /* 空态 = 打开即可看：直接嵌完整舆情看板（:8000 自带车型切换器/时间预设），零点击、无前置门 */
  if (phase === 'empty') return (
    <EmbedBoard
      path="/sentiment-board/"
      title="舆情看板"
      miss="舆情板经 prism-api 的 /sentiment-board/ 反代不可达（:8000 未启动或未登录）。"
      ask="启动舆情板服务并确认反代 200；已登录主站后重试。"
      reloadKey={reloadKey}
    />
  );
  if (phase === 'nomatch') return (
    <div className="sc-wrap">
      <GapCard title={`舆情车池未收录「${seriesKey}」`} miss={`当前采集车池（${pool.length} 台）：${pool.join(' / ') || '—'}。`} ask="车池内的车系才有日更舆情；其他车系可在对话中查询库外信息（不可复算）。" />
      <button className="sc-full-btn" onClick={openFull}>查看完整舆情看板 →</button>
    </div>
  );

  const ov = data.overview || {};
  const trendDays = data.trend || [];
  const volume = trendDays.map(d => (d.positive || 0) + (d.negative || 0) + (d.neutral || 0));
  const negDims = [...(data.dims || [])].sort((a, b) => a.score - b.score).slice(0, 3);
  const events = [...(data.events || [])].filter(e => e.post_count >= 2).sort((a, b) => b.post_count - a.post_count).slice(0, 3);
  const platRows = [...(data.plat || [])].sort((a, b) => b.count - a.count);
  const platTotal = platRows.reduce((s, r) => s + r.count, 0) || 1;
  const diffAll = data.diff || [];
  const pos2neg = diffAll.filter(p => p.post_sentiment === 'positive' && p.comment_sentiment === 'negative').sort((a, b) => (b.likes || 0) - (a.likes || 0)).slice(0, 2);
  const neg2pos = diffAll.filter(p => p.post_sentiment === 'negative' && p.comment_sentiment === 'positive').sort((a, b) => (b.likes || 0) - (a.likes || 0)).slice(0, 2);
  const heatSeries = (data.heat || []).map(d => d.attention_index).filter((v): v is number => typeof v === 'number' && v > 0);

  return (
    <div className="sc-wrap">
      <div className="board-head">
        <div>
          <div className="eyebrow">舆情 · 全网讨论</div>
          <h2 className="board-title">{vehicle?.name}</h2>
          <p className="board-desc">小红书 + 抖音（含非车主声音）· 数据窗截至 {end}</p>
        </div>
        <button className="sc-full-btn" onClick={openFull}>查看完整舆情看板 →</button>
      </div>

      <div className="sc-grid">
        {/* ① 最近热度 */}
        <div className="card sc-card">
          <div className="card-head"><h3 className="card-title">最近热度</h3><span className="card-meta">30 天 {volume.reduce((s, v) => s + v, 0)} 帖</span></div>
          <Spark values={volume} />
          {platRows.length > 0 && (
            <div className="sc-plat">
              <div className="sc-plat-bar">
                {platRows.map(r => (
                  <span key={r.platform} className={`sc-plat-seg${STOPPED.has(r.platform) ? ' is-stopped' : ''}`}
                    style={{ width: `${(r.count / platTotal) * 100}%` }}
                    title={`${PLAT_LABEL[r.platform] || r.platform} ${r.count}${STOPPED.has(r.platform) ? '（已停采，历史存量）' : ''}`} />
                ))}
              </div>
              <div className="sc-plat-legend">
                {platRows.map(r => (
                  <span key={r.platform} className="sc-plat-item">
                    {PLAT_LABEL[r.platform] || r.platform} {Math.round((r.count / platTotal) * 100)}%
                    {STOPPED.has(r.platform) && <em>已停采</em>}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ② 舆情健康分 */}
        <div className="card sc-card">
          <div className="card-head"><h3 className="card-title">舆情健康分</h3>
            {ov.sample_insufficient && <span className="card-meta">样本偏薄</span>}
          </div>
          <div className="kpi-value">{typeof ov.health_score === 'number' ? ov.health_score.toFixed(1) : '—'}<span className="kpi-unit">/100</span></div>
          <div className="sc-dims">
            {negDims.length > 0 ? negDims.map(d => (
              <span key={d.dim} className="sc-dim is-neg" title={`维度得分 ${d.score.toFixed(2)} · 样本 ${d.count}`}>{d.dim}</span>
            )) : <span className="sc-dim-none">暂无显著负面维度</span>}
            <span className="sc-dim-note">负面维度 TOP3</span>
          </div>
          <div className="kpi-foot">
            {typeof data.complaints === 'number' && <span>车质网投诉 <b>{data.complaints}</b> 条（30 天窗）</span>}
            {ov.week_total !== undefined && <span>本周 {ov.week_total} 帖</span>}
          </div>
        </div>

        {/* ③ 正在发酵 */}
        <div className="card sc-card">
          <div className="card-head"><h3 className="card-title">正在发酵</h3>
            <span className="card-meta">本周新增负面帖 {data.incr?.new_negative_count ?? '—'}</span>
          </div>
          {events.length > 0 ? (
            <ul className="sc-events">
              {events.map((e, i) => (
                <li key={i} className="sc-event">
                  <span className="sc-event-tag">{e.event_tag}</span>
                  <span className="sc-event-meta">{e.post_count} 帖{e.start_date ? ` · ${e.start_date.slice(5)}` : ''}</span>
                </li>
              ))}
            </ul>
          ) : <p className="sc-empty">暂无发酵事件</p>}
        </div>

        {/* ④ 翻车帖/护车帖（固定块，点击直跳原帖；拍板 B 10-19，无 url 降级进完整版） */}
        <div className="card sc-card">
          <div className="card-head"><h3 className="card-title">翻车帖 / 护车帖</h3><span className="card-meta">帖子正面 · 评论区反转</span></div>
          <div className="sc-diff">
            {pos2neg.length > 0 ? pos2neg.map((p, i) => (
              <button key={`pn${i}`} className="sc-diff-item is-pn" onClick={() => openPost(p)} title={p.title}>
                <span className="sc-diff-arrow">🔥</span><span className="sc-diff-title">{p.title || '（无标题）'}</span>
                <span className="sc-diff-meta">{PLAT_LABEL[p.platform || ''] || p.platform} · {p.likes || 0} 赞</span>
              </button>
            )) : <p className="sc-empty">近期无翻车帖</p>}
            {neg2pos.length > 0 && (
              <>
                <div className="sc-diff-sep">护车帖（帖子负面 · 评论区正名）</div>
                {neg2pos.map((p, i) => (
                  <button key={`np${i}`} className="sc-diff-item is-np" onClick={() => openPost(p)} title={p.title}>
                    <span className="sc-diff-arrow">🛡</span><span className="sc-diff-title">{p.title || '（无标题）'}</span>
                    <span className="sc-diff-meta">{PLAT_LABEL[p.platform || ''] || p.platform} · {p.likes || 0} 赞</span>
                  </button>
                ))}
              </>
            )}
          </div>
        </div>

        {/* ⑤ 搜索热度（R38 保留；无指数数据则整块隐藏） */}
        {heatSeries.length >= 2 && (
          <div className="card sc-card">
            <div className="card-head"><h3 className="card-title">搜索热度</h3><span className="card-meta">搜索行为 ≠ 讨论量</span></div>
            <Spark values={heatSeries} tone="xt" />
            <p className="sc-note">平台搜索指数（抖音+小红书合成，0-100），反映搜索行为而非本系统讨论量。</p>
          </div>
        )}
      </div>

      <p className="sc-foot">
        口碑 = 车主长期使用评价（汽车之家）· 舆情 = 全网实时讨论（小红书 + 抖音，含非车主声音）<br />
        健康分已剔除官方与商家账号 · 停采平台（微博/快手/新闻）为历史存量
      </p>
    </div>
  );
}
