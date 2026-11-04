/**
 * 登录门禁（登录门禁 change T4，2026-10-15）：前端身份态 + 登录/恢复 + 全局 401 拦截。
 * 设计：统一口令门（共享密码），身份=用户名（token 服务端签发，HttpOnly cookie——
 * 前端不可读也不需要读，所有请求同源自动携带）。
 */

export interface AuthUser {
  username: string;
  role: string; // admin | viewer
}

let authUser: AuthUser | null = null;
const listeners = new Set<() => void>();

export function getAuthUser(): AuthUser | null {
  return authUser;
}

export function setAuthUser(u: AuthUser | null): void {
  authUser = u;
  listeners.forEach((l) => l());
}

/** 订阅身份变化（App 门控用）；返回退订函数 */
export function subscribeAuth(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** 启动身份恢复：/auth/me（cookie 有效则 200） */
export async function fetchMe(): Promise<AuthUser | null> {
  try {
    const r = await fetch('/auth/me');
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.username ? (j as AuthUser) : null;
  } catch {
    return null;
  }
}

/** 登录结果：成功=身份；失败=带后端文案的错误（P2-8：400 用户名格式不合法 ≠ 密码错误，不能混一个文案） */
export interface LoginResult {
  user: AuthUser | null;
  error?: string;
}

export async function login(username: string, password: string): Promise<LoginResult> {
  try {
    const r = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const j = await r.json().catch(() => ({}) as Record<string, unknown>);
    if (!r.ok) {
      return { user: null, error: (typeof j.detail === 'string' && j.detail) || '登录失败' };
    }
    return j && j.username ? { user: j as AuthUser } : { user: null, error: '登录响应异常' };
  } catch {
    return { user: null, error: '网络异常，请重试' };
  }
}

/**
 * 全局 401 拦截（不逐点改几十处 fetch）：包装 window.fetch，同源 API 调用返回 401
 * → 广播 prism:unauthorized（App 听到即回登录页并断在途流）。
 * 不拦 /auth/* 自身（登录失败≠会话失效，避免拦截器打自己）。
 */
export const AUTH_EVENT = 'prism:unauthorized';
let interceptorInstalled = false;

export function install401Interceptor(): void {
  if (interceptorInstalled) return;
  interceptorInstalled = true;
  const orig = window.fetch.bind(window);
  window.fetch = async (...args: Parameters<typeof fetch>): Promise<Response> => {
    const res = await orig(...args);
    try {
      // 尾巴包（2026-10-16）：URL 归一化——同源绝对 URL 与相对路径都判定广播；
      // 跨源/非 API 路径不广播（盲区收窄：EventSource 未用、iframe 走反代已覆盖）
      const rawUrl = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url;
      const u = new URL(rawUrl, window.location.href);
      if (res.status === 401 && u.origin === window.location.origin && !u.pathname.startsWith('/auth/')) {
        window.dispatchEvent(new CustomEvent(AUTH_EVENT));
      }
    } catch {
      /* 拦截器自身异常不影响原响应 */
    }
    return res;
  };
}
