# 配置说明

本文档用于说明 `backend/config.py` 中哪些配置当前仍在使用，哪些属于历史残留或弱依赖配置。

## 1. 配置文件位置

- `backend/config.py`

Flask app 会通过 `app.config.from_object(config)` 载入该模块。

---

## 2. 当前明确在主流程中使用的配置

### 2.1 数据库配置

#### `SQLALCHEMY_DATABASE_URI`
用于 Flask-SQLAlchemy 连接数据库。

#### `SQLALCHEMY_TRACK_MODIFICATIONS`
SQLAlchemy 追踪修改开关。

---

### 2.2 TMDB 配置

#### `TMDB_TOKEN`
用于 `app/services/tmdb.py` 请求 TMDB API。

必须通过环境变量或 `.env.local` 提供。代码中不再内置默认 token；未配置时 TMDB 请求会被跳过，扫描会继续走 NFO / Bangumi / Local fallback 等其他 provider。

#### `TMDB_IMAGE_BASE`
用于拼接海报地址。

#### `TMDB_BACKDROP_BASE`
用于拼接背景图地址。

#### `TMDB_PROXY_ENABLED`
控制 TMDB 请求是否走独立代理，默认开启。

#### `TMDB_PROXY_URL`
TMDB 专用代理地址，默认 `http://127.0.0.1:17890`。

说明：
- 该代理只在 `app/services/tmdb.py` 中使用
- TMDB 请求会关闭 `requests` 的环境代理读取，仅使用 `TMDB_PROXY_URL` 指定的代理
- WebDAV、AList/OpenList、SMB、FTP 等存储访问不读取这组 TMDB 代理配置，继续走各自原有网络路径
- 如需关闭：设置 `TMDB_PROXY_ENABLED=false`

#### `TMDB_PROXIES` / `PROXIES`
由 `TMDB_PROXY_URL` 派生的 requests 代理字典。`PROXIES` 仅保留为历史兼容别名。

---

### 2.3 Bangumi 配置

#### `BANGUMI_API_BASE`
Bangumi / 番组计划 API 地址，默认 `https://api.bgm.tv`。

#### `BANGUMI_USER_AGENT`
Bangumi API 请求使用的 User-Agent，默认 `Purewo/CyberStream/1.21.0 (https://github.com/Purewo/CyberStream)`。Bangumi 官方要求非浏览器 API 使用者提供明确的开发者 ID 和应用名；当前默认值已带项目 GitHub 仓库地址。

#### `BANGUMI_TIMEOUT_SECONDS`
Bangumi API 请求超时时间，默认 `10` 秒。

---

### 2.4 扫描规则配置

以下配置在扫描逻辑或通用工具中仍被使用：

#### `VIDEO_EXTENSIONS`
合法视频扩展名列表。

#### `IGNORE_FOLDERS`
扫描时应忽略的目录名。

#### `IGNORE_FILES`
扫描时应忽略的噪音文件关键字。

#### `REGEX_PATTERNS`
扫描器用于提取年份等字段的正则规则。

---

### 2.5 FFmpeg 实时转码配置

#### `FFMPEG_BIN`
指定 ffmpeg 可执行文件路径。未设置时后端会自动查找 `ffmpeg`、`~/.local/bin/ffmpeg`、`/usr/local/bin/ffmpeg`、`/usr/bin/ffmpeg`。

环境变量：`CYBER_FFMPEG_BIN` 或 `FFMPEG_BIN`。

#### `FFMPEG_AUDIO_TRANSCODE_MAX_CONCURRENT`
实时音频转码全局并发上限，默认 `1`。联调阶段不建议调高，避免前端误触发多条远程下载和转码流。

#### `FFMPEG_AUDIO_TRANSCODE_READ_TIMEOUT_SECONDS`
ffmpeg 读取远程输入的超时时间，默认 `60` 秒。AList/网盘大文件在首次 seek 时可能触发多段 Range 读取，低于该值容易出现首包前超时。

