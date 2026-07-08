# Frontend Managed GuangYaPan Integration

本文档是前端/安卓接入托管光鸭云盘的最小联调契约。完整类型以 OpenAPI 为准：

- `GET /api/v1/openapi.json`
- `GET /api/v1/openapi/modules/storage-system.json`
- `GET /api/v1/docs/frontend-managed-guangyapan`

## 目标

用户不需要填写 AList 地址、账号、密码、token 或驱动参数。前端只展示“光鸭云盘”入口，让用户输入手机号和短信验证码。CyberStream 后端负责管理 localhost AList，并在播放时解析 AList 的 302 到最终云盘直链。

前端不要暴露、拼接或保存 AList 地址。AList 只运行在后端本机 `127.0.0.1:5244`。

## 能力发现

页面初始化时可调用：

```http
GET /api/v1/storage/provider-types
GET /api/v1/storage/capabilities
```

当返回项包含：

```json
{
  "type": "guangyapan",
  "display_name": "GuangYaPan",
  "capabilities": {
    "managed": true,
    "sms_login": true,
    "redirect_stream": true
  }
}
```

前端可以展示“光鸭云盘”托管登录入口。该入口应独立于普通 AList/OpenList 表单。

## 状态机

托管光鸭来源有三个前端需要关心的状态：

- `sms_pending`：已发送验证码，等待用户提交短信验证码。不要展示浏览、扫描、绑定资源库、播放入口。
- `ready`：短信验证完成，可以按普通存储源浏览、绑定资源库、扫描和播放。
- `auth_expired`：已登录过，但上游光鸭凭证失效。不要展示浏览、扫描、刷新、播放入口，应提示用户对原挂载点重新授权。

以 `source.config.auth_state` 和 `source.actions` 为准。`sms_pending` 时后端会返回：

```json
{
  "config": {
    "auth_state": "sms_pending"
  },
  "actions": {
    "can_preview": false,
    "can_scan": false,
    "can_refresh": false,
    "can_stream": false
  }
}
```

`ready` 后这些 action 会按能力恢复为可用。

如果后端在运行时检测到光鸭登录态过期，会返回：

```json
{
  "auth_state": "auth_expired",
  "requires_reauthorization": true,
  "health": {
    "status": "offline",
    "reason": "auth_expired",
    "message": "GuangYaPan authorization expired; please reauthorize",
    "action": "reauthorize",
    "reauthorize": {
      "method": "POST",
      "endpoint": "/api/v1/storage/managed/guangyapan/sms/restart"
    }
  },
  "actions": {
    "can_preview": false,
    "can_scan": false,
    "can_refresh": false,
    "can_stream": false,
    "can_reauthorize": true,
    "reauthorize": {
      "method": "POST",
      "endpoint": "/api/v1/storage/managed/guangyapan/sms/restart",
      "required_fields": ["source_id"],
      "body": {
        "source_id": 3
      }
    }
  }
}
```

前端可以通过以下任一信号判断需要提示重新授权：

- `source.requires_reauthorization === true`
- `source.auth_state === "auth_expired"` 或 `source.config.auth_state === "auth_expired"`
- `source.health.reason === "auth_expired"`
- 浏览/刷新等操作返回 `code=40062`

列表页如需一次性拿到实时过期状态，可以调用：

```http
GET /api/v1/storage/sources?include_health=true
```

单个挂载点详情也支持：

```http
GET /api/v1/storage/sources/{id}?include_health=true
```

## 发送短信验证码

```http
POST /api/v1/storage/managed/guangyapan/sms/start
Content-Type: application/json
```

请求体：

```json
{
  "name": "光鸭云盘",
  "phone_number": "+861380001234",
  "root_path": ""
}
```

字段说明：

- `phone_number` 必填，建议使用 `+86` 格式。
- `name` 可选，未传默认 `GuangYaPan`。
- `root_path` 可选，表示光鸭云盘内的根路径；空字符串表示云盘根目录。
- `captcha_token` 可选，只有光鸭账号接口要求图形/风控验证码时才传。

成功响应：

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "verification_sent": true,
    "auth_state": "sms_pending",
    "source": {
      "id": 3,
      "type": "guangyapan",
      "display_name": "GuangYaPan",
      "config": {
        "auth_state": "sms_pending",
        "phone_number_masked": "+********1234",
        "cloud_root_path": "/"
      },
      "actions": {
        "can_preview": false,
        "can_scan": false,
        "can_refresh": false,
        "can_stream": false
      }
    }
  }
}
```

前端只需要保存 `data.source.id`，用于下一步提交验证码。`alist_storage_id`、`mount_path` 这类内部字段不会出现在普通 `StorageSource.config` 响应里，前端也不应通过其他方式读取或依赖。

## 重新登录已有来源

如果光鸭登录态失效，不要新建存储源。对原 `source.id` 重新发送短信：

```http
POST /api/v1/storage/managed/guangyapan/sms/restart
Content-Type: application/json
```

```json
{
  "source_id": 3
}
```

- `source_id` / `id` 必填，必须是已有 `guangyapan` 来源。
- 不要提交 `phone_number`。后端会读取该 source 原绑定的光鸭手机号发送验证码，避免误授权到其他账号。
- `root_path` / `cloud_root_path` 可选；不传则沿用当前 `source.config.cloud_root_path`。

成功后仍返回同一个 `source.id`，`auth_state=sms_pending`，并返回 `phone_number_masked` 供展示；前端继续调用 `sms/verify` 提交验证码。资源索引和媒体库绑定不会被重建。

## 校验短信验证码

```http
POST /api/v1/storage/managed/guangyapan/sms/verify
Content-Type: application/json
```

请求体：

```json
{
  "source_id": 3,
  "verify_code": "123456"
}
```

成功响应：

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "verified": true,
    "auth_state": "ready",
    "source": {
      "id": 3,
      "type": "guangyapan",
      "config": {
        "auth_state": "ready",
        "phone_number_masked": "+********1234",
        "cloud_root_path": "/"
      },
      "actions": {
        "can_preview": true,
        "can_scan": true,
        "can_refresh": true,
        "can_stream": true
      }
    }
  }
}
```

