/**
 * Prism-Agent · AppShell（四区：应用栏/侧栏/主区/右抽屉）
 * 主区内两个视图：看板(BI) / 对话(Agent)，共享底部状态栏
 * composer 仅对话视图渲染
 * UI-5：应用栏 Logo 改卢浮宫金字塔 SVG
 * UI-6：视图保活（display:none 而非 unmount，切换不丢状态）
 */

import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import KanbanView from './components/KanbanView';
import ChatView from './components/ChatView';
import EvidenceDrawer, { type EvidenceData } from './components/EvidenceDrawer';
import SkillsPanel from './components/SkillsPanel';
import Dock from './components/Dock';
import PyramidLogo from './components/PyramidLogo';
import LoginGate from './components/LoginGate';
import { initTracker } from './lib/tracker';
import { pushRecentSeries } from './lib/series';
import { getUserId, cancelActiveStream } from './lib/chat';
import { fetchMe, install401Interceptor, AUTH_EVENT, type AuthUser } from './lib/auth';

type View = 'kanban' | 'chat';

/** 当前分析对象（C2）：name=库源权威名，id 供配置看板直达。 */
interface SeriesSelection {
  name: string;
  id?: string | number;
}

/** D2（2026-11-02）：URL 路由——刷新后保留视图与会话 */
function readUrlState(): { view: View; session?: string } {
  try {
    const p = new URLSearchParams(window.location.search);
    const v = p.get('view');
    return {
      view: v === 'kanban' || v === 'chat' ? v : 'chat',
      session: p.get('session') || undefined,
    };
  } catch {
    return { view: 'chat' };
  }
}

const _INITIAL_URL = readUrlState();

