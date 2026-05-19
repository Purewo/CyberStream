# 1.19.0-beta 更新说明

本文档记录 `1.19.0-beta` 的接口变化，作为 `main` 主干上的新一轮前后端联调基线。

## 当前重点

`1.19.0` 在 `1.18.0` 字幕、图片缓存、Bangumi、多 provider 和总影视库发布控制基线之上，继续推进资料库质量与元数据复核工作台。

本轮第一阶段重点：

- 元数据复核工作台问题筛选精确化
- CDN 前置的图片缓存状态、批量预热、单片清理、public base URL 与 purge/refresh 编排能力
- Super CDN 国内 `china_all` 非视频资产桶接入：海报、背景图、绑定字幕原文和 WebVTT 字幕可上传到新桶，视频主播放链路保持原样
- HTTPS 反向代理下播放、转码和字幕绝对 URL 生成修正
- PC / 外部播放器 handoff manifest 与 M3U 播放列表接口
- 单 token API 鉴权、SQLite 数据库备份/恢复脚本和 gunicorn 优先服务脚本
- 保持 `1.18.0-beta` 已有接口兼容
- 新增或调整接口时统一进入 `openapi-1.19.0-beta`

## 运行加固

本轮补齐单机私有部署的最低保护能力：

- `CYBER_API_TOKEN`：设置后管理类 API 要求 `Authorization: Bearer <token>` 或 `X-Cyber-API-Token`
- `CYBER_AUTH_ENABLED`：鉴权总开关，默认随 token 是否存在自动启用
- `CYBER_AUTH_EXEMPT_MEDIA_GET`：媒体流和影片图片 GET 默认豁免，便于浏览器播放器和外部播放器读取
- `TMDB_TOKEN`：不再内置于代码，未配置时跳过 TMDB 请求并继续其他 provider fallback
- `./scripts/db_backup.py backup|list|restore`：提供 SQLite 备份、列出和带确认恢复能力
- `./scripts/backend_service.sh`：默认 `auto` runner，优先使用 gunicorn，缺失时回退 Flask 内置服务器

## HTTPS 外部 URL

后端生成的播放、音频转码和字幕绝对 URL 现在会信任反向代理传入的 `X-Forwarded-Proto` / `X-Forwarded-Host` / `X-Forwarded-Port`。HTTPS 入口下不应再返回 `http://...` 链接。

新增配置：

- `CYBER_TRUST_PROXY_HEADERS`：默认 `true`
- `CYBER_BACKEND_PUBLIC_BASE_URL`：可强制指定后端 API 外部 base URL，例如 `https://pw.pioneer.fan:84`

受影响字段包括：

- `playback.stream_url`
- `playback.web_player.url`
- `playback.external_player.url`
- `playback.audio.server_transcode.endpoint`
- `playback.audio.server_transcode.url`
- `playback.subtitles.items[].url`
- `playback.subtitles.items[].web_player.url`

## PC / 外部播放器播放清单

新增接口：

- `GET /api/v1/resources/{id}/external-playback`

默认返回 JSON manifest，包含：

- 资源标题、文件名和关键技术信息摘要
- 绝对 `stream.url`
- 默认字幕 URL 与字幕列表
- `handoff.manifest_url`
- `handoff.playlist_url`
- `player_profiles`

传 `format=m3u` 时返回 `audio/x-mpegurl` 播放列表，可直接交给 VLC、mpv、IINA、PotPlayer 等播放器打开。M3U 会写入现有 stream URL；如果当前资源有默认字幕，会通过 `#EXTVLCOPT:sub-file=...` 附带默认字幕。

该接口只包装现有 `/resources/{id}/stream` 与字幕 URL，不改变默认网页播放、302/proxy 行为或音频转码链路。

## 元数据工作台

`GET /api/v1/metadata/work-items` 与 `GET /api/v1/movies` 的 `metadata_issue_code` 筛选语义已调整：