验证码成功后，前端重新拉取：

```http
GET /api/v1/storage/sources
```

然后按现有存储源流程浏览目录、绑定资源库或触发扫描。

## 后续浏览、绑定、扫描

托管光鸭 `ready` 后使用现有接口：

```http
GET /api/v1/storage/sources/{id}/browse?path=&dirs_only=true
POST /api/v1/storage/sources/{id}/refresh
POST /api/v1/storage/sources/{id}/scan
```

资源库绑定仍使用现有资源库接口。前端不要调用通用：

```http
POST /api/v1/storage/sources
```

手工创建 `type=guangyapan`。托管光鸭必须从短信接口创建，否则后端没有对应的 AList 内部挂载。

## 播放链路

前端和安卓播放逻辑不需要特殊处理。继续使用资源详情中的播放 URL 或：

```http
GET /api/v1/resources/{id}/stream
```

后端内部流程：

1. CyberStream 找到 `guangyapan` 存储源。
2. 后端请求 localhost AList `/d/...`。
3. AList 返回光鸭云盘最终直链 `Location`。
4. CyberStream 把这个最终直链作为 302 返回给前端。

前端看到的只会是 CyberStream 播放接口和最终云盘直链，不会拿到 localhost AList 地址。

同样，`GET /api/v1/storage/sources/{id}/health` 对托管光鸭只返回 CyberStream 视角的健康状态，不返回 `base_url`、AList 内部挂载根或 AList 运行时元数据。

## 删除来源

删除仍走现有接口：

```http
DELETE /api/v1/storage/sources/{id}
```

删除托管光鸭来源时，后端会先删除 localhost AList 内部挂载，再删除 CyberStream 本地数据。如果 AList 挂载已经不存在，后端继续清理本地数据；如果 AList 删除失败，接口返回 `50262`，本地来源和资源数据保留，前端应提示用户检查本机 AList 后重试。

## 错误处理

| code | HTTP | 场景 | 前端建议 |
| --- | --- | --- | --- |
| `40001` | 400 | 首次授权缺少 `phone_number`，或缺少 `source_id` / `verify_code` | 表单提示必填 |
| `40036` | 400 | `source_id` 不是整数 | 前端参数 bug，修正调用 |
| `40060` | 400 | 后端未启用托管 AList 或缺少 AList 管理凭据 | 提示服务端未配置，交给后端处理 |
| `40061` | 400 | 来源不是托管光鸭、状态不正确或内部挂载缺失 | 重新拉取来源列表，必要时删除后重试 |
| `40062` | 400 | 光鸭登录态已过期 | 对原 `source.id` 调用 `sms/restart`，提示用户重新短信授权 |
| `40402` | 404 | `source_id` 不存在 | 重新拉取来源列表 |
| `50260` | 502 | localhost AList 或光鸭账号接口失败，包括短信发送/验证码校验被上游拒绝 | 显示后端返回的 `msg`，允许重试 |
| `50016` | 500 | 发送短信流程非预期异常 | 提示稍后重试并上报 |
| `50017` | 500 | 校验短信流程非预期异常 | 提示稍后重试并上报 |

不要为了适配错误返回去猜 AList 内部字段。前端只消费 CyberStream 标准响应：

```json
{
  "code": 40001,
  "msg": "Missing required field: source_id",
  "trace_id": "1779888583",
  "data": null
}
```

## 前端接入清单

- 光鸭首次挂载走 `storage/managed/guangyapan/sms/start`，已有来源重新登录走 `sms/restart`，验证码提交走 `sms/verify`；不要走普通 AList 表单。
- 首次授权 UI 要求手机号；重新授权只传原 `source_id`，验证码页展示后端返回的 `phone_number_masked`。
- 只保存 `source.id`、`source.config.auth_state`、`source.actions` 和脱敏手机号展示字段。
- `auth_state !== "ready"` 时禁用浏览、扫描、绑定和播放。
- 播放逻辑保持现有 CyberStream 资源播放入口，不直接访问 AList。
- OpenAPI 类型生成使用 `/api/v1/openapi.json` 或 `/api/v1/openapi/modules/storage-system.json`。
