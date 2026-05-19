# 前端审查工作台对接指南

本文档给前端定义“非标准资源”的展示边界和接口使用方式，避免在页面里自行推断资源状态。

当前后端约定：普通影视库、元数据审查、剧集审查、资源治理、其他视频归档和目录发布控制是六个不同视角。

## 1. 启动字典

前端进入维护/审查相关页面时，先请求：

```http
GET /api/v1/metadata/review-taxonomy
```

这个接口只读，不触发扫描，不写库。

前端应把它作为工作台字典使用：

- `buckets`：页面分区，包含普通影视库、元数据审查、剧集审查、资源治理、目录发布控制
- `issue_codes`：所有问题码到页面分区、列表接口和推荐动作的映射
- `metadata_issue_codes`：只属于元数据/剧集审查的问题码
- `resource_governance_issue_codes`：只属于资源治理的问题码
- `metadata_sources`：`scraper_source` 的标准解释
- `catalog_visibility`：发布/隐藏状态、blocker 和 warning 解释
- `frontend_rules`：前端必须遵守的边界规则

前端可以缓存该字典；它是后端契约，不是用户数据。

## 2. 页面边界

### 普通影视库

使用：

```http
GET /api/v1/movies
```

默认不传这些参数：

- `needs_attention`
- `metadata_source_group`
- `metadata_review_priority`
- `metadata_issue_code`

普通影视库只展示公开目录可见影片。后端默认会隐藏占位资料、本地兜底、缺海报、低置信和需要人工处理的条目。

### 元数据审查

使用：

```http
GET /api/v1/metadata/quality-summary
GET /api/v1/metadata/work-items
```

列表筛选只使用后端问题码：

```http
GET /api/v1/metadata/work-items?metadata_issue_code=poster_missing
```

前端不要根据 `scraper_source` 自己判断问题标签，应该使用：

- `metadata_issues[].code`
- `metadata_state.needs_attention`
- `metadata_state.review_priority`
- `metadata_actions.primary_action`
- `/metadata/review-taxonomy` 中同一 `code` 的 `bucket/list/action`

### 剧集审查

使用：

```http
GET /api/v1/metadata/episode-review-items
GET /api/v1/movies/{movie_id}/episode-diagnostics
PATCH /api/v1/movies/{movie_id}/resources/metadata
```

剧集类问题码：

- `season_metadata_missing`
- `episode_number_missing`
- `duplicate_episode_numbers`
- `missing_episode_numbers`
- `episode_count_mismatch`

`episode-review-items` 返回的 `apply_payload` 是后端 dry-run 后认为可自动提交的修正项。前端应先展示给用户确认，再提交到对应 `apply_endpoint`。

### 资源治理

使用：

```http
GET /api/v1/resources/governance-summary
GET /api/v1/resources/governance-items
POST /api/v1/resources/governance/plan
POST /api/v1/resources/governance/jobs
POST /api/v1/resources/governance/live-check/jobs
POST /api/v1/resources/governance/restore/plan
POST /api/v1/resources/governance/restore/jobs
```

资源治理只处理文件和索引问题，例如：

- `detached_source_resource`
- `movie_without_resources`
- `duplicate_playback_resource`
- `invalid_path`
- `size_mismatch`
- `source_unavailable`
- `live_check_skipped`

资源治理不代表元数据修复。不要把它和 `/metadata/work-items` 混成同一个列表，最多在同一个审查工作台下做不同 tab。

### 其他视频归档

使用：

```http
GET /api/v1/other-videos
POST /api/v1/movies/manual
POST /api/v1/movies/{movie_id}/resources/attach
```

适合自建课程、录屏、爬虫视频和其他不适合自动刮削的内容。

后端边界：

