# 1.21.0-beta 更新说明

本文档记录 `1.21.0-beta` 的接口变化，作为其他视频归档联调基线。

## 外部 URL scheme

- 后端播放、音频转码和字幕 URL 不再用 `PREFERRED_URL_SCHEME=https` 把公开 HTTP 请求隐式改写成 HTTPS。
- `PREFERRED_URL_SCHEME` 仅保留 Flask 原生语义；需要固定外部入口时使用 `CYBER_BACKEND_PUBLIC_BASE_URL=http://...` 或 `https://...`，scheme 会原样保留。

## QuarkTV / UCTV 云端转码播放

- 新增 `GET /api/v1/resources/{id}/streaming-qualities`，返回 QuarkTV/UCTV provider 云端转码画质列表。
- 新增 `GET /api/v1/resources/{id}/stream-transcoded?resolution=...`，按指定画质 302 到 provider 转码直链。
- `ResourcePlayback` 新增 `cloud_transcode`，前端可据此发现 `qualities_endpoint`、`stream_endpoint` 和支持的 `low/normal/high/super/2k/4k` 档位。
- QuarkTV/UCTV 原始下载直链保留为兼容入口，但前端 Web 播放应优先使用 `cloud_transcode`，避免 raw download URL 无法在线播放。
- QuarkTV/UCTV 挂载时 `link_method` 明确支持 `download` / `streaming` 用户选择；`source.config` 会返回当前选择。
- 新增 `POST /api/v1/storage/managed/{quarktv|uctv}/qr/restart`，用于登录态被踢后在同一个 `source_id` 上重新扫码，不重建 CyberStream 存储源、不破坏资源索引和媒体库绑定。

## 资源库影片筛选

- `GET /api/v1/libraries/{id}/movies` 现在会正确应用 `genre`、`country`、`year` 查询参数，语义与全局 `GET /api/v1/movies` 保持一致。
- `year` 支持单一年份或 `2020-2024` 这种闭区间。

## 其他视频归档

新增接口：

- `GET /api/v1/other-videos`
- `POST /api/v1/movies/manual`
- `POST /api/v1/movies/{id}/resources/attach`

用途：

- 面向自建课程、爬虫视频、录屏和其他不可能稳定刮削成功的视频。
- 管理员可以先新建一个手工电影或电视剧壳，只要求标题和简介。
- 可把已有 `MediaResource` 重新挂入该条目，并同步加入一个或多个资源库。
- 可在挂载资源时更新 `season/episode/title/overview/label`。

兼容性：

- 新建手工条目默认 `catalog_visibility_status=hidden`，不会污染当前普通影视库。
- 手工来源为 `LOCAL_MANUAL_MOVIE` / `LOCAL_MANUAL_TV`，默认不进入 `needs_attention` 元数据工作台。
- 接口只修改数据库索引和资源元数据，不移动、不删除实体视频文件。

## 电视剧资源按季 hydrate

- `GET /api/v1/movies/{id}/resources` 新增可选 `season` query。
- 不传 `season` 时保持旧行为，仍返回全量 `items` 和全量分组索引。
- 传 `season=N` 时，`items` 只返回该季资源和无季资源，`groups.seasons` 仍保留完整季索引。
- 响应 `summary` 额外暴露 `selected_season`、`hydrated_item_count` 和 `hydrated_playback_source_count`，方便前端识别局部 hydrate。

## 单片资源同步

- 新增 `POST /api/v1/movies/{id}/resources/sync`，用于前端针对某一部影视一键刷新目录并补扫新增资源。
- 后端按当前影片已有资源路径推导每个存储源的最小扫描目录，默认不把多目录影片扩大成整盘扫描。
- 默认 `refresh=true`；只有 `alist/openlist` 会在扫描前刷新上游目录缓存，其他存储源直接扫描。
- 任务异步执行并复用现有扫描锁；返回 `202` 后前端轮询 `GET /api/v1/scan`，扫描完成后重新拉取 `/movies/{id}/resources`。
- 该接口不强制把任意新文件挂到当前影视，仍遵循现有路径解析和元数据匹配规则。