- 现在按条目实际返回的 `metadata_issues[].code` 精确筛选
- 不再仅按 `scraper_source` 做来源粗筛
- 前端从 `GET /api/v1/filters` 的 `metadata_issue_codes` 点入后，列表命中逻辑与条目问题标签保持一致

当前覆盖的问题类型包括：

- `placeholder_metadata`
- `local_only_metadata`
- `low_confidence_resources`
- `fallback_pipeline_match`
- `nfo_candidates_available`
- `poster_missing`
- `locked_fields_present`
- `season_metadata_missing`
- `manual_review_required`

## 图片缓存与 CDN 前置准备

新增图片缓存状态接口：

- `GET /api/v1/movies/{id}/images/status`

该接口不触发远端下载，只返回当前影片 `poster/backdrop` 的源 URL、源 URL 校验结果、本地缓存状态、缓存文件元数据和源 URL 是否已变化。

新增图片资产 public base URL 配置：

- `CYBER_IMAGE_ASSET_PUBLIC_BASE_URL`

未配置时，`poster_asset_url/backdrop_asset_url` 与状态接口的 `asset_url` 继续返回后端相对路径。配置后，这些字段会返回 CDN/public base 下的绝对 URL，例如 `https://cdn.example.com/api/v1/movies/{id}/images/poster`。实际图片读取、缓存、刷新和清理仍由后端图片接口处理。

新增图片 CDN purge / refresh 编排接口：

- `POST /api/v1/images/refresh`

该接口按 `movie_ids/kinds/limit` 选择图片资产，支持 `purge/clear_cache/preload/refresh` 四个动作开关。当前 `CYBER_IMAGE_ASSET_CDN_PURGE_PROVIDER=noop`，不会调用外部 CDN，只返回待 purge 的 `urls`；配置为 `manual` 时表示由外部人工或脚本处理。真实 CDN 供应商确定后，在 provider adapter 中接入 SDK 或 HTTP API，前端调用形状保持不变。

新增图片来源追踪字段：

- `MovieSimple.poster_source_info`
- `MovieDetailed.backdrop_source_info`
- `MovieImageCacheStatus.source_info`
- `MovieImageCacheFile.source_info`

第一阶段不新增数据库 schema，后端基于 `scraper_source`、图片 URL host 和字段锁状态推断来源 provider，例如 `tmdb`、`bangumi`、`nfo`、`manual`、`external`、`none`。新写入缓存会保存 `cache.source_info` 来源快照，便于后续 CDN 排查源图来源。

新增图片批量预热接口：

- `POST /api/v1/images/preload`

新增图片本地缓存清理接口：

- `DELETE /api/v1/movies/{id}/images/{kind}`

该接口只清理 `CACHE_DIR` 下对应 `poster/backdrop` 的后端本地缓存文件和缓存元数据，不修改数据库里的远端图片源 URL。无缓存可删时返回 `status=missing`，已清理时返回 `status=cleared`，并包含 `before/after` 缓存状态。

预热请求体支持：

- `movie_ids`：可选；不传时按最近更新影片取 `limit` 条
- `kinds`：可选，默认 `["poster", "backdrop"]`
- `refresh`：可选，强制刷新远端图片
- `limit`：可选，默认 `20`，最大 `100`

返回结果：

- 每个图片项返回 `cached/stale/skipped/failed`
- 结果包含 `before/after` 缓存状态
- 缺源图返回 `skipped + missing_source`
- 图片源非法、远端失败且无旧缓存、影片不存在返回 `failed`

该能力不绑定具体 CDN 供应商，后续接自建 CDN 时可复用为预热清单、失败原因收集和 purge / refresh 编排入口。

## Super CDN 国内全线路静态资产

新增 Super CDN provider 配置，默认面向国内全线路 `china_all`：

- `CYBER_CDN_PROVIDER=supercdn`
- `CYBER_SUPERCDN_ENABLED=true`
- `CYBER_SUPERCDN_URL` / `CYBER_SUPERCDN_TOKEN`
- `CYBER_SUPERCDN_BUCKET`，默认 `cyberstream-cn-assets`
- `CYBER_SUPERCDN_ROUTE_PROFILE`，默认 `china_all`
- `CYBER_SUPERCDN_BUCKET_ALLOWED_TYPES`，默认 `image,document`

