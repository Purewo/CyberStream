# 1.21.0-beta 更新说明

本文档记录 `1.21.0-beta` 的接口变化，作为其他视频归档联调基线。

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
- `storage-config-flow`
- `runbook`
- `test-checklist`

## 存储源目录刷新

新增 `POST /api/v1/storage/sources/{id}/refresh`，用于手动刷新已保存存储源的指定目录缓存。

说明：

- 当前仅 `alist/openlist` 支持，底层调用上游 `fs/list` 并带 `refresh=true`
- 该接口只刷新目录缓存并返回刷新后的列表，不触发扫描、不触发刮削
- `StorageSource.actions` 现在会额外暴露 `can_refresh`

## 资源库扫描刷新

- `POST /api/v1/libraries/{id}/scan` 默认会在扫描前刷新支持该能力的 `alist/openlist` 绑定目录。
- 前端可传 `{"refresh": false}` 跳过上游刷新，维持纯扫描行为。
- 目录刷新失败只写入扫描状态和后端日志，不会阻断后续扫描与刮削。
- `POST /api/v1/scan` 在没有任何启用的资源库目录绑定时会返回 `40013`，避免旧全库扫描入口误扫存储源根目录。
- `POST /api/v1/storage/sources/{id}/scan` 在没有显式 `root_path` 且该存储源未绑定任何资源库时会返回 `40013`，避免误触发存储源根目录扫描。

## TMDB 本机配置

- 新增 `GET /api/v1/system/tmdb-config`，返回 `token_set`、`proxy_enabled`、`proxy_url`，不会返回 TMDB token 明文。
- 新增 `PUT /api/v1/system/tmdb-config`，支持写入或清空 `TMDB_TOKEN`，以及更新 `TMDB_PROXY_ENABLED` / `TMDB_PROXY_URL`。写入 `.env.local` 后会尽量热更新运行时配置，响应包含 `hot_reload`。

## 在线字幕搜索稳定性

- 默认在线字幕搜索继续只跑 `subhd`，`srtku` 保持显式慢备用源。
- 搜索关键字默认先使用资源展示标题，再使用原名和文件名，避免中文片名资源优先被英文文件名带偏。
- 显式传入 `srtku` 时后端会实际尝试该备用源，但受独立超时预算限制；超时会记录到 `providers.errors`，并返回 `reason=timeout`。
- `CYBER_ONLINE_SUBTITLE_SRTKU_SEARCH_TIMEOUT_SECONDS` 默认改为 `5` 秒。
- 字幕下载、手动上传和 WebVTT 预览转换默认不限制字幕文件大小；如需限制，可显式设置 `CYBER_ONLINE_SUBTITLE_EXTRACTED_MAX_BYTES`、`CYBER_ONLINE_SUBTITLE_NESTED_ARCHIVE_MAX_BYTES`、`CYBER_SUBTITLE_MANUAL_UPLOAD_MAX_BYTES` 或 `CYBER_SUBTITLE_WEBVTT_CONVERSION_MAX_BYTES`。

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