## 用户成就

- 新增 `GET /api/v1/user/achievements`，返回统一成就定义 `defs` 和当前用户解锁状态 `user`。
- 新增 `POST /api/v1/user/achievements/unlock`，用于前端幂等解锁 `category=behavior` 的交互类成就。
- 后端自动结算 `category=milestone` 中已有可靠数据依据的指标：看完影片数、收藏数、老片观看、4K/REMUX、Dolby Vision、Dolby Atmos、多设备播放。
- milestone 不能通过 unlock 端点直接解锁，避免前端绕过后端统计口径。

## 收藏虚拟资源库

- 新增 `GET /api/v1/user/favorites`、`GET/POST/DELETE /api/v1/user/favorites/{movie_id}`，用于当前用户收藏影视。
- 新增 `GET /api/v1/user/vault/status`、`POST /api/v1/user/vault/password`、`POST /api/v1/user/vault/unlock`、`POST /api/v1/user/vault/lock`，用于保险库独立 PIN 门禁。
- 当前单用户/默认模式临时按默认管理员处理；开启用户系统后保险库仅已登录管理员本人可访问，普通用户不能读取或写入收藏虚拟库。
- 访问收藏关系和 `libraries/favorites*` 前，默认管理员或已登录管理员必须先设置并解锁 6 位数字 PIN；开启用户系统后 PIN 不能与登录密码相同。
- 保险库 PIN 在 24 小时窗口内最多修改 10 次；第 11 次会锁定保险库直到窗口结束。
- 管理员首次收藏后，保险库仍不出现在 `GET /api/v1/libraries` 的片库列表中，避免导航层泄露保险库存在性；前端应使用固定保险库入口和 `/api/v1/user/vault/status` 驱动展示。
- “收藏家”成就的 `favorites_count` 在默认模式统计默认管理员保险库；开启用户系统后只统计管理员自己的保险库收藏，避免普通用户间接暴露保险库数量。
- 收藏虚拟库支持普通资源库读取入口：`GET /api/v1/libraries/favorites`、`/movies`、`/featured`、`/recommendations`、`/filters`。
- 收藏虚拟库没有存储源绑定，也没有 `/api/v1/libraries/favorites/scan`；前端应根据 `actions.can_scan=false` 隐藏扫描入口。

## 契约变化

- `MovieSimple`、`MovieDetailed` 和 `MetadataWorkItem` 增加 `manual_content`。
- `MetadataState.source_group` 增加 `manual`。
- `MetadataState.confidence` 增加 `manual`。
- `/api/v1/metadata/review-taxonomy` 的 taxonomy version 升为 `review-workbench-v2`，新增“其他视频归档”边界。

## 文档

- `docs/API_OVERVIEW.md` 增加其他视频归档接口说明。
- `docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md` 增加其他视频归档页边界。

## 文档接口

新增公开只读文档入口，减少前端联调时人工转发契约文件：

- `GET /api/v1/docs`：返回当前 OpenAPI 和 Markdown 文档索引。
- `GET /api/v1/openapi.json`：返回当前 OpenAPI JSON 原文，不包标准响应壳。
- `GET /api/v1/docs/openapi.json`：OpenAPI JSON 的文档命名空间别名。
- `GET /api/v1/openapi/modules`：返回模块化 OpenAPI 索引，供前端按领域懒加载契约。
- `GET /api/v1/openapi/modules/{module_key}.json`：返回单个模块 OpenAPI JSON 原文，只包含该模块 paths 和递归引用到的 components。
- `GET /api/v1/docs/{doc_key}`：返回白名单 Markdown 文档原文。

当前白名单 key：

