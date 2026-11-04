/**
 * 通用看板嵌入：iframe 嵌 Prism Dashboards 子服务（/dash/* 经 prism-api 反代到 :8010）
 *
 * - 与 SentimentBoard 同构：铺满 + 同源注入 CSS 去冗余 + loading/缺口覆盖层（不占高度）
 * - 三看板（口碑 / 车型配置 / 销量）共用，仅路径与文案不同
 * - 同源注入只隐藏内页顶部导航 body>nav（Prism 侧已有 tab），不改内页其余布局
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { GapCard, Loading } from './_shared';

export default function EmbedBoard({ path, title, miss, ask, reloadKey }: {
  path: string; title: string; miss: string; ask: string;
  /** C3：变化时重载内页 + 重探活（看板顶部刷新按钮驱动） */
  reloadKey?: number;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  // 探测 /dash/ 反代是否可达（用 GET）
  const probe = useCallback(async () => {
    setState('loading');
    try {
      const res = await fetch(path, { method: 'GET' });
      setState(res.ok ? 'ready' : 'error');
    } catch {
      setState('error');
    }
  }, [path]);

  useEffect(() => { probe(); }, [probe]);

  // 刷新：iframe 与页面同源（经 vite 代理），直接 reload 内页；未就绪时退化为重挂 src
  useEffect(() => {
    if (!reloadKey) return;
    const f = frameRef.current;
    try { f?.contentWindow?.location.reload(); } catch { if (f) f.src = f.src; }
    probe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  // 同源：隐藏内页顶部导航（Prism 侧 tab 已表达「在看哪个看板」，去掉重复入口）
  const hideInnerNav = useCallback(() => {
    try {
      const doc = frameRef.current?.contentDocument;
      if (!doc || doc.getElementById('prism-embed-hide-nav')) return;
      const st = doc.createElement('style');
      st.id = 'prism-embed-hide-nav';
      st.textContent = 'body > nav{display:none !important}';
      doc.head?.appendChild(st);
    } catch { /* 跨域或文档未就绪：跳过，不影响嵌入 */ }
  }, []);

  return (
    <div className="xt-frame">
      <iframe
        ref={frameRef}
        className="xt-iframe"
        src={path}
        title={title}
        onLoad={hideInnerNav}
      />
      {state === 'loading' && (
        <div className="xt-overlay">
          <Loading />
        </div>
      )}
      {state === 'error' && (
        <div className="xt-overlay is-center">
          <GapCard title={`${title}未连接`} miss={miss} ask={ask} />
          <button className="xt-retry" onClick={probe}>重试</button>
        </div>
      )}
    </div>
  );
}
