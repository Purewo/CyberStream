# 运行与排障手册

## 1. 启动

项目根目录：

```bash
cd /home/pureworld/赛博影视
```

使用虚拟环境启动：

```bash
cp .env.local.example .env.local
# 填入 CYBER_SUPERCDN_TOKEN、TMDB_TOKEN、CYBER_API_TOKEN 等本机私密配置后：
./scripts/backend_service.sh start
```

常用服务命令：

```bash
./scripts/backend_service.sh status
./scripts/backend_service.sh restart
./scripts/backend_service.sh stop
```

服务脚本默认 `CYBER_BACKEND_RUNNER=auto`：如果 `.venv/bin/gunicorn` 存在，会优先用 gunicorn；否则回退 Flask 内置服务器。需要指定时可设置 `CYBER_BACKEND_RUNNER=gunicorn` 或 `CYBER_BACKEND_RUNNER=flask`。

开发调试时也可以前台运行 `/home/pureworld/赛博影视/.venv/bin/python -m backend.run`。

## 2. 停止

查找 5004 端口对应进程：

```bash
./scripts/backend_service.sh status
```

停止后台服务：

```bash
./scripts/backend_service.sh stop
```

## 3. 验收

### 本地验收

```bash
curl -i http://127.0.0.1:5004/
```

预期返回 `200` 与健康检查 JSON（`data.version` 应等于 `APP_VERSION`，当前为 `1.21.0`）。

如果已设置 `CYBER_API_TOKEN`，管理类接口需要携带 token：

```bash
curl -i http://127.0.0.1:5004/api/v1/storage/sources \
  -H "Authorization: Bearer $CYBER_API_TOKEN"
```

### 公网验收

```bash
curl -i http://pioneer.fan:884/
curl -i http://pioneer.fan:884/api/v1/openapi.json
```

## 4. 当前已知运行事实

- 当前 IPv4 公网入口为 `http://pioneer.fan:884`，映射到本机 `5004`
- 后台运行优先使用 `./scripts/backend_service.sh`，脚本会加载项目根目录 `.env.local`
- 服务脚本优先使用 gunicorn，缺失时自动回退 Flask 内置服务器
- `.env.local` 存放 token 等本机私密配置，已加入 git 忽略；提交前只维护 `.env.local.example`
- `CYBER_API_TOKEN` 未设置时 API 鉴权不启用；设置后管理类 API 要求 Bearer token 或 `X-Cyber-API-Token`
- `CYBER_USER_MANAGEMENT_ENABLED` 默认关闭；开启前必须设置 `CYBER_SESSION_SECRET` 和初始管理员账号，开启后网页端使用 Cookie 会话登录
- `TMDB_TOKEN` 不再写在代码里；未设置时 TMDB 请求会被跳过，扫描继续走其他 provider fallback
- 正式海报层 CDN 默认使用 Super CDN 图片桶 `hd-wallpapers`，加载链路为 CDN -> 后端本地图片入口 -> 原始元数据 URL
- 不建议直接用 `python backend/run.py`
- 当前 `main` 是唯一主干分支，`1.21.0` 是当前运行版本；`1.16.0` 保留为历史稳定标签

### 4.1 SQLite 备份与恢复

风险操作前先备份：

```bash
./scripts/db_backup.py backup
```

查看已有备份：

```bash
./scripts/db_backup.py list
```

恢复会先自动创建一次恢复前备份，再替换当前数据库；必须显式确认：

```bash
./scripts/db_backup.py restore backups/<backup-file>.db --yes
```

### 4.2 启用用户管理

`.env.local` 最小配置：

```bash
CYBER_USER_MANAGEMENT_ENABLED=true
CYBER_SESSION_SECRET=<long-random-secret>
CYBER_BOOTSTRAP_ADMIN_USERNAME=<admin>
CYBER_BOOTSTRAP_ADMIN_PASSWORD=<password>
CYBER_SESSION_COOKIE_SECURE=true
CYBER_LOGIN_RATE_LIMIT_ENABLED=true
```

重启后用 `POST /api/v1/auth/login` 登录。普通用户可见范围由管理员在 `/api/v1/admin/users/<id>/library-rules` 配置；默认可见全部公开影视。管理员操作、登录失败和限流事件可通过 `GET /api/v1/admin/audit-logs` 查询。

### 4.3 启用托管光鸭云盘

CyberStream 只对外暴露自己的 HTTPS API；AList 只跑在本机。最小配置：

```bash
CYBER_MANAGED_ALIST_ENABLED=true
CYBER_MANAGED_ALIST_BASE_URL=http://127.0.0.1:5244
CYBER_MANAGED_ALIST_USERNAME=admin
CYBER_MANAGED_ALIST_PASSWORD=<alist-admin-password>
# 或使用 CYBER_MANAGED_ALIST_TOKEN=<alist-admin-token>
CYBER_MANAGED_ALIST_MOUNT_PREFIX=/cyberstream
```

短信登录流程：

```bash
curl -s http://127.0.0.1:5004/api/v1/storage/managed/guangyapan/sms/start \
  -H "Content-Type: application/json" \
  -d '{"name":"光鸭云盘","phone_number":"+861380001234","root_path":""}'

curl -s http://127.0.0.1:5004/api/v1/storage/managed/guangyapan/sms/verify \
  -H "Content-Type: application/json" \
  -d '{"source_id":1,"verify_code":"123456"}'
```

成功后来源状态为 `ready`。播放时后端会先解析 localhost AList `/d/...` 的 302，再把最终云盘直链返回给客户端。

### 4.4 启用托管 OpenList 云盘

天翼云盘、115 云盘、QuarkTV、UCTV 使用 OpenList 托管驱动，OpenList 只跑在本机，端口与 AList 分开。最小配置：

