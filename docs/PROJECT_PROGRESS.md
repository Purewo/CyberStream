# PROJECT_PROGRESS

## 2026-05-03

### 1.21.0 其他视频归档

新增手工归档接口，用于自建课程、爬虫视频和其他不适合自动刮削的资源：

- `GET /api/v1/other-videos`：返回待手工归档的其他视频队列。
- `POST /api/v1/movies/manual`：新建手工电影/电视剧壳，默认隐藏，不影响普通影视库。
- `POST /api/v1/movies/{movie_id}/resources/attach`：把已有 `MediaResource` 挂入指定影片，并可顺手更新季/集、标题和简介。

手工内容会被识别为 `LOCAL_MANUAL_MOVIE` / `LOCAL_MANUAL_TV`，默认不进入 `needs_attention` 工作台，也不会再被当成刮削失败条目。

### 审查工作台边界收口

已完成后端审查工作台边界字典和前端对接说明：

- 新增 `GET /api/v1/metadata/review-taxonomy`，返回普通影视库、元数据审查、剧集审查、资源治理和目录发布控制的固定分类。
- `issue_code` 现在有统一字典，可映射到列表入口、详情入口、推荐动作和批量 dry-run 动作，前端不再需要按 `scraper_source` 自行推断。
- 补齐 `BANGUMI` 元数据来源边界：`metadata_review_priority=none` 与 OpenAPI 枚举现在包含 `BANGUMI/bangumi`。
- 新增 `docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md`，明确普通列表、审查工作台、资源治理和发布隐藏的使用边界。

## 2026-05-02

### 1.20.0 用户管理第一阶段

已完成后端用户管理基础能力，默认关闭，不影响当前公网使用：

- 新增 `admin/user` 两级角色和 Cookie 会话登录。
- `CYBER_API_TOKEN` 保留为管理员后门。
- 支持环境变量引导初始管理员。
- 普通用户只能读取可见影视、播放、维护自己的观看历史和字幕样式。
- 用户可见性通过资源库 allow/deny 规则控制，默认可见全部公开影视，deny 优先。
- 开启用户管理后，列表、详情、资源、图片、播放流、字幕、推荐和历史都会校验当前用户可见性。
- 补齐用户管理安全底座：最后一个启用管理员保护、密码/角色/启用状态变更后的 session 版本失效、登录失败限流、审计日志，以及普通用户自助资料/密码接口。
- 新增 OpenAPI `1.20.0-beta`。

### PC / 外部播放器播放契约第一阶段

前端暂无阻塞后，继续推进播放体验中低风险的一环：不改视频主播放链路，只补外部播放器交接契约。

已完成：

- 新增 `GET /api/v1/resources/<id>/external-playback`，返回面向 PC/外部播放器的 handoff manifest。
- manifest 包含绝对 `stream.url`、默认字幕 URL、`handoff.playlist_url`、`player_profiles` 和关键资源信息摘要。
- `GET /api/v1/resources/<id>/external-playback?format=m3u` 返回 `audio/x-mpegurl` M3U 播放列表。
- M3U 复用现有 `/stream` URL；有默认字幕时附带 `#EXTVLCOPT:sub-file=...`。
- OpenAPI `1.19.0-beta`、API 文档和测试清单已同步。

边界：

- 不新增底层播放器进程管理。
- 不改变 `/resources/<id>/stream` 的 200/206/302 行为。
- 不自动替用户选择播放器或执行本机程序；PC 客户端或前端可基于 manifest 自行发起 handoff。

### 运行加固与上线前 P0 收口

在进入用户管理前，先补齐单机私有部署必须的基础保护与回滚能力。

已完成：

- 新增最小 API token 鉴权：设置 `CYBER_API_TOKEN` 后，管理类 API 要求 Bearer token 或 `X-Cyber-API-Token`。
- 健康检查、媒体流和影片图片 GET 默认公开，避免浏览器播放器、图片和外部播放器读取链路被 header 限制挡住。
- `TMDB_TOKEN` 和历史 WebDAV 凭证不再保留代码内明文默认值；未配置 TMDB token 时跳过 TMDB 请求并继续其他 provider fallback。
- 新增 `scripts/db_backup.py`，支持 SQLite `backup`、`list`、`restore --yes`，恢复前会自动做一次安全备份。
- `scripts/backend_service.sh` 默认 `auto` runner：优先 gunicorn，缺失时回退 Flask 内置服务器。
- `.env.local.example`、运行手册、配置说明、测试清单和 OpenAPI 说明已同步。

## 2026-04-30

### Super CDN 国内全线路非视频资产接入

CDN 已按国内主访问场景开始接入，范围刻意限制在非视频静态资产，视频主播放链路继续保持现有 302/proxy 行为。

已完成：

- 新增 Super CDN provider/client，默认桶 `cyberstream-cn-assets`，默认线路 `china_all`。
- 首次上传前可自动创建 Super CDN 资产桶；默认允许类型为 `image,document`，不包含 `video`。
- 图片缓存写入后可上传到 Super CDN，`poster_asset_url/backdrop_asset_url` 在已有上传记录时优先返回 CDN `/a/{bucket}/...` URL。
- `GET /api/v1/movies/<id>/images/status` 和 `POST /api/v1/images/refresh` 返回 `cdn` 上传状态，维护页可看 `summary.cdn_status_counts`。
- 在线绑定字幕和手动上传字幕会上传原始字幕；`srt/ass/ssa/vtt` 额外上传 WebVTT 版本，网页播放器优先使用 CDN `web_player.url`。
- 配置默认关闭；未配置 Super CDN 时全部回退原后端图片/字幕 URL。

本次定向验收：

- 图片资产与在线/手动字幕专项测试通过：`43 tests OK`。
- OpenAPI / 图片 / 在线字幕 / 字幕发现专项测试通过：`54 tests OK`。
- 全量后端测试通过：`240 tests OK`。

当前决策：

- 赛博影视只先替换海报层，运行桶为公网已有图片桶 `hd-wallpapers`，图片加载链路为 CDN -> 后端本地图片入口 -> 原始元数据 URL。
- 当前 Super CDN 的稳定 `/a/{bucket}/...` 公开 URL 实测返回 `200/206`，底层 `storage_url/cdn_url` 才会 302 到豆包/飞书下载流；后端继续只向前端暴露稳定 `public_url`，不直接暴露带签名的底层网盘直链。
- 后续背景图、字幕等静态资源暂不继续迁移到 CDN；等待 Super CDN 开发侧明确并修复 asset bucket `/a/...` 的 redirect 策略后再推进。
- 不阻塞主线开发，下一模块先转入“资料库质量 / 剧集识别复核”。

