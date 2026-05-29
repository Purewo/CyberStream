# Frontend Managed Aliyundrive Integration

本接口用于前端接入 CyberStream 托管的阿里云盘。前端只调用 CyberStream 后端，不直接接触 OpenList 地址、OpenList token、阿里 refresh token 或内部挂载路径。

- 文档入口：`GET /api/v1/docs/frontend-managed-aliyundrive`
- OpenAPI：`GET /api/v1/openapi.json`
- 公网基地址示例：`https://cyberstream.ma1.gameuniverse.top`

## 1. 能力发现

前端先读取：

```http
GET /api/v1/storage/provider-types
GET /api/v1/storage/capabilities
```

当返回项包含：

```json
{
  "type": "aliyundrive",
  "display_name": "Aliyundrive",
  "capabilities": {
    "managed": true,
    "qr_login": true,
    "preview": true,
    "scan": true,
    "refresh": true,
    "stream": true,
    "redirect_stream": true
  }
}
```

即可展示“阿里云盘扫码登录”。不要用普通 `/storage/sources` 表单手工创建 `type=aliyundrive`，否则后端没有对应的扫码会话。

## 2. 启动扫码

```http
POST /api/v1/storage/managed/aliyundrive/qr/start
Content-Type: application/json
```

请求体：

```json
{
  "name": "阿里云盘"
}
```

字段说明：

- `name` / `source_name`：可选，存储源显示名，默认 `Aliyundrive`
- `root_folder_id`：可选，OpenList `AliyundriveOpen` 技术根目录 ID，默认 `root`
- `drive_type`：可选，`default`、`resource` 或 `backup`，默认 `resource`
- `alipan_type`：可选，`default` 或 `alipanTV`，默认 `default`

首轮联调只传 `name`。`root_folder_id`、`drive_type` 和 `alipan_type` 属于高级项，普通用户不需要看到。

成功响应：

```json
{
  "code": 200,
  "data": {
    "qr_started": true,
    "auth_state": "qr_pending",
    "pending_reason": "waiting_for_scan",
    "qr_status": "WaitLogin",
    "qr_code_url": "https://openapi.alipan.com/oauth/qrcode/...",
    "qr_code_data_url": "https://openapi.alipan.com/oauth/qrcode/...",
    "qr_content": "https://openapi.alipan.com/oauth/qrcode/...",
    "source": {
      "id": 12,
      "name": "阿里云盘",
      "type": "aliyundrive",
      "config": {
        "auth_state": "qr_pending",
        "cloud_root_path": "/",
        "root_folder_id": "root",
        "drive_type": "resource",
        "alipan_type": "default"
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

前端优先把 `qr_code_url` 或 `qr_code_data_url` 作为图片地址展示。阿里云盘返回的是可直接用于 `<img>` 的 URL，不一定是 `data:image/...`。

响应不会返回以下内部字段：

- OpenList 地址
- OpenList token
- 阿里云盘 refresh token / access token
- 内部 OpenList storage id
- 内部 OpenList mount path
- 阿里云盘二维码 sid

## 2.1 重新登录已有来源

如果阿里云盘登录态失效，不要新建存储源。对原 `source.id` 重新发起扫码：

```http
POST /api/v1/storage/managed/aliyundrive/qr/restart
Content-Type: application/json
```

```json
{
  "source_id": 12
}
```

- `source_id` / `id` 必填，必须是已有 `aliyundrive` 来源。
- `root_folder_id`、`drive_type`、`alipan_type` 可选；不传则沿用当前 source 配置。

成功后仍返回同一个 `source.id`，`auth_state=qr_pending`，前端继续调用 `qr/poll`。阿里云盘的新 OpenList 挂载要等扫码成功后才创建，因此旧挂载会先保留，扫码成功创建新挂载后后端再清理旧挂载。资源索引和媒体库绑定不会被重建。

## 3. 轮询扫码状态

```http
POST /api/v1/storage/managed/aliyundrive/qr/poll
Content-Type: application/json
```

请求体：

```json
{
  "source_id": 12
}
```

`id` 可作为 `source_id` 的兼容别名。

### 3.1 等待扫码

用户还没有扫码：

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_pending",
    "pending_reason": "waiting_for_scan",
    "qr_status": "WaitLogin",
    "source": {
      "id": 12,
      "type": "aliyundrive",
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

前端继续展示“等待扫码”，不要把它当失败。

### 3.2 已扫码，等待手机确认

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_pending",
    "pending_reason": "waiting_for_confirm",
    "qr_status": "ScanSuccess",
    "source": { "id": 12, "type": "aliyundrive" }
  }
}
```

