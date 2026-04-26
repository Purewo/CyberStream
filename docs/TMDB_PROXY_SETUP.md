# TMDB 代理说明

当前后端已支持“仅 TMDB 刮削走代理”，不会影响 WebDAV、AList/OpenList、SMB、FTP 等存储访问。

## 默认行为

- 默认开启 TMDB 独立代理
- 默认代理地址：`http://127.0.0.1:17890`
- 仅 `backend/app/services/tmdb.py` 使用该代理
- TMDB 请求显式关闭 `requests` 的环境代理继承，避免系统级 `HTTP_PROXY` / `HTTPS_PROXY` 污染其他网络请求

## 可用环境变量

### `TMDB_PROXY_ENABLED`

- `true` / `false`
- 默认：`true`

示例：

```bash
TMDB_PROXY_ENABLED=false
```

### `TMDB_PROXY_URL`

- 默认：`http://127.0.0.1:17890`
- 支持直接写 `127.0.0.1:17890`，后端会自动补成 `http://`

示例：

```bash
TMDB_PROXY_URL=http://127.0.0.1:17890
```

## 推荐启动方式

如果你已经启动了 `mihomo`，可以这样启动后端：

```bash
TMDB_PROXY_ENABLED=true TMDB_PROXY_URL=http://127.0.0.1:17890 ./.venv/bin/python -m backend.run
```

## 设计边界

- 该代理只用于 TMDB 搜索、详情、外部 ID 查询
- 存储协议仍然直连各自服务
- 这样可以避免刮削翻墙需求影响局域网或内网存储访问