### 剧集识别复核第一阶段

CDN 后续迁移暂缓后，主线转入资料库质量模块。已完成：

- 新增剧集完整性诊断 service，按季计算 `episode_diagnostics`。
- `GET /api/v1/movies/<id>/resources` 与 `GET /api/v1/movies/<id>/seasons` 返回每季诊断：缺集、重复集号、资源缺集号、资源数与季元数据集数不一致。
- `summary.episode_diagnostics` 汇总整部影片的剧集诊断状态和需要复核的季号。
- 新增 `GET /api/v1/movies/<id>/episode-diagnostics`，返回只读 dry-run 修复建议、可确认后提交到批量资源编辑接口的 `apply_payload`，以及需要人工复核的重复/缺失剧集提示。
- 元数据工作台问题列表接入剧集诊断 issue：`missing_episode_numbers`、`duplicate_episode_numbers`、`episode_number_missing`、`episode_count_mismatch`。
- `/api/v1/metadata/work-items` 和 `/api/v1/movies` 的 `metadata_issue_code` 现在可直接筛选这些剧集问题，方便前端进入复核工作台。

今晚收口清单已完成：

1. 新增 `GET /api/v1/metadata/quality-summary`，聚合 issue 计数、样例影片和建议动作。
2. 新增 `POST /api/v1/metadata/re-scrape/plan`，先覆盖 `fallback_pipeline_match`、`poster_missing`、`low_confidence_resources`，确认后再提交现有批量 re-scrape。
3. 新增 `GET /api/v1/metadata/episode-review-items`，把缺集、重复集号、资源缺集号和季元数据缺失聚合成前端可直接处理的工作台列表。
4. 新增轻量后台任务注册表，`POST /api/v1/metadata/re-scrape/jobs` 可后台执行批量重识别，`GET /api/v1/jobs` 与 `GET /api/v1/jobs/<job_id>` 可追踪进度和结果。

### 扫描与资源治理第一阶段

继续避开 CDN、安全权限和播放体验主链路，新增只读资源治理入口：

- 新增 `GET /api/v1/resources/governance-summary`，返回孤儿资源、空壳影片、重复播放资源、失效路径检查和治理建议。
- 新增 `GET /api/v1/resources/governance-items`，分页查看具体治理问题条目，支持 `issue_code` 过滤。
- 默认不访问存储源，只做数据库层 dry-run 分析；传 `live_check=true` 时才按 `live_check_limit` 有界检查资源父目录，不删除、不改库、不触发扫描。
- 失效路径检测使用父目录 `list_items()` 匹配文件名和大小，避免误用 provider 的目录型 `path_exists()` 判断视频文件。

### 扫描与资源治理第二阶段

在不触碰 CDN、用户管理和播放主链路的前提下，补上资源治理闭环：

- 新增 `POST /api/v1/resources/governance/plan`，生成清理 dry-run 和可提交的 `apply_payload`。
- 新增 `POST /api/v1/resources/governance/jobs`，接入轻量后台任务注册表执行确认后的清理计划。
- 自动执行范围限定为重复资源副本、孤儿资源索引和 live check 后确认缺失的资源索引。
- 安全保护覆盖播放历史、已绑定字幕、影片最后资源和重复主资源；执行前重新校验 issue，且只删除 `MediaResource` 索引，不删除实体文件。
- 清理 job 的已删除项会返回 `restore_snapshot`，包含完整 `MediaResource` 字段，便于人工恢复资源索引。
- `plan` 支持 `limit` 和 `page/page_size`，前端可按批次展示和提交真实库的大计划。
- 新增 `POST /api/v1/resources/governance/live-check/jobs`，把较大批量路径检查放进后台任务，只读返回汇总和分页问题项。
- 后台维护任务新增 `maintenance_jobs` 持久化记录，`/jobs` 和 `/jobs/<job_id>` 可在进程内存丢失后继续查询任务状态和结果。
- 新增 `POST /api/v1/resources/governance/restore/plan` 与 `/restore/jobs`，可用 `restore_snapshot` 恢复误删的 `MediaResource` 索引；恢复不触碰实体文件、历史和字幕。
- 维护任务持久化结果新增瘦身策略：按 `MAINTENANCE_JOB_RESULT_ITEM_LIMIT` 截断过长 `result.items`，避免 SQLite 长期膨胀。
- 新增 `POST /api/v1/jobs/prune`，按 `MAINTENANCE_JOB_RETENTION_DAYS` 或请求参数清理过期 succeeded/failed 任务，支持 `dry_run`。

### HTTPS 外部 URL 修复

前端发现 `audio-transcode` 等后端生成链接返回 `http://pw.pioneer.fan:84/...`，但实际后端公网入口是 HTTPS。已完成：

- Flask 应用启用 `ProxyFix`，默认信任一层反向代理的 `X-Forwarded-Proto`、`X-Forwarded-Host`、`X-Forwarded-Port` 和 `X-Forwarded-Prefix`。
- 新增 `CYBER_BACKEND_PUBLIC_BASE_URL`，可在反代未正确传头时强制指定后端外部 base URL，例如 `https://pw.pioneer.fan:84`。
- `playback.stream_url`、`audio.server_transcode.endpoint/url`、字幕原始 `url` 和 `web_player.url` 统一走外部 URL helper，避免同一响应中混入 HTTP 链接。
- 新增代理头回归测试，覆盖 `https://pw.pioneer.fan:84` 下的播放、转码和字幕 URL。

### CDN 对接前置边界

本次完成：

- 新增配置 `CYBER_IMAGE_ASSET_PUBLIC_BASE_URL`，用于让 `poster_asset_url/backdrop_asset_url` 和图片状态接口的 `asset_url` 返回 CDN/public base 下的绝对 URL。
- 默认不配置时仍返回原有后端相对路径，前端字段名和语义保持兼容。
- 真实图片读取、缓存、刷新、预热和清理仍走后端图片接口；当前适合先用 CDN 反向代理后端图片路由，后续再接对象存储上传与供应商 purge provider。
- 新增 `POST /api/v1/images/refresh`，用于批量编排图片 CDN purge / 本地缓存清理 / 重新预热；当前 `noop` provider 只返回待 purge URL 清单，后续真实 CDN 接入时复用同一入口。
- 新增图片来源追踪：列表/详情返回 `poster_source_info/backdrop_source_info`，状态接口返回当前 `source_info`，新缓存元数据写入 `cache.source_info` 来源快照。
- 图片来源追踪第一阶段不改 schema，先基于 `scraper_source`、图片 URL host 和字段锁状态推断 TMDB、Bangumi、NFO、manual、external/local 等来源。

