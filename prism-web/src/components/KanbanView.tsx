/** 看板视图：4 格 tab + 内容区 + 状态栏（无 composer）
 * UI-6：active 由父级控制（保活模式下 display:none 切换）
 * C2：seriesKey/seriesId 由 App 下传（对话检测或侧栏核验），经 URL 参数进 iframe 子服务
 * C3：as_of 实时取 /dash/as_of（iframe 化后无 _meta 上抛通道）；刷新按钮重载当前看板
 */

import { useState, useEffect } from 'react';
import { Icon } from './Icons';
import SentimentBoard from './dashboards/SentimentBoard';
import MarketBoard from './dashboards/MarketBoard';
import ConfigBoard from './dashboards/ConfigBoard';
import ReviewsBoard from './dashboards/ReviewsBoard';

type Board = 'sentiment' | 'config' | 'reviews' | 'sales';

export default function KanbanView({ onEvidence, active, seriesKey, seriesId }: {
  onEvidence?: (data: any) => void;
  active?: boolean;
  seriesKey?: string;
  seriesId?: string | number;
}) {
  const [board, setBoard] = useState<Board>('config');
  const [reloadTick, setReloadTick] = useState(0);
  const [asOf, setAsOf] = useState<{ sales?: string | null; reviews?: string | null; config?: string | null; sentiment?: string | null } | null>(null);
  // 社媒深挖能力包 M4：TikHub 余额/可用性黄灯（configured=false 灰、余额低/用量未知黄、异常红）
  const [tikhub, setTikhub] = useState<{ configured?: boolean; error?: string; low?: boolean; usageUnknown?: boolean } | null>(null);

  // C3：as_of 直读主库口径（销量最新月末批 + 口碑最新发帖日）；刷新时同取
  useEffect(() => {
    let alive = true;
    fetch('/dash/as_of').then(r => r.json()).then(j => { if (alive) setAsOf(j); }).catch(() => {});
    fetch('/tikhub/status').then(r => r.json()).then(j => {
      if (!alive) return;
      if (!j?.configured) { setTikhub({ configured: false }); return; }
      // 黄灯盯日消耗（TikHub 无公开余额 API；今日 spend ≥ $5 亮黄；用量拉取失败亮"用量未知"P2-6）
      const spend = j.daily_usage?.spend_usd;
      const low = typeof spend === 'number' && spend >= 5;
      const usageUnknown = !j.error && !j.daily_usage;
      setTikhub({ configured: true, error: j.error, low, usageUnknown });
    }).catch(() => { if (alive) setTikhub(null); });
    return () => { alive = false; };
  }, [reloadTick]);

  const asOfText = asOf
    ? [asOf.sales && `销量 ${asOf.sales}`, asOf.reviews && `口碑 ${asOf.reviews}`, asOf.config && `配置 ${asOf.config}`, asOf.sentiment && `舆情 ${asOf.sentiment}`].filter(Boolean).join(' · ') || '—'
    : '—';

  return (
    <div className={`view ${active ? 'is-active' : ''}`} id="viewBoard">
      {/* ③ 看板栏 */}
      <header className="board-bar">
        <div className="bar-left">
          <span className="bar-brand"><Icon name="atom" size={14} />棱镜看板</span>
          <div className="seg" role="tablist">
            <button className="seg-btn" aria-selected={board === 'sentiment'} onClick={() => setBoard('sentiment')}>舆情</button>
            <span className="seg-div" />
            <button className="seg-btn" aria-selected={board === 'config'} onClick={() => setBoard('config')}>车型配置</button>
            <button className="seg-btn" aria-selected={board === 'reviews'} onClick={() => setBoard('reviews')}>口碑</button>
            <button className="seg-btn" aria-selected={board === 'sales'} onClick={() => setBoard('sales')}>销量</button>
          </div>
        </div>
        <div className="bar-right">
          {seriesKey && <span className="bar-meta">{seriesKey}</span>}
          <span className="bar-meta">as_of <b>{asOfText}</b></span>
          {tikhub && (
            <span className="bar-meta" title={tikhub.error || (tikhub.configured ? 'TikHub 社媒 API（用量查询失败时不静默）' : 'TikHub 未配置（prism-api/.env）')}>
              社媒API{' '}
              {!tikhub.configured ? <b style={{ color: 'var(--muted, #999)' }}>未配置</b>
                : tikhub.error ? <b style={{ color: '#9c2a25' }}>异常</b>
                : tikhub.low ? <b style={{ color: '#b8860b' }}>低余额</b>
                : tikhub.usageUnknown ? <b style={{ color: '#b8860b' }}>用量未知</b>
                : <b style={{ color: '#2e7d32' }}>✓</b>}
            </span>
          )}
          <button className="icon-btn" aria-label="刷新" onClick={() => setReloadTick(t => t + 1)}><Icon name="refresh" /></button>
        </div>
      </header>

      {/* ④ 内容区：四个 tab 均为 iframe → 一律 is-bleed（去留白 / 去 1240 上限，让 iframe 顶到边） */}
      <div className="board-scroll is-bleed">
        <div className="board is-active is-bleed">
          {board === 'sentiment' && <SentimentBoard seriesKey={seriesKey} reloadKey={reloadTick} />}
          {board === 'config' && <ConfigBoard onEvidence={onEvidence} seriesId={seriesId} reloadKey={reloadTick} />}
          {board === 'reviews' && <ReviewsBoard onEvidence={onEvidence} series={seriesKey} reloadKey={reloadTick} />}
          {board === 'sales' && <MarketBoard onEvidence={onEvidence} seriesKey={seriesKey} reloadKey={reloadTick} />}
        </div>
      </div>
    </div>
  );
}
