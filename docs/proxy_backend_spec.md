# PC 客户端代理设置 · 后端配合需求

## 背景

PC 客户端需要实现分类代理设置，将网络请求分为三类独立配置：

| 类别 | 涵盖范围 | 典型场景 |
|------|----------|----------|
| 静态资源 | 封面图、背景图、字幕文件下载 | 境外图片 CDN 需要代理 |
| API 接口 | 所有 `/api/` 请求（心跳、搜索、元数据） | 后端部署在需代理才能访问的网络 |
| 视频流 | mpv 播放器拉取的 HLS/直连流 | 特定媒体库的存储在境外 |

其中**前两类（静态资源、API）的全局默认代理**由 PC 客户端本地存储管理，不需要后端参与。

**需要后端配合的是：按媒体库设置独立代理**。不同媒体库的存储后端可能分布在不同网络环境（如媒体库 A 的 WebDAV 在境内直连，媒体库 B 的 AList 在境外需代理），PC 客户端需要获知每个媒体库的代理偏好，以便在拉取该库资源时使用正确的代理。

---

## 需求 1：媒体库代理配置存储

### 数据模型

在 `Library` 模型上新增字段（或新建关联表 `library_proxy_config`，取决于后端偏好）：

```python
# 方案 A：直接加字段到 Library 模型
class Library(db.Model):
    # ... existing fields ...
    proxy_video: str | None = None      # 视频流代理 URL，None 表示跟随全局/直连
    proxy_resource: str | None = None   # 该库静态资源代理 URL，None 表示跟随全局
```

字段语义：
- `None` / 空字符串 = 使用客户端全局设置（即"跟随全局"）
- `"direct"` = 强制直连（即使全局设了代理，该库也不走）
- `"http://..."` / `"socks5://..."` = 使用指定代理地址

### 为什么需要两个字段

同一个媒体库里，视频流和封面/字幕的存取路径可能不同：
- 视频流走存储 provider 直连（如内网 SMB），不需要代理
- 但封面图走后端 `/api/v1/resources/.../poster`，如果后端本身在境外就需要代理

大多数情况下用户只需设置 `proxy_video`（视频流量大、延迟敏感），`proxy_resource` 可留空跟随全局。

---

## 需求 2：API 接口

### 2.1 读取所有媒体库代理配置

PC 客户端启动时需要一次性拉取全部媒体库的代理设置，用于后续请求路由。

```
GET /api/v1/libraries/proxy-config
```

响应：
```json
{
  "code": 0,
  "data": {
    "libraries": [
      {
        "library_id": "uuid-xxxx",
        "library_name": "4K 电影",
        "proxy_video": "socks5://127.0.0.1:1080",
        "proxy_resource": null
      },
      {
        "library_id": "uuid-yyyy",
        "library_name": "番剧",
        "proxy_video": null,
        "proxy_resource": null
      }
    ]
  }
}
```

或者：也可以在现有 `GET /api/v1/libraries` 响应里直接附带这两个字段（如果不想新增端点）。PC 客户端启动时本来就会调 libraries 列表接口，直接在 library 对象里多返回两个字段即可：

```json
{
  "id": "uuid-xxxx",
  "name": "4K 电影",
  "proxy_video": "socks5://127.0.0.1:1080",
  "proxy_resource": null,
  // ... other existing fields
}
```

**推荐后者**（在现有 libraries 接口附带），减少额外请求。

### 2.2 更新单个媒体库代理配置

```
PATCH /api/v1/libraries/{library_id}/proxy-config
Content-Type: application/json

{
  "proxy_video": "socks5://127.0.0.1:1080",
  "proxy_resource": null
}
```

响应：
```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "library_id": "uuid-xxxx",
    "proxy_video": "socks5://127.0.0.1:1080",
    "proxy_resource": null
  }
}
```

字段校验规则：
- `null` 或空字符串 → 清除（跟随全局）
- `"direct"` → 允许（强制直连标记）
- 以 `http://`、`https://`、`socks5://` 开头的 URL → 允许
- 其他 → 返回 400

---

## 需求 3：现有接口适配

### 3.1 资源播放流 URL 不变

PC 客户端获取播放地址仍走现有接口（`GET /api/v1/resources/{id}/stream` 等），只是客户端在发请求时会根据该资源所属 library 的 `proxy_video` 设置决定是否走代理。**后端无需在流接口层面做任何改动**。

### 3.2 资源归属 library_id

PC 客户端需要知道一个 resource 属于哪个 library，以决定用哪个代理。当前 movie detail 响应里是否包含 `library_id`？如果没有，需要在以下接口补上：

- `GET /api/v1/movies/{id}` 响应的 movie 对象
- 或者 resource 对象上带 `library_id`

请确认当前是否已有此字段。如已有则无需改动。

---

## 客户端侧实现概要（供后端了解上下文）

PC 客户端的代理路由逻辑：

```
请求发出前:
  1. 判断请求类别（API / 静态资源 / 视频流）
  2. 如果能关联到某个 library_id:
     - 查该库的 proxy_video / proxy_resource 配置
     - 非 null → 用库级代理（"direct" 则强制直连）
  3. 否则 fallback 到全局分类代理设置
  4. 全局也为空 → 直连
```

全局分类代理存储在客户端本地（localStorage），不需要后端参与。

---

## 实现优先级建议

1. **P0**：在 `GET /api/v1/libraries` 响应里补上 `proxy_video` / `proxy_resource` 字段（默认 null）
2. **P0**：新增 `PATCH /api/v1/libraries/{id}/proxy-config` 端点
3. **P1**：确认 movie/resource 对象里有 `library_id` 字段（供客户端做代理路由）

如果字段直接加在 Library 模型上，预计改动量很小（model 加两个 nullable string 列 + 一个 PATCH 路由 + serialize 时带上字段）。

---

## 问题确认

1. `Library` 模型现有 `proxy_video` / `proxy_resource` 类似字段吗？还是完全新增？
2. 现有 `GET /api/v1/libraries` 返回的 library 对象有哪些字段？直接扩展还是新建端点？
3. Movie/Resource 对象里是否已有 `library_id`？
4. 是否需要鉴权限制（仅管理员可改代理配置）？

以上确认后我可以直接写 PR。