### 字幕加载修复

前端联调发现网页播放器加载字幕失败，后端排查后确认主因是浏览器 `<track>` 不能直接加载 ASS/SRT 原始字幕。已完成：

- `playback.subtitles.items[].url` 继续保留原始字幕流，供外部播放器使用。
- `playback.subtitles.items[].web_player.url` 改为网页播放器专用入口；`srt/ass/ssa` 会追加 `format=vtt`，由后端动态转换为 WebVTT。
- `GET /api/v1/resources/<id>/stream?subtitle_id=<subtitle_id>&format=vtt` 返回 `text/vtt; charset=utf-8`，并标记原始字幕格式响应头。
- `sub/sup` 当前仍不声明网页播放器支持，避免前端把位图字幕交给 HTML5 `<track>`。
- OpenAPI `1.19.0-beta` 和播放链路测试清单已同步更新。

随后继续排查在线字幕下载失败，确认前端搜索“阿凡达：水之道”后第一条候选为 SubHD 的 `SUP` 位图字幕，解包后的 `.sup` 超过后端单字幕大小限制。已继续完成：

- 在线字幕搜索候选新增 `format_normalized` 与 `web_player` 兼容性提示。
- 候选排序优先展示 `srt/ass/ssa/vtt` 文本字幕，再展示未知格式，最后展示 `sub/sup` 位图字幕，避免网页播放器优先选到不可加载的 SUP。
- 字幕文件或嵌套压缩包超过大小限制时返回 HTTP `413`，不再伪装成远端下载 `502`。
- SubHD 返回 RAR 压缩包时当前仍不解压，但错误语义已调整为 HTTP `415`，前端可提示用户更换候选；真实 RAR 解压需后续明确部署环境中的 `unar/7z/bsdtar` 等运行依赖后再接。

本次验收：

- 字幕发现、在线字幕和 OpenAPI 契约专项测试通过：`33 tests OK`。
- 播放/字幕/代理 URL/OpenAPI 契约专项测试通过：`20 tests OK`。
- 全量后端测试通过：`240 tests OK`。

## 2026-04-29

### 1.19.0 开发基线建立

前端对 `1.18.0` 基本完成对接后，后端进入 `1.19.0` 小步迭代。本轮先沿“资料库质量 / 元数据复核工作台”推进，同时新建 OpenAPI `1.19.0-beta` 作为后续联调基线。

本次完成：

- 修正 `metadata_issue_code` 筛选语义：`GET /api/v1/metadata/work-items` 与 `GET /api/v1/movies` 现在按条目实际返回的 `metadata_issues[].code` 精确筛选。
- 覆盖此前来源粗筛无法准确命中的复合问题类型，包括 `low_confidence_resources`、`locked_fields_present`、`season_metadata_missing`、`manual_review_required` 等。
- 修正 `local_only_metadata` 可能误带 `LOCAL_FALLBACK/LOCAL_ORPHAN` 占位条目的问题；现在以模型实际 issue 列表为准。
- 记录 CDN 前置准备项：图片缓存状态、批量预热、清理刷新策略和图片来源追踪。
- 新增 `GET /api/v1/movies/<id>/images/status`，用于查看单片 `poster/backdrop` 图片源、源 URL 校验结果、本地缓存状态、缓存文件元数据和源 URL 是否变化。
- 新增 `POST /api/v1/images/preload`，用于按 `movie_ids/kinds/refresh/limit` 小批量同步预热图片缓存，并返回逐项 `cached/stale/skipped/failed` 结果。
- 新增 `DELETE /api/v1/movies/<id>/images/<kind>`，用于清理单片 `poster/backdrop` 的后端本地缓存文件和缓存元数据，不修改数据库图片源。
- 新建 OpenAPI `1.19.0-beta` 目录，并同步更新运行版本、API 文档和 release notes。

本次验收：

- 工作台、图片缓存和公开列表相关专项测试通过。
- OpenAPI JSON 可解析，OpenAPI 契约测试通过。
- 全量后端测试通过：`232 tests OK`。
- 本地后端已重启，`GET /` 健康检查返回 `1.19.0`。

## 2026-04-28

### 1.18.0 开发与当日收口

今天按昨日计划先推进“字幕配置”第一阶段，范围控制在播放矩阵与安全字幕流，不改变视频主播放链路。

### 本次完成

