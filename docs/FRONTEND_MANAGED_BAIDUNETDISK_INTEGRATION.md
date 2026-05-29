# Frontend Managed Baidu Netdisk Integration

本接口用于前端接入 CyberStream 托管的百度网盘。前端只调用 CyberStream 后端，不直接接触 OpenList 地址、OpenList token、百度 access token / refresh token 或内部挂载路径。

- 文档入口：`GET /api/v1/docs/frontend-managed-baidunetdisk`
- OpenAPI：`GET /api/v1/openapi.json`
- 公网基地址示例：`https://cyberstream.ma1.gameuniverse.top`

## 1. 能力发现

```http
GET /api/v1/storage/provider-types
GET /api/v1/storage/capabilities
```

当返回项包含：

```json
{
  "type": "baidunetdisk",
  "display_name": "Baidu Netdisk",
  "capabilities": {
    "managed": true,
    "oauth_login": true,
    "preview": true,
    "scan": true,
    "refresh": true,
    "stream": true,
    "redirect_stream": true
  }
}
```

即可展示“百度网盘授权登录”。百度网盘这条不是扫码登录，而是 OAuth 授权跳转。

## 2. 启动授权

```http
POST /api/v1/storage/managed/baidunetdisk/oauth/start
Content-Type: application/json
```

请求体：

```json
{
  "name": "百度网盘"
}
```

字段说明：

- `name` / `source_name`：可选，存储源显示名，默认 `Baidu Netdisk`
- `root_path` / `cloud_root_path` / `root_folder_path`：可选，百度网盘侧根路径，默认 `/`
- `download_api`：可选，默认 `official`。普通用户不要暴露。

成功响应：

```json
{
  "code": 200,
  "data": {
    "oauth_started": true,
    "auth_state": "oauth_pending",
    "pending_reason": "waiting_for_authorization",
    "authorization_url": "https://openapi.baidu.com/oauth/2.0/authorize?...",
    "callback_mode": "redirect",
    "requires_authorization_code": false,
    "callback_url": "https://cyberstream.ma1.gameuniverse.top/api/v1/storage/managed/baidunetdisk/oauth/callback",
    "authorization_code_submit_url": null,
    "source": {
      "id": 12,
      "type": "baidunetdisk",
      "config": {
        "auth_state": "oauth_pending",
        "cloud_root_path": "/",
        "root_folder_path": "/",
        "download_api": "official"
      },
      "actions": {
        "can_preview": false,
        "can_scan": false,
        "can_stream": false,
        "can_refresh": false
      }
    }
  }
}
```

前端打开 `authorization_url`。Web 端可以新窗口打开；安卓端可以使用系统浏览器或 WebView。

- `callback_mode=redirect`：百度授权完成后会跳回 `callback_url`，前端继续轮询 poll。
- `callback_mode=oob`：百度授权完成后页面会显示授权码。前端需要让用户粘贴授权码，然后调用 `oauth/complete`。这是未配置自有百度开放平台应用、使用 AList 公开默认 OAuth 应用时的默认模式；不要继续只轮询等待 callback。

响应不会返回以下内部字段：

- OpenList 地址
- OpenList token
- 百度 access token / refresh token
- 内部 OpenList storage id
- 内部 OpenList mount path
- OAuth state

## 2.1 重新授权已有来源

如果百度网盘授权失效，不要新建存储源。对原 `source.id` 重新发起 OAuth：

```http
POST /api/v1/storage/managed/baidunetdisk/oauth/restart
Content-Type: application/json
```

```json
{
  "source_id": 12
}
```

- `source_id` / `id` 必填，必须是已有 `baidunetdisk` 来源。
- `root_path` / `cloud_root_path` / `root_folder_path`、`download_api` 可选；不传则沿用当前 source 配置。

成功后仍返回同一个 `source.id`，`auth_state=oauth_pending`，前端打开新的 `authorization_url`，再按原有 `oauth/poll` 或 `oauth/complete` 流程收口。百度的新 OpenList 挂载要等授权完成后才创建，因此旧挂载会先保留，授权成功创建新挂载后后端再清理旧挂载。资源索引和媒体库绑定不会被重建。

## 3. 授权完成

### 3.1 redirect 模式：轮询 callback 结果

当 `oauth/start` 返回 `callback_mode=redirect` 时，百度授权完成后会跳转到 `callback_url`，后端在 callback 内完成 token exchange 并创建 localhost OpenList `BaiduNetdisk` 挂载。前端不需要直接调用 callback，只需要继续轮询：

```http
POST /api/v1/storage/managed/baidunetdisk/oauth/poll
Content-Type: application/json
```

请求体：

```json
{
  "source_id": 12
}
```

#### 等待授权

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "oauth_pending",
    "pending_reason": "waiting_for_authorization",
    "source": {
      "id": 12,
      "type": "baidunetdisk",
      "actions": {
        "can_preview": false,
        "can_scan": false,
        "can_stream": false,
        "can_refresh": false
      }
    }
  }
}
```

前端继续展示“等待授权完成”，不要当失败。

#### 授权失败

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "oauth_failed",
    "pending_reason": "oauth_failed",
    "error_message": "access_denied",
    "source": { "id": 12, "type": "baidunetdisk" }
  }
}
```

