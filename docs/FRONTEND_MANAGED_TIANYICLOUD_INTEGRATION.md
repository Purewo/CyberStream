# 托管天翼云盘扫码登录前端接入说明

本文档是前端和安卓联调用的稳定合同。天翼云盘由 CyberStream 后端托管 localhost OpenList 的 `189CloudTV` 驱动完成扫码登录；前端不要直接配置 OpenList，也不会拿到 OpenList 地址、OpenList token 或内部挂载路径。

## 文档入口

- OpenAPI：`GET /api/v1/openapi.json`
- 本文档：`GET /api/v1/docs/frontend-managed-tianyicloud`
- 存储能力：`GET /api/v1/storage/capabilities`

## 状态机

```text
qr_pending -> ready
```

- `qr_pending`：二维码已生成，等待用户用天翼云盘 App 扫码确认。
- `ready`：扫码完成，后端已拿到 OpenList 侧 token，来源可预览、扫描、刷新和播放。

`qr_pending` 时响应中的 `source.actions.can_preview/can_scan/can_refresh/can_stream` 均为 `false`。前端不要展示浏览、绑定资源库、扫描或播放入口。

## 1. 能力发现

```http
GET /api/v1/storage/capabilities
```

前端可以在 `items[]` 中找到：

```json
{
  "type": "tianyicloud",
  "display_name": "TianYiCloud",
  "managed": true,
  "qr_login": true,
  "preview": true,
  "scan": true,
  "refresh": true,
  "stream": true,
  "redirect_stream": true
}
```

含义：这是托管来源，登录入口应该走二维码接口，不要展示普通 OpenList/AList 表单。

## 2. 发起扫码

```http
POST /api/v1/storage/managed/tianyicloud/qr/start
Content-Type: application/json
```

请求体：

```json
{
  "name": "天翼云盘"
}
```

字段：

- `name` / `source_name`：可选，存储源显示名，默认 `TianYiCloud`。
- `cloud_type`：可选，默认 `personal`。当前前端先不要暴露给普通用户；后端只接受 `personal` 或 `family`。
- `root_folder_id`：可选，OpenList `189CloudTV` 的技术根目录 ID。当前前端不要让普通用户填写，默认即可。

成功响应：