- 新增同目录外挂字幕发现服务，当前支持 `srt`、`ass`、`ssa`、`vtt`。
- `GET /api/v1/movies/<id>/resources` 返回的 `playback.subtitles.items` 已从占位升级为真实字幕列表。
- 字幕匹配规则：只匹配当前视频同目录、同文件名前缀的字幕文件，避免误扫跨目录内容。
- 字幕语言会根据文件名识别 `zh-Hans`、`zh-Hant`、`zh`、`en`、`ja`、`ko`，并支持 `default` / `默认` 标记作为默认字幕。
- `playback.external_player.subtitle_urls` 会同步返回字幕 URL，便于 PotPlayer、IINA、VLC 等外部播放器接入。
- 字幕流复用 `GET /api/v1/resources/<id>/stream?subtitle_id=...`，后端会校验 `subtitle_id` 必须来自当前资源已发现字幕，不开放任意路径下载。
- 新增在线字幕搜索接口 `GET /api/v1/resources/<id>/subtitles/online/search`，启用来源为 `subhd` 与 `srtku`。
- 新增在线字幕下载接口 `POST /api/v1/resources/<id>/subtitles/online/download`，按搜索结果 `candidate_id` 返回字幕文件流。
- 新增在线字幕绑定接口 `POST /api/v1/resources/<id>/subtitles/online/bind`，必须传 `confirm: true`，只绑定用户手动确认的候选，并保存为后端缓存字幕。
- 新增手动上传字幕接口 `POST /api/v1/resources/<id>/subtitles/upload`，支持直接字幕文件和 `zip/7z/tar/gzip` 压缩包提取，上传结果以 `source=manual_upload` 暴露。
- 新增已绑定在线字幕管理接口：`DELETE /api/v1/resources/<id>/subtitles/<subtitle_id>` 移除缓存字幕，`POST /api/v1/resources/<id>/subtitles/<subtitle_id>/default` 持久化默认绑定字幕。
- `opensubtitles` 因中文覆盖和免费下载限额问题暂不接入；前端传入该来源时后端只会记录到 `providers.ignored`。
- 新增电影图片缓存接口 `GET /api/v1/movies/<id>/images/<kind>`，第一阶段支持 `poster/backdrop`。
- 电影列表/详情保留原 `poster_url/backdrop_url`，新增 `poster_asset_url/backdrop_asset_url` 作为后端稳定图片资源入口。
- 图片缓存落盘到 `CACHE_DIR/images/movies/<movie_id>/`；接口只按数据库中的 `cover/background_cover` 回源，不接受任意 URL，避免开放代理风险。
- 支持 `refresh=true` 刷新远端图片；刷新失败且已有缓存时返回旧缓存并标记 `X-Cyber-Image-Cache=stale`。
- 新增元数据 provider 能力接口 `GET /api/v1/metadata/providers`，当前注册 `nfo/tmdb/bangumi/local`。
- `GET /api/v1/movies/<id>/metadata/search` 改为 provider 抽象候选搜索，候选新增 `provider/source_key/candidate_id/external_id`，并返回 `providers.attempts` 解释各来源状态；指定 `query` 但不指定 `year` 时不再继承当前影片年份。
- 新增 Bangumi / 番组计划 provider，支持动画候选搜索、subject URL 定点查询、扫描刮削和手动匹配 `candidate_id + provider`；默认不自动启用，动漫库可显式配置 `provider_order: ["nfo", "bangumi", "tmdb", "local"]`。
- 存储源扫描和资源库绑定新增 `scraper_policy.provider_order`，资源库扫描现在会实际使用绑定上的 `content_type/scrape_enabled/scraper_policy`。
- 运行版本推进到 `1.18.0`，新增 OpenAPI `1.18.0-beta` 联调基线。
- 新增总影视库显式发布控制：影片级 `catalog_visibility_status` 支持 `auto/published/hidden`，`PATCH /api/v1/movies/<id>/catalog-visibility` 必须由用户显式触发，强制发布需要 `force=true`。
- 已确认 `SMB/FTP/AList/OpenList` 代码链路接入主流程：配置校验、provider 工厂、预览、已保存来源浏览、扫描、播放、OpenAPI 和文档均已覆盖；协议相关 53 个单元测试通过。
- 已记录 Emby/Jellyfin 对标差距与长期超越路线，明确 PC 端播放优先、多用户后置、资料库长期打磨、未来接入 `skill` / agent 工作流。

### 今日验收

- 全量后端测试在总影视库显式发布控制完成后通过：`213 tests OK`。
- OpenAPI JSON 可解析，运行时路由与 OpenAPI path/method 对齐。
- 后端已在本地 `5004` 端口运行，`/api/v1/storage/provider-types` 与 `/api/v1/storage/capabilities` 可正常返回 `smb/ftp/alist/openlist`。
- 协议专项测试通过：`tests.test_storage_protocol_support`、`tests.test_smb_ftp_providers`、`tests.test_alist_provider`、`tests.test_storage_preview_optimization`、`tests.test_storage_source_scan_scope`、`tests.test_playback_capabilities`，共 53 个测试。
- 当前不再继续新增大功能，等待前端完成 `1.18.0` 对接和测试反馈。

### 当前边界

- 暂不做字幕转码、字幕烧录、跨目录递归查找、字幕内容解析或在线字幕自动落盘；在线字幕绑定必须由用户确认后触发；移除/默认设置只作用于后端缓存的 `online_bound/manual_upload` 字幕。
- 图片缓存第一阶段暂不做对象存储/CDN 上传、裁剪转码、季级独立海报缓存或批量预热；当前是按需回源并落盘。CDN 切换层等待自建 CDN 完工后再继续。
- 元数据 provider 第一阶段已接入 TMDB 与 Bangumi 在线候选搜索；新增来源暂缓，后续重点转向图片来源追踪和批量预热。
- `SMB/FTP` 当前是 mock 单测覆盖，真实 NAS / FTP 环境尚未做完整端到端验证；AList/OpenList 已有 provider 级测试，但仍建议用真实服务做目录浏览、扫描和播放抽样。
- 长期对标 Emby/Jellyfin 的差距和超越路线已记录到 `docs/MAINTENANCE_TODO.md`：当前仍以个人向私有媒体库为核心，多用户后置；播放体验后续优先进军 PC 端，借助开源播放器内核或原生 Windows 播放能力；资料库质量作为长期打磨主线；未来重点差异化是与 `skill`、OpenClaw 类 agent 集成，但关键动作必须保留用户显式确认。

### 明日接手待办

1. 先看前端联调反馈，不急着进新模块；如果有接口字段、OpenAPI 扁平度、响应结构或交互确认类问题，优先当天收敛。
2. 针对字幕链路做前端联调回归：同目录字幕、在线搜索、候选下载、用户确认绑定、默认字幕、删除绑定字幕、手动上传字幕和压缩包提取。
3. 针对元数据和总影视库发布做回归：Bangumi 手动匹配、`scraper_policy.provider_order`、`catalog_visibility` 展示、`published/hidden/auto` 切换和 `force=true` 确认逻辑。
4. 抽样验证图片缓存：列表/详情中的 `poster_asset_url/backdrop_asset_url`、`refresh=true`、远端失败时旧缓存回退。
5. 抽样验证存储协议运行态接口：`provider-types`、`capabilities`、`preview`、已保存来源 `browse`，有真实环境时再补 `SMB/FTP/AList/OpenList` 端到端联调记录。
6. 如果前端没有后端阻塞，再进入下一个模块；优先从“资料库质量/剧集识别/复核工作台”或“PC 端播放契约”里选一个，不要同时改扫描、播放、存储三大核心链路。

## 2026-04-27

### 当前决策

- `1.17.0` 先停止继续加新功能，当前阶段以真实联调、前端接入和问题收敛为主。
- 后续继续保持单主干维护：`main` 始终代表最新版，不再保留长期开发分支。

### 今日联调收口