前端停止当前轮询，提示用户重新授权。已有来源重新授权走 `oauth/restart`，首次挂载才走 `oauth/start`。

#### 授权完成

```json
{
  "code": 200,
  "data": {
    "authenticated": true,
    "auth_state": "ready",
    "source": {
      "id": 12,
      "type": "baidunetdisk",
      "config": {
        "auth_state": "ready",
        "cloud_root_path": "/",
        "root_folder_path": "/",
        "download_api": "official"
      },
      "actions": {
        "can_preview": true,
        "can_scan": true,
        "can_stream": true,
        "can_refresh": true
      }
    }
  }
}
```

收到 `authenticated=true` 且 `auth_state=ready` 后，更新本地来源状态并停止轮询。

### 3.2 oob 模式：提交授权码

当 `oauth/start` 返回：

```json
{
  "callback_mode": "oob",
  "requires_authorization_code": true,
  "authorization_code_submit_url": "https://cyberstream.ma1.gameuniverse.top/api/v1/storage/managed/baidunetdisk/oauth/complete"
}
```

前端打开 `authorization_url` 后，百度页面会展示授权码。用户把授权码填回前端后，前端调用：

```http
POST /api/v1/storage/managed/baidunetdisk/oauth/complete
Content-Type: application/json
```

请求体：

```json
{
  "source_id": 12,
  "authorization_code": "百度页面显示的授权码"
}
```

成功响应与 poll ready 相同：

```json
{
  "code": 200,
  "data": {
    "authenticated": true,
    "auth_state": "ready",
    "source": { "id": 12, "type": "baidunetdisk" }
  }
}
```

收到 ready 后停止轮询。授权码只提交给 CyberStream 后端，前端不要保存。

## 4. 预览、扫描和播放

授权完成前，`source.actions` 全部为 `false`，前端不要开放目录预览、资源库绑定、扫描或播放。

授权完成后使用现有通用接口：

```http
GET /api/v1/storage/sources/{source_id}/browse?path=/&dirs_only=true
POST /api/v1/storage/sources/{source_id}/scan
```

百度网盘直链需要特定 User-Agent，普通 Web 播放器无法稳定处理 302 后的上游 UA。后端会在资源 `playback` 矩阵中直接禁用网页播放：

```json
{
  "storage_type": "baidunetdisk",
  "web_player": {
    "supported": false,
    "url": null,
    "reason": "baidunetdisk_requires_pc_client",
    "message": "Baidu Netdisk web playback is not supported. Please use the PC client.",
    "recommended_action": "download_pc_client"
  },
  "external_player": {
    "supported": true,
    "requires_local_backend": true,
    "requires_user_agent_rewrite": true,
    "reason": "baidunetdisk_requires_user_agent_rewrite"
  }
}
```

前端 Web 端遇到 `storage_type=baidunetdisk` 且 `web_player.supported=false` 时，不要进入网页播放器，也不要直接使用 `stream_url`，直接提示用户下载/使用 PC 客户端。PC 模式由 PC 本地后端负责对上游百度直链改写 UA；本 Web 前端只需要提示和交接，不需要实现 UA 改写。

## 5. 后端配置

百度 OAuth 默认使用 AList 公开默认应用凭据，便于托管挂载开箱即用；生产环境如需使用自有百度开放平台应用，可以覆盖以下配置：

```env
CYBER_MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_ID=...
CYBER_MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_SECRET=...
CYBER_BACKEND_PUBLIC_BASE_URL=https://cyberstream.ma1.gameuniverse.top
```

如果使用自有百度应用，百度开放平台里的回调地址必须配置为：

```text
https://cyberstream.ma1.gameuniverse.top/api/v1/storage/managed/baidunetdisk/oauth/callback
```

## 6. 错误

- `40001`：缺少必填字段，通常是 `source_id` 或 `authorization_code`
- `40036`：字段类型或枚举非法，例如 `download_api`
- `40060`：托管 OpenList 未启用、未配置，或百度 OAuth 凭据缺失
- `40061`：来源类型不匹配、OAuth state 缺失，或来源尚未 ready
- `50260`：后端访问 localhost OpenList 或百度 OAuth 接口失败

## 7. 前端规则

- 使用 `/api/v1/storage/managed/baidunetdisk/oauth/start`、`/api/v1/storage/managed/baidunetdisk/oauth/poll`，以及 oob 模式下的 `/api/v1/storage/managed/baidunetdisk/oauth/complete`
- 不要调用 OpenList，不要保存隐藏字段
- `source.actions` 是是否开放预览、扫描、播放和刷新的唯一依据
- `callback_mode=redirect` 时打开 `authorization_url` 后继续 poll；`callback_mode=oob` 时必须提交授权码到 `oauth/complete`
- 不要试图从百度回调 URL 里解析 token