#### `FFMPEG_AUDIO_TRANSCODE_INPUT_RETRIES`
实时音频转码内部输入代理的上游重试次数，默认 `2`。用于处理 AList `/d` 链接或网盘 CDN 首次 Range 请求偶发失败、断流、超时的问题；重试发生在同一个后端转码请求内部，不需要前端重建 `audio`。

#### `FFMPEG_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS`
实时音频转码首包超时时间，默认 `90` 秒。拖动到远处时间点后，如果 ffmpeg 长时间没有输出任何音频字节，后端会在首包前主动重建输入代理和 ffmpeg，避免前端无限等待。

#### `FFMPEG_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS`
实时音频转码抢占限流等待时间，默认 `3` 秒。同一 `session_id` seek 时后端会先停止旧流，再给旧 ffmpeg 短时间退出窗口，避免新流被旧流瞬时占用的单并发名额挡成 `429`。

#### `FFMPEG_AUDIO_TRANSCODE_REALTIME_INPUT`
ffmpeg 原生 `-re` 输入限速开关，默认 `true`。优先保护原始视频直链，避免音频转码从同一个远端原片过度预读，挤占浏览器视频播放带宽并把 Range 缓存窗口推得过远。若后续只在高速内网或本地源上使用，可按场景关闭。

#### `FFMPEG_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER`
实时音频转码输出限速倍率，默认 `1.5`。后端会按目标音频码率的约 1.5 倍向前端输出，让 audio 元素持续积累小缓冲，避免严格 1 倍实时输出导致网络轻微抖动后卡顿。

#### `FFMPEG_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS`
实时音频转码初始突发缓冲秒数，默认 `8`。每条转码流启动后，后端会先尽快输出约 8 秒音频给前端，之后再进入输出限速。

#### `FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED`
实时音频转码远程输入 Range 内存缓存开关，默认 `true`。缓存的是 AList `/d` / 网盘 CDN 返回的原始视频字节片段，主要用于复用 MKV 头部、尾部索引和相邻 seek 的 cluster，不缓存完整转码文件。缓存按资源归属管理；history 判断同一 `session_id` 切换到其他资源且旧资源没有其他活跃观看会话时，会清理旧资源缓存。

#### `FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_BYTES`
实时音频转码远程输入 Range 内存缓存上限，默认 `268435456` 字节（256MB）。超过上限按最近使用情况淘汰旧片段；缓存只在后端进程内存中，重启后清空，不写磁盘。

#### `FFMPEG_AUDIO_TRANSCODE_HISTORY_TIMEOUT_SECONDS`
实时音频转码 history watchdog 超时时间，默认 `180` 秒。超过该时间未收到对应资源的 `POST /api/v1/user/history` 播放进度提交时，后端会主动停止 ffmpeg。

### 2.6 图片静态资源缓存配置

#### `CYBER_IMAGE_ASSET_MAX_BYTES`
单张海报/背景图允许缓存的最大字节数，默认 `20971520` 字节（20MB）。超过限制会返回上游图片过大错误；如果已有旧缓存，刷新失败时会回退旧缓存。

#### `CYBER_IMAGE_ASSET_TIMEOUT_SECONDS`
图片回源请求超时时间，默认 `15` 秒。当前只对数据库中已有的 `cover/background_cover` 回源，不接受前端传任意 URL。

#### `CYBER_IMAGE_ASSET_CACHE_MAX_AGE_SECONDS`
图片接口响应给浏览器的 `Cache-Control` 秒数，默认 `86400`。后端落盘缓存位于 `CACHE_DIR/images/movies/<movie_id>/`。

#### `CYBER_IMAGE_ASSET_PUBLIC_BASE_URL`
图片资产对外访问 base URL，默认不设置。未设置时 `poster_asset_url/backdrop_asset_url` 返回后端相对路径，例如 `/api/v1/movies/<id>/images/poster`；设置为 `https://cdn.example.com` 后会返回 `https://cdn.example.com/api/v1/movies/<id>/images/poster`。