启用后：

- 图片缓存写入后会自动上传 Super CDN，`MovieImageCacheStatus.cdn` 与 `POST /api/v1/images/refresh` 的 `cdn` 子结果会暴露上传状态。
- 已上传的 `poster_asset_url/backdrop_asset_url` 会优先返回 Super CDN `/a/{bucket}/...` 公开 URL。
- 在线绑定字幕和手动上传字幕会上传原始字幕；`srt/ass/ssa/vtt` 会额外上传 WebVTT 版本，网页播放器优先使用 CDN `web_player.url`。
- 新桶默认使用 `china_all`，允许类型为 `image,document`，明确不包含 `video`。
- 视频文件和 `/api/v1/resources/{id}/stream` 主播放链路不接入 CDN，继续保持现有 302/proxy 行为。

## 字幕网页播放器兼容

修复前端 HTML5 播放器加载字幕失败的问题：

- `playback.subtitles.items[].url` 继续返回原始字幕流，供外部播放器使用
- `playback.subtitles.items[].web_player.url` 改为网页播放器专用入口
- `srt/ass/ssa` 字幕会通过 `GET /api/v1/resources/{id}/stream?subtitle_id=...&format=vtt` 动态转换为 WebVTT
- `vtt` 字幕直接作为浏览器原生支持格式返回
- `sub/sup` 当前不声明网页播放器支持

前端接入时，HTML5 `<track>` 应优先使用 `web_player.url`，不要直接使用原始 `url`。

新增按资源保存的字幕显示设置：

- `GET /api/v1/resources/{id}/subtitle-settings`：打开播放页时读取当前资源的字幕显示参数。
- `PUT / PATCH /api/v1/resources/{id}/subtitle-settings`：保存字幕显示参数，支持请求体 `{ "settings": { ... } }`，也兼容直接传顶层字段。
- 统一字段为 `zhSize`、`zhColor`、`enSize`、`enColor`、`gap`、`offset`。
- `playback.subtitles.settings` 会内嵌同一份结构，前端拿资源列表后无需额外请求也能直接初始化播放器字幕样式。
- 当前按 `Resource` 维度保存；多用户系统上线后可扩展为 `User + Resource`。

在线字幕候选也补充了网页播放兼容性：

- 搜索结果每条候选新增 `format_normalized` 与 `web_player`
- 搜索排序优先展示 `srt/ass/ssa/vtt` 文本字幕，再展示未知格式，最后展示 `sub/sup` 位图字幕
- `sub/sup` 会标记为 `web_player.supported=false`，前端可提示它们不适合浏览器 `<track>`
- 字幕文件或嵌套压缩包超过后端大小限制时返回 HTTP `413`，不再按远端下载失败返回 `502`
- SubHD 返回 RAR 压缩包时当前仍不解压，但错误语义调整为 HTTP `415`

## 兼容性

- `metadata_issue_code` 参数名不变
- 响应结构不变
- `poster_asset_url/backdrop_asset_url` 字段名不变；未配置 `CYBER_IMAGE_ASSET_PUBLIC_BASE_URL` 时返回值仍是旧的后端相对路径
- `metadata_issues`、`metadata_state`、`metadata_actions`、`metadata_diagnostics` 字段继续沿用 `1.18.0` 结构
- 原始字幕 `url` 保持兼容；新增的 `web_player.url` 用于网页播放器 WebVTT 字幕
- 在线字幕候选仅新增字段并调整排序；`candidate_id`、`id`、下载/绑定请求形状保持兼容
- 旧 `openapi-1.18.0-beta` 目录保留，作为上一轮联调基线

## 验收状态

- OpenAPI JSON 可解析
- 运行时路由与 OpenAPI path/method 对齐
- OpenAPI / 图片 / 在线字幕 / 字幕发现专项测试通过：`54 tests OK`
- 全量后端测试通过：`240 tests OK`
