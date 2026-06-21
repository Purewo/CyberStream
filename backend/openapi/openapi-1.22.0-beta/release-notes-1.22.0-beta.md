# 1.22.0-beta 更新说明

本文档记录代托管多租户最小闭环接口变化。1.21.0-beta 目录保留为历史契约，1.22.0-beta 是当前 `/api/v1/openapi.json` 返回版本。

## 代托管多租户

- 新增 `Account` / `AccountMembership` 账号空间模型，业务数据以 `current_account.id` 为隔离边界。
- 新增开放注册 `POST /api/v1/auth/register`：创建普通 `users.role=user` 登录身份、账号空间、owner membership、默认片库和首页配置，并直接建立 Cookie 会话。
- `GET /api/v1/auth/me`、`POST /api/v1/auth/login` 返回新增 `current_account`、`account_role`、`permissions.manage_storage`、`permissions.manage_account_users`。
- 新增 `POST /api/v1/auth/playback-ticket`，用于 PC/mpv 等拿不到 HttpOnly Cookie 的外部播放器换取 12 小时播放临时票据；`/resources/{id}/stream`、`stream-transcoded`、`streaming-qualities`、`audio-transcode`、`subtitles/online/search` 和 `subtitles/online/download` 可通过 `?ticket=` 鉴权，非法或过期返回 `40130`，并继续按 current_account 做隔离。
- 普通注册用户不会成为平台 admin；账号 owner 可管理自己账号下的片库、挂载、扫描、审查和元数据。
- 平台级 `users.role=admin` 保留给托管商语义；在没有平台后台时，默认也只操作自己的 current account。

## 自助挂载和扫描

- 代托管模式不再封禁账号 owner 的 storage source 创建、托管云盘登录、默认片库绑定和扫描入口。
- `GET /api/v1/storage/sources`、详情、刷新、扫描、删除等均按当前账号过滤；直接访问其他账号 id 优先返回 404。
- 新建托管 AList/OpenList mount path 采用账号前缀，目标格式为 `/cyberstream/accounts/{account_id}/sources/{source_id}/...`。
- 百度网盘 OAuth callback 属于公开回调入口，也会根据 `oauth_state -> source.account_id` 恢复账号上下文，确保最终 OpenList mount path 不会丢失 account 前缀。
- storage source 创建后自动绑定账号默认片库，前端注册后可直接进入挂载和扫描流程。
- 资源治理、批量重识别等持久化后台任务会写入 `account_id`，异步执行和 `/jobs` 查询都按账号上下文隔离。

## 服务器级配置仍由平台维护

以下能力在 `CYBER_HOSTED_MANAGED_MODE=true` 下仍返回 `40390`：

- `PUT /api/v1/system/tmdb-config`
- `POST /api/v1/images/preload`
- `POST /api/v1/images/refresh`
- `DELETE /api/v1/movies/{id}/images/{kind}`
- `GET /api/v1/movies/{id}/images/{kind}?refresh=true`

前端应使用 `permissions.manage_server_config=false` 隐藏 TMDB token、代理、CDN 和图片缓存运维入口。

## 数据库和迁移

- 新增 `CYBER_DATABASE_URL` / `DATABASE_URL` 优先级，正式代托管建议使用 PostgreSQL。
- 引入 Flask-Migrate/Alembic 迁移目录，SQLite 继续作为本地开发和自托管 fallback。
- 旧数据迁移会要求存在 `pureworld`（或 `CYBER_LEGACY_ACCOUNT_USERNAME` 指定用户），并把既有片库、影视、资源、审查、历史、收藏和字幕设置归入该账号。
- `movies.tmdb_id`、`libraries.name`、`libraries.slug` 从全局唯一调整为账号内唯一。
- SQLite 运行时兼容 patch 会移除旧库遗留的全局 `movies.tmdb_id` 唯一索引，并创建 `account_id + tmdb_id` 账号级唯一索引；正式 hosted 仍建议走 Alembic/PostgreSQL。

## 前端必须调整