- `release-notes`
- `api-overview`
- `frontend-review-workbench`
- `frontend-user-management`
- `frontend-audio-transcode`
- `frontend-managed-guangyapan`
- `frontend-managed-tianyicloud`
- `frontend-managed-115cloud`
- `frontend-managed-aliyundrive`
- `frontend-managed-baidunetdisk`
- `frontend-managed-quark-uc`
- `storage-config-flow`
- `runbook`
- `test-checklist`

## 存储源目录刷新

新增 `POST /api/v1/storage/sources/{id}/refresh`，用于手动刷新已保存存储源的指定目录缓存。

说明：

- 当前支持 `alist/openlist/guangyapan/tianyicloud/115cloud/aliyundrive/baidunetdisk/quarktv/uctv`，底层调用上游 `fs/list` 并带 `refresh=true`
- 该接口只刷新目录缓存并返回刷新后的列表，不触发扫描、不触发刮削
- `StorageSource.actions` 现在会额外暴露 `can_refresh`

## 托管光鸭云盘

- 新增 beta 存储类型 `guangyapan`，由 CyberStream 通过本机 AList 管理接口创建 GuangYaPan 挂载。
- 新增 `POST /api/v1/storage/managed/guangyapan/sms/start`，提交手机号并触发光鸭短信验证码。
- 新增 `POST /api/v1/storage/managed/guangyapan/sms/verify`，提交短信验证码后把来源状态更新为 `ready`。
- 新增前端专项联调文档 `GET /api/v1/docs/frontend-managed-guangyapan`，包含短信登录时序、状态机、错误码和播放链路说明。
- `sms_pending` 状态下托管光鸭来源的 `source.actions.can_preview/can_scan/can_refresh/can_stream` 均为 `false`，避免前端误展示可用操作。
- 托管光鸭的 `StorageSource.config` 与健康检查响应不会暴露 localhost AList 地址或内部挂载路径。
- 托管光鸭播放仍走 302，但后端会先访问 localhost AList `/d/...`，解析出最终云盘直链后再返回给前端，不暴露 AList 地址。
- 运行时需启用 `CYBER_MANAGED_ALIST_ENABLED=true` 并配置本机 AList 地址和管理凭据。

## 托管天翼云盘

- 新增 beta 存储类型 `tianyicloud`，由 CyberStream 通过本机 OpenList 管理接口创建 `189CloudTV` 挂载。
- 新增 `POST /api/v1/storage/managed/tianyicloud/qr/start`，创建托管来源并返回二维码 data URL。
- 新增 `POST /api/v1/storage/managed/tianyicloud/qr/poll`，轮询扫码结果并在认证成功后把来源状态更新为 `ready`。
- 新增前端专项联调文档 `GET /api/v1/docs/frontend-managed-tianyicloud`，包含扫码时序、状态机、错误码和播放链路说明。
- `qr_pending` 状态下托管天翼来源的 `source.actions.can_preview/can_scan/can_refresh/can_stream` 均为 `false`，避免前端误展示可用操作。
- 托管天翼的 `StorageSource.config` 与健康检查响应不会暴露 localhost OpenList 地址或内部挂载路径。
- 托管天翼播放仍走 302，但后端会先访问 localhost OpenList `/d/...`，解析出最终云盘直链后再返回给前端，不暴露 OpenList 地址。
- 运行时需启用 `CYBER_MANAGED_OPENLIST_ENABLED=true` 并配置本机 OpenList 地址和管理凭据。

## 托管 115 云盘