```bash
CYBER_MANAGED_OPENLIST_ENABLED=true
CYBER_MANAGED_OPENLIST_BASE_URL=http://127.0.0.1:5245
CYBER_MANAGED_OPENLIST_USERNAME=admin
CYBER_MANAGED_OPENLIST_PASSWORD=<openlist-admin-password>
# 或使用 CYBER_MANAGED_OPENLIST_TOKEN=<openlist-admin-token>
CYBER_MANAGED_OPENLIST_MOUNT_PREFIX=/cyberstream
```

扫码登录流程：

```bash
curl -s http://127.0.0.1:5004/api/v1/storage/managed/tianyicloud/qr/start \
  -H "Content-Type: application/json" \
  -d '{"name":"天翼云盘"}'

curl -s http://127.0.0.1:5004/api/v1/storage/managed/tianyicloud/qr/poll \
  -H "Content-Type: application/json" \
  -d '{"source_id":2}'
```

115、QuarkTV、UCTV 分别使用：

```http
POST /api/v1/storage/managed/115cloud/qr/start
POST /api/v1/storage/managed/115cloud/qr/poll
POST /api/v1/storage/managed/quarktv/qr/start
POST /api/v1/storage/managed/quarktv/qr/poll
POST /api/v1/storage/managed/uctv/qr/start
POST /api/v1/storage/managed/uctv/qr/poll
```

`qr/start` 返回二维码展示字段。用户扫码确认后，轮询接口会返回 `authenticated=true` 且来源状态变为 `ready`。播放时后端会先解析 localhost OpenList `/d/...` 的 302，再把最终云盘直链返回给客户端。

115 云盘扫码登录流程：

```bash
curl -s http://127.0.0.1:5004/api/v1/storage/managed/115cloud/qr/start \
  -H "Content-Type: application/json" \
  -d '{"name":"115 云盘"}'

curl -s http://127.0.0.1:5004/api/v1/storage/managed/115cloud/qr/poll \
  -H "Content-Type: application/json" \
  -d '{"source_id":3}'
```

115 默认使用 `qrcode_source=wechatmini`，避免占用用户常用的 Web、Android 或 iOS 登录态。`qr/poll` 会区分 `waiting_for_scan`、`waiting_for_confirm`、`qr_expired` 和 `qr_canceled`。只有返回 `authenticated=true` 且 `auth_state=ready` 后，来源才允许预览、扫描、刷新和播放。

## 5. 常见问题

### 5.1 `ModuleNotFoundError: No module named 'backend'`
旧版本可能因直接执行 `backend/run.py` 而报错。

当前已兼容以下两种启动方式：

```bash
./scripts/backend_service.sh start
python -m backend.run
python backend/run.py
```

但长期维护仍建议优先使用服务脚本；需要前台调试时使用模块方式：

```bash
./scripts/backend_service.sh start
python -m backend.run
```

### 5.2 公网返回 502
重点排查：

1. 本地 `5004` 是否已启动
2. Lucky 是否正常运行
3. Lucky/反代的 `884 -> 5004` 映射是否还在

### 5.3 WebDAV 无法播放
重点排查：

1. 存储源配置是否正确
2. WebDAV 凭证是否失效
3. 上游是否返回 302 直链
4. 目标链接是否被鉴权或过期

### 5.4 Bangumi 元数据搜索无结果
重点排查：

1. 先确认 provider 能力接口正常：

```bash
curl -s http://127.0.0.1:5004/api/v1/metadata/providers
```

预期包含 `anilist`、`bangumi`，且 `supports_search=true`。`tencent_video` 只用于手动候选搜索，预期 `manual_only=true`、`supports_scrape=false`，不要加入扫描配置。

2. 动漫搜索建议显式指定 provider 和媒体类型：

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=Frieren&providers=anilist&media_type_hint=tv"
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=葬送的芙莉莲&providers=bangumi&media_type_hint=tv"
```

3. 如果知道 Bangumi 条目，可用 subject URL 定点搜索：

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=https%3A%2F%2Fbgm.tv%2Fsubject%2F400602&providers=bangumi&media_type_hint=tv"
```

4. 若 `providers.attempts[].status=failed` 且 warnings 包含 `anilist_search_failed` 或 `bangumi_search_failed`，优先检查网络、`ANILIST_API_URL`、`BANGUMI_API_BASE`、对应 User-Agent 和上游限流，不要按“作品不存在”处理。

5. 腾讯视频备用源只在用户显式选择时使用：

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=诛仙3&providers=tencent_video&media_type_hint=tv"
```

该源只取标题、年份、简介、海报、标签、演员和季集信息，不使用播放地址。

6. 前端匹配时建议提交 `candidate_id + provider`：

```json
{
  "candidate_id": "anilist/154587",
  "provider": "anilist",
  "media_type_hint": "tv"
}
```

## 6. 推荐联动文档

- 配置说明：`docs/CONFIG_REFERENCE.md`
- 测试清单：`docs/TEST_CHECKLIST.md`
- 版本规范：`docs/VERSIONING.md`
- 存储源配置流：`docs/STORAGE_CONFIG_FLOW.md`
- 托管 115 云盘前端接入：`docs/FRONTEND_MANAGED_115CLOUD_INTEGRATION.md`
- 托管 QuarkTV / UCTV 前端接入：`docs/FRONTEND_MANAGED_QUARK_UC_INTEGRATION.md`
- 维护优先级：`docs/MAINTENANCE_TODO.md`

## 7. 当前运行文件

- 数据库：`cyber_library.db`
- 日志：`backend_server.log`
- PID 文件：`backend_server.pid`
- 本机环境文件：`.env.local`
- 核心配置：`backend/config.py`
