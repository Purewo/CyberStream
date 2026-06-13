import { getApiBase } from '../platform';
import { fetchApi } from './core';

/**
 * 用户管理状态。GET /api/v1/auth/me 永远返回 200——
 * - user_management_enabled === false：旧模式，不拦
 * - user_management_enabled === true && authenticated === false：进登录页
 * - user_management_enabled === true && authenticated === true：进用户态
 *
 * 后端写 HttpOnly cookie 维持会话，前端不能也不要保存密码或 token。
 */
export interface AuthStatus {
  user_management_enabled: boolean;
  authenticated: boolean;
  role: 'admin' | 'user' | null;
  auth_via: 'session' | 'api_token' | null;
  user: null | {
    id: number;
    username: string;
    display_name: string | null;
    role: 'admin' | 'user';
    is_enabled: boolean;
    library_rules?: Array<{ library_id: number; mode: 'allow' | 'deny' }>;
  };
  permissions: {
    admin: boolean;
    read_catalog: boolean;
    manage_catalog: boolean;
    manage_users: boolean;
    personal_history: boolean;
    personal_subtitle_settings: boolean;
  };
}

export interface LoginResult {
  ok: boolean;
  status: number;
  /** 后端业务码：401 凭证无效，429 触发限流，其他 0 表示网络异常。 */
  code?: number;
  /** 后端 msg 透传，UI 直接用。 */
  msg?: string;
  /** 429 时来自 Retry-After 响应头的秒数。无该头时为 undefined。 */
  retryAfterSec?: number;
  data?: AuthStatus;
}

export const authService = {
  // 登录态被动探测：启动时 / 401 后调一次。任何部署形态都返回 200，
  // 看 user_management_enabled & authenticated 决定 UI。
  getStatus: async (): Promise<AuthStatus | null> => {
    return await fetchApi<AuthStatus>('/v1/auth/me');
  },

  // 不走 fetchApi——需要拿 status code 区分凭证无效(401) 与限流(429)，
  // 还要读 Retry-After 响应头给登录页倒计时。
  login: async (username: string, password: string): Promise<LoginResult> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/auth/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      let body: any = null;
      try { body = await res.json(); } catch { /* non-json or empty */ }
      const retry = res.headers.get('Retry-After');
      const retryAfterSec = retry ? Math.max(0, parseInt(retry, 10) || 0) : undefined;
      if (res.ok && (body?.code === 200 || body?.code === 20000)) {
        return { ok: true, status: res.status, code: body.code, data: body.data as AuthStatus };
      }
      return {
        ok: false,
        status: res.status,
        code: body?.code,
        msg: body?.msg || body?.message,
        retryAfterSec,
      };
    } catch {
      return { ok: false, status: 0, msg: '网络连接异常' };
    }
  },

  logout: async (): Promise<boolean> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
      return res.ok || res.status === 401;
    } catch {
      return false;
    }
  },
};
