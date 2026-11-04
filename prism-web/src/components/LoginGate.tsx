/**
 * 登录门禁（登录门禁 change T4）：统一口令门登录页。
 * 用户名（归因+权限分层）+ 共享密码；错密码固定提示，不区分哪个错。
 */
import { useState, type FormEvent } from 'react';
import PyramidLogo from './PyramidLogo';
import { login, type AuthUser } from '../lib/auth';

export default function LoginGate({ onLogin }: { onLogin: (u: AuthUser) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const name = username.trim();
    if (!name || !password) {
      setError('请输入用户名和密码');
      return;
    }
    setBusy(true);
    setError('');
    const res = await login(name, password);
    setBusy(false);
    if (res.user) onLogin(res.user);
    else setError(res.error || '密码错误');
  }

  return (
    <div className="login-gate">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <PyramidLogo size={28} />
          <span className="login-brand-text">Prism <small>Agent</small></span>
        </div>
        <label className="login-field">
          <span>用户名</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="你的名字（用于记录与权限）"
            autoComplete="username"
            autoFocus
          />
        </label>
        <label className="login-field">
          <span>密码</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="共享密码"
            autoComplete="current-password"
          />
        </label>
        {error ? <div className="login-error">{error}</div> : null}
        <button className="login-submit" type="submit" disabled={busy}>
          {busy ? '进入中…' : '进入'}
        </button>
      </form>
    </div>
  );
}
