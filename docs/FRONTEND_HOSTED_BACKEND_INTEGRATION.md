# 前端代托管后端接入说明

本文档给前端内测分支使用。代托管版本面向只拿前端、不自行部署后端的用户；后端由我们统一维护，前端不能暴露修改服务器关键配置的入口。

## 当前联调地址

后端 API 基地址：

```text
https://cyberstream.gameuniverse.top:40162
```

文档接口地址：

```text
https://cyberstream.gameuniverse.top:40162/api/v1/docs
```

本文档在线地址：

```text
https://cyberstream.gameuniverse.top:40162/api/v1/docs/frontend-hosted-backend
```

OpenAPI 地址：

```text
https://cyberstream.gameuniverse.top:40162/api/v1/openapi.json
```

模块化 OpenAPI 地址：

```text
https://cyberstream.gameuniverse.top:40162/api/v1/openapi/modules
https://cyberstream.gameuniverse.top:40162/api/v1/openapi/modules/auth-users.json
https://cyberstream.gameuniverse.top:40162/api/v1/openapi/modules/catalog.json
https://cyberstream.gameuniverse.top:40162/api/v1/openapi/modules/playback.json
```

旧的自托管/当前公网试点后端仍是：

```text
https://cyberstream.gameuniverse.top:40160
```

前端做代托管内测时使用 `40162`，不要混用 `40160`。两套后端在同一域名不同端口上，前端本地调试必须始终带 `credentials: "include"`。

## 前端开发方式

请前端单独新建一个本地开发文件夹，例如：

```text
CyberStream-frontend-hosted-beta
```

把当前前端代码复制过去后在新文件夹开发。内测阶段不要提交 GitHub，不要把代托管配置硬编码进主线仓库。建议只通过本地 `.env.local` 指定：

```env
VITE_API_BASE_URL=https://cyberstream.gameuniverse.top:40162
```

如果项目已有 API base 配置项，直接复用现有配置项，不要新增第二套请求客户端。

## 启动探测

应用启动、刷新页面、注册成功、登录成功、退出后、任意接口返回 `401` 后，都请求：

```http
GET /api/v1/auth/me
```

请求必须携带 Cookie：

```ts
fetch(`${API_BASE}/api/v1/auth/me`, {
  credentials: "include",
});
```

当前代托管后端应返回：

```json
{
  "user_management_enabled": true,
  "hosted_managed_mode": true,
  "authenticated": false,
  "role": null,
  "auth_via": null,
  "user": null,
  "current_account": null,
  "account_role": null,
  "permissions": {
    "admin": false,
    "read_catalog": false,
    "manage_catalog": false,
    "manage_users": false,
    "manage_storage": false,
    "manage_account_users": false,
    "manage_server_config": false,
    "personal_history": false,
    "personal_favorites": false,
    "personal_vault": false,
    "personal_subtitle_settings": false
  }
}
```

登录后再以返回的 `AuthStatus` 为准。不要读取 Cookie 内容，不要在前端保存后端 token。

## PC / 外部播放器播放票据

PC WebView 登录后，如果要把播放交给 mpv 等独立进程，先调用：

```http
POST /api/v1/auth/playback-ticket
```

返回 `data.ticket`、`data.expires_at`、`data.ttl`。把 `ticket` 拼到外部播放器会直接请求的播放和字幕 URL 上；浏览器内播放仍然走 Cookie。

适用 URL：

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

票据默认 12 小时有效，绑定当前用户和 session_version，不绑定单个资源。非法或过期返回 HTTP `401`、业务码 `40130`，PC 端重新换票后重试。代托管后端会按 ticket 所属用户恢复 current_account，并继续做账号隔离和资源可见性校验。

## 注册、登录与退出

注册：

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "username": "<username>",
  "password": "<password>",
  "display_name": "<optional>"
}
```

注册成功后后端会直接写入登录 Cookie，并返回和 `/auth/me` 一致的 `AuthStatus`。新注册用户是 `users.role=user`，但会成为自己账号空间的 `account_role=owner`，因此可以管理自己账号下的片库、挂载和扫描。

登录：

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "username": "<username>",
  "password": "<password>"
}
```

退出：

```http
POST /api/v1/auth/logout
```

所有请求都必须带：

```ts
credentials: "include"
```

如果本地前端调用公网 HTTPS 后端时忘记 `credentials: "include"`，登录接口可能返回成功，但浏览器不会保存或回传 HttpOnly Cookie，后续接口会继续 `401`。

