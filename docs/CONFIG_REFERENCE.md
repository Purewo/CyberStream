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

### 2.3 扫描规则配置

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

### 2.4 FFmpeg 实时转码配置

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
2. 当前虽然已支持优先从环境变量读取 TMDB / 历史 WebDAV 配置，但文件内仍保留默认值回退，尚未完成彻底外置化
3. 配置职责边界不够清晰：
   - 一部分是 Flask 配置
   - 一部分是扫描规则
   - 一部分是历史运行配置

---

## 6. 环境变量支持（当前已兼容）

为降低后续迁移风险，当前 `backend/config.py` 已支持“**优先环境变量，未设置则回退现有默认值**”的兼容模式。

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
- 后续如果要继续做配置外置化，应优先从这组开始

---

## 7. 维护建议

### 短期
- 暂时不要激进删除历史字段
- 先补注释与文档，确保维护人员知道哪些配置真正生效
- 新部署优先通过环境变量注入 TMDB / 历史兼容敏感配置

### 中期
- 将敏感信息彻底迁移到环境变量或独立配置机制，不再保留明文默认值
- 将旧版单源配置逐步移除
- 将扫描配置与应用配置进行职责拆分