说明：
- 该配置只影响列表、详情和图片状态接口返回的资产 URL
- 实际图片读取、缓存、刷新和清理仍由后端图片接口处理
- 适合让真实 CDN 反向代理后端图片接口，后续接对象存储/CDN SDK 时再扩展上传与 purge provider

#### `CYBER_IMAGE_ASSET_CDN_PURGE_PROVIDER`
图片 CDN purge provider，默认 `noop`。

说明：
- `noop` 不调用外部 CDN，只在 `POST /api/v1/images/refresh` 中返回待 purge 的图片 URL 清单
- `manual` 表示由运维或外部脚本手动处理 purge，接口仍返回 URL 清单
- Super CDN 资产上传已走独立配置，不依赖该 purge provider；图片使用内容 hash 路径，通常不需要 purge 旧 URL

### 2.7 Super CDN 国内静态资产配置

Super CDN 接入只处理非视频静态资产：海报、背景图、用户绑定字幕原文和网页播放器用 WebVTT 字幕。视频主播放链路仍走当前 StorageSource / `/resources/<id>/stream`，不会上传到 CDN。

#### `CYBER_CDN_PROVIDER` / `CYBER_SUPERCDN_ENABLED`
启用 Super CDN provider。推荐设置：

```bash
CYBER_CDN_PROVIDER=supercdn
CYBER_SUPERCDN_ENABLED=true
```

默认关闭；关闭时所有新字段返回空或 `skipped`，不影响现有后端图片/字幕 URL。

#### `CYBER_SUPERCDN_URL` / `CYBER_SUPERCDN_TOKEN`
Super CDN 控制面地址和 root/user token。也兼容读取 `SUPERCDN_URL` / `SUPERCDN_TOKEN`。

本地运行推荐把 Super CDN 配置放在项目根目录 `.env.local`，可从 `.env.local.example` 复制后填写 token；`.env.local` 不提交到 git，后台服务脚本会自动加载。

#### `CYBER_SUPERCDN_BUCKET`
非视频资产桶 slug，默认 `cyberstream-cn-assets`。后端会在首次上传前调用 Super CDN 创建桶，除非关闭 `CYBER_SUPERCDN_AUTO_CREATE_BUCKET`。

当前正式先替换海报层时使用公网已有图片桶 `hd-wallpapers`：

```bash
CYBER_SUPERCDN_BUCKET=hd-wallpapers
CYBER_SUPERCDN_BUCKET_ALLOWED_TYPES=image
CYBER_SUPERCDN_AUTO_UPLOAD_IMAGES=true
CYBER_SUPERCDN_AUTO_UPLOAD_SUBTITLES=false
CYBER_SUPERCDN_SERVE_ASSET_URLS=true
```

当前只继续维护海报层 CDN 接入。Super CDN 稳定 `/a/{bucket}/...` URL 现阶段实测由 Super CDN 代理返回 `200/206`，底层 `storage_url/cdn_url` 才会 302 到豆包/飞书下载流；赛博影视不直接向前端暴露签名网盘直链。背景图、字幕等后续静态资源迁移暂缓，等 Super CDN asset bucket redirect 策略明确后再继续。

#### `CYBER_SUPERCDN_ROUTE_PROFILE`
桶默认线路，默认 `china_all`，用于国内全线路加速。当前不要改成视频桶，也不要用于 `/resources/<id>/stream` 主播放资源。

#### `CYBER_SUPERCDN_BUCKET_ALLOWED_TYPES`
桶允许类型，默认 `image,document`，明确排除 `video`。

#### `CYBER_SUPERCDN_BUCKET_CACHE_CONTROL`
上传对象默认缓存策略，默认 `public, max-age=86400`。图片和字幕对象使用内容 hash 路径，刷新后会生成新 URL。

#### `CYBER_SUPERCDN_AUTO_UPLOAD_IMAGES` / `CYBER_SUPERCDN_AUTO_UPLOAD_SUBTITLES`
分别控制图片缓存写入后、用户绑定字幕写入后是否自动上传 Super CDN，默认均为 `true`，但只有在 Super CDN provider 启用后生效。