- 前端对 `1.17.0` 当前能力的联调已完成，未发现需要今天继续补的新后端阻塞问题。
- 已实际联调通过的重点包括：元数据工作台、单片推荐、资源播放源分组、版本与文档同步。
- 当前收口原则：今天不再继续新增后端功能，未决事项统一进入明日 `1.18.0` 计划。

### 1.18.0 明日计划

明天的新一轮开发先围绕三个主题展开：

1. 字幕配置
   - 补齐字幕发现、外挂字幕关联、默认字幕选择与播放器接入契约。
   - 将当前 `playback.subtitles.items` 从占位推进到真实数据。

2. 静态资源优化存储
   - 为 `poster`、`background_cover` 设计更稳定的缓存与存储策略。
   - 自建 CDN 完工后再设计 CDN 切换层，当前先保持本地按需缓存。

3. 多刮削器支持
   - 当前只有 TMDB，复杂影视数据覆盖不够。
   - 下一步要抽象 scraper provider，支持主刮削器、fallback 刮削器和字段来源追踪。

4. 总影视库显式发布控制
   - 当前总影视库可见性仍依赖 `scraper_source` 和海报条件，和 TMDB 路径绑得太死。
   - 下一步应把“是否进入总影视库”从刮削来源判断中解耦，增加显式发布/纳入控制接口。
   - 资源库与总影视库规则分开：资源库允许自录视频、课程、无海报内容存在，总影视库继续保持更严格门槛。

## 2026-04-26

### 1.17.0 主干开发启动

当前已在本地 Gitea 建立项目仓库，并以 `1.16.0` 稳定版作为 Git 基线。后续暂按单主干维护：

- `main`：唯一主干分支，始终代表当前最新版
- `v1.16.0`：稳定版标签
- 暂不再保留长期开发分支；小步提交直接进入 `main`

### 本次完成

- 新版本第一笔工程性清理：将后端和测试中的 SQLAlchemy legacy `Query.get()` 调用迁移为 `db.session.get(Model, primary_key)`。
- 涉及 API 层、播放链路、存储源管理、资源库管理、数据库适配层和相关测试断言。
- 本次只做等价替换，不改变接口路径、响应结构、数据库结构或业务语义。

### 本次验收

- `rg "\.query\.get\(|Query\.get" backend tests` 已无残留。
- 全量 unittest：`126 tests OK`。

### 今晚攻坚目标

今晚 `1.17.0` 重点围绕三个可感知能力推进：

1. 播放能力矩阵
   - 先明确每个资源的可播放方式与限制，不直接改造现有播放主链路。
   - 输出直连/代理/跳转、Range、MIME、外部播放器、字幕、转码、FFmpeg 输入等能力字段。
   - 后续字幕、转码、投屏等功能都基于该矩阵逐步扩展。
   - 当前已在资源对象中新增 `playback` 块，随 `GET /api/v1/movies/<id>/resources` 等已有接口返回。
   - `playback.external_player.url` 暂指向后端 stream 入口，AList/OpenList 继续走 302 直链。
   - `GET /api/v1/movies/<id>/resources` 已新增 `groups.playback_sources`，用于把同名同大小的物理副本折叠成一个主播放源和多个备用播放源；`items` 仍保留全量资源，不改变播放主链路。
   - 字幕当前只返回占位空数组；实时音频转码已提供独立 `audio-transcode` 流，前端可用 video/audio 双标签做同步播放。
   - 音频转码按 `start` 参数从指定时间点启动，seek 时由前端重建 audio 流；后端包含 ffmpeg 进程清理、默认单并发闸门、同 session 替换旧流、AList `/d` 上游重试、远程输入 Range 内存缓存、DELETE 主动停止、history watchdog 兜底停止，以及默认 `-re` 输入限速，避免音频转码过度预读远端原片、挤占视频直链。
   - 当前音频转码实现细节已沉淀到 `docs/AUDIO_TRANSCODE_DESIGN_NOTES.md`；前端安全接入方式见 `docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md`。已新增资源级诊断接口 `GET /api/v1/resources/<id>/audio-transcode/diagnostics`，用于查看缓存命中、上游 Range、首包耗时、输出节流和关闭原因；后续继续验证真实前端小幅 seek、缓存命中后的持续流畅性和双标签同步策略。

2. 元数据工作台增强
   - 先增强失败分类、候选解释和批量重识别结果说明。
   - 优先服务 raw/占位/缺海报/低置信度影片的人工复核闭环。
   - 暂不一开始引入复杂持久化状态，避免把扫描和刮削主链路打乱。

3. 推荐观看
   - 面向首页或独立入口补强“现在适合看什么”的推荐能力。
   - 优先综合观看历史、未继续观看、最近入库、评分、质量标签、类型多样性和资源可播放性。
   - 避免只做随机推荐，返回可解释原因，方便前端展示推荐文案。
   - 已补强全局 `/recommendations` 与库级 `/libraries/<id>/recommendations`：`default` 升级为综合推荐，新增 `continue_watching` 策略，并给每个影片条目返回 `recommendation` 理由、分数、排序和信号。
   - 已新增单片上下文推荐 `/movies/<id>/recommendations`：详情/播放页下方按同系列/同标题族、同类型、同分区兜底排序，并强制动漫与非动漫互不推荐；资源库内详情页可传 `library_id`，先推库内影视，不足再全局补齐。

## 2026-04-25

### 1.16.0 稳定版收口

当时 `1.16.0` 已作为前后端联调稳定基线冻结，大功能暂停进入下一版本。本轮最后收口内容：

