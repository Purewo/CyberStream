# 前端用户管理接入方案

当前公网托管试点已经开启强制账号登录：

- 后端基地址：`https://cyberstream.gameuniverse.top:40160`
- 运行状态：`CYBER_USER_MANAGEMENT_ENABLED=true`
- 匿名访问影视列表、存储管理、播放流等受保护接口会返回 `401`
- 登录态由后端写入 `HttpOnly` Cookie，前端不能读取 Cookie，也不要保存密码或自定义 token

自托管和本地开发环境仍可能关闭用户管理。前端必须通过 `GET /api/v1/auth/me` 被动探测，不要把某个部署形态硬编码到页面逻辑里。

## 启动探测

应用启动时先请求：

```http
GET /api/v1/auth/me
```

这个接口在用户管理关闭时也会返回 `200`，即使旧的 `CYBER_API_TOKEN` 已启用也不需要 token。推荐前端始终带 `credentials: "include"`，用户系统关闭时不会有副作用。

判定逻辑：

- `user_management_enabled === false`：进入旧模式，不显示登录页，不拦截旧页面
- `user_management_enabled === true && authenticated === false`：进入登录页
- `user_management_enabled === true && authenticated === true`：进入用户态，按 `permissions` 控制管理入口显示
- `hosted_managed_mode === true`：当前后端由平台统一托管，前端应隐藏服务器级设置和 CDN/cache 运维入口
- `current_account !== null && account_role === "owner"`：当前用户可按 `permissions` 管理自己账号下的数据

## 请求约定

- 所有请求都带 `credentials: "include"`，包括 `GET /api/v1/auth/me`、登录、登出、目录、播放和管理接口。
- 本地前端 `http://localhost:3000` 调用公网 HTTPS 后端属于跨站请求；如果缺少 `credentials: "include"`，登录接口仍可能返回 `authenticated=true`，但浏览器不会保存或回传后端写入的 HttpOnly Cookie，后续受保护接口会继续 `401`。
- 登录成功后以后端返回的 `AuthStatus` 为准，不要从 Cookie 里解析用户信息。
- 任意受保护接口返回 `401` 时，清空前端内存中的登录状态并重新请求 `/api/v1/auth/me`；确认未登录后展示登录页。
- `POST /api/v1/auth/logout` 成功或返回 `401` 后，都清空前端登录状态。
- 不要在前端代码、配置、文档或日志里写死任何测试账号密码；账号由服务端运维侧发放。
- 普通用户只展示 `permissions` 允许的页面。管理员入口至少需要检查 `permissions.admin`、`permissions.manage_users`、`permissions.manage_catalog`。
- 服务器级配置入口单独检查 `permissions.manage_server_config`；代托管模式下管理员也会返回 `false`。
- 代托管 1.22.0 后，注册用户默认是自己账号的 owner。不要因为 `user.role === "user"` 就隐藏账号内挂载、扫描、审查和元数据编辑；这些入口看 `permissions.manage_storage` 与 `permissions.manage_catalog`。
- `/api/v1/admin/users` 仍是平台用户管理语义，不是家庭子账号管理入口。未来家庭子账号会走账号级接口；当前 `permissions.manage_account_users=false`。

## PC / 外部播放器播放票据

WebView 内的 HttpOnly Cookie 不能可靠交给 mpv 等独立播放器进程。PC 端启动外部播放器前先在登录态下请求：

```http
POST /api/v1/auth/playback-ticket
```

响应仍是标准 `ApiResponse`，`data` 包含：

```json
{
  "ticket": "<opaque>",
  "expires_at": 1780000000,
  "ttl": 43200
}
```

把 `ticket` 作为 query 拼到外部播放器会直接请求的 URL 上，例如：

```text
/api/v1/resources/{id}/stream?ticket=<opaque>
/api/v1/resources/{id}/stream?subtitle_id=<subtitle_id>&ticket=<opaque>
/api/v1/resources/{id}/stream-transcoded?resolution=high&ticket=<opaque>
/api/v1/resources/{id}/streaming-qualities?ticket=<opaque>
/api/v1/resources/{id}/subtitles/online/search?keyword=<keyword>&ticket=<opaque>
/api/v1/resources/{id}/subtitles/online/download?ticket=<opaque>
/api/v1/resources/{id}/subtitles/online/bind?ticket=<opaque>
/api/v1/resources/{id}/subtitles/{subtitle_id}?ticket=<opaque>
/api/v1/resources/{id}/audio-transcode?start=0&ticket=<opaque>
```

票据绑定当前用户和 session_version，不绑定单个 resource；默认有效期 12 小时，可覆盖一整场观影和换集。代托管模式下，ticket 请求会恢复当前账号上下文并继续按 account 隔离。非法或过期票据返回 HTTP `401`、业务码 `40130`，PC 端应重新请求 `/auth/playback-ticket` 后重试。浏览器内播放继续走 Cookie，不强制使用 ticket。

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
  hosted_managed_mode: boolean;
  authenticated: boolean;
  role: "admin" | "user" | null;
  auth_via: "session" | "api_token" | null;
  current_account: null | {
    id: string;
    name: string;
    slug: string;
    status: "active" | "disabled" | "pending_delete";
  };
  account_role: "owner" | "member" | null;
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
    manage_storage: boolean;
    manage_account_users: boolean;
    manage_server_config: boolean;
    personal_history: boolean;
    personal_favorites: boolean;
    personal_vault: boolean;
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

## 托管试点回归点

- 未登录访问 `GET /api/v1/movies` 应进入登录态处理，不展示空片库。
- 未登录访问 `GET /api/v1/storage/sources`、扫描、元数据和资源治理入口应被拦截。
- 未登录访问资源播放、字幕或外部播放器入口应按 `401` 处理，不重试死循环。
- 管理员登录后能看到全部影视库和管理入口。
- 普通用户登录后只看到后端授权的影视库，且直连播放也不能越权。
- 刷新页面后通过 `/auth/me` 恢复登录态，不要求用户重新输入密码。
- 管理员重置密码、禁用用户或修改角色后，目标用户旧页面的下一次请求应回到登录态。

## 回归重点

- 用户管理关闭时，首页、列表、详情、播放页不出现登录跳转。
- 用户管理开启后，刷新页面仍能通过 cookie 恢复登录态。
- 普通用户不能看到存储源、扫描、元数据、资源治理等管理入口。
- 管理员配置 allow/deny 资源库后，列表和直连播放都不能越权。
- 管理员重置密码或禁用用户后，该用户旧页面下一次请求应进入未登录态。