#### `CYBER_SUPERCDN_SERVE_ASSET_URLS`
默认 `true`。当本地缓存元数据中存在已上传的 Super CDN URL 时，`poster_asset_url/backdrop_asset_url` 和绑定字幕 `url/web_player.url` 会优先返回 CDN URL；上传失败或未上传时自动回退后端 URL。

图片接口的正式加载链路为 CDN -> 后端本地图片入口 -> 原始元数据 URL。列表、详情和状态接口会返回 `*_asset_urls` 与 `*_asset_fallback_urls`，后端本地图片入口在无缓存且回源失败时会 302 到原始 URL。

#### `CYBER_SUPERCDN_WARMUP_AFTER_UPLOAD` / `CYBER_SUPERCDN_WARMUP_METHOD`
上传后是否调用 Super CDN 桶预热，默认关闭；预热方法默认 `HEAD`。国内网盘线路如果 HEAD 兼容性差，可改为 `GET`。

#### `CYBER_SUPERCDN_TIMEOUT_SECONDS` / `CYBER_SUPERCDN_MAX_FILE_SIZE_BYTES`
Super CDN API 超时默认 `20` 秒；非视频资产单文件上限默认 `104857600` 字节（100MB）。

### 2.8 反向代理与外部 URL 配置

#### `CYBER_TRUST_PROXY_HEADERS`
是否信任反向代理传入的 `X-Forwarded-*` 请求头，默认 `true`。启用后，后端生成的 `playback.stream_url`、`audio.server_transcode.url`、字幕 URL 等绝对地址会根据 `X-Forwarded-Proto` / `X-Forwarded-Host` 使用公网 HTTPS 地址。

如果公网反代未正确传 `X-Forwarded-Proto`，后端生成 URL 时会对非本地主机按 `PREFERRED_URL_SCHEME=https` 兜底修正，避免公网响应里出现 `http://pw.pioneer.fan:84/...`。

#### `CYBER_PROXY_FIX_X_FOR` / `CYBER_PROXY_FIX_X_PROTO` / `CYBER_PROXY_FIX_X_HOST` / `CYBER_PROXY_FIX_X_PORT` / `CYBER_PROXY_FIX_X_PREFIX`
传给 Flask `ProxyFix` 的信任层数，默认均为 `1`。当前部署如果只有一层 Nginx/Caddy/网关反代，保持默认即可。

#### `CYBER_BACKEND_PUBLIC_BASE_URL`
后端 API 的强制外部 base URL，默认不设置。设置后会覆盖请求头推断结果，用于反代没有正确传 `X-Forwarded-Proto` 的部署。

示例：

```bash
CYBER_BACKEND_PUBLIC_BASE_URL=https://pw.pioneer.fan:84
```

设置后，资源播放、音频转码和字幕等后端生成 URL 会返回 `https://pw.pioneer.fan:84/api/v1/...`。

### 2.9 最小 API 鉴权配置

#### `CYBER_API_TOKEN`
单机私有部署的最低保护 token。设置后，后端会要求管理类 API 携带：

```http
Authorization: Bearer <token>
```

也兼容：

```http
X-Cyber-API-Token: <token>
```

未设置 `CYBER_API_TOKEN` 时，鉴权不会启用，以保持本地开发和当前前端兼容。

#### `CYBER_AUTH_ENABLED`
鉴权总开关。默认随 `CYBER_API_TOKEN` 是否存在自动启用；如果需要临时关闭，可显式设置为 `false`。

#### `CYBER_AUTH_EXEMPT_MEDIA_GET`
媒体读取豁免开关，默认 `true`。开启后以下 GET 请求不要求 token，避免浏览器 `<video>`、`<img>`、外部播放器和字幕加载无法携带 Authorization 头：

- `/`
- `/api/v1/resources/<id>/stream`
- `/api/v1/resources/<id>/audio-transcode`
- `/api/v1/movies/<id>/images/poster`
- `/api/v1/movies/<id>/images/backdrop`

