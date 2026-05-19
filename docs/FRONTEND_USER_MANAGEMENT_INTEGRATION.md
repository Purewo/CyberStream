# 前端用户管理平滑接入方案

当前用户管理后端已经可用，但默认关闭。前端接入必须保持被动探测，不要在用户系统关闭时改变现有页面行为。

## 启动探测

应用启动时先请求：

```http
GET /api/v1/auth/me
```

这个接口在用户管理关闭时也会返回 `200`，即使旧的 `CYBER_API_TOKEN` 已启用也不需要 token。推荐前端始终带 `credentials: "include"`，用户系统关闭时不会有副作用。

判定逻辑：

- `user_management_enabled === false`：进入旧模式，不显示登录页，不拦截旧页面。
- `user_management_enabled === true && authenticated === false`：进入登录页。
- `user_management_enabled === true && authenticated === true`：进入用户态，按 `permissions` 控制管理入口显示。

## 最小 API 客户端草案

```ts
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

type ApiResponse<T> = {
  code: number;
  msg: string;
  trace_id: string;
  data: T;
};

export type AuthStatus = {
  user_management_enabled: boolean;
  authenticated: boolean;
  role: "admin" | "user" | null;
  auth_via: "session" | "api_token" | null;
  user: null | {
    id: number;
    username: string;
    display_name: string | null;
    role: "admin" | "user";
    is_enabled: boolean;
    library_rules?: Array<{ library_id: number; mode: "allow" | "deny" }>;
  };
  permissions: {
    admin: boolean;
    read_catalog: boolean;
    manage_catalog: boolean;
    manage_users: boolean;
    personal_history: boolean;
    personal_subtitle_settings: boolean;
  };
};

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  const payload = (await response.json()) as ApiResponse<T>;
  if (!response.ok) {
    throw Object.assign(new Error(payload.msg || "request failed"), {
      status: response.status,
      code: payload.code,
      payload,
    });
  }
  return payload.data;
}

export function getAuthStatus() {
  return apiFetch<AuthStatus>("/api/v1/auth/me");
}

export function login(username: string, password: string) {
  return apiFetch<AuthStatus>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return apiFetch<null>("/api/v1/auth/logout", { method: "POST" });
}

export function updateProfile(displayName: string) {
  return apiFetch<AuthStatus>("/api/v1/user/profile", {
    method: "PATCH",
    body: JSON.stringify({ display_name: displayName }),
  });
}

export function updatePassword(currentPassword: string, newPassword: string) {
  return apiFetch<AuthStatus>("/api/v1/user/password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}
```

## UI 接入顺序

1. 先接 `GET /api/v1/auth/me`，只存状态，不改变现有页面。
2. 加登录页，但只在后端返回 `user_management_enabled: true` 且未登录时显示。
3. 普通用户隐藏管理入口；管理员显示用户管理入口。
4. 管理员用户页再接：
   - `GET /api/v1/admin/users`
   - `POST /api/v1/admin/users`
   - `PATCH /api/v1/admin/users/{id}`
   - `POST /api/v1/admin/users/{id}/password`
   - `PUT /api/v1/admin/users/{id}/library-rules`
   - `GET /api/v1/admin/users/{id}/visibility-preview`
   - `GET /api/v1/admin/audit-logs`

资源库规则保存后，建议立即请求 `visibility-preview`，用 `visible_library_ids`、`visible_movie_count` 和 `sample_movies` 做管理员页面的结果预览。

## 回归重点

- 用户管理关闭时，首页、列表、详情、播放页不出现登录跳转。
- 用户管理开启后，刷新页面仍能通过 cookie 恢复登录态。
- 普通用户不能看到存储源、扫描、元数据、资源治理等管理入口。
- 管理员配置 allow/deny 资源库后，列表和直连播放都不能越权。
- 管理员重置密码或禁用用户后，该用户旧页面下一次请求应进入未登录态。
