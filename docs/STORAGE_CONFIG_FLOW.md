# 存储源配置流说明

本文档用于说明赛博影视项目中存储源配置的真实流转方式，包括：

- 接口接收的配置结构
- 数据库存储结构
- provider 的字段消费方式
- 扫描、预览、播放如何使用同一份配置
- 当前存在的字段不一致与风险点

---

## 1. 当前支持的存储协议

当前真正已接入主流程的协议：

- `local`
- `webdav`
- `smb`
- `ftp`
- `alist`
- `openlist`

`alist/openlist` 当前按同一套兼容 REST API 接入。`smb/ftp` 已完成 provider、配置校验、目录预览、扫描和播放链路接入，但因为本地暂无稳定测试环境，当前仅做单元级 mock 验证。

---

## 2. 配置流总览

当前主流程的真实配置链路如下：

```text
客户端请求 JSON
  -> POST /api/v1/storage/sources
  -> StorageSource(type, config) 存入数据库
  -> provider_factory.get_provider(storage_source)
  -> LocalProvider / WebDAVProvider / SMBProvider / FTPProvider / AListProvider
  -> 被 preview / scanner / stream 共同消费
```

也就是说：

> 当前真正生效的存储配置，核心不是 `backend/config.py` 里的旧全局配置，而是数据库表 `storage_sources.config` 中的 JSON。

---

## 3. 数据模型结构

模型：`app/models.py` -> `StorageSource`

核心字段：

- `id`
- `name`
- `type`
- `config`（JSON）

其中：

- `type` 决定用哪个 provider
- `config` 是 provider 的原始配置对象

新增存储源时，后端会通过 `backend/app/storage/source_registry.py` 做集中字段校验与归一化。请求至少需要：

- `name` 存在
- `type` 存在
- `config` 存在

同时，`config` 必须符合对应协议的字段定义；未知字段会被拒绝，缺少必填字段会返回错误。

这意味着：

- 保存前即可拦截明显错误配置
- 具体连通性仍需要通过 preview / health / browse 验证

---

## 4. 接口层配置流

## 4.1 新增存储源

接口：`POST /api/v1/storage/sources`

请求体结构：

```json
{
  "name": "示例存储源",
  "type": "local / webdav / smb / ftp / alist / openlist",
  "config": { ... }
}
```

后端行为：

- 校验并归一化 `type`
- 按协议校验并归一化 `config`
- 存入 `StorageSource`
- 返回脱敏后的来源摘要、能力矩阵、使用情况和变更保护信息

---

## 4.2 更新存储源

接口：`PATCH /api/v1/storage/sources/<id>`

当前支持更新：

- `name`
- `type`
- `config`

注意：
- `config` 是整对象替换，不是字段级 merge
- 因此前端更新时应传完整配置对象，避免漏字段
- 若来源已被资源或资源库绑定引用，当前不允许直接修改 `type`

---

## 4.3 预览配置

接口：`POST /api/v1/storage/preview`

请求体结构：

```json
{
  "type": "local / webdav / smb / ftp / alist / openlist",
  "config": { ... },
  "target_path": "/"
}
```

后端行为：

- 不写数据库
- 直接调用 `provider_factory.create(type, config)`
- 立即用 provider 列目录
- 返回 `storage_type`、`current_path`、`parent_path`、`items`
- `dirs_only` 默认 `true`，用于前端目录选择器

这个接口非常关键，因为它反映了：

> 只要 `type + config` 能成功构造 provider，后续扫描和播放理论上就具备可行性。

---

## 5. ProviderFactory 如何消费配置

文件：`app/providers/factory.py`

逻辑：

- `type=local` -> `LocalProvider(config)`
- `type=webdav` -> `WebDAVProvider(config)`
- `type=smb` -> `SMBProvider(config)`
- `type=ftp` -> `FTPProvider(config)`
- `type=alist` -> `AListProvider(config, platform='alist')`
- `type=openlist` -> `AListProvider(config, platform='openlist')`
- 其他类型 -> 抛错 `Unsupported storage type`

因此，所有配置字段最终都由具体 provider 自己解释。

---

## 6. Local 配置结构

文件：`app/providers/local.py`

### 6.1 当前真实字段

`LocalProvider` 只明确读取一个核心字段：

- `root_path`

代码：

```python
self.root_path = config.get('root_path', '')
```

### 6.2 推荐配置示例

```json
{
  "name": "本地影视库",
  "type": "local",
  "config": {
    "root_path": "/mnt/media/movies"
  }
}
```

### 6.3 运行逻辑

- `relative_path` 由上层传入
- provider 用 `root_path + relative_path` 拼成真实路径
- `list_items()` 返回相对路径
- `get_stream_data()` 读取真实文件并支持 Range

### 6.4 必填/选填判断

- 必填：`root_path`
- 选填：当前无明确额外字段

### 6.5 注意事项

- `root_path` 为空时，provider 仍可实例化，但运行会异常或返回空结果
- 路径必须是后端运行机器可访问的本地路径

---

## 7. WebDAV 配置结构

文件：`app/providers/webdav.py`

### 7.1 当前真实字段

`WebDAVProvider` 当前会读取：

- `host`
- `port`
- `secure`
- `username`
- `password`
- `root`

代码行为：

- `host` 默认 `localhost`
- `port` 默认 `443`
- `secure` 默认 `True`
- `username` 默认空串
- `password` 默认空串
- `root` 默认 `/`