管理、扫描、元数据修改、字幕绑定、资源治理 job 等接口仍会要求 token。

### 2.10 用户管理配置

#### `CYBER_USER_MANAGEMENT_ENABLED`
用户管理总开关，默认 `false`。关闭时不改变现有业务行为；开启后网页端通过 Cookie 会话登录，`CYBER_API_TOKEN` 仍保留为管理员后门。

#### `CYBER_SESSION_SECRET`
用户管理开启时必须设置，用于签名 Flask session cookie。

#### `CYBER_BOOTSTRAP_ADMIN_USERNAME` / `CYBER_BOOTSTRAP_ADMIN_PASSWORD`
初始管理员账号。用户管理开启且两者均设置时，启动阶段会幂等创建或更新该管理员。

#### `CYBER_SESSION_COOKIE_SECURE` / `CYBER_SESSION_DAYS`
控制会话 cookie 是否只允许 HTTPS 发送，以及会话有效天数。公网 HTTPS 部署建议设置 `CYBER_SESSION_COOKIE_SECURE=true`。

#### `CYBER_LOGIN_RATE_LIMIT_ENABLED`
登录失败限流开关，默认 `true`。只在用户管理登录接口中使用。

#### `CYBER_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` / `CYBER_LOGIN_RATE_LIMIT_WINDOW_SECONDS` / `CYBER_LOGIN_RATE_LIMIT_LOCK_SECONDS`
登录限流参数，默认 5 分钟内失败 `5` 次后锁定 `900` 秒。限流按客户端 IP + 用户名在当前后端进程内记录。

### 2.11 维护任务持久化配置

#### `CYBER_MAINTENANCE_JOB_RESULT_ITEM_LIMIT`
维护任务写入 `maintenance_jobs` 时，`result.items` 最多保留的条数，默认 `20`。内存中的刚执行结果仍保持完整；持久化结果会附加 `result_truncated`、`result_item_count` 和 `persisted_item_limit`。

#### `CYBER_MAINTENANCE_JOB_RETENTION_DAYS`
维护任务默认保留天数，默认 `30`。`POST /api/v1/jobs/prune` 未显式传 `retention_days` 时使用该配置；只清理过期 `succeeded/failed`，不清理 `queued/running`。

---

## 3. 当前属于历史残留或弱依赖的配置

### 3.1 `STORAGE_MODE`
当前仅在 `app/utils/common.py` 的 `normalize_path()` 中被引用。

说明：
- 当前项目的主存储架构实际上已经迁移到 `StorageSource + ProviderFactory`
- 因此 `STORAGE_MODE` 不再是核心运行开关
- 目前更像是旧版单存储模式残留字段

### 3.2 `LOCAL_ROOT_PATH`
旧版本地存储根目录配置。

说明：
- 当前真正运行时，本地 provider 使用的是 `StorageSource.config.root_path` 作为标准字段
- 为兼容历史数据，local provider 也可回退读取旧字段 `path`
- 因此该配置不再决定主流程扫描根目录

### 3.3 `WEBDAV_CONFIG`
旧版 WebDAV 全局配置。

说明：
- 当前主流程中，WebDAV provider 使用的是数据库里的存储源配置
- 该全局配置不再直接驱动实际挂载

### 3.4 `WEBDAV_BASE_URL`
旧版 WebDAV 全局地址配置，当前未见主流程直接引用。

### 3.5 `WEBDAV_ROOT_PATH`
旧版 WebDAV 根目录配置，当前未见主流程直接引用。

### 3.6 `TARGET_ROOT_PATH`
由旧版 `STORAGE_MODE` 与路径配置计算而来，当前未见主流程直接引用。

### 3.7 `CACHE_DIR`
当前未见明确使用点。

### 3.8 `SCAN_INTERVAL_HOURS`
当前未见主动调度逻辑使用，属于预留或旧逻辑残留。

---

## 4. 当前有效配置策略总结

### 存储源
当前实际以数据库中的 `StorageSource.config` 为准，而不是 `config.py` 中的全局单源配置。

当前真正已接入主流程的协议包括：

