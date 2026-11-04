/** 侧栏（对齐原型 §4 区②）
 * UI-1：空壳项下架（产物/设置/已置顶空列表/硬编码最近车系）
 * UI-3：SKILLS 库入口（onOpenSkills 回调）
 * UI-4：会话行 onClick 切换 + 双击行内重命名（POST /session/rename）
 * 2026-10：下架「车系」tab（车系由对话侧说出，不再从侧栏先选对象）、
 *          右上「更多」按钮、底部无功能的「主页/帮助」图标。
 */

import { useState, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Icon } from './Icons';
import { getUserId } from '../lib/chat';
import { track } from '../lib/tracker';

interface Props {
  active: 'kanban' | 'chat';
  onNavigate: (v: 'kanban' | 'chat') => void;
  onOpenSkills?: () => void;
  onSessionSelect?: (sessionId: string) => void;
  selectedSessionId?: string;
  /** Gap9：「新建会话」≠「返回对话视图」——回调语义上抛 App（清 selectedSessionId）；
   *  缺省回落 onNavigate('chat')（旧视图切换行为） */
  onNewSession?: () => void;
}

export default function Sidebar({ active, onNavigate, onOpenSkills, onSessionSelect, selectedSessionId, onNewSession }: Props) {
  const userId = getUserId();
  const qc = useQueryClient();
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState('');
  // D2/D5（2026-11-03）：窄屏（≤900px）侧栏折叠为图标栏后，会话列表被隐藏，
  // 删除/切换入口不可达——用顶端 panel 按钮切换展开态，宽屏下该按钮无实际视觉变化。
  const [expanded, setExpanded] = useState(false);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const { data: sessionData } = useQuery({
    queryKey: ['sessions', userId],
    queryFn: () => fetch('/session?user_id=' + userId).then(r => r.json()),
    refetchInterval: 10000,
  });
  const sessions: Array<{ id: string; name?: string; custom_name?: string }> = sessionData?.sessions ?? [];

  function startRename(id: string, current: string) {
    setRenameId(id);
    setRenameVal(current);
    setTimeout(() => renameInputRef.current?.select(), 0);
  }

  async function commitRename(id: string) {
    const name = renameVal.trim();
    setRenameId(null);
    if (!name) return;
    try {
      await fetch('/session/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: id, name, user_id: userId }),
      });
      qc.invalidateQueries({ queryKey: ['sessions', userId] });
      track('session_rename', { value: id });
    } catch { /* 主会话补后端时统一处理 */ }
  }

  /** D2（2026-11-02）：删除会话（不可恢复，二次确认） */
  async function deleteSession(id: string) {
    if (!window.confirm('删除该会话？此操作不可恢复')) return;
    try {
      const r = await fetch(`/session/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('failed');
      qc.invalidateQueries({ queryKey: ['sessions', userId] });
      if (selectedSessionId === id) onNewSession?.();
      track('session_delete', { value: id });
    } catch {
      window.alert('删除失败，请重试');
    }
  }

  function selectSession(id: string) {
    onSessionSelect?.(id);
    track('session_switch', { value: id });
  }

  return (
    <aside className={`sidebar ${expanded ? 'is-expanded' : ''}`}>
      <div className="sb-top">
        <button className="icon-btn" aria-label={expanded ? '收起侧栏' : '展开侧栏'} aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}><Icon name="panel" /></button>
        <div className="sb-tabs" role="tablist">
          <span className="sb-tab is-on">会话</span>
        </div>
      </div>

      <nav className="sb-nav">
        <button className={`sb-item ${active === 'chat' ? 'is-active' : ''}`} onClick={() => (onNewSession ? onNewSession() : onNavigate('chat'))}>
          <Icon name="plus" /><span>新建会话</span><kbd>Ctrl N</kbd>
        </button>
        <button className={`sb-item ${active === 'kanban' ? 'is-active' : ''}`} onClick={() => onNavigate('kanban')}>
          <Icon name="kanban" /><span>棱镜工作台</span>
        </button>
        {/* UI-3 能力总览入口（原 SKILLS 库，2026-10-12 概念诚实化：skill≠tool≠护栏） */}
        <button className="sb-item" onClick={() => onOpenSkills?.()}>
          <Icon name="layers" /><span>能力总览</span>
        </button>
      </nav>

      <div className="sb-search">
        <Icon name="search" />
        <input placeholder="搜索会话…" />
      </div>

      <div className="sb-scroll">
        <div className="sb-group">
          <div className="sb-label"><Icon name="chat" size={13} />会话</div>
          <ul className="sb-list">
            {sessions.length === 0 ? (
              <li className="sb-row"><span className="sb-row-title" style={{ color: 'var(--ink-3)' }}>暂无会话</span></li>
            ) : sessions.map((s) => {
              const title = s.custom_name || s.name || s.id.slice(0, 12);
              const selected = selectedSessionId === s.id;
              return (
                <li
                  className={`sb-row ${selected ? 'is-active' : ''}`}
                  key={s.id}
                  onClick={() => selectSession(s.id)}
                  onDoubleClick={() => startRename(s.id, title)}
                  title="单击切换 · 双击重命名"
                >
                  <span className="dot" />
                  {renameId === s.id ? (
                    <input
                      ref={renameInputRef}
                      className="sb-rename-input"
                      value={renameVal}
                      onChange={(e) => setRenameVal(e.target.value)}
                      onBlur={() => commitRename(s.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commitRename(s.id);
                        if (e.key === 'Escape') setRenameId(null);
                      }}
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <span className="sb-row-title">{title}</span>
                  )}
                  {renameId !== s.id && (
                    <button
                      className="sb-del"
                      title="删除会话"
                      onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                    >×</button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </aside>
  );
}