### 7.2 推荐配置示例

```json
{
  "name": "远程 WebDAV",
  "type": "webdav",
  "config": {
    "host": "example.com",
    "port": 5244,
    "secure": true,
    "username": "demo",
    "password": "demo-pass",
    "root": "/影视库"
  }
}
```

### 7.3 运行逻辑

- `base_url = protocol://host:port`
- `root` 会标准化为以 `/` 开头、不以 `/` 结尾
- `list_items()` 按相对路径列目录
- `get_stream_data()`：
  - 拼接完整 WebDAV URL
  - 手动带 Basic Auth
  - 支持 Range
  - 支持 302 重定向透传

### 7.4 必填/选填判断

从“代码能否实例化”角度看，全部都有默认值；
但从“业务能否正常工作”角度看，建议视为必填：

- `host`
- `root`

通常也应提供：

- `port`
- `secure`
- `username`
- `password`

### 7.5 注意事项

- 当前使用的字段名是 `username` / `password`
- 旧配置里出现过 `login`，但当前 provider 并不读取 `login`
- 如果前端还在传 `login`，则会出现“看起来有账号，实际鉴权没带上”的问题

---

## 8. 配置如何被扫描、预览、播放复用

## 8.1 预览

路径：`/storage/preview`

- 直接使用请求里的 `type + config`
- 不依赖数据库

## 8.2 扫描

路径：`/storage/sources/<id>/scan` 或全量 `/scan`

- 从数据库取 `StorageSource`
- 用 `provider_factory.get_provider(storage_source)` 构造 provider
- 通过 provider 递归列目录与读取文件路径

## 8.3 播放

路径：`/resources/<id>/stream`

- 先查 `MediaResource`
- 再通过 `resource.source` 找到 `StorageSource`
- 再构造 provider
- 再用 provider 获取流或重定向地址

这说明：

> 同一份 `StorageSource.config` 同时决定目录预览、资源扫描和播放行为。

因此配置问题不是局部问题，而是全链路问题。

---

## 9. 当前发现的字段不一致与风险点

## 9.1 Local 字段历史不一致（已做兼容）

历史上：

- `StorageSource.to_dict()` 展示曾使用 `path`
- `LocalProvider` 实际运行使用 `root_path`

当前已调整为兼容模式：

- 优先使用 `root_path`
- 若缺失则回退兼容旧字段 `path`

当前建议：

- 新配置统一使用 `root_path`
- 旧数据若仍为 `path`，暂不强制迁移，也可继续运行

## 9.2 WebDAV 旧字段与当前字段可能混用

旧版全局配置中出现的是：

- `login`

当前 provider 读取的是：

- `username`

如果前端或旧数据沿用旧字段，将导致运行时认证失败。

## 9.3 更新接口为整对象替换

`PATCH /storage/sources/<id>` 更新 `config` 时，当前是直接整对象替换。

后果：
- 前端只改一个字段时，如果没把其他字段一起带上，可能会把配置冲掉

这点在前端联调时必须特别注意。

## 9.4 缺少字段级校验

当前新增/更新/预览存储源时，都会通过 `source_registry` 对 `config` 做最小字段校验和类型归一化。

仍需注意：
- 字段合法不等于远端服务可连接
- 账号、权限、目录是否存在仍需要通过 preview / browse / health 验证

---

## 10. 当前建议

### 10.1 当前阶段先不大改
先把真实字段与配置流文档化，避免误用。

### 10.2 后续优先可做的低风险修复
1. 继续清理历史 local `path` 字段，只在兼容层保留读取能力
2. 明确 WebDAV 是否继续兼容旧 `login -> username`
3. 为真实网络错误补充更细的 health reason
4. 在前端联调中统一按 provider-types 返回的字段定义生成表单

---

## 11. 当前推荐标准

### Local 标准

```json
{
  "name": "本地影视库",
  "type": "local",
  "config": {
    "root_path": "/data/media"
  }
}
```

### WebDAV 标准

```json
{
  "name": "WebDAV 影视库",
  "type": "webdav",
  "config": {
    "host": "dav.example.com",
    "port": 443,
    "secure": true,
    "username": "user",
    "password": "pass",
    "root": "/movies"
  }
}
```

### AList 标准

```json
{
  "name": "AList 影视库",
  "type": "alist",
  "config": {
    "base_url": "https://alist.example.com",
    "token": "alist-token",
    "root": "/movies"
  }
}
```

### OpenList 标准

```json
{
  "name": "OpenList 影视库",
  "type": "openlist",
  "config": {
    "host": "openlist.local",
    "port": 5244,
    "secure": true,
    "username": "admin",
    "password": "secret",
    "root": "/movies"
  }
}
```

后续所有新增配置说明与前端联调，建议都以上述结构为准。

### AList / OpenList 路径边界

- 新建来源时，前端目录选择器选中的“挂载根”应写入 `config.root`
- 已保存来源浏览目录时，`target_path` / `path` 只是相对于 `config.root` 的临时浏览位置
- 指定来源扫描时，`root_path` / `target_path` 只是本次扫描起点，不会修改 `config.root`
- 资源库绑定时，`LibrarySource.root_path` 是逻辑库范围，不替代 `StorageSource.config.root`
- 已经扫描出资源的来源不建议直接修改 `config.root`，否则旧资源路径可能和新的技术根重复拼接