- 启动、登录、注册、退出和 401 后统一请求 `/api/v1/auth/me`。
- 不要在普通业务请求里传 `account_id`，也不要信任本地保存的 account 状态决定数据范围。
- 使用 `permissions.manage_storage` 展示云盘挂载入口。
- 使用 `permissions.manage_catalog` 展示片库、扫描、审查工作台和元数据编辑入口。
- 不要把 `users.role=user` 理解成没有管理自己片库的权限；账号内权限看 `account_role=owner` 和 permissions。

## 兼容性

- 登录、退出、播放、历史、收藏、字幕等旧接口路径保持不变。
- `AuthStatus.permissions.manage_users` 保留平台用户管理语义；未来家庭子账号管理会走账号级接口，1.22.0-beta 中 `manage_account_users=false`。
- 代托管部署中的 `40162` 后端使用本版本契约；旧 `40160` 自托管/试点后端不要和新前端配置混用。

---

# 1.21.0-beta 历史更新说明

本文档记录 `1.21.0-beta` 的接口变化，作为其他视频归档联调基线。

## API token 鉴权开关

- 用户管理开启时，`CYBER_API_TOKEN` 管理员后门现在也严格遵守 `CYBER_AUTH_ENABLED`。
- 显式设置 `CYBER_AUTH_ENABLED=false` 后，即使环境中仍保留旧 token，也不能通过 Bearer 或 `X-Cyber-API-Token` 获得管理员权限；Cookie 会话登录不受影响。
- 登录失败限流新增 `CYBER_LOGIN_RATE_LIMIT_MAX_BUCKETS`，默认最多保留 `10000` 个 `IP:username` 尝试桶，防止公开登录接口被大量唯一用户名撑爆进程内记录。
- 登录失败限流现在只读取 Flask/ProxyFix 处理后的 `request.remote_addr`，不再直接信任任意 `X-Forwarded-For` 头。
- 托管试点前端契约已更新：`/api/v1/auth/me` 是启动探测入口，Cookie 会话请求必须带 `credentials: include`，受保护接口返回 `401` 时前端应重新确认登录态。
- 新增 `CYBER_HOSTED_MANAGED_MODE` 统一代托管模式；开启后 `/api/v1/auth/me` 返回 `hosted_managed_mode=true` 且 `permissions.manage_server_config=false`。
- 代托管模式下，管理员 session 和有效 API token 也不能修改服务器级配置或触发运维写接口；被封禁的 TMDB 配置、存储源/托管云盘写入、专辑来源绑定、扫描、图片 CDN/cache 预热刷新清理会返回 HTTP `403`、业务码 `40390`。
- `AuthStatus.permissions` 现在显式暴露 `personal_favorites` 与 `personal_vault`，普通账号可在自己的可见影片范围内使用收藏和收藏保险库。
- 普通账号现在可以访问可见资源的云端转码清晰度、云端转码播放和在线字幕下载；未授权资源仍返回 `403`。
- 非对象 JSON 请求体不再让登录、历史、字幕等接口落入 `500`，会按缺字段或非法凭据返回稳定 `4xx`。

## 运维 smoke check

- `scripts/backend_smoke_check.py` 支持 `--login-username` / `--login-password`，也可读取 `CYBER_BACKEND_SMOKE_USERNAME` / `CYBER_BACKEND_SMOKE_PASSWORD`；强制用户登录且 API token 后门关闭时，会先登录再用 Cookie 检查受保护接口。

## 官方客户端更新检查

- 没有正式 update manifest 或没有可用 CDN 下载项时，`update_available` 不再返回 `true`，避免客户端出现“提示可更新但没有下载按钮”的坏状态；响应仍保留 `warnings` 说明 manifest/download 缺失。

## 托管图片资产

- 新增 `CYBER_IMAGE_ASSET_PREFER_ORIGINAL_URLS`。开启后 `poster_asset_url/backdrop_asset_url` 优先返回原始元数据图片链接，`asset_urls.strategy=original_local`，适合代托管试点阶段不启用图片 CDN。
- `CYBER_SUPERCDN_SERVE_ASSET_URLS` 现在只有在 Super CDN provider 启用时才会返回历史 CDN URL，避免 provider 关闭后仍把旧 CDN 对象作为首选图片地址。

## 外部资源聚合搜索