- `local`
- `webdav`
- `smb`
- `ftp`
- `alist`
- `openlist`

其中 `alist/openlist` 当前共用一套兼容 REST API 的 provider。以上协议支持：

- 来源创建与更新
- 目录预览
- 扫描
- 播放时直接返回 AList/OpenList 带域名的 `/d/...` 播放入口，由前端直接使用

### TMDB 与扫描规则
当前仍主要依赖 `config.py`。

---

## 5. 已知问题

1. `config.py` 中仍保留历史单存储模式配置，容易造成误解
2. 历史单存储字段仍在文件内保留兼容默认值，但 TMDB token 与历史 WebDAV 凭证已不再内置明文默认值
3. 配置职责边界不够清晰：
   - 一部分是 Flask 配置
   - 一部分是扫描规则
   - 一部分是历史运行配置

---

## 6. 环境变量支持（当前已兼容）

为降低后续迁移风险，当前 `backend/config.py` 已支持运行时环境变量覆盖。敏感项必须来自环境变量或 `.env.local`；历史兼容项仍保留无敏感信息的安全默认值。

### 6.1 历史单存储兼容变量

- `CYBER_STORAGE_MODE`
- `CYBER_LOCAL_ROOT_PATH`
- `CYBER_WEBDAV_HOSTNAME`
- `CYBER_WEBDAV_LOGIN`
- `CYBER_WEBDAV_PASSWORD`
- `CYBER_WEBDAV_BASE_URL`
- `CYBER_WEBDAV_ROOT_PATH`

说明：
- 这些变量主要服务于历史兼容逻辑
- **不代表当前主存储配置入口**
- 当前主流程依然以数据库 `storage_sources.config` 为准

### 6.2 TMDB 相关变量

- `TMDB_TOKEN`
- `TMDB_IMAGE_BASE`
- `TMDB_BACKDROP_BASE`
- `TMDB_PROXY_ENABLED`
- `TMDB_PROXY_URL`

说明：
- 这组变量属于当前主流程真实有效配置
- `TMDB_TOKEN` 未设置时不会请求 TMDB，扫描会继续尝试 NFO / Bangumi / Local fallback

### 6.3 最小 API 鉴权变量

- `CYBER_API_TOKEN`
- `API_TOKEN`
- `CYBER_AUTH_ENABLED`
- `CYBER_AUTH_EXEMPT_MEDIA_GET`
- `CYBER_USER_MANAGEMENT_ENABLED`
- `CYBER_SESSION_SECRET`
- `CYBER_BOOTSTRAP_ADMIN_USERNAME`
- `CYBER_BOOTSTRAP_ADMIN_PASSWORD`
- `CYBER_SESSION_COOKIE_SECURE`
- `CYBER_SESSION_DAYS`
- `CYBER_LOGIN_RATE_LIMIT_ENABLED`
- `CYBER_LOGIN_RATE_LIMIT_MAX_ATTEMPTS`
- `CYBER_LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `CYBER_LOGIN_RATE_LIMIT_LOCK_SECONDS`

说明：
- 推荐使用 `CYBER_API_TOKEN`，`API_TOKEN` 只作为兼容别名
- 未设置 token 时不启用鉴权，便于本地开发和当前前端继续联调
- 设置 token 后，管理类接口要求 `Authorization: Bearer <token>` 或 `X-Cyber-API-Token: <token>`
- 媒体流和图片 GET 默认豁免，避免浏览器播放器与外部播放器无法带鉴权头
- 开启用户管理后，媒体流和图片也会走 Cookie 会话鉴权与用户可见性校验，不再公开豁免

---

## 7. 维护建议

### 短期
- 暂时不要激进删除历史字段
- 先补注释与文档，确保维护人员知道哪些配置真正生效
- 新部署优先通过环境变量注入 `TMDB_TOKEN`、`CYBER_API_TOKEN`、Super CDN token 等敏感配置

### 中期
- 将旧版单源配置逐步移除
- 将扫描配置与应用配置进行职责拆分