- 手工创建影片时只需要标题和简介，默认隐藏，不影响普通影视库。
- 手工内容会被标记为 `LOCAL_MANUAL_MOVIE` 或 `LOCAL_MANUAL_TV`。
- 手工条目默认不进入 `needs_attention`，也不要再按“刮削失败”处理。
- 默认队列只收未带季集号的未归档资源；带 `season` 的剧集资源只走 `/metadata/episode-review-items`。
- 其他视频项如果 `recommended_resolution=match_metadata`，优先让用户走 `actions.match_metadata.search -> preview -> apply_payload`；只有确认不是影视内容时才走 `actions.create_manual_movie`。
- 挂载资源时可以同时更新季/集、标题和简介，但不会移动实体文件。

### 目录发布控制

使用：

```http
PATCH /api/v1/movies/{movie_id}/catalog-visibility
```

`catalog_visibility` 只控制普通影视库是否可见：

- `auto`：后端自动判断
- `published`：管理员手动发布
- `hidden`：管理员手动隐藏

发布或隐藏不等于修复元数据。若 `requires_force=true`，前端必须明确提示 blocker，并要求用户确认后才传 `force=true`。

## 3. 非标准资源分类

前端按后端返回的 `issue_code` 分流：

| 类型 | 典型问题码 | 页面 |
| --- | --- | --- |
| 元数据不标准 | `placeholder_metadata`、`local_only_metadata`、`fallback_pipeline_match`、`low_confidence_resources`、`poster_missing` | 元数据审查 |
| 剧集结构不标准 | `season_metadata_missing`、`missing_episode_numbers`、`duplicate_episode_numbers` | 剧集审查 |
| 文件/索引不标准 | `invalid_path`、`duplicate_playback_resource`、`detached_source_resource` | 资源治理 |
| 自建视频归档 | `LOCAL_MANUAL_MOVIE`、`LOCAL_MANUAL_TV` | 其他视频归档 |
| 目录可见性 | `catalog_visibility.blockers` | 发布控制 |

## 4. 推荐前端流程

1. 进入审查工作台时请求 `/metadata/review-taxonomy`。
2. 请求 `/metadata/quality-summary` 渲染总览卡片和问题入口。
3. 用户点击某个问题码时，根据 taxonomy 中的 `list.endpoint` 和 `list.params` 打开列表。
4. 其他视频归档页先调用 `/other-videos`，再用 `POST /movies/manual` 或 `POST /movies/{movie_id}/resources/attach` 完成整理。
5. 列表项按钮优先使用 taxonomy 的 `action`，再结合条目自身 `metadata_actions` 做禁用态。
6. 批量操作必须先走 `plan` 或 `dry-run`，用户确认后再提交 job。
7. 普通影视库、首页、推荐、播放页面不使用审查工作台筛选参数。

## 5. 禁止自由发挥的地方

- 不要用 `scraper_source` 直接决定问题标签。
- 不要在普通 `/movies` 默认请求里带 `needs_attention=true`。
- 不要把资源治理问题当成元数据问题。
- 不要把 `published` 当成“资料已修复”。
- 不要前端自己硬编码 issue code 的中文名和按钮，优先使用 `/metadata/review-taxonomy`。
- 不要绕过 `plan` 直接批量删除资源索引。

## 6. 用户系统过渡

用户管理默认关闭时，现有前端可以继续使用当前接口。

用户管理开启后：

- 审查工作台、资源治理、目录发布和用户管理页面只应给管理员展示。
- 普通用户只展示普通影视库、详情、播放、历史和个性化设置。
- 用户系统详细接入见 `docs/FRONTEND_USER_MANAGEMENT_INTEGRATION.md`。

## 7. 最小联调清单

```http
GET /api/v1/metadata/review-taxonomy
GET /api/v1/metadata/quality-summary
GET /api/v1/metadata/work-items?metadata_issue_code=poster_missing
GET /api/v1/metadata/episode-review-items
GET /api/v1/resources/governance-summary
GET /api/v1/resources/governance-items?issue_code=invalid_path
```

预期：

- 普通影视库不出现默认隐藏的非标准资源。
- 审查工作台能按 issue code 进入正确列表。
- 剧集问题和资源治理问题不混在同一列表里。
- 发布/隐藏只影响普通影视库可见性，不清除问题码。