- 新增 `GET /api/v1/aggregator/sources`、`/search`、`/detail`、`/magnet`，将原 PC 本地桥接的外部影视资源站搜索并入后端统一 API。
- 每次请求只访问一个 `source`，不会在后端并发遍历全部资源站；`btbtla` 可通过后端配置走本机代理。
- `detail` / `magnet` 的 HTTP(S) `link` 必须属于所选 `source` 域名；相对链接会按该 source 根地址补全，跨域或本机地址会被拒绝。
- `magnet` 接口仍允许直接传 `magnet:?` 或 `ed2k://` URI；`detail` 接口不接受这两类非 HTTP 链接。
- `keyword` 最长 120 字符，`link` 最长 2048 字符，`page` 仅接受 `1..50`，未知 `source` 会在抓取前拒绝。
- 同一个 `source` 的抓取请求会串行执行；锁等待超时返回 `429`，避免共享 session/proxy 状态被并发请求互相覆盖。
- 模块化 OpenAPI 新增 `aggregator` 模块，便于前端按领域懒加载契约。

## 外部 URL scheme

- 后端播放、音频转码和字幕 URL 不再用 `PREFERRED_URL_SCHEME=https` 把公开 HTTP 请求隐式改写成 HTTPS。
- `PREFERRED_URL_SCHEME` 仅保留 Flask 原生语义；需要固定外部入口时使用 `CYBER_BACKEND_PUBLIC_BASE_URL=http://...` 或 `https://...`，scheme 会原样保留。
- 新增 `GET /api/v1/health`，作为 `GET /` 的 API 前缀健康检查别名，公开可访问，方便前端、反向代理和监控统一探活。
- local、SMB、FTP 视频流统一支持单段 `Range`、开放结尾范围和 suffix range；非法、多段或不可满足范围返回 `416` 与 `Content-Range: bytes */<size>`，不再落入 `500`。
- 播放流、字幕流和云端转码的 302 Location 只允许公网 HTTP(S) URL；本机、私网、链路本地、保留地址和非 HTTP scheme 会被拒绝。

## TMDB 配置预检

- 新增 `GET /api/v1/system/tmdb-config/check`，主动调用 TMDB 认证接口验证当前 token 是否有效。
- 响应不返回 token 明文；前端可在批量刮削前检查 `data.ready === true`，否则根据 `data.status` 展示 `missing_token`、`invalid_token`、`proxy_error`、`network_error` 等原因，避免无效配置下继续刮削。
- 新增平台托管用 `CYBER_TMDB_TOKEN_POOL` / `TMDB_TOKEN_POOL`，支持多个 TMDB bearer token 去重后轮询；`GET /system/tmdb-config` 和 `/check` 会返回 `token_pool_size`、`token_pool_enabled`、`token_valid_count`、`token_invalid_count`，但不会返回 token 明文。池子中部分 token 可用时 `status=partial_ok` 且 `ready=true`。

## QuarkTV / UCTV 云端转码播放

- 新增 `GET /api/v1/resources/{id}/streaming-qualities`，返回 provider 云端转码画质列表；当前支持 QuarkTV、UCTV 和 Aliyundrive。
- 新增 `GET /api/v1/resources/{id}/stream-transcoded?resolution=...`，按指定画质 302 到 provider 转码直链。
- `ResourcePlayback` 新增 `cloud_transcode`，前端可据此发现 `qualities_endpoint`、`stream_endpoint` 和 provider-specific 档位；QuarkTV/UCTV 常见为 `low/normal/high/super/2k/4k`，Aliyundrive 常见为 `ld/sd/hd/fhd/qhd/4k`。
- QuarkTV/UCTV 原始下载直链保留为 PC/外部播放器入口；前端 Web 播放应优先使用 `cloud_transcode`，避免 raw download URL 无法在线播放。
- QuarkTV/UCTV 挂载固定使用 OpenList `download` 原文件链路，不再要求前端提供 `download` / `streaming` 用户选择；同一个资源响应会同时暴露 raw stream 与 cloud transcode 入口。
- Aliyundrive 新增云端转码适配，后端通过托管 OpenList `video_preview` 能力获取清晰度列表；Aliyundrive raw stream 仍保留为网页/外部播放器原文件入口。
- 新增 `POST /api/v1/storage/managed/{quarktv|uctv}/qr/restart`，用于登录态被踢后在同一个 `source_id` 上重新扫码，不重建 CyberStream 存储源、不破坏资源索引和媒体库绑定。
- 新增光鸭、天翼、115、阿里云盘、百度网盘、123Pan 的 existing-source 重新登录入口；前端应优先用 restart/relogin 保留原 `source_id`，不要为了重新授权创建新来源。