- 首页门户接口稳定：`GET /api/v1/homepage` 支持 hero 指定影片、默认/手动分类区块、分类去重；默认分类为 `科幻` / `动作` / `剧情` / `动画`，每类默认最多 15 个影视条目。
- 首页动画特殊规则已落地：当首页包含动画分类时，其他分类不再展示动画内容，避免多分类命中导致门户被动画刷屏。
- 首页和列表返回 `quality_badge`，影片级海报标签只返回 `Remux`、`4K`、`HD` 或 `null`。
- 资源库模型稳定：`Library` 是逻辑资源库层，`StorageSource` 是物理来源层，`LibrarySource` 是挂载点绑定层。
- 资源库内容规则稳定为 `(挂载点路径自动命中 ∪ 手动 include) - 手动 exclude`。
- 资源库创建/更新已移除 `library_type`；分类不再作为资源库模型字段。
- `GET /api/v1/libraries/{id}/movies` 已真正接入分页、排序和 `pagination` 返回，不再让 `page` 参数形同虚设。
- 全局影视库和资源库自动命中默认只纳入无需人工处理且有海报的公开影视；raw/占位/缺海报待处理影片必须手动 `include` 才能进入资源库。
- `media_resources` 已增加 `(source_id, path)` 唯一约束，降低重刮削或并发扫描产生同路径重复资源的风险。
- 全量扫描、指定存储源扫描、资源库扫描已统一运行锁；已有扫描运行时新触发请求返回 `429`。
- 播放接口按资源扩展名返回 `Content-Type`，覆盖 MP4、MKV、WebM、TS/M2TS、MOV、AVI 等常见格式。
- 观看历史继续保留；列表、首页、资源库、详情和资源分组不再返回 `is_played`，前端不应展示“已观看”标签。
- 资源技术信息已结构化增强，历史已入库资源也能通过文件名纠偏返回 `UHD Blu-ray Remux`、`HDR10`、`Dolby TrueHD 7.1 Atmos`、声道、无损音频等字段。
- OpenAPI `backend/openapi/openapi-1.16.0-beta/openapi-1.16.0-beta.json` 已补齐全局 `featured/recommendations`，移除未实现字幕接口，并新增运行时路由漂移测试。

### 本轮最终验收

- OpenAPI JSON 可解析校验通过。
- 运行时路由与 OpenAPI path/method 对齐：`59/59`。
- 全量 unittest：`126 tests OK`。
- 本地健康检查：`GET http://127.0.0.1:5004/` 返回 `200`。
- 公网 HTTPS 抽样资源接口已验证，Avatar 资源返回 `UHD Blu-ray Remux`、`HDR10`、`Dolby TrueHD 7.1 Atmos`、`HEVC` 等结构化字段。

### 下一版本边界

该版本不再继续塞大功能。下一版本可优先考虑：

- 资源副本折叠或备用播放源展示策略。
- 播放兼容性继续优化，尤其是字幕、转码、外部播放器能力矩阵。
- 元数据复核工作台继续增强。
- SQLAlchemy `Query.get()` 迁移到 `Session.get()`，清理 2.0 警告。
- 更完整的用户、权限、运行安全开关设计；域名和部署形态敲定前暂不实现运行安全开关。

## 2026-04-04

### 本次完成
- 新增 `backend/app/api/system_routes.py`，将系统类接口 `/api/v1/scan`（查询扫描状态、触发全库扫描）从旧 `routes.py` 中独立拆出。
- 更新 `backend/app/__init__.py`，注册新的 `system_bp` 蓝图。
- 新增 `backend/app/api/player_routes.py`，将播放相关接口 `/api/v1/resources/<uuid:id>/stream` 从旧 `routes.py` 中独立拆出。
- 再次收缩 `backend/app/api/routes.py`，当前仅保留旧兼容接口 `/movies/recommend`。
- 为 `backend/app/api/routes.py` 增加 legacy 兼容层说明，明确后续新增业务接口不要继续写回旧 `routes.py`。
- 更新 `docs/API_OVERVIEW.md`，补充当前 API 路由模块拆分结构与维护约定说明。
- 顺手修复旧兼容接口 `/movies/recommend` 的潜在问题：补充 `db` 导入，避免 `db.func.random()` 在运行时触发 `NameError`。
- 临时注释掉两个旧接口，供前端回归观察：
  - `/api/v1/movies/recommend`
  - `/api/v1/genres`
- 本地验证结果：上述两个旧接口当前均返回 `404`。
- 新增 `PATCH /api/v1/movies/<id>`，支持手动修改影片元数据。
- 当前支持更新字段：`title`、`original_title`、`year`、`rating`、`description`、`cover`、`background_cover`、`category`、`director`、`actors`、`country`。
- 补充了基础校验：不支持字段拦截、`category/actors` 字符串数组校验、`rating` 范围校验、`year` 正整数校验。
- 新增资源库设计文档 `docs/LIBRARY_DESIGN_V1.md`，明确“StorageSource = 物理来源层、Library = 逻辑资源库层”的分层方案，并给出推荐表结构、关系设计、接口草案与分阶段落地路径。
- 已开始落地第一版 Library：在 `backend/app/models.py` 中新增 `Library`、`LibrarySource` 模型，并新增 `backend/app/api/libraries_routes.py` 提供基础 CRUD、来源绑定、按库查看影片列表接口。
- 已在 `backend/app/__init__.py` 注册 `libraries_bp`。
- 本地真接口验收通过：已验证 `GET/POST/PATCH/DELETE /api/v1/libraries`、`GET/POST/PATCH/DELETE /api/v1/libraries/<id>/sources`、`GET /api/v1/libraries/<id>/movies` 基本可用；验收过程中创建的临时测试库已删除，避免污染正式数据。
- 已继续补上库级展示接口：`GET /api/v1/libraries/<id>/featured`、`GET /api/v1/libraries/<id>/recommendations`、`GET /api/v1/libraries/<id>/filters`。
- 本地验收结果：库级 `recommendations` 与 `filters` 已可正常返回；`featured` 当前在命中库内存在背景横图资源时返回内容，否则返回空列表，符合第一阶段实现预期。验收过程中创建的临时测试库已删除。
- 已继续把 Library 查询从“按 `source_id` 聚合”升级为“按 `source_id + root_path` 过滤”，当前会依据 `LibrarySource.root_path` 只匹配该路径及其子路径下的 `MediaResource.path`。
- 本地路径级验收通过：当绑定 `root_path=剑来` 时，`/api/v1/libraries/<id>/movies` 已只返回《剑来》相关内容，不再兜入同一 source 的其他影片；验收用测试库已删除。
- 已新增 `POST /api/v1/libraries/<id>/scan`，支持按资源库触发扫描任务；当前实现会按绑定顺序扫描所有启用的 source，并支持以 `root_path` 作为起始扫描路径。
- 同步调整 `backend/app/services/scanner.py`：`scan_source()` 新增 `root_path` 参数，扫描时从库绑定路径起步，但入库前会补回完整 source 相对路径，保持 `MediaResource.path` 的现有语义不变。
- 本地验收通过：触发 `/api/v1/libraries/1/scan` 后返回 `202`，随后 `/api/v1/scan` 状态显示 `WEBDAV:剑来` 正在扫描，说明按库扫描链路已打通。验收用测试库已删除。
- 已确认并修复旧 OpenAPI 文件 `backend/openapi/openapi-1.9.4-beta/openapi.json` 的 JSON 语法错误（`bitrate.example` 多余引号），恢复为可解析状态。
- 按用户约定采用“新建版本文件夹”方式更新 OpenAPI，已新增 `backend/openapi/openapi-1.11.0-beta/openapi.json`。
- 新版 OpenAPI 已补入本轮新增接口：影片元数据修改、Library CRUD、Library source 绑定、按库 movies/featured/recommendations/filters、按库 scan，并完成 JSON 可解析校验。
- 已继续完成一轮 OpenAPI 与真实返回对齐：补充了更具体的 Library 响应 schema、将 `PATCH /api/v1/movies/{id}` 响应明确为 `MovieDetailed`、把 `ScanStatus` 修正为贴近当前后端真实字段（`status/phase/current_source/total_items/processed_items`），并在创建/接受类接口描述中注明“HTTP 状态码与 body.code 当前并不完全一致”的现状。