前端继续轮询，文案可改为“请在阿里云盘 App 中确认登录”。

### 3.3 二维码过期或取消

二维码过期：

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_expired",
    "pending_reason": "qr_expired",
    "qr_status": "QRCodeExpired",
    "source": { "id": 12, "type": "aliyundrive" }
  }
}
```

用户取消：

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_canceled",
    "pending_reason": "qr_canceled",
    "source": { "id": 12, "type": "aliyundrive" }
  }
}
```

前端应停止当前轮询，提示重新发起扫码。已有来源重新扫码走 `qr/restart`，首次挂载才走 `qr/start`。

### 3.4 登录完成

用户确认后，后端会换取 token，并创建 localhost OpenList `AliyundriveOpen` 挂载：

```json
{
  "code": 200,
  "data": {
    "authenticated": true,
    "auth_state": "ready",
    "qr_status": "LoginSuccess",
    "source": {
      "id": 12,
      "type": "aliyundrive",
      "config": {
        "auth_state": "ready",
        "cloud_root_path": "/",
        "root_folder_id": "root",
        "drive_type": "resource",
        "alipan_type": "default"
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

前端收到 `authenticated=true` 且 `auth_state=ready` 后，更新本地来源状态并停止轮询。

## 4. 预览、扫描和播放

阿里云盘登录完成前，`source.actions` 全部为 `false`，前端不要开放目录预览、资源库绑定、扫描或播放。

登录完成后使用现有通用接口：

```http
GET /api/v1/storage/sources/{source_id}/browse?path=/&dirs_only=true
POST /api/v1/storage/sources/{source_id}/scan
```

播放仍走 CyberStream 播放 API。CyberStream 会解析本机 OpenList `/d` 的 302，前端只使用后端返回的播放地址。

## 5. 后端授权模式

后端支持以下阿里云盘授权模式：

- `auto`：默认值。有 `CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_ID` 和 `CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_SECRET` 时使用自有官方 OpenAPI；否则使用 OpenList 官方公共工具接口。
- `official`：强制使用 CyberStream 自己配置的阿里 OpenAPI 应用凭据。
- `openlist`：强制使用 OpenList 官方公共工具接口，适合当前托管 OpenList 挂载链路。
- `alistgo`：强制使用 AList 官方公共工具接口，仅保留兼容；该模式拿到的 token 可能无法被 OpenList v4 的 renew API 刷新，不建议用于托管 OpenList 挂载。

这些配置只在后端使用，不返回给前端。

## 6. 错误

- `40001`：缺少必填字段，通常是 `source_id`
- `40036`：字段类型或枚举非法，例如 `drive_type`
- `40060`：托管 OpenList 未启用、未配置，或 `official` 模式缺少阿里 OpenAPI 凭据
- `40061`：来源类型不匹配、二维码会话缺失，或来源尚未 ready
- `50260`：后端访问 localhost OpenList、阿里 OpenAPI 或公共工具接口失败

## 7. 前端规则

- 使用 `/api/v1/storage/managed/aliyundrive/qr/start`、`/api/v1/storage/managed/aliyundrive/qr/restart` 和 `/api/v1/storage/managed/aliyundrive/qr/poll`
- 轮询间隔建议 2 到 3 秒，登录完成、过期、取消或用户关闭弹窗后停止
- 不要调用 OpenList，不要解析 OpenList HTML，不要保存隐藏字段
- `source.actions` 是是否开放预览、扫描、播放和刷新的唯一依据