## 资源库影片筛选

- `GET /api/v1/libraries/{id}/movies` 现在会正确应用 `genre`、`country`、`year` 查询参数，语义与全局 `GET /api/v1/movies` 保持一致。
- `year` 支持单一年份或 `2020-2024` 这种闭区间。

## 其他视频归档

新增接口：

- `GET /api/v1/other-videos`
- `POST /api/v1/movies/manual`
- `POST /api/v1/movies/{id}/resources/attach`
- `POST /api/v1/metadata/pending-review/backfill`

用途：

- 面向自建课程、爬虫视频、录屏和其他不可能稳定刮削成功的视频。
- 管理员可以先新建一个手工电影或电视剧壳，只要求标题和简介。
- 可把已有 `MediaResource` 重新挂入该条目，并同步加入一个或多个资源库。
- 可在挂载资源时更新 `season/episode/title/overview/label`。

兼容性：

- 新建手工条目默认 `catalog_visibility_status=hidden`，不会污染当前普通影视库。
- 手工来源为 `LOCAL_MANUAL_MOVIE` / `LOCAL_MANUAL_TV`，默认不进入 `needs_attention` 元数据工作台。
- 接口只修改数据库索引和资源元数据，不移动、不删除实体视频文件。
- `catalog_visibility.status=pending_review` 的条目不再出现在 `/other-videos`；历史遗留的可疑 `auto` 条目可用 backfill 先 dry-run 再回填到待审批池。

## 批量重识别搜索关键词覆盖

- `POST /api/v1/metadata/re-scrape/plan` 调整为本地快速关键词预览：不访问 TMDB、sidecar NFO 或存储 provider，不再因为 dry-run 真搜 TMDB 阻塞批量操作。
- 每条成功计划新增 `search_query`、`search_title` 和 `search_year`，明确提交后实际会用什么关键词搜索；旧 `preview/diff/resolution/explanation` 在该阶段固定为 `null`。
- `apply_payload.items[]` 会带出 `search_title/search_year`，前端可先展示可编辑关键词，再把用户修正后的值提交给 `/metadata/re-scrape` 或 `/metadata/re-scrape/jobs`。
- `apply_payload.items[]` 同步带出 `media_type_hint`，避免前端确认关键词后丢失电影/剧集类型，导致提交阶段重新误判。
- 单条和批量 re-scrape 请求新增可选 `search_title`、`search_year`；`query_override` 是 `search_title` 的兼容别名。显式传 `search_year: null` 可清除路径解析误判年份。
- 单条和批量 re-scrape 默认不读取同目录 sidecar NFO，避免离线/高延迟挂载点把一次重新识别拖到几十秒；确实需要 NFO 时传 `allow_nfo=true` 或 `include_sidecar_nfo=true`。
- 响应中的 `entity_context` 继续表示路径解析结果；`search_query` 表示实际进入 metadata pipeline 的搜索参数，避免二者混淆。
- `plan.apply_endpoint` 默认指向 `/metadata/re-scrape/jobs`；创建任务后响应会返回 `progress_endpoint` 和建议轮询间隔 `poll_interval_ms`。
- 修复 `DTS5.1` 这类音轨标记被路径解析器误识别为 `S5` 季号的问题，避免电影被当作剧集搜索。

## 剧集诊断多版本片源

- `SeasonEpisodeDiagnostics` 新增 `alternate_episode_numbers` 和 `alternate_episode_resources`。
- 当一季集数完整、同一集只是存在多个可播放版本时，后端会把这些资源标记为 alternate，不再作为 `duplicate_episode_numbers` 进入剧集复核队列。
- `SeasonMetadata` 新增 `aired_episode_count`；剧集完整性诊断优先按已播集数计算，避免 TMDB 已登记但尚未播出的未来集进入缺集复核。

