# Frontend Managed 115 Cloud Integration

本接口用于前端接入 CyberStream 托管的 115 云盘。前端只调用 CyberStream 后端，不直接接触 OpenList 地址、OpenList token、115 cookie 或内部挂载路径。

- 文档入口：`GET /api/v1/docs/frontend-managed-115cloud`
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
  "type": "115cloud",
  "display_name": "115 Cloud",
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

即可展示“115 云盘扫码登录”。不要使用普通 `/storage/sources` 表单手工创建 `type=115cloud`，否则后端没有对应的本机 OpenList 托管挂载和二维码会话。

## 2. 启动扫码

```http
POST /api/v1/storage/managed/115cloud/qr/start
Content-Type: application/json
```

请求体：

```json
{
  "name": "115 云盘",
  "qrcode_source": "wechatmini"
}
```

字段说明：

- `name` / `source_name`：可选，存储源显示名，默认 `115 Cloud`
- `qrcode_source`：可选，默认 `wechatmini`。允许值：`web`、`android`、`ios`、`tv`、`alipaymini`、`wechatmini`、`qandroid`
- `root_folder_id`：可选，OpenList `115 Cloud` 技术根目录 ID，普通用户先不要暴露，默认 `0`

默认使用 `wechatmini` 是为了避免默认占用用户常用的 Web、Android 或 iOS 登录态。前端首轮联调不需要显式传该字段，只有排障或用户明确要求时再暴露高级选项。

成功响应：

```json
{
  "code": 200,
  "data": {
    "qr_started": true,
    "auth_state": "qr_pending",
    "qr_code_data_url": "data:image/png;base64,...",
    "qr_content": "https://115.com/scan/...",
    "source": {
      "id": 12,
      "name": "115 云盘",
      "type": "115cloud",
      "config": {
        "auth_state": "qr_pending",
        "cloud_root_path": "/",
        "root_folder_id": "0",
        "qrcode_source": "wechatmini"
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

前端显示 `qr_code_data_url`。`qr_content` 是二维码原始内容，可用于需要自行生成二维码的客户端。

响应不会返回以下内部字段：

- OpenList 地址
- OpenList token
- 115 cookie
- 内部 OpenList storage id
- 内部 OpenList mount path
- 115 二维码 uid/sign/time

## 2.1 重新登录已有来源

如果 115 登录态失效或二维码过期后需要重新扫码，不要新建存储源。对原 `source.id` 重启二维码：

```http
POST /api/v1/storage/managed/115cloud/qr/restart
Content-Type: application/json
```

```json
{
  "source_id": 12,
  "qrcode_source": "wechatmini"
}
```

- `source_id` / `id` 必填，必须是已有 `115cloud` 来源。
- `qrcode_source`、`root_folder_id` 可选；不传则沿用当前 source 配置。

成功后仍返回同一个 `source.id`，`auth_state=qr_pending`，前端继续调用 `qr/poll`。资源索引和媒体库绑定不会被重建。

## 3. 轮询扫码状态

```http
POST /api/v1/storage/managed/115cloud/qr/poll
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
    "qr_status": 0,
    "source": {
      "id": 12,
      "type": "115cloud",
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

用户已扫码但还没有在手机上确认：

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_pending",
    "pending_reason": "waiting_for_confirm",
    "qr_status": 1,
    "source": { "id": 12, "type": "115cloud" }
  }
}
```

前端继续轮询，文案可改为“请在 115 App 中确认登录”。

### 3.3 二维码过期或取消

二维码过期：

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_expired",
    "pending_reason": "qr_expired",
    "qr_status": -1,
    "source": { "id": 12, "type": "115cloud" }
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
    "qr_status": -2,
    "source": { "id": 12, "type": "115cloud" }
  }
}
```

前端应停止当前轮询，提示重新发起扫码。已有来源重新扫码走 `qr/restart`，首次挂载才走 `qr/start`。

### 3.4 登录完成

用户确认后，后端会让 localhost OpenList 完成 115 登录并持久化 cookie：

```json
{
  "code": 200,
  "data": {
    "authenticated": true,
    "auth_state": "ready",
    "source": {
      "id": 12,
      "type": "115cloud",
      "config": {
        "auth_state": "ready",
        "cloud_root_path": "/",
        "qrcode_source": "wechatmini"
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

115 登录完成前，`source.actions` 全部为 `false`，前端不要开放目录预览、资源库绑定、扫描或播放。

登录完成后使用现有通用接口：

```http
GET /api/v1/storage/sources/{source_id}/browse?path=/
POST /api/v1/storage/sources/{source_id}/scan
POST /api/v1/storage/sources/{source_id}/refresh
POST /api/v1/playback/resources/{resource_id}
```

播放链路仍由后端访问 localhost OpenList `/d/...` 并解析 302，返回最终可播放直链给客户端；安卓端不会拿到 OpenList 地址。

## 5. 删除

```http
DELETE /api/v1/storage/sources/{source_id}
```

删除托管 `115cloud` 来源时，后端会先删除 localhost OpenList 中对应的内部挂载，再删除 CyberStream 本地数据。如果 OpenList 挂载已经不存在，后端继续清理本地数据；如果 OpenList 删除失败，接口返回 `50262`，本地来源和资源数据保留，前端应提示用户检查本机 OpenList 后重试。

## 6. 前端注意事项

- 使用准确路径：`/api/v1/storage/managed/115cloud/qr/start`、`/api/v1/storage/managed/115cloud/qr/restart` 和 `/api/v1/storage/managed/115cloud/qr/poll`
- 不要猜 `/v1/...`、`/storage/managed/115/...`、`/storage/managed/115Cloud/...`
- `qr_pending` 是正常轮询状态，业务码仍为 `200`
- 只有 `auth_state=ready` 才能浏览、扫描、刷新和播放
- `qr_expired` / `qr_canceled` 不是程序错误，停止轮询并让用户重新扫码
- 不要在前端保存或展示任何 OpenList 内部配置；接口已经隐藏这些字段
