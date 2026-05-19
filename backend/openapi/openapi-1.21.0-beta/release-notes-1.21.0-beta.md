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

## 手动元数据匹配防幽灵数据

- `POST /api/v1/movies/{id}/metadata/match` 默认改为 dry-run 预览，不再因为前端点击候选就直接写库。
- 前端确认覆盖时需提交预览返回的 `apply_payload`，其中包含 `apply=true`。
- 预览响应新增 `current`、`preview`、`identity`、`diff`、`warnings`、`apply_method`、`apply_endpoint`、`apply_payload`。
- 当候选和当前影片最终都没有海报时，`apply=true` 会返回 `409`，防止无海报影片被前端过滤成不可见幽灵数据；确需写入时传 `allow_missing_poster=true`。