export default function App() {
  // 登录门禁 T4：三态门控（checking → login | ready）；401 广播回登录页
  const [authChecked, setAuthChecked] = useState(false);
  const [authUser, setAuthState] = useState<AuthUser | null>(null);
  useEffect(() => {
    install401Interceptor();
    fetchMe().then((u) => {
      setAuthState(u);
      setAuthChecked(true);
    });
    const on401 = () => {
      cancelActiveStream();
      setAuthState(null);
    };
    window.addEventListener(AUTH_EVENT, on401);
    return () => window.removeEventListener(AUTH_EVENT, on401);
  }, []);

  // 对话优先：默认落在对话视图（对象由对话里说出，不由看板先拦）
  const [view, setView] = useState<View>(_INITIAL_URL.view);
  const [pendingMsg, setPendingMsg] = useState<string | undefined>();
  const [evidence, setEvidence] = useState<EvidenceData | null>(null);
  const [skillsOpen, setSkillsOpen] = useState(false);
  const [selectedSessionId, setSelectedSessionId] = useState<string | undefined>(_INITIAL_URL.session);
  const [series, setSeries] = useState<SeriesSelection | undefined>();

  // D2：视图/会话写入 URL，刷新可恢复
  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      p.set('view', view);
      if (selectedSessionId) p.set('session', selectedSessionId); else p.delete('session');
      const qs = p.toString();
      history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
    } catch { /* URL 不可写时忽略 */ }
  }, [view, selectedSessionId]);

  // 登录门禁：未登录不启埋点（心跳 fetch 会打未授权 401）
  useEffect(() => {
    if (authUser) return initTracker();  // tracker 自带清理（心跳+兜底 flush 两个 interval）
  }, [authUser]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [asOf, setAsOf] = useState('—');

  /** 对话检测到车系（agent 工具调用里的 series_key）→ 记最近 + best-effort 核验补 id。
   * 单向流动：只更新看板联动状态，不把 series_key 回传对话（agent 自主 resolve，防跨轮污染）。 */
  async function detectSeries(name: string) {
    const key = name.trim();
    if (!key) return;
    setSeries((prev) => (prev?.name === key ? prev : { name: key }));
    pushRecentSeries(key);
    try {
      const r = await fetch('/identity/resolve?series_key=' + encodeURIComponent(key));
      const j = await r.json();
      if (j && !j.ambiguous && !j.needs_online_verify && j.series_id != null) {
        const canonical = j.canonical_name || key;
        setSeries((prev) => (prev && prev.name === key ? { name: canonical, id: j.series_id } : prev));
      }
    } catch { /* 核验不可达：保留裸名（口碑看板 q= 预筛仍可用） */ }
  }

  function openEvidence(data: EvidenceData) {
    setEvidence(data);
    setDrawerOpen(true);
  }

  // 登录门禁 T4：检查中 → 启动闪屏；未登录 → 登录页（主树不挂载：ChatView/埋点/看板 iframe 均不启动）
  if (!authChecked) {
    return (
      <div className="login-gate login-gate--boot" aria-label="正在检查登录状态">
        <PyramidLogo size={28} />
      </div>
    );
  }
  if (!authUser) {
    return <LoginGate onLogin={(u) => setAuthState(u)} />;
  }

  return (
    <div className="app">
      {/* ① 应用栏 40px */}
      <header className="appbar">
        <span className="brand">
          <PyramidLogo size={18} />
          <span className="brand-text">Prism <small>Agent</small></span>
        </span>
        <span className="appbar-spacer"></span>
      </header>

      {/* ② 侧栏 */}
      <Sidebar
        active={view}
        onNavigate={(v) => setView(v)}
        onOpenSkills={() => setSkillsOpen(true)}
        onSessionSelect={(id) => { setSelectedSessionId(id); setView('chat'); }}
        selectedSessionId={selectedSessionId}
        /* T-A4/Gap9 + 审查P0-1：新建会话≠返回对话——必须真正调 POST /session 开新会话。
         * 仅清 selectedSessionId 不够：/chat 的 session_id=null 只是"不 switch"，
         * 消息会落在 pi 进程当前活跃会话（刚浏览过的旧会话）上。 */
        onNewSession={async () => {
          setView('chat');
          setSelectedSessionId(undefined);
          try {
            const r = await fetch('/session', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ user_id: getUserId() }),
            });
            if (r.ok) {
              const j = await r.json();
              if (j.session_id && j.session_id !== 'unknown') {
                setSelectedSessionId(j.session_id);
                return;
              }
            }
          } catch { /* 建会话失败：保持 undefined，首轮对话由 session_info 回填真实 id */ }
        }}
      />

      {/* ③ 主区 */}
      <div className="main">
        {/* UI-6 视图保活：两视图常驻，display:none 切换，不卸载 */}
        <div className="view-stack">
          <KanbanView active={view === 'kanban'} onEvidence={openEvidence} seriesKey={series?.name} seriesId={series?.id} />
          <div className={`view ${view === 'chat' ? 'is-active' : ''}`} id="viewChat">
            <ChatView
              sessionId={selectedSessionId}
              initialMessage={pendingMsg}
              onConsumed={() => setPendingMsg(undefined)}
              onAsOf={(v: string) => setAsOf(v)}
              onSessionCreated={(id) => setSelectedSessionId(id)}
              series={series?.name}
              onSeriesDetected={detectSeries}
              /* T-B2：溯源条点击 → 复用现有证据抽屉管线（openEvidence/drawerOpen） */
              onOpenEvidence={openEvidence}
            />
          </div>
        </div>

        {/* ⑥ 状态栏（2026-10-25：移除左下角重复的模型名，模型只在输入框内的选择器展示） */}
        <div className="statusbar">
          <div className="status-right">
            <span className="status-item" style={{ fontFamily: 'var(--font-ui)', fontVariantNumeric: 'tabular-nums' }}>as_of {asOf}</span>
          </div>
        </div>
      </div>

      {/* ⑦ 证据抽屉 */}
      <EvidenceDrawer open={drawerOpen} data={evidence} onClose={() => setDrawerOpen(false)} />

      {/* UI-3 SKILLS 库面板 */}
      <SkillsPanel open={skillsOpen} onClose={() => setSkillsOpen(false)} />

      {/* 左下角浮动入口组：产品介绍（视频）+ 用户反馈 */}
      <Dock />
    </div>
  );
}