## 请求客户端建议

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

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      traceId: payload.trace_id,
      payload,
    });
  }
  return payload.data;
}
```

## UI 权限规则

前端不要按“是不是管理员”单独决定所有管理入口。代托管模式下管理员也不能改服务器配置。

建议规则：

- `authenticated === false`：显示登录页。
- `permissions.read_catalog === true`：允许进入影视目录、首页、详情、播放页。
- `permissions.manage_storage === true`：允许进入云盘挂载、重新登录、目录刷新、挂载点删除等账号内存储入口。
- `permissions.manage_catalog === true`：允许进入片库、扫描、审查工作台、影视元数据编辑和资源同步入口。
- `permissions.manage_users === true`：仅表示平台管理员用户管理入口，不是家庭子账号入口。
- `permissions.manage_account_users === true`：预留未来家庭子账号管理；当前固定为 false。
- `permissions.manage_server_config === false`：隐藏所有服务器配置和运维入口。

代托管版本必须隐藏：

- TMDB token 配置和 TMDB 代理配置
- 代理设置页面
- 图片预热、图片刷新、图片缓存清理、CDN purge/refresh
- Super CDN 或任何 CDN 控制面入口

可以保留：

- 影视首页、列表、筛选、详情、推荐
- 注册、登录、退出
- 账号内云盘挂载、扫码/短信/OAuth 登录、重新登录、删除挂载点
- 默认片库绑定、片库扫描、挂载点扫描、单片资源同步
- 审查工作台、影视元数据编辑、手工整理
- 播放、外部播放器、清晰度选择
- 用户观看历史、收藏、收藏保险库
- 在线字幕搜索、下载、绑定
- 用户资料、修改自己的密码

前端不要在普通业务接口上传 `account_id`。账号空间由后端根据 Cookie session 解析出的 `current_account` 决定；客户端传入的任意 `account_id` 都不能作为数据范围依据。

## 图片与 CDN

当前代托管试点不启用 CDN 图片分发。后端会把 `poster_asset_url/backdrop_asset_url` 配置为优先返回原始 `poster_url/backdrop_url`，`asset_urls.strategy=original_local`。

前端规则：

- 优先加载 `poster_asset_url/backdrop_asset_url`。
- 不要自行调用图片预热、刷新、清理或 CDN purge 接口。
- 不要把 Super CDN、图片 CDN、缓存刷新入口暴露给用户。
- 如果 `asset_urls.fallback_urls` 存在，可按顺序做图片加载失败回退。

## TMDB 托管状态

代托管后端的 TMDB token 和代理由平台统一维护，前端不要提供编辑入口。需要在元数据操作前确认服务状态时，只读调用：

```http
GET /api/v1/system/tmdb-config/check
```

判断规则：

- `ready=true`：至少一个平台 token 可用，可以继续。
- `status=partial_ok`：仍可继续，但平台 token 池存在失效项；普通用户不需要看到 token 明细。
- `ready=false`：阻止本次元数据操作并提示“平台元数据服务暂不可用”。
- `token_pool_size`、`token_valid_count`、`token_invalid_count` 只用于管理员诊断。
- `token_checks` 仅包含池内序号和检查结果，不包含 token 明文。

## 托管封禁错误

如果前端误调用托管封禁接口，后端返回：

```json
{
  "code": 40390,
  "msg": "Hosted managed mode blocks server configuration changes",
  "data": null
}
```

前端处理：

- 不弹“登录失效”
- 不重试
- 隐藏触发该请求的入口
- 可提示“当前为平台托管模式，该配置由服务端统一维护”

OpenAPI 顶层也有 `x-hosted-managed-mode`，列出同一批封禁接口。

## 401 与 403 处理

- `401`：登录态缺失或失效。清空前端内存登录态，重新请求 `/api/v1/auth/me`，确认未登录后显示登录页。
- `40310`：需要管理员权限。隐藏对应管理入口。
- `40320` / `40321` / `40322`：当前用户不可见该影片、资源或专辑。不要继续直连重试。
- `40390`：代托管模式封禁服务器配置或运维操作。隐藏入口，不要重试。

## 对接顺序

1. 新建本地前端工作目录，不提交 GitHub。
2. 设置 `VITE_API_BASE_URL=https://cyberstream.gameuniverse.top:40162`。
3. 所有请求统一带 `credentials: "include"`。
4. 启动时接 `GET /api/v1/auth/me`。
5. 接 `POST /api/v1/auth/register`、`POST /api/v1/auth/login` 和 `POST /api/v1/auth/logout`。
6. 用 `permissions.manage_storage` 接云盘挂载入口。
7. 用 `permissions.manage_catalog` 接扫描、审查和元数据入口。
8. 用 `permissions.manage_server_config=false` 隐藏服务器配置入口。
9. 用 `401/40390` 做全局错误处理。
10. 再接影视目录、播放、历史、收藏、字幕等普通用户功能。

## 快速验收

未登录探测：

```bash
curl -i https://cyberstream.gameuniverse.top:40162/api/v1/auth/me
```

健康检查：

```bash
curl -i https://cyberstream.gameuniverse.top:40162/api/v1/health
```

文档索引：

```bash
curl -i https://cyberstream.gameuniverse.top:40162/api/v1/docs
```

OpenAPI：

```bash
curl -i https://cyberstream.gameuniverse.top:40162/api/v1/openapi.json
```

浏览器本地开发验收：

- 登录后刷新页面仍然保持登录态。
- 影视列表不是空白，也不会因为一次 `401` 后无限重试。
- 注册后 `/auth/me` 返回 `current_account` 和 `account_role=owner`。
- 注册用户能看到账号内挂载和扫描入口，但看不到 TMDB、代理、CDN 配置入口。
- 平台管理员也看不到服务器配置入口，或入口禁用且不会发起请求。
- 如果误调用封禁接口，能识别 `code=40390`，不跳登录页。