## NFO 候选资源留痕

- `MetadataTrace` 和 `MetadataEditContext` 新增 `nfo_candidate_count` 与 `nfo_candidates`。
- 后续扫描和 re-scrape 会把同目录 sidecar NFO 候选以 `{ path, name, kind }` 摘要写入资源 trace，前端可在资源审查或手动编辑界面直接展示。
- 历史资源可能只保存了 `has_nfo_candidates=true`，没有候选路径；这类资源详情会兼容返回 `nfo_candidate_count=1` 且 `nfo_candidates=[]`。


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
- 当前单用户/默认模式临时按默认管理员处理；开启用户系统后每个已登录用户访问自己的收藏保险库和收藏虚拟库。
- 访问收藏关系和 `libraries/favorites*` 前，默认管理员或已登录用户必须先设置并解锁 6 位数字 PIN；开启用户系统后 PIN 不能与登录密码相同。
- 保险库 PIN 在 24 小时窗口内最多修改 10 次；第 11 次会锁定保险库直到窗口结束。
- 管理员首次收藏后，保险库仍不出现在 `GET /api/v1/libraries` 的片库列表中，避免导航层泄露保险库存在性；前端应使用固定保险库入口和 `/api/v1/user/vault/status` 驱动展示。
- “收藏家”成就的 `favorites_count` 在默认模式统计默认管理员保险库；开启用户系统后只统计当前登录用户自己的保险库收藏。
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
- AList/OpenList 的 `StorageSource.config` 响应现在会脱敏 `token`、`password`、`otp_code`、`path_password`；同协议 `PATCH /storage/sources/{id}` 带回 `***` 时保留原始凭据，避免编辑配置时把真实 secret 覆盖为占位符。

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
- `POST /api/v1/scan` 不要求预先创建专辑或资源库目录绑定；没有专辑时仍会扫描已配置存储源。
- `POST /api/v1/storage/sources/{id}/scan` 不要求该存储源已绑定专辑；没有显式 `root_path` 时按存储源根目录扫描。

## TMDB 本机配置

- 新增 `GET /api/v1/system/tmdb-config`，返回 `token_set`、`proxy_enabled`、`proxy_url` 和 `proxy_url_redacted`；不会返回 TMDB token 明文，代理 URL 含凭证时也会脱敏。
- 新增 `PUT /api/v1/system/tmdb-config`，支持写入或清空 `TMDB_TOKEN`，以及更新 `TMDB_PROXY_ENABLED` / `TMDB_PROXY_URL`。接口拒绝换行/控制字符注入，使用跨线程/Unix 进程锁和原子替换写入 `.env.local`，写盘成功后才更新运行时环境，响应包含 `hot_reload`。

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
- 在线字幕原始下载、解压、嵌套压缩包和手动上传默认限制为 20MB，ZIP/TAR/7z 默认最多 200 个条目，归档内候选字幕累计默认最多 40MB；SubHD/SrtKu 下载、ZIP/GZip 解压均按限制流式读取，SrtKu 不再在 provider 内自行解压，7z 会先按条目元数据预检并只解压候选文件，超限返回 `413`。可通过 `CYBER_ONLINE_SUBTITLE_DOWNLOAD_MAX_BYTES`、`CYBER_ONLINE_SUBTITLE_EXTRACTED_MAX_BYTES`、`CYBER_ONLINE_SUBTITLE_NESTED_ARCHIVE_MAX_BYTES`、`CYBER_ONLINE_SUBTITLE_ARCHIVE_MAX_ENTRIES`、`CYBER_ONLINE_SUBTITLE_ARCHIVE_TOTAL_MAX_BYTES`、`CYBER_SUBTITLE_MANUAL_UPLOAD_MAX_BYTES` 调整，设为 `0` 可关闭对应限制；WebVTT 转换仍由 `CYBER_SUBTITLE_WEBVTT_CONVERSION_MAX_BYTES` 独立控制。
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
