# 天翼云盘 PC 扫码登录实验接口

本文档仅用于后端/前端临时联调。该功能还不是稳定合同，不会出现在 `GET /api/v1/storage/capabilities` 的正式能力里，也不要放进普通新增存储入口。

## 目标

当前正式天翼托管登录使用 OpenList `189CloudTV`。部分老账号在 TV 扫码链路里会反复返回二维码，无法完成挂载；同一账号直接走 PC 扫码登录可能正常。因此新增一组实验接口，内部改用 OpenList `189CloudPC` 的 `login_type=qrcode`。

## 接口

### `POST /api/v1/storage/managed/tianyicloud/pc-qr/start`

创建一个新的实验天翼来源，并返回 PC 扫码二维码。

请求：

```json
{
  "name": "天翼云盘 PC 扫码测试",
  "cloud_type": "personal",
  "root_folder_id": ""
}
```

响应关键字段：

```json
{
  "data": {
    "experimental": true,
    "login_mode": "pc_qr",
    "qr_started": true,
    "auth_state": "qr_pending",
    "qr_code_data_url": "data:image/jpeg;base64,...",
    "qr_content": "二维码原始内容",
    "source": {}
  }
}
```

### `POST /api/v1/storage/managed/tianyicloud/pc-qr/poll`

轮询扫码状态。

请求：

```json
{
  "source_id": 123
}
```

未完成：

```json
{
  "data": {
    "experimental": true,
    "login_mode": "pc_qr",
    "authenticated": false,
    "auth_state": "qr_pending",
    "pending_reason": "waiting_for_scan",
    "qr_code_data_url": "data:image/jpeg;base64,...",
    "source": {}
  }
}
```

已扫码、等待手机确认时，`pending_reason` 可能是 `waiting_for_confirm`。

二维码过期：

```json
{
  "data": {
    "experimental": true,
    "login_mode": "pc_qr",
    "authenticated": false,
    "auth_state": "qr_expired",
    "pending_reason": "qr_expired",
    "source": {}
  }
}
```

成功：

```json
{
  "data": {
    "experimental": true,
    "login_mode": "pc_qr",
    "authenticated": true,
    "auth_state": "ready",
    "source": {}
  }
}
```

### `POST /api/v1/storage/managed/tianyicloud/pc-qr/restart`

为已有天翼来源重新生成 PC 扫码二维码。可用于二维码过期，或把已有 TV 扫码来源临时切换到 PC 扫码实验链路。

请求：

```json
{
  "source_id": 123
}
```

响应字段和 `pc-qr/start` 基本一致，会额外返回：

```json
{
  "replaced_openlist_storage_id": 88,
  "old_openlist_storage_deleted": true
}
```

## 前端临时规则

- 只能在测试入口里调用，不要根据 `storage/capabilities` 自动展示。
- 只展示 `qr_code_data_url`，不要展示 OpenList 地址、OpenList storage id、内部挂载路径。
- `auth_state=ready` 前不要允许扫描、浏览、播放。
- `auth_state=qr_expired` 后调用 `pc-qr/restart`，不要继续轮询旧二维码。
- 如果返回 4xx/5xx，直接展示后端 `msg`，并保留 source id 方便排查。

## 后端实现边界

- 当前实现复用 OpenList `189CloudPC`，不自行保存天翼账号密码。
- 成功后 OpenList storage 内部会保存 `access_token` / `refresh_token`，CyberStream 对前端隐藏这些字段。
- 这个实验入口不会改变正式 `tianyicloud` 的 `qr_login=true` 语义；正式入口仍是 `/storage/managed/tianyicloud/qr/*`，对应 `189CloudTV`。
