/**
 * Hermes 图标 sprite（搬自 hermes-agent-kanban.html）
 * 用 <Icon name="kanban" /> 引用，渲染 <svg><use href="#ico-xxx"/></svg>
 */
import { useEffect, useState } from 'react';

const SYMBOLS = `
<symbol id="ico-plus" viewBox="0 0 24 24"><path d="M12 5.5v13M5.5 12h13"/></symbol>
<symbol id="ico-chat" viewBox="0 0 24 24"><path d="M4.5 5.5h15v10h-8.5l-4 3.5v-3.5H4.5z"/></symbol>
<symbol id="ico-kanban" viewBox="0 0 24 24"><rect x="3.8" y="4.6" width="4.6" height="14.8" rx="1.4"/><rect x="9.7" y="4.6" width="4.6" height="9.4" rx="1.4"/><rect x="15.6" y="4.6" width="4.6" height="12.2" rx="1.4"/></symbol>
<symbol id="ico-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.2"/><path d="M15.6 15.6 20 20"/></symbol>
<symbol id="ico-panel" viewBox="0 0 24 24"><rect x="3.8" y="4.6" width="16.4" height="14.8" rx="2.2"/><path d="M9.6 4.6v14.8"/></symbol>
<symbol id="ico-refresh" viewBox="0 0 24 24"><path d="M19.4 12a7.4 7.4 0 1 1-2.2-5.3"/><path d="M19.6 4.7v4.6h-4.6"/></symbol>
<symbol id="ico-chev" viewBox="0 0 24 24"><path d="M7.5 10 12 14.5 16.5 10"/></symbol>
<symbol id="ico-x" viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17"/></symbol>
<symbol id="ico-unplug" viewBox="0 0 24 24"><path d="M9 3.4v4.2M15 3.4v4.2"/><path d="M6.4 7.6h11.2v3.2a5.6 5.6 0 0 1-5.6 5.6 5.6 5.6 0 0 1-5.6-5.6z"/><path d="M12 16.4v4.2"/></symbol>
<symbol id="ico-arrow-up" viewBox="0 0 24 24"><path d="M12 19V5.6M6 11.6 12 5.6l6 6"/></symbol>
<symbol id="ico-stop" viewBox="0 0 24 24"><rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/></symbol>
<symbol id="ico-arrow-right" viewBox="0 0 24 24"><path d="M5.5 12h13M13 6.5 18.5 12 13 17.5"/></symbol>
<symbol id="ico-atom" viewBox="0 0 24 24"><circle cx="12" cy="12" r="2.2"/><ellipse cx="12" cy="12" rx="9" ry="4"/><ellipse cx="12" cy="12" rx="9" ry="4" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="4" transform="rotate(120 12 12)"/></symbol>
<symbol id="ico-layers" viewBox="0 0 24 24"><path d="M12 3.8 20.5 8 12 12.2 3.5 8z"/><path d="M3.5 12 12 16.2 20.5 12M3.5 16 12 20.2 20.5 16"/></symbol>
<symbol id="ico-flask" viewBox="0 0 24 24"><path d="M9.6 3.6h4.8"/><path d="M10.6 3.6v6.1l-4.5 7.6a2 2 0 0 0 1.7 3h8.4a2 2 0 0 0 1.7-3l-4.5-7.6V3.6"/><path d="M7.9 15.2h8.2"/></symbol>
`;

let injected = false;
function injectSprite() {
  if (injected || typeof document === 'undefined') return;
  const div = document.createElement('div');
  div.className = 'sprite';
  div.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
  div.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">${SYMBOLS}</svg>`;
  document.body.appendChild(div);
  injected = true;
}

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    injectSprite();
    setReady(true);
  }, []);
  if (!ready) return null;
  return (
    <svg className="ico" style={{ width: size, height: size }} aria-hidden>
      <use href={`#ico-${name}`} />
    </svg>
  );
}