- 新增 beta 存储类型 `115cloud`，由 CyberStream 通过本机 OpenList 管理接口创建 `115 Cloud` 挂载。
- 新增 `POST /api/v1/storage/managed/115cloud/qr/start`，创建托管来源并返回 115 二维码 data URL。
- 新增 `POST /api/v1/storage/managed/115cloud/qr/poll`，轮询扫码状态；未扫码、已扫码待确认、过期和取消都按业务状态返回 `code=200`。
- 新建 115 来源默认使用 `qrcode_source=wechatmini`，避免占用用户常用的 Web、Android 或 iOS 登录态；仍允许前端显式传其他 OpenList 支持的端类型用于排障。
- 新增前端专项联调文档 `GET /api/v1/docs/frontend-managed-115cloud`，包含二维码登录、轮询状态机、过期/取消处理和播放链路说明。
- `qr_pending`、`qr_expired`、`qr_canceled` 状态下托管 115 来源的 `source.actions.can_preview/can_scan/can_refresh/can_stream` 均为 `false`。
- 托管 115 的 `StorageSource.config` 与健康检查响应不会暴露 localhost OpenList 地址、内部挂载路径、115 cookie 或二维码会话字段。
- 播放仍走 302：后端先访问 localhost OpenList `/d/...`，解析出最终 115 直链后再返回给前端，不暴露 OpenList 地址。
- 运行时复用 `CYBER_MANAGED_OPENLIST_ENABLED=true` 与本机 OpenList 管理凭据。

## 托管阿里云盘

- 新增 beta 存储类型 `aliyundrive`，由 CyberStream 通过阿里云盘 OpenAPI 二维码会话完成登录，再创建本机 OpenList `AliyundriveOpen` 挂载。
- 新增 `POST /api/v1/storage/managed/aliyundrive/qr/start`，创建托管来源并返回阿里云盘二维码 URL。
- 新增 `POST /api/v1/storage/managed/aliyundrive/qr/poll`，轮询扫码状态；未扫码、已扫码待确认、过期和取消都按业务状态返回 `code=200`。
- 新增前端专项联调文档 `GET /api/v1/docs/frontend-managed-aliyundrive`，包含二维码登录、轮询状态机、授权模式、错误码和播放链路说明。
- `qr_pending`、`qr_expired`、`qr_canceled` 状态下托管阿里云盘来源的 `source.actions.can_preview/can_scan/can_refresh/can_stream` 均为 `false`。
- 托管阿里云盘的 `StorageSource.config` 与健康检查响应不会暴露 localhost OpenList 地址、内部挂载路径、refresh token、access token 或二维码 sid。
- 播放仍走 302：后端先访问 localhost OpenList `/d/...`，解析出最终阿里云盘直链后再返回给前端，不暴露 OpenList 地址。
- 运行时复用 `CYBER_MANAGED_OPENLIST_ENABLED=true` 与本机 OpenList 管理凭据；未配置自有阿里 OpenAPI 凭据时，默认走 OpenList 公共工具链 `https://api.oplist.org/alicloud`，避免 AListgo token 与 OpenList renew API 不匹配。
- 生产建议配置 `CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_ID` 和 `CYBER_MANAGED_OPENLIST_ALIYUNDRIVE_CLIENT_SECRET`；`alistgo` 授权模式仅保留兼容，不建议用于托管 OpenList 挂载。

## 托管百度网盘

- 新增 beta 存储类型 `baidunetdisk`，由 CyberStream 通过百度开放平台 OAuth 授权，再创建本机 OpenList `BaiduNetdisk` 挂载。
- 新增 `POST /api/v1/storage/managed/baidunetdisk/oauth/start`，创建 pending 来源并返回百度 `authorization_url`。
- 新增 `POST /api/v1/storage/managed/baidunetdisk/oauth/poll`，轮询 OAuth 授权状态；未授权完成返回 `auth_state=oauth_pending`，失败返回 `oauth_failed`，成功返回 `ready`。
- 新增公开回调 `GET /api/v1/storage/managed/baidunetdisk/oauth/callback`，供百度开放平台回跳，前端不需要主动调用。
- 新增前端专项联调文档 `GET /api/v1/docs/frontend-managed-baidunetdisk`，包含 OAuth 时序、状态机、后端配置和播放链路说明。
- `oauth_pending`、`oauth_failed` 状态下托管百度网盘来源的 `source.actions.can_preview/can_scan/can_refresh/can_stream` 均为 `false`。
- 托管百度网盘的 `StorageSource.config` 与健康检查响应不会暴露 localhost OpenList 地址、内部挂载路径、百度 access token、refresh token 或 OAuth state。
- 百度网盘 Web 播放显式禁用：资源 `playback.web_player.supported=false`、`reason=baidunetdisk_requires_pc_client`，前端应提示用户下载/使用 PC 客户端。PC 模式通过 `external_player.requires_local_backend=true` 与 `requires_user_agent_rewrite=true` 交给本地后端处理百度上游 User-Agent。
- 运行时复用 `CYBER_MANAGED_OPENLIST_ENABLED=true` 与本机 OpenList 管理凭据，并必须配置 `CYBER_MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_ID` 和 `CYBER_MANAGED_OPENLIST_BAIDUNETDISK_CLIENT_SECRET`；百度开放平台回调地址应配置为公网后端 `/api/v1/storage/managed/baidunetdisk/oauth/callback`。

