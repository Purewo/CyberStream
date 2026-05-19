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