### 当前状态
- API 路由已进一步拆分为：`system`、`library`、`libraries`、`history`、`storage`、`player`、`legacy(api_bp)`。
- `legacy(api_bp)` 当前代码层面仍为兼容层，但 `/movies/recommend` 已临时注释停用，等待前端验证结果。
- `/genres` 旧兼容入口也已临时注释停用，等待前端验证结果。
- 今日还排查了一次“继续播放偶发失败”问题：同一资源在本地与公网复测均可正常返回 `302`，跳转后的目标直链支持 `200/206`，当前判断更像代理或链路抖动，暂不改后端逻辑。
- 资源库（Library）第一版基础骨架已落地，目前已具备：库管理、来源绑定、按库影片列表、按库推荐、按库筛选、按库 featured、按库扫描的第一阶段能力。
- 当前 Library 查询与扫描都已支持按绑定级 `root_path` 过滤/起步，资源库概念相比前一版更完整；但扫描结果的聚合与刮削策略仍主要沿用现有 source 扫描逻辑。
- OpenAPI 文档已形成新的版本目录，并完成第一轮与真实接口对齐，可继续作为后续前后端联调基线使用。
- 当时统一版本：`1.16.0`

## 2026-04-20

### 本次完成
- 对 `PATCH /api/v1/movies/<id>` 做了一轮低风险增强，暂不改扫描链路与数据库结构，优先提升元数据编辑接口可用性。
- 新增编辑字段别名兼容：
  - `overview -> description`
  - `poster_url -> cover`
  - `backdrop_url -> background_cover`
  - `tags/genres -> category`
- 新增输入归一化：
  - 文本字段自动去首尾空格
  - `category/tags/genres` 自动去空值、去重
  - `actors` 兼容字符串数组与 `{name}` 对象数组，并统一保存为演员名列表
  - `year` / `rating` 兼容字符串数字输入
- 新增更严格校验：
  - `title` 不允许为空白字符串
  - 同一目标字段不允许同时传原字段与别名，例如 `cover + poster_url`
  - 当提交值与当前值完全一致时，返回 `Movie metadata unchanged`，避免无意义写入
- 新增影片级元数据锁定能力：
  - 新增 `movie_metadata_locks` 表
  - 影片详情返回 `metadata_locked_fields`
  - 手动 PATCH 默认会锁定本次修改字段，后续扫描/刮削不再覆盖
  - 支持通过 `metadata_locked_fields` / `metadata_unlocked_fields` 显式控制锁定状态
- 新增 `POST /api/v1/movies/<id>/metadata/refresh`：
  - 只刷新单条影片的外部元数据
  - 不触发全库扫描
  - 若影片当前是 `loc-*` 占位 ID，会先按标题/年份尝试搜索 TMDB
  - 支持 `candidate_id/external_id + provider`，也兼容旧 `tmdb_id`
  - 已锁定字段默认不覆盖，可通过 `metadata_unlocked_fields` 定点解锁后再刷新
- 新增手动匹配链路：
  - `GET /api/v1/movies/<id>/metadata/search`：按 provider 搜索单条影片的元数据候选
  - `POST /api/v1/movies/<id>/metadata/match`：将影片匹配到指定 `candidate_id + provider`
  - 全流程均不触发全库扫描，只操作当前影片
- 新增季/集级资源编辑第一版：
  - `GET /api/v1/movies/<id>/resources`：返回影片资源列表、无季资源、按季分组资源
  - `PATCH /api/v1/resources/<id>/metadata`：支持修改单个资源的 `season`、`episode`、`title`、`overview`、`label`
  - `PATCH /api/v1/movies/<id>/resources/metadata`：支持按影片批量修改多个资源的 `season`、`episode`、`title`、`overview`、`label`
  - 修改 `season/episode` 时若未显式传 `label`，自动按 `SxxExx - 分辨率` 重建标签
  - `title` / `label` 空字符串会自动归一为 `null`，便于前端清空手动值
  - 批量接口现已先完成整批校验，再统一写入，避免半路失败导致前端感知不一致
  - 该能力只修改当前资源记录，不触发全库扫描，也不涉及图片/文件管理
- 补强资源编辑返回结构，便于前端直接构建季/集编辑页：
  - 资源新增 `sort_key`、`has_manual_metadata`、`metadata_edited_at`
  - `GET /api/v1/movies/<id>/resources` 新增 `summary`
  - `season_groups` 新增 `episode_count`、`edited_items_count`、`has_manual_metadata`、`sort`
  - 单资源与批量资源编辑在真正写入时会自动刷新 `metadata_edited_at`
- 新增季级聚合与编辑能力：
  - 新增 `movie_season_metadata` 表，保存单季的 `title`、`overview`、`air_date`
  - `GET /api/v1/movies/<id>/resources` 的 `season_groups` 已可直接返回季级元数据
  - 新增 `GET /api/v1/movies/<id>/seasons`，供前端直接获取季级聚合列表
  - 新增 `PATCH /api/v1/movies/<id>/seasons/<season>/metadata`，只修改当前影片的指定季，不触发扫描
  - 季级元数据全字段清空后会自动删除空壳记录，`summary.season_metadata_count` 只统计有实际手动内容的季
  - `season_groups` 补充 `resource_ids`，方便前端批量操作当前季资源