## 托管 123 云盘

- 新增 beta 存储类型 `123pan`，由 CyberStream 通过本机 OpenList 管理接口创建 `123Pan` 挂载。
- 新增 `POST /api/v1/storage/managed/123pan/login`，使用 123 云盘账号密码完成托管登录并直接返回 `auth_state=ready` 的存储源。
- 新增前端专项联调文档 `GET /api/v1/docs/frontend-managed-123pan`，明确这是账号密码登录，不是扫码或短信流程。
- 托管 123Pan 的 `StorageSource.config` 与健康检查响应不会暴露 localhost OpenList 地址、内部挂载路径或账号密码；响应只展示脱敏账号、`root_folder_id` 和 `platform`。
- `GET /api/v1/storage/capabilities` 为 `123pan` 返回 `managed=true`、`password_login=true`，前端可据此展示账号密码表单。
- 播放仍走 302：后端先访问 localhost OpenList `/d/...`，解析出最终 123Pan 直链后再返回给前端，不暴露 OpenList 地址。
- 运行时复用 `CYBER_MANAGED_OPENLIST_ENABLED=true` 与本机 OpenList 管理凭据。

## 托管 QuarkTV / UCTV

- 新增 beta 存储类型 `quarktv` 和 `uctv`，由 CyberStream 通过本机 OpenList 管理接口创建 `QuarkTV` / `UCTV` 挂载。
- 新增 `POST /api/v1/storage/managed/quarktv/qr/start`、`POST /api/v1/storage/managed/quarktv/qr/poll`。
- 新增 `POST /api/v1/storage/managed/uctv/qr/start`、`POST /api/v1/storage/managed/uctv/qr/poll`。
- 新增前端专项联调文档 `GET /api/v1/docs/frontend-managed-quark-uc`，包含二维码登录、轮询、状态机、错误码和播放链路说明。
- `qr_pending` 状态下托管 QuarkTV / UCTV 来源的 `source.actions.can_preview/can_scan/can_refresh/can_stream` 均为 `false`。
- 托管 QuarkTV / UCTV 的 `StorageSource.config` 与健康检查响应不会暴露 localhost OpenList 地址或内部挂载路径。
- 播放仍走 302：后端先访问 localhost OpenList `/d/...`，解析出最终网盘直链后再返回给前端，不暴露 OpenList 地址。
- 运行时复用 `CYBER_MANAGED_OPENLIST_ENABLED=true` 与本机 OpenList 管理凭据。

## 资源库扫描刷新

- `POST /api/v1/libraries/{id}/scan` 默认会在扫描前刷新支持该能力的 `alist/openlist/guangyapan/tianyicloud/115cloud/aliyundrive/baidunetdisk/123pan/quarktv/uctv` 绑定目录。
- 前端可传 `{"refresh": false}` 跳过上游刷新，维持纯扫描行为。
- 目录刷新失败只写入扫描状态和后端日志，不会阻断后续扫描与刮削。
- `POST /api/v1/scan` 在没有任何启用的资源库目录绑定时会返回 `40013`，避免旧全库扫描入口误扫存储源根目录。
- `POST /api/v1/storage/sources/{id}/scan` 在没有显式 `root_path` 且该存储源未绑定任何资源库时会返回 `40013`，避免误触发存储源根目录扫描。