```json
{
  "code": 200,
  "data": {
    "qr_started": true,
    "auth_state": "qr_pending",
    "qr_code_data_url": "data:image/jpeg;base64,...",
    "qr_content": "opaque-login-content",
    "source": {
      "id": 12,
      "name": "天翼云盘",
      "type": "tianyicloud",
      "config": {
        "auth_state": "qr_pending",
        "cloud_type": "personal",
        "cloud_root_path": "/",
        "root_folder_id": "-11"
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

前端处理：

- 直接渲染 `qr_code_data_url` 为二维码图片。
- 保存 `source.id`，后续轮询使用。
- 不要依赖 `qr_content` 做业务判断；它只是给需要原始扫码内容的客户端备用。
- 响应中的 `source.config` 不包含 `openlist_storage_id` 和 `mount_path`，这是预期的隐私保护。

## 2.1 重新登录已有来源

如果天翼云盘登录态失效，不要新建存储源。对原 `source.id` 重新生成二维码：

```http
POST /api/v1/storage/managed/tianyicloud/qr/restart
Content-Type: application/json
```

```json
{
  "source_id": 12
}
```

- `source_id` / `id` 必填，必须是已有 `tianyicloud` 来源。
- `cloud_type`、`root_folder_id` 可选；不传则沿用当前 source 配置。

成功后仍返回同一个 `source.id`，`auth_state=qr_pending`，前端继续调用 `qr/poll`。资源索引和媒体库绑定不会被重建。

## 3. 轮询扫码结果

```http
POST /api/v1/storage/managed/tianyicloud/qr/poll
Content-Type: application/json
```

请求体：

```json
{
  "source_id": 12
}
```

仍未扫码或未确认：

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_pending",
    "pending_reason": "waiting_for_scan",
    "source": {
      "id": 12,
      "type": "tianyicloud",
      "config": {
        "auth_state": "qr_pending",
        "cloud_type": "personal",
        "cloud_root_path": "/"
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

扫码成功：

```json
{
  "code": 200,
  "data": {
    "authenticated": true,
    "auth_state": "ready",
    "source": {
      "id": 12,
      "type": "tianyicloud",
      "config": {
        "auth_state": "ready",
        "cloud_type": "personal",
        "cloud_root_path": "/"
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

轮询建议：

- 二维码展示后每 2 到 3 秒调用一次 `qr/poll`。
- `authenticated=false` 时留在扫码页。
- `authenticated=true` 时关闭扫码页，并用响应中的 `source` 更新本地存储源列表。
- 如果 `qr/poll` 返回新的 `qr_code_data_url`，说明 OpenList 侧重新生成了二维码，前端应替换当前二维码图片。
- 如果请求返回非 200 业务码，显示后端返回的 `message`，用户重新点击“添加天翼云盘”即可重新发起。

## 4. 纯预览

扫码完成后，纯目录预览仍使用通用接口：

```http
GET /api/v1/storage/sources/{source_id}/browse?path=&dirs_only=true
```

说明：

- 这是纯浏览，不会扫描、不刮削、不写入媒体库。
- `path` 是相对路径，根目录传空字符串或 `/`。
- 前端应以响应中的 `items[]` 构建目录选择器。

## 5. 绑定、扫描和播放

登录 `ready` 后，天翼来源与其他存储源一致：

- 绑定资源库：使用现有 Library Source 接口，保存 `source_id` 和选中的相对目录。
- 扫描：使用资源库扫描接口或指定存储源扫描接口。
- 播放：使用现有资源播放接口。

播放链路：

1. CyberStream 找到 `tianyicloud` 存储源。
2. 后端访问 localhost OpenList 的 `/d/...`。
3. OpenList `189CloudTV` 返回天翼云盘最终 302 直链。
4. CyberStream 把最终直链给前端，不暴露 localhost OpenList 地址。

## 6. 删除

```http
DELETE /api/v1/storage/sources/{source_id}
```

删除托管天翼来源时，后端会尽量同步删除 localhost OpenList 的内部挂载。即使内部删除失败，CyberStream 来源删除也不受影响，失败会进入后端日志。

## 7. 前端不要做的事

- 不要手工创建 `type=tianyicloud` 存储源。
- 不要要求用户填写 OpenList 地址、token、driver、挂载路径或 root folder id。
- 不要在 `qr_pending` 时允许浏览、扫描、绑定资源库或播放。
- 不要保存或展示任何内部 OpenList 字段；正常响应里也不会返回这些字段。

## 8. 错误码

- `40001`：缺少必填字段，例如 `source_id`。
- `40036`：字段类型错误，或 `cloud_type` 非法。
- `40060`：后端未启用或未配置托管 OpenList。
- `40061`：来源类型不匹配，或来源缺少内部 OpenList storage id。
- `50260`：后端调用 localhost OpenList 失败。
- `50018`：启动天翼扫码失败。
- `50019`：轮询天翼扫码失败。

## 9. 联调清单

- `GET /api/v1/storage/capabilities` 能看到 `tianyicloud.managed=true` 和 `qr_login=true`。
- `qr/start` 后展示 `qr_code_data_url`，并保存返回的 `source.id`。
- `qr_pending` 时所有 `actions` 都是 `false`。
- `qr/poll` 成功后 `auth_state=ready`，所有动作按能力恢复为 `true`。
- `source.config` 不出现 `openlist_storage_id` 和 `mount_path`。
- 健康检查响应不出现 localhost OpenList 地址、内部根路径或 OpenList 运行时元数据。