- 存储源层开始做“先规范再扩协议”：
  - `ProviderFactory` 现在内置 provider 注册表，不再散落写死 `if/elif`
  - 新增 `GET /api/v1/storage/provider-types`，前端可动态获取支持的协议和配置字段
  - provider 注册表开始返回 `capabilities`，用于前端按能力显示扫描、预览、播放入口
  - 存储源接口返回已补充脱敏 `config` 和 `actions`，前端不必自己猜哪些按钮该显示
  - 新增 `GET /api/v1/storage/sources/<id>`，便于单条编辑页对接
  - 将 provider 级 `health check` 从列表接口中拆出，避免来源变多后拖慢列表
  - 新增 `GET /api/v1/storage/sources/<id>/health`，前端按需单独探测实时状态
  - `health` 响应新增 `reason` 字段，前端和运维可直接区分 `ok`、`dns_resolution_failed`、`auth_failed`、`permission_denied`、`root_not_found`、`timeout` 等原因
  - 存储源返回新增 `config_valid/config_error`，区分“配置本身非法”和“连接暂时不可用”
  - 存储源返回新增 `usage`，便于前端在删除/迁移来源前先评估影响范围
  - 存储源返回新增 `guards`，前端可直接判断是否允许改类型或直接删除
  - 对已被资源/资源库引用的来源，后端现在禁止直接改 `type`
  - 对仍有资源的来源，删除时必须显式传 `keep_metadata=true`
  - `POST /api/v1/storage/sources`、`PATCH /api/v1/storage/sources/<id>`、`POST /api/v1/storage/preview` 已接入统一的 `type/config` 校验
  - 当前已接入主流程的协议为 `local`、`webdav`、`smb`、`ftp`、`alist`、`openlist`；`smb/ftp` 先完成 mock 级回归，真实环境联调后再标记生产验证完成
- 本地真接口回归已通过：已验证详情读取、别名字段 PATCH、生效后的返回结构、空标题校验、冲突字段校验、字段锁定/解锁、单影片元数据刷新、单影片候选搜索；回归过程中临时修改过的影片元数据已恢复。
- 元数据刮削链路已完成一轮重塑，正式拆成独立管线层：
  - `backend/app/metadata/parser.py`：规范解析 + 经验兜底解析
  - `backend/app/metadata/nfo.py`：sidecar NFO 读取与 ID 解析
  - `backend/app/metadata/scraper.py`：`nfo -> structured -> fallback -> ai` 的统一决策入口
  - `backend/app/metadata/ai.py`：预留 AI 刮削接入位
  - `backend/app/metadata/pipeline.py`：对扫描器和 API 暴露统一管线接口
  - `backend/app/metadata/rescrape.py`：单影片定点重跑服务
- 当前扫描器已接入新元数据管线，但仍保持“只处理当前目标资源”的思路，没有额外扩大扫描范围。
- 已为 provider 抽象补齐 `read_text`，本地与 WebDAV 现在都可读取 sidecar NFO。
- 扫描写入时会把元数据诊断痕迹落入资源 `metadata_trace`，便于前端区分规范命中、经验兜底、NFO 命中和低置信度情况。
- 电影与资源返回结构已补齐一批前端联调用字段：
  - `metadata_state`
  - `metadata_actions`
  - `metadata_diagnostics`
  - `metadata_issues`
  - `metadata_trace`
  - `metadata_edit_context`
- 已补齐面向元数据工作台的接口：
  - `POST /api/v1/movies/<id>/metadata/re-scrape`
  - `POST /api/v1/movies/<id>/metadata/preview`
  - `POST /api/v1/metadata/re-scrape`
  - `GET /api/v1/metadata/overview`
  - `GET /api/v1/metadata/work-items`
- 元数据工作台接口已补强复核反馈：
  - 单片 preview/re-scrape 返回 `explanation`，说明候选、解析信号、结果分类和推荐动作
  - 批量 re-scrape 逐条返回 `status/changed/updated_fields/season_metadata_result`
  - 批量失败项返回 `error.category/retryable/recommended_action`，前端可区分无资源、不可读、请求错误和后端错误
  - 候选搜索返回 `rank/match_explanation`，说明标题、年份和媒体类型命中信号
- 已补齐相关筛选能力：
  - `/api/v1/movies` 支持 `metadata_source_group`、`metadata_review_priority`、`metadata_issue_code`、`needs_attention`
  - `/api/v1/filters` 默认返回 `metadata_source_groups`、`metadata_review_priorities`、`metadata_issue_codes`
- OpenAPI 联调基线已先升级到 `1.15.0-beta`，此前一轮大改已完成版本目录收口，避免继续污染 `1.14.0-beta`。
- 存储源协议继续推进：已补 `alist/openlist` 兼容 provider，并接入来源创建、预览、扫描和播放跳转链路。
- 已从误落的旧目录迁回 `smb/ftp` provider、目录浏览、mock 单测、脏数据清洗测试和刮削年份策略测试；该条为当日迁移记录，当前实际开发目录以 `/home/pureworld/赛博影视` 为准。
- `POST /api/v1/storage/preview` 当前已返回目录选择器友好的 browse payload：`storage_type/current_path/parent_path/items/capabilities`。
- `GET /api/v1/storage/capabilities`、`GET /api/v1/storage/sources/<id>/browse`、`GET /api/v1/reviews/resources` 已补入后端实现与 OpenAPI。
- OpenAPI 联调基线已继续推进到 `1.16.0-beta`，本轮 `local/webdav/smb/ftp/alist/openlist`、目录预览/已保存来源浏览、协议能力矩阵和脏数据复核队列已统一收口到新版本目录。

### 当前判断
- 这一轮已从“编辑接口加固”推进到“最小可用的人工编辑保护层”。
- 仍未完成的 Emby 级能力主要包括：演员/导演实体化、季/集级批量编排与更完整的剧集级独立字段。
- 图片单独管理暂不做，等待后续复杂文件管理系统对接。
- 当前元数据工作台所需的后端基础已经基本成形，下一步重点会更偏向：
  - 批量动作继续细化
  - 刮削结果解释性继续增强
  - 前后端联调中发现的字段/交互缺口补齐

### 明日续接建议
1. 继续做 `smb/ftp/alist/openlist` 的真实环境联调，尤其是目录浏览、播放直链、Range 读取和异常提示。
2. 进入刮削器深度定制：先梳理 provider 抽象、候选结果结构、字段覆盖策略和人工复核入口。
3. 继续完善元数据工作台批量入口，优先做“批量重识别”后的可读反馈和失败分类。