## TMDB 本机配置

- 新增 `GET /api/v1/system/tmdb-config`，返回 `token_set`、`proxy_enabled`、`proxy_url`，不会返回 TMDB token 明文。
- 新增 `PUT /api/v1/system/tmdb-config`，支持写入或清空 `TMDB_TOKEN`，以及更新 `TMDB_PROXY_ENABLED` / `TMDB_PROXY_URL`。写入 `.env.local` 后会尽量热更新运行时配置，响应包含 `hot_reload`。

## 官方客户端更新检查

- 新增公开只读 `GET /api/v1/system/update-check`，用于 PC 客户端检查最新官方发行版。
- 响应返回 `latest.version`、`latest.release`、`update_available`、`downloads` 和 `selected_download`。
- 下载项只来自后端发布清单中的 CDN URL；非 CDN URL 会被忽略并写入 `warnings`。
- 前端只消费该官方接口，不对接 CDN 控制面；CDN 上传、建桶和清理属于后端发布运维流程。

## 在线字幕搜索稳定性

- 默认在线字幕搜索继续只跑 `subhd`，`srtku` 保持显式慢备用源。
- 搜索关键字默认先使用资源展示标题，再使用原名和文件名，避免中文片名资源优先被英文文件名带偏。
- 显式传入 `srtku` 时后端会实际尝试该备用源，但受独立超时预算限制；超时会记录到 `providers.errors`，并返回 `reason=timeout`。
- `CYBER_ONLINE_SUBTITLE_SRTKU_SEARCH_TIMEOUT_SECONDS` 默认改为 `5` 秒。
- 字幕下载、手动上传和 WebVTT 预览转换默认不限制字幕文件大小；如需限制，可显式设置 `CYBER_ONLINE_SUBTITLE_EXTRACTED_MAX_BYTES`、`CYBER_ONLINE_SUBTITLE_NESTED_ARCHIVE_MAX_BYTES`、`CYBER_SUBTITLE_MANUAL_UPLOAD_MAX_BYTES` 或 `CYBER_SUBTITLE_WEBVTT_CONVERSION_MAX_BYTES`。
- 搜索候选现在固定带 `downloads` 数组，前端可使用 `items[].downloads[].download_index` 调用下载或绑定；SubHD 只有默认入口 `0`。
- Provider 下载运行时异常会收敛成 `502` 来源错误并返回可读 `msg`，不再统一落到泛化 `50061`。

## 手动元数据匹配防幽灵数据

- `POST /api/v1/movies/{id}/metadata/match` 默认改为 dry-run 预览，不再因为前端点击候选就直接写库。
- 前端确认覆盖时需提交预览返回的 `apply_payload`，其中包含 `apply=true`。
- 预览响应新增 `current`、`preview`、`identity`、`diff`、`warnings`、`apply_method`、`apply_endpoint`、`apply_payload`。
- 当候选和当前影片最终都没有海报时，`apply=true` 会返回 `409`，防止无海报影片被前端过滤成不可见幽灵数据；确需写入时传 `allow_missing_poster=true`。

## AniList 元数据来源

- 新增 `anilist` provider，使用 AniList 官方 GraphQL API，不需要密钥。
- `GET /api/v1/metadata/providers` 会返回 `anilist`，支持候选搜索和显式扫描刮削，但不进入默认 provider 顺序。
- `GET /api/v1/movies/{id}/metadata/search?providers=anilist` 可返回 `candidate_id=anilist/<id>`、`source_url`、`episode_count`、`format`、海报和评分。
- `POST /api/v1/movies/{id}/metadata/match` 支持 `candidate_id=anilist/<id>` 或 AniList anime URL。
- `ANILIST` 入库后归为 `metadata_source_group=anilist`，默认无需进入元数据审查队列。
