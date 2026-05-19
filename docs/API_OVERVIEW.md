# API 概览

当前后端蓝图前缀为：`/api/v1`

## 0. 当前基线

当前版本：`1.21.0`

当前 OpenAPI 联调基线：

- `backend/openapi/openapi-1.21.0-beta/openapi-1.21.0-beta.json`
- `backend/openapi/openapi-1.21.0-beta/release-notes-1.21.0-beta.md`

当前 `main` 即最新版主干，后续小步提交直接进入 `main`。

## 0.1 鉴权

默认用户管理关闭时，设置 `CYBER_API_TOKEN` 后，除健康检查、媒体流和影片图片 GET 外，管理类 API 需要携带：

```http
Authorization: Bearer <token>
```

也兼容：

```http
X-Cyber-API-Token: <token>
```

未设置 token 时鉴权不启用，便于本地开发和当前前端联调。

启用 `CYBER_USER_MANAGEMENT_ENABLED=true` 后，网页端使用 `POST /api/v1/auth/login` 写入 HttpOnly cookie；`CYBER_API_TOKEN` 仍作为管理员后门。普通用户只允许读取可见影视、播放、维护自己的观看历史和字幕样式。

前端平滑接入方案见：`docs/FRONTEND_USER_MANAGEMENT_INTEGRATION.md`。

审查工作台边界和非标准资源对接方案见：`docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md`。

### 0.2 用户管理接口

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET/PATCH /api/v1/user/profile`
- `POST /api/v1/user/password`
- `GET/POST /api/v1/admin/users`
- `GET/PATCH /api/v1/admin/users/<id>`
- `POST /api/v1/admin/users/<id>/password`
- `PUT /api/v1/admin/users/<id>/library-rules`
- `GET /api/v1/admin/users/<id>/visibility-preview`
- `GET /api/v1/admin/audit-logs`

## 1. 健康检查

### `GET /`
返回服务状态与版本信息。

---

## 1.1 文档与契约入口

这些接口是给前端开发者自助联调用的公开只读入口，不需要猜线上 Swagger 地址。

### `GET /api/v1/docs`
返回当前文档索引，包含 OpenAPI JSON 和白名单 Markdown 文档地址。

### `GET /api/v1/openapi.json`
返回当前 OpenAPI JSON 原文，不包标准 `ApiResponse` 外壳，适合前端类型生成器直接消费。

### `GET /api/v1/docs/openapi.json`
`/api/v1/openapi.json` 的文档命名空间别名，返回内容相同。

### `GET /api/v1/docs/<doc_key>`
按固定 key 返回 Markdown 文档原文。当前白名单：

- `release-notes`
- `api-overview`
- `frontend-review-workbench`
- `frontend-user-management`
- `frontend-audio-transcode`
- `storage-config-flow`
- `runbook`
- `test-checklist`

---

## 2. 当前路由模块结构

当前 API 已按领域拆分：

- `backend/app/api/system_routes.py`
  - 扫描系统相关接口
- `backend/app/api/library_routes.py`
  - 影视库、筛选、推荐、详情、影片元数据修改等接口
- `backend/app/api/libraries_routes.py`
  - 逻辑资源库（Library）管理、来源绑定、按库浏览、按库扫描接口
- `backend/app/api/history_routes.py`
  - 用户观看历史相关接口
- `backend/app/api/storage_routes.py`
  - 存储源管理、预览、指定源扫描
- `backend/app/api/player_routes.py`
  - 播放流相关接口
- `backend/app/api/routes.py`
  - **legacy 兼容层**，当前仅保留历史兼容接口位置（接口已临时停用）

维护约定：
- 新增业务接口默认不要继续写入 `routes.py`
- `routes.py` 只用于保留旧接口兼容入口

---

## 3. 逻辑资源库（Library）

### `GET /api/v1/libraries`
列出所有逻辑资源库。

### `POST /api/v1/libraries`
创建逻辑资源库。

核心字段：
- `name`
- `slug`

可选字段：
- `description`
- `is_enabled`
- `sort_order`
- `settings`

### `GET /api/v1/libraries/<id>`
获取单个资源库详情（含已绑定来源）。

### `PATCH /api/v1/libraries/<id>`
更新资源库信息。

支持字段：
- `name`
- `slug`
- `description`
- `is_enabled`
- `sort_order`
- `settings`

### `DELETE /api/v1/libraries/<id>`
删除资源库。

### `GET /api/v1/libraries/<id>/sources`
查看资源库绑定的存储源。

### `POST /api/v1/libraries/<id>/sources`
为资源库绑定存储源。

核心字段：
- `source_id`

可选字段：
- `root_path`
- `content_type`
- `scrape_enabled`
- `scraper_policy.provider_order`
- `provider_order`，为 `scraper_policy.provider_order` 的扁平别名
- `scan_order`
- `is_enabled`

说明：
- `provider_order` 当前支持 `nfo`、`tmdb`、`bangumi`、`local`
- 默认顺序仍为 `nfo -> tmdb -> local`；动漫库可显式传 `nfo -> bangumi -> tmdb -> local`
- 资源库扫描会按绑定上的 `content_type`、`scrape_enabled` 和 `scraper_policy` 执行

动漫库绑定示例：

```json
{
  "source_id": 1,
  "root_path": "/Anime",
  "content_type": "tv",
  "provider_order": ["nfo", "bangumi", "tmdb", "local"]
}
```

### `PATCH /api/v1/libraries/<id>/sources/<binding_id>`
更新资源库与存储源的绑定关系。

### `DELETE /api/v1/libraries/<id>/sources/<binding_id>`
解除资源库与存储源的绑定关系。

### `GET /api/v1/libraries/<id>/movie-memberships`
查看资源库的手动影视规则。

支持查询参数：
- `mode=include|exclude`

说明：
- `include` 表示把某个已入库影视手动加入该资源库
- `exclude` 表示把自动命中该库的影视从该资源库中排除

### `POST /api/v1/libraries/<id>/movie-memberships`
批量新增或更新资源库手动影视规则。

请求体：
- `mode=include|exclude`
- `movie_ids`
- `sort_order`

说明：
- 只允许引用已经存在的影视条目
- 同一资源库与同一影视只保留一条规则，重复提交会更新 `mode`

### `POST /api/v1/libraries/<id>/movie-memberships/delete`
批量删除资源库手动影视规则。

请求体：
- `movie_ids`

### `GET /api/v1/libraries/<id>/movies`
按资源库分页查看影片列表（当前支持按 `source_id + root_path` 过滤）。

支持查询参数：
- `page`
- `page_size`
- `sort_by=date_added|updated_at|year|rating|title`
- `order=asc|desc`

返回数据：
- `items`
- `total`
- `pagination`

返回项补充：
- `library_membership=auto|manual|both`

资源库内容规则：
- 自动内容来自已绑定挂载点与 `root_path`，但只纳入无需人工处理且有海报的公开影视
- 手动 `include` 会补充不在绑定路径内的影视
- 需要人工处理的 raw/占位/缺海报影片不会因挂载点自动进入资源库，必须通过手动 `include` 拉入
- 手动 `exclude` 会从该资源库隐藏自动命中的影视

### `GET /api/v1/libraries/<id>/featured`
按资源库获取置顶/轮播内容（当前支持按 `source_id + root_path` 过滤）。

### `GET /api/v1/libraries/<id>/recommendations`
按资源库获取推荐内容。

支持参数：
- `limit`
- `strategy=default|latest|top_rated|surprise|continue_watching`

说明：
- 返回结构仍是影片数组
- 每个影片条目会额外带 `recommendation`
- `recommendation.primary_reason` 给前端展示主推荐理由
- `recommendation.reasons` 包含续看、最近入库、高评分、清晰度、可播放资源、类型多样性等信号

### `GET /api/v1/libraries/<id>/filters`
按资源库获取筛选项。

支持：
- `genres`
- `years`
- `countries`

### `POST /api/v1/libraries/<id>/scan`
按资源库触发扫描任务。

当前行为：
- 按绑定顺序扫描该库所有启用的 source
- 扫描时支持 `root_path` 限定起始路径
- 入库时仍保持 `MediaResource.path` 为相对 source 根路径，避免破坏现有播放与资源定位逻辑
- 与全量扫描、指定存储源扫描共用同一个运行锁；已有扫描任务执行中时返回 `429`

---

## 4. 存储源管理

### `GET /api/v1/storage/sources`
列出所有存储源。

返回字段补充：
- `display_name`
- `is_supported`
- `config_valid`
- `config_error`
- `capabilities`：当前来源是否支持 `preview`、`scan`、`stream`、`ffmpeg_input`
- `config`：脱敏后的当前配置摘要
- `actions`：前端可直接判断是否展示 `preview/scan/stream` 入口
- `usage`：当前来源被多少资源库绑定、已有多少资源引用
- `guards`：当前来源是否允许改类型、是否允许直接删除

说明：
- 列表接口默认不做实时网络探测，避免来源多了以后把列表拉慢
- 此时 `status` 只表达静态支持状态：当前通常是 `unknown` 或 `unsupported`

### `GET /api/v1/storage/sources/<id>`
获取单个存储源详情。

说明：
- 返回结构与列表项一致，但适合编辑页单条拉取
- 敏感字段会做脱敏展示，例如 `password` 仅返回 `***`

### `GET /api/v1/storage/sources/<id>/health`
显式获取单个存储源的实时健康状态。

说明：
- 该接口会实际触发 provider 健康检查
- 返回 `health` 字段，包含 `status`、`reason` 和 `message`
- `status` 可能为 `online|offline|unknown|unsupported`
- `reason` 为机器可读原因，便于前端和运维快速区分 `dns_resolution_failed`、`auth_failed`、`permission_denied`、`root_not_found`、`timeout` 等问题

### `GET /api/v1/storage/provider-types`
列出当前后端真正支持的存储协议与配置字段定义。

说明：
- 当前稳定支持：`local`、`webdav`、`smb`、`ftp`、`alist`、`openlist`
- 该接口应作为前端动态表单的首选来源，而不是硬编码协议类型
- 后续新增来源时，优先扩展该接口和 provider 注册表，而不是散落到多个地方手写判断
- 每个协议会返回 `capabilities`，用于前端决定是否展示扫描、播放、预览等入口

### `GET /api/v1/storage/capabilities`
返回目录选择器、资源库绑定和播放链路所需的协议能力矩阵。

说明：
- `supported_types` 给出当前后端可用协议
- `items[].browse`、`items[].validate_path`、`items[].library_root_path` 可直接驱动前端目录选择器
- `items[].config_root_key` 区分本地 `root_path` 与远端协议 `root`
- `range_stream`、`redirect_stream` 用于播放链路能力展示

### `POST /api/v1/storage/sources`
新增存储源。

请求体核心字段：
- `name`
- `type`
- `config`

说明：
- 当前会对 `type` 和 `config` 做集中校验
- `local` 当前要求 `config.root_path`
- `webdav` 当前要求 `config.host`，其余字段按默认值补齐或校验
- `smb` 当前要求 `config.host` 和 `config.share`
- `ftp` 当前要求 `config.host`，未提供账号密码时使用 anonymous 默认值
- `alist/openlist` 当前要求 `config.base_url` 或 `config.host` 至少一个
- `alist/openlist` 的 `config.root` 是技术挂载根目录；目录选择器选定挂载目录时应写入该字段
- 不支持的配置字段会直接报错，避免脏配置落库

### `PATCH /api/v1/storage/sources/<id>`
更新存储源名称或配置。

说明：
- 现支持更新 `name`、`type`、`config`
- `config` 仍为整对象替换，不做字段级 merge
- 若切换 `type`，新的 `config` 也会按目标协议重新校验
- 若该来源已被资源或资源库绑定引用，当前不允许直接改 `type`

### `DELETE /api/v1/storage/sources/<id>`
删除存储源。

支持查询参数：
- `keep_metadata=true|false`

说明：
- 若该来源下仍有资源，当前默认不允许直接删除
- 需要显式传 `keep_metadata=true`，或先做资源迁移/解绑

### `POST /api/v1/storage/sources/<id>/scan`
扫描指定存储源。

支持请求体：
- `root_path` / `target_path`
- `content_type`
- `scrape_enabled`
- `scraper_policy.provider_order`
- `provider_order`，为 `scraper_policy.provider_order` 的扁平别名

说明：
- 与全量扫描、资源库扫描共用同一个运行锁；已有扫描任务执行中时返回 `429`
- `provider_order` 当前支持 `nfo`、`tmdb`、`bangumi`、`local`；未传时使用默认顺序
- 动漫源建议显式传 `["nfo", "bangumi", "tmdb", "local"]`；后端不会自动替用户把普通影视库切到 Bangumi 优先

### `GET /api/v1/storage/sources/<id>/browse`
浏览已保存存储源的目录。

说明：
- 用于资源库绑定时选择 `root_path`
- 支持查询参数 `path` 和 `dirs_only`
- 返回结构与 `POST /api/v1/storage/preview` 的目录列表一致，并额外带回 `source`
- `path` 是相对于已保存 `config.root` 的浏览路径，不会修改来源配置

### `POST /api/v1/storage/preview`
测试某类存储配置并预览目录。

说明：
- 走与正式存储源相同的 `type/config` 校验链路
- 可作为前端“测试连接 + 目录预览”的统一入口
- 当前支持 `local/webdav/smb/ftp/alist/openlist`
- `target_path` 只表示本次预览路径；保存来源时仍需把最终挂载根写入 `config.root`

---

## 5. 扫描系统

### `GET /api/v1/scan`
获取扫描状态。

说明：
- `phase` 会在 `preparing/indexing/grouping/optimizing/processing/idle` 之间变化
- `indexing` 阶段不提前计算总文件数，`discovered_files`、`total_files`、`indexed_dirs` 会随遍历实时增长
- `total_items_known=false` 表示当前阶段总数还不可确定，前端应展示不定长进度或“已发现 N 个文件”
- `processing` 阶段表示正在刮削/入库，`current_item`、`current_file`、`processed_items`、`total_items`、`processed_files` 可用于显示刮削进度
- `active_items` 表示当前并发处理中的条目，前端可展示“正在刮削”的文件/影片列表

### `POST /api/v1/scan`
触发全量扫描。

说明：
- 与资源库扫描、指定存储源扫描共用同一个运行锁；已有扫描任务执行中时返回 `429`

---

## 6. 影视库

### `GET /api/v1/filters`
获取筛选项。

可包含：
- `genres`
- `years`
- `countries`

说明：
- 全局筛选项默认只统计公开影视库，不包含需要人工处理的 raw/占位/缺海报影片
- 元数据工作台筛选仍通过 `metadata_source_groups`、`metadata_review_priorities`、`metadata_issue_codes` 返回完整处理维度

### `GET /api/v1/featured`
获取首页置顶/轮播内容。

### `GET /api/v1/recommendations`
获取推荐影视。

查询参数示例：
- `limit`
- `strategy=default|latest|top_rated|surprise|continue_watching`

说明：
- `default` 现在是综合推荐：会考虑续看、最近入库、评分、清晰度、可播放资源和类型多样性
- `latest` 偏最近入库
- `top_rated` 偏高评分
- `continue_watching` 偏未看完的续看内容
- `surprise` 保留轻随机探索
- 每个影片条目会带 `recommendation`，便于前端展示推荐理由而不是只展示随机列表

### `GET /api/v1/movies/<id>/recommendations`
获取单片上下文相关推荐，适合详情页或播放页下方列表。

支持参数：
- `limit`
- `library_id`：可选。资源库内详情页传当前资源库 ID，推荐会先从该库最终影片集合里选，不足再从全局补齐。

说明：
- 返回结构仍是影片数组，每个条目带 `recommendation`
- 未传 `library_id` 时按全局单片上下文推荐
- 传 `library_id` 时先按当前资源库候选排序，库内候选不足 `limit` 才使用库外候选补齐
- 同系列 / 同标题族优先，例如同一电影系列或误拆成多个条目的不同季
- 同系列数量不足时，用同类型内容补齐
- 同类型仍不足时，只在同分区内兜底
- 动漫与非动漫严格隔离：当前影片含 `动画` 时只推荐动漫；当前影片不含 `动画` 时绝不推荐动漫
- 候选不足时允许返回少于 `limit`，不会跨动漫边界补齐

### `GET /api/v1/homepage`
获取首页门户聚合数据。

返回：
- `hero`：超大海报影片，支持后台指定；未指定时自动返回最新且有横幅图的影片
- `sections`：首页分类区块，默认包含 `科幻`、`动作`、`剧情`、`动画`，每个分类默认最多 15 个
- 首页区块按影片条目计数，不返回可展开的 `season_cards`，避免多季动漫在门户里突破分类数量限制

首页去重规则：
- hero 影片不会出现在下方分类区块
- 后面的分类区块不会重复前面已经返回过的影片
- 一旦启用 `动画` 分类，其余分类不会展示带 `动画` 标签的影片

### `GET /api/v1/homepage/config`
获取首页配置。

### `PATCH /api/v1/homepage/config`
更新首页配置。

支持字段：
- `hero_movie_id`
- `sections`

`sections` 为完整数组替换，每项支持：
- `key`
- `title`
- `genre`
- `mode=custom|latest`
- `limit`
- `movie_ids`
- `enabled`
- `sort_order`

### `GET /api/v1/reviews/resources`
获取路径清洗阶段标记为 `needs_review` 的资源复核队列。

支持查询参数：
- `page`
- `page_size`
- `source_id`
- `provider`
- `parse_mode`
- `keyword`

说明：
- 返回 `path_cleaning` 与 `scraping` 两层分析结果
- 返回 `resource_info` 作为资源原始信息统一入口
- 用于后续人工复核、重新刮削和命名修正工作台

### `GET /api/v1/resources/governance-summary`
获取资源治理只读汇总。

支持查询参数：
- `live_check`，默认 `false`
- `live_check_limit`，默认 `50`，最大 `500`
- `sample_size`，默认 `3`

说明：
- 只读 dry-run，不删除资源、不修改影片、不触发扫描
- 默认只做数据库层治理分析：孤儿资源、空壳影片、重复播放资源
- `live_check=true` 时才访问存储源；后端会按资源父目录 `list_items()`，再匹配文件名和大小，不直接用 `path_exists()` 判断视频文件
- 返回 `issues[].samples` 和 `actions`，前端可作为扫描治理工作台入口
- 失效路径、大小变化或存储源不可用只作为建议，不自动清理

### `GET /api/v1/resources/governance-items`
分页获取资源治理问题条目。

支持查询参数：
- `issue_code`
- `page`
- `page_size`
- `live_check`
- `live_check_limit`

当前 issue：
- `detached_source_resource`
- `movie_without_resources`
- `duplicate_playback_resource`
- `invalid_path`
- `size_mismatch`
- `source_unavailable`
- `live_check_skipped`

### `POST /api/v1/resources/governance/plan`
生成资源治理清理 dry-run。

请求体：
- `issue_codes`，默认 `duplicate_playback_resource`、`detached_source_resource`、`invalid_path`
- `resource_ids`
- `movie_ids`
- `live_check`
- `live_check_limit`
- `limit`
- `page`
- `page_size`

说明：
- 只生成计划，不修改数据库
- 自动计划只覆盖重复资源副本、孤儿资源索引和 live check 后确认缺失的资源索引
- 有播放历史、已绑定字幕或属于影片最后一个资源时会跳过
- `limit` 或 `page/page_size` 会限制返回的 `items` 和 `apply_payload.items`，`summary` 仍保留全量统计
- `returned_summary` 统计当前返回范围内的计划项
- `apply_payload` 可直接提交给 `/api/v1/resources/governance/jobs`
- `delete_physical_file=false`，后端不会删除实体文件

### `POST /api/v1/resources/governance/jobs`
后台执行资源治理清理计划。

请求体：
- `confirm=true`
- `items`，来自 `/resources/governance/plan` 的 `apply_payload.items`

说明：
- 执行前重新校验资源仍符合原 issue
- 仅删除 `MediaResource` 数据库索引，不删除影片、不删除实体文件
- 重复资源只删除当前副本，当前主资源永远不会被删除
- 每个已删除项会在 job result 里返回 `restore_snapshot`，包含 `MediaResource` 完整字段，便于人工恢复索引
- 任务状态通过 `GET /api/v1/jobs/<job_id>` 查询

### `POST /api/v1/resources/governance/live-check/jobs`
后台执行有界资源路径 live check。

请求体：
- `live_check_limit`，默认 `100`，最大 `500`
- `sample_size`
- `issue_code`
- `page`
- `page_size`

说明：
- 只读任务，不删除资源、不修改数据库
- 适合大批量真实存储检查，避免同步请求阻塞
- job result 返回 `summary`、分页后的 `items`、`pagination` 和 `item_summary`
- 仍使用父目录 `list_items()` 匹配文件名和大小

### `POST /api/v1/resources/governance/restore/plan`
根据清理 job 返回的 `restore_snapshot` 生成资源索引恢复 dry-run。

请求体：
- `restore_snapshots`，数组，来自 `/resources/governance/jobs` 的 `result.items[].restore_snapshot`

说明：
- 只生成计划，不修改数据库
- 恢复前检查影片是否存在、存储源是否存在、resource id 是否已存在、`source_id + path` 是否冲突
- 只恢复 `MediaResource` 索引，不恢复观看历史、不恢复字幕绑定、不移动或写入实体文件
- `apply_payload` 可直接提交给 `/api/v1/resources/governance/restore/jobs`

### `POST /api/v1/resources/governance/restore/jobs`
后台执行资源索引恢复。

请求体：
- `confirm=true`
- `items`，来自 `/resources/governance/restore/plan` 的 `apply_payload.items`

说明：
- 执行前重新检查恢复安全条件
- 只重建 `MediaResource` 行，不改实体文件、不恢复历史或字幕
- 任务状态通过 `GET /api/v1/jobs/<job_id>` 查询

### `GET /api/v1/jobs`
查询维护后台任务。

说明：
- `metadata_re_scrape`、`resource_governance_apply`、`resource_governance_live_check`、`resource_governance_restore` 等任务会写入 `maintenance_jobs`
- 后端重启后仍可通过 `/jobs` 和 `/jobs/<job_id>` 查询已持久化任务
- 返回的 `job.persisted=true` 表示该任务来自持久化记录
- 持久化结果会按 `MAINTENANCE_JOB_RESULT_ITEM_LIMIT` 截断 `result.items`，内存中的刚执行结果仍保持完整

### `POST /api/v1/jobs/prune`
清理过期维护后台任务。

请求体：
- `retention_days`，默认读取 `MAINTENANCE_JOB_RETENTION_DAYS`
- `type`
- `dry_run`

说明：
- 只清理 `succeeded`、`failed` 且 `finished_at` 早于保留窗口的任务
- 不清理 `queued`、`running`
- `dry_run=true` 只返回匹配项，不删除
- 返回 `matched/removed`、任务 id 列表和类型/状态统计

### `GET /api/v1/movies`
获取影视列表。

支持：
- 分页
- 关键词搜索
- 类型筛选
- 地区筛选
- 年份筛选
- 来源筛选
- 排序

列表项补充：
- `quality_badge`：影片级海报标签，只会返回 `Remux`、`4K`、`HD` 或 `null`

清晰度标签规则：
- 任一资源为 Remux 时返回 `Remux`
- 否则任一资源为 4K/2160P 时返回 `4K`
- 否则任一资源为 1080P 时返回 `HD`
- 其他情况返回 `null`

默认行为：
- 不传 `needs_attention` 且不传元数据工作台筛选时，只返回总影视库可见影片：默认规则为无需人工处理且有海报，也包含用户显式 `published` 的影片，并排除用户显式 `hidden` 的影片
- `needs_attention=true` 返回待人工处理的影片，包含 raw/占位/缺海报条目，适合做处理队列入口
- 显式传 `metadata_source_group`、`metadata_review_priority`、`metadata_issue_code` 时按工作台筛选语义返回，不额外强制公开库过滤
- 手工归档影片默认不会混入普通列表，需通过 `/api/v1/other-videos`、资源库显式 `include` 或手动发布进入可见范围

### `GET /api/v1/movies/<id>`
获取影视详情。

说明：
- 只返回影片主体、元数据状态、观看状态、季卡片摘要等详情页主信息
- 不再内嵌资源列表；资源面板统一调用 `GET /api/v1/movies/<id>/resources`
- 影片列表和详情都会返回 `catalog_visibility`，前端可据此展示“自动发布 / 手动发布 / 手动隐藏”和阻塞原因

### `GET /api/v1/other-videos`
获取待手工归档的其他视频资源。

说明：
- 默认只返回未手工归档、未带季集号的 `LOCAL_FALLBACK`、`LOCAL_ORPHAN`、未知来源等需要人工整理的单文件资源
- 带 `season` 的剧集资源不进入该队列；缺集、重复集号、集号缺失和季资料问题统一走 `/api/v1/metadata/episode-review-items`
- `include_manual=true` 时也可把已手工归档的资源重新纳入列表
- 每条返回 `resource_info`、`playback`、`metadata_state`、`catalog_visibility` 和手工归档所需的动作入口；这里的 `metadata_issues` 不包含剧集审查问题码
- 每条同时返回 `metadata_match_context` 与 `actions.match_metadata`，用于把明显是真实电影/剧集的资源走“搜索候选 -> 预览匹配 -> 确认覆盖”流程，而不是强制手工创建
- 这是给“自建课程 / 爬虫视频 / 录屏 / 零散视频”使用的整理页入口，不属于元数据审查工作台

前端推荐流程：
- 如果 `recommended_resolution=match_metadata`，展示“匹配影视元数据”入口，默认查询参数取 `actions.match_metadata.search.params`
- 用户可编辑 `metadata_match_context.suggested_query/suggested_year/suggested_media_type_hint` 后调用 `actions.match_metadata.search`
- 用户选中候选后，先调用 `actions.match_metadata.preview`，不传 `apply` 或传 `apply=false`
- 用户确认覆盖后，直接提交 preview 响应里的 `apply_payload`；不要自己拼最终覆盖 payload
- 只有确认这是课程、录屏、广告、零散自建视频等非影视内容时，才使用 `actions.create_manual_movie`

### `POST /api/v1/movies/manual`
新建手工电影或电视剧壳，并可同步挂入已有资源。

支持请求体：
- `title` / `name`
- `description` / `overview` / `intro`
- `media_type` / `type`，值为 `movie` 或 `tv`
- `resource_ids` 或 `resources`
- `library_ids`
- `default_season`
- `episode_start`
- `catalog_visibility_status` / `status`
- `note`
- `preserve_episode_metadata`

说明：
- 默认创建为隐藏条目，不会污染普通影视库
- `resources` 里的每个项可以单独覆盖 `season/episode/title/overview/label`
- 适合把“爬虫课程”“录屏合集”“自建视频课件”整理成一个普通电影或电视剧条目

### `POST /api/v1/movies/<id>/resources/attach`
给已有影片追加挂载资源。

支持请求体：
- `resource_ids` 或 `resources`
- `library_ids`
- `default_season`
- `episode_start`
- `preserve_episode_metadata`
- `media_type`
- `note`

说明：
- 只重挂索引和资源元数据，不移动实体文件
- 如果目标影片是手工影片，后端会继续把它维持为手工来源

### `PATCH /api/v1/movies/<id>/catalog-visibility`
更新单条影片在总影视库中的发布状态。

支持请求体：
- `status=auto|published|hidden`
- `force`
- `note`

说明：
- `auto`：使用默认规则，当前为“可信外部/本地 NFO 元数据 + 有海报”进入总影视库
- `published`：用户手动纳入总影视库；如果当前存在 `metadata_needs_attention`、`poster_missing` 等阻塞原因，后端会先返回 `409`，需要前端让用户确认后再带 `force=true` 提交
- `hidden`：用户手动从总影视库隐藏；不影响通过影片详情 ID 访问，也不影响资源库手动 `include`
- 该接口只控制总影视库、全局推荐、全局筛选和 featured 自动候选，不替代资源库 `movie-memberships include/exclude`

推荐请求体：

```json
{
  "status": "published",
  "force": true,
  "note": "用户确认加入总影视库"
}
```

### `GET /api/v1/movies/<id>/resources`
获取单条影片下的资源列表与按季分组结果。

说明：
- 返回唯一资源列表 `items`
- 返回分组索引 `groups.standalone.resource_ids`（无季信息资源）
- 返回分组索引 `groups.seasons`（按 `season` 分组后的资源，只包含 `resource_ids`，不重复嵌入资源对象）
- 返回播放源分组索引 `groups.playback_sources`，用于详情页默认展示主播放源，并把同文件副本折叠为备用播放源
- 返回 `summary`，包含总资源数、去重后播放源数、重复副本组数、备用资源数、季数、无季资源数、已手动编辑资源数
- `summary` 额外包含 `season_metadata_count`
- `items` 仍保留全量资源对象，不改变现有资源管理与排查入口；前端默认播放源列表应优先读取 `groups.playback_sources[].primary_resource_id`
- 当前副本判定规则为同一影片内 `season/episode + filename + size_bytes` 一致；只有判定为副本的资源会出现在 `alternate_resource_ids`
- 主播放源选择优先级：最近观看记录 > 质量层级 > 分辨率 > 文件大小 > 创建时间；这样用户从备用源看过后，默认续播会优先落到该资源
- 每个资源只包含：
  - `id`
  - `resource_info.file`：文件名、路径、大小、容器、存储源
  - `resource_info.display`：展示标题、展示标签、季集、排序信息
  - `resource_info.technical`：分辨率、编码、HDR、音频、片源和质量层级
  - `playback`：播放能力矩阵、外部播放器链接、同目录外挂字幕、网页音频兼容和转码状态
  - `metadata.trace`：解析/刮削留痕
  - `metadata.analysis`：路径清洗与刮削分析
  - `metadata.edit_context`：人工编辑上下文
- 电影/剧集级 `tags` 表示内容分类；资源额外标签读取 `resource_info.technical.extra_tags`
- `4K` 不再作为独立标签重复返回；前端可由 `resource_info.technical.video_resolution_bucket = "4k"` 推导展示
- `resource_info.technical` 已在 OpenAPI 中完全展开，前端推荐按以下稳定字段读取：
  - `video_resolution_code/video_resolution_label/video_resolution_bucket/video_resolution_rank/video_resolution_badge_label/video_resolution_is_known`：`2160P` 保留在 `label/code`，`4K` 由 `bucket = "4k"` 或 `badge_label = "4K"` 推导
  - `video_codec_code/video_codec_label/video_codec_is_known`：视频编码，例如 `hevc`
  - `video_dynamic_range_code/video_dynamic_range_label/video_dynamic_range_is_hdr/video_dynamic_range_is_known`：HDR10/HDR10+/Dolby Vision/HLG/SDR/Unknown；普通 `HDR` 会规范为 `HDR10`，只有明确出现 SDR 标记才返回 `sdr`
  - `video_bit_depth_code/video_bit_depth_label/video_bit_depth_value/video_bit_depth_detected`：位深，例如 `10bit`
  - `audio_codec_code/audio_codec_label/audio_codec_is_atmos/audio_codec_is_known/audio_is_atmos/audio_channels_label/audio_channel_count/audio_is_lossless/audio_summary_label`：音频编码、声道、Atmos 和无损标记，例如 `Dolby TrueHD 7.1 Atmos`
  - `source_code/source_label/source_kind/source_is_remux/source_is_uhd_bluray/source_is_known`：片源类型和 REMUX/UHD Blu-ray 标记，例如 `UHD Blu-ray Remux`
  - `quality_tier/quality_tier_label/quality_rank/quality_is_reference/quality_is_original_quality`：资源质量层级
  - `flag_is_4k/flag_is_1080p/flag_is_hdr/flag_is_hdr10/flag_is_hdr10_plus/flag_is_hlg/flag_is_dolby_vision/flag_is_remux/flag_is_uhd_bluray/flag_is_lossless_audio/flag_is_original_quality/flag_is_movie_feature/flag_imax/flag_ten_bit`：解析得到的布尔辅助特征
  - `extra_tags`：仅放结构化字段覆盖不了的额外标签，例如 `IMAX`
- `playback.stream_url` 是后端播放入口；外部播放器也可以使用该地址，AList/OpenList 会继续由该入口 302 到上游 `/d/...` 直链
- 后端生成的播放、音频转码和字幕绝对 URL 会信任反向代理 `X-Forwarded-Proto` / `X-Forwarded-Host`；HTTPS 部署若反代未传这些头，可设置 `CYBER_BACKEND_PUBLIC_BASE_URL=https://<domain>` 强制返回 HTTPS 地址
- `playback.subtitles.items` 当前会发现与视频同目录、同文件名前缀的外挂字幕，也会包含用户确认后绑定的在线字幕缓存；支持 `srt/ass/ssa/vtt/sub/sup`，每个字幕项包含 `id`、`source`、`format`、`language`、`is_default`、`url` 和 `web_player` 等字段
- 字幕项的 `url` 保留原始字幕流，主要给外部播放器使用；网页播放器应优先读取 `web_player.url`。当原始字幕为 `srt/ass/ssa` 时，`web_player.url` 会自动追加 `format=vtt`，后端动态转成 HTML5 `<track>` 可加载的 WebVTT；启用 Super CDN 后，用户绑定的在线/手动字幕会优先返回 `china_all` 桶中的原始字幕和 WebVTT CDN URL；`sub/sup` 当前不支持浏览器字幕
- `playback.subtitles.settings` 返回当前资源的字幕显示设置，统一字段为 `zhSize`、`zhColor`、`enSize`、`enColor`、`gap`、`offset`；前端打开播放页可直接使用该结构初始化播放器字幕样式
- 字幕显示设置也可通过 `GET /api/v1/resources/<id>/subtitle-settings` 单独读取，并通过 `PUT` 或 `PATCH /api/v1/resources/<id>/subtitle-settings` 保存；请求体推荐 `{ "settings": { ... } }`，也兼容直接传顶层字段，当前按 Resource 维度保存
- `playback.external_player.subtitle_urls` 会同步填充原始字幕 URL；字幕流复用 `GET /api/v1/resources/<id>/stream?subtitle_id=...`，只允许访问当前资源已发现的字幕
- `GET /api/v1/resources/<id>/external-playback` 返回面向 PC/外部播放器的播放交接清单，包含绝对 `stream.url`、默认字幕 URL、`playlist_url` 和播放器 profile；传 `format=m3u` 会返回 M3U 文本，适合直接交给 VLC、mpv、IINA、PotPlayer 等播放器打开。该接口只包装现有 stream/subtitle URL，不改变视频流行为。
- 在线字幕新增 `GET /api/v1/resources/<id>/subtitles/online/search`、`POST /api/v1/resources/<id>/subtitles/online/download` 和 `POST /api/v1/resources/<id>/subtitles/online/bind`；当前只接入 `subhd` 与 `srtku`，`opensubtitles` 因中文覆盖和下载限额问题会被忽略；前端可传 `keyword` 或 `keywords` 显式指定搜索关键字，旧 `query` 参数继续兼容；搜索响应候选数组在标准响应体的 `data.items`，每条候选提供扁平字段 `candidate_id` 和 `source_key`，下载/绑定优先使用 `items[].candidate_id`；搜索会在单来源无结果时回退到资源原名/标题/年份/季集号/文件名，电视剧结果优先按当前季集号排序，并会把 `srt/ass/ssa/vtt` 文本字幕排在未知格式和 `sub/sup` 位图字幕前；每条候选包含 `format_normalized` 与 `web_player`，前端可据此提示 `sub/sup` 不适合网页 `<track>`；`limit` 是每来源上限，`max_query_attempts` 控制每个来源最多尝试多少个关键字；下载接口会把 `zip/7z/tar/gzip` 内的真实字幕提取后返回，RAR 等后端不支持的媒体类型返回 `415`，超过后端大小限制返回 `413`，来源下载失败、压缩包无字幕或解析失败返回 `502`；绑定接口必须传 `candidate_id` 与 `confirm: true`，只绑定用户确认的候选，不会按排序自动选择；手动上传使用 `POST /api/v1/resources/<id>/subtitles/upload` 的 multipart `file` 字段，支持直接字幕和 `zip/7z/tar/gzip` 压缩包，上传后以 `source=manual_upload` 进入字幕列表；后端缓存字幕可用 `DELETE /api/v1/resources/<id>/subtitles/<subtitle_id>` 移除，用 `POST /api/v1/resources/<id>/subtitles/<subtitle_id>/default` 设为默认，这两个接口只作用于 `source=online_bound/manual_upload`，不会删除或修改同目录外挂字幕
- `playback.audio.web_decode_status` 会标记 DTS/AC3/E-AC3/TrueHD 等网页播放器常见无声风险；`server_transcode.available=true` 只表示后端音频转码能力可用，前端可让用户手动启用，`server_transcode.recommended=true` 表示后端建议优先使用转码音频
- `GET /api/v1/resources/<id>/audio-transcode?start=0&audio_track=0&format=mp3` 返回独立实时音频流；前端 seek 后用新的 `start=video.currentTime` 重建 audio 流，与原始 video 流同步
- 音频转码流采用 forward-only 策略：前端应优先使用当前 `audio.buffered` 完成缓冲区内 seek；只有目标时间超出音频缓冲区时才重建 `audio-transcode` 流
- `GET /api/v1/resources/<id>/audio-transcode/diagnostics?session_id=...` 返回该资源最近音频转码诊断快照，用于联调缓存命中、上游 Range、首包耗时、输出节流和关闭原因
- 音频转码默认输出 `audio/mpeg` MP3、双声道、48kHz，优先保证 HTML `audio` 兼容性；也支持 `format=aac` 输出 ADTS AAC
- 前端必须为转码音频请求携带稳定 `session_id`；同一资源同一 `session_id` 的新请求会停止旧转码进程，页面卸载时调用 `DELETE /api/v1/resources/<id>/audio-transcode?session_id=...`
- 音频转码流受 history watchdog 保护：默认 `180s` 内未收到该资源 `POST /api/v1/user/history` 进度提交，后端会主动停止 ffmpeg
- 详细安全对接约束见 `docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md`
- 每个 `season_group` 额外包含：
  - `resource_ids`
  - `primary_resource_ids`
  - `episode_count`
  - `playback_source_count`
  - `alternate_resource_count`
  - `episode_diagnostics`
  - `edited_items_count`
  - `has_manual_metadata`
  - `sort`
  - `title`
  - `overview`
  - `air_date`
  - `metadata_edited_at`
- 每个 `groups.playback_sources[]` 包含：
  - `primary_resource_id`
  - `resource_ids`
  - `alternate_resource_ids`
  - `is_duplicate_group`
  - `duplicate_key`
  - `match`
  - `display`
  - `file`
  - `source_summary`
  - `user_data`

### `GET /api/v1/movies/<id>/seasons`
获取单条影片的季级聚合结果。

说明：
- 返回 `items`，结构与 `resources.groups.seasons` 一致
- 返回 `summary`，便于前端直接渲染季列表视图
- 每季的 `episode_diagnostics` 会返回 `status/coverage_status/issue_codes`，覆盖缺集、重复集号、资源缺集号和资源数与季元数据集数不一致
- `summary.episode_diagnostics` 汇总整部影片的剧集诊断状态、问题计数和需要复核的季号
- 该诊断是只读视图，不修改扫描结果；前端可把它作为剧集复核工作台入口，再调用资源批量编辑接口修正季/集

### `GET /api/v1/movies/<id>/episode-diagnostics`
获取单条影片的剧集完整性诊断和 dry-run 修复建议。

说明：
- 该接口只读，不写入数据库，不修改扫描结果
- `summary` 返回整部影片的剧集诊断汇总
- `seasons[].diagnostics` 返回每季缺集、重复集号、资源缺集号和集数不一致等诊断
- `seasons[].suggestions` 返回建议动作：补齐资源集号、复核重复集号、定位缺失剧集、复核季元数据集数或人工复核
- `suggested_updates` 只包含可自动形成批量资源编辑 payload 的建议；解析结果如果和现有集号冲突，或不在当前缺失集号列表内，只返回人工复核建议
- `apply_method/apply_endpoint/apply_payload` 给前端确认后复用；真正写入仍走 `PATCH /api/v1/movies/<id>/resources/metadata`
- `warnings` 返回解析结果与现有集号冲突等需要谨慎处理的提示

### `GET /api/v1/movies/<id>/images/<kind>`
获取电影海报或背景图的后端缓存资源。

路径参数：
- `kind=poster` 对应 `poster_url/cover`
- `kind=backdrop` 对应 `backdrop_url/background_cover`

说明：
- `MovieSimple.poster_asset_url` 和 `MovieDetailed.backdrop_asset_url` 会返回当前首选图片 URL；前端应优先加载该字段
- 图片加载顺序为 CDN -> 后端本地图片入口 -> 原始 `poster_url/backdrop_url`
- 列表、详情和状态接口会额外返回 `poster_asset_urls/backdrop_asset_urls` 与 `poster_asset_fallback_urls/backdrop_asset_fallback_urls`，前端在图片加载失败时按 `fallback_urls` 顺序切换
- 默认首选后端相对路径；配置 `CYBER_IMAGE_ASSET_PUBLIC_BASE_URL` 后，本地图片入口会返回 CDN/public base 下的绝对 URL
- 启用 Super CDN 后，已上传的海报/背景图会优先返回 `cyberstream-cn-assets`、`hd-wallpapers` 等国内 `china_all` 桶 URL；未上传或上传失败时自动回退后端本地图片入口
- `MovieSimple.poster_source_info` 和 `MovieDetailed.backdrop_source_info` 会返回图片来源追踪信息，包括 `provider/source_type/field/locked/evidence`
- 接口只按数据库里的图片源回源，不接受前端传任意 URL
- `refresh=true` 会强制尝试刷新远端图片；如果刷新失败且已有缓存，会返回旧缓存并带 `X-Cyber-Image-Cache=stale`
- 如果后端本地图片入口无可用缓存且回源失败，会返回 `302` 到原始图片 URL，并带 `X-Cyber-Image-Cache=fallback_original`
- 响应内容是图片二进制，不包标准 JSON；错误响应仍使用统一 `api_error`

### `DELETE /api/v1/movies/<id>/images/<kind>`
清理单条影片指定图片的后端本地缓存。

路径参数：
- `kind=poster` 对应 `poster_url/cover`
- `kind=backdrop` 对应 `backdrop_url/background_cover`

说明：
- 只删除 `CACHE_DIR/images/movies/<movie_id>/` 下对应图片缓存文件和缓存元数据
- 不修改数据库里的 `cover/background_cover` 源 URL，也不删除媒体源文件
- 无缓存可删时仍返回成功，`data.status=missing`
- 返回 `before/after` 缓存状态和已删除文件的相对路径，后续接 CDN 时可作为 purge / refresh 编排入口

### `GET /api/v1/movies/<id>/images/status`
获取单条影片图片缓存状态，不触发远端下载。

支持查询参数：
- `kind=poster|backdrop`
- `kinds=poster,backdrop`

说明：
- 返回每类图片的 `source_url`、`has_source`、`source_valid`、`cache_state`、`cached`、`source_changed`
- `asset_url` 与列表/详情中的图片资产 URL 一致，会跟随 `CYBER_IMAGE_ASSET_PUBLIC_BASE_URL` 或已上传的 Super CDN 对象切到外部 URL
- `asset_urls` 包含 `cdn_url`、`local_url`、`original_url`、`primary_url` 和 `fallback_urls`，用于前端实现 CDN -> 本地 -> 原始 URL 的失败回退链
- `source_info` 表示当前图片源追踪，第一阶段基于 `scraper_source`、图片 URL host 和字段锁状态推断 provider，例如 `tmdb`、`bangumi`、`nfo`、`manual`
- 已上传 Super CDN 时返回 `cdn`，包含 `bucket`、`route_profile`、`logical_path`、`sha256`、`url` 和上传状态
- 已缓存项的 `cache.source_info` 是写入缓存时的来源快照；当前 `source_info` 则反映数据库里此刻的图片字段
- `cache_state` 可能为 `cached`、`missing`、`missing_source`、`invalid_source`、`stale_source`
- 已有缓存会返回相对 `CACHE_DIR` 的缓存文件名、大小、更新时间和缓存年龄，不暴露服务器绝对路径
- 该接口用于 CDN 接入前的缓存治理和维护页展示

### `POST /api/v1/images/preload`
批量预热电影图片缓存。

请求体：
- `movie_ids`：可选；不传时按最近更新影片取 `limit` 条
- `kinds`：可选，默认 `["poster", "backdrop"]`
- `refresh`：可选，强制刷新远端图片
- `limit`：可选，默认 `20`，最大 `100`

说明：
- 当前是小批量同步接口，不引入后台任务队列
- 每个结果返回 `cached/stale/skipped/failed`，并带 `before/after` 缓存状态
- 缺图片源会返回 `skipped + missing_source`
- 图片源非法、远端失败且无旧缓存、影片不存在会返回 `failed` 项
- 启用 Super CDN 后，预热写入本地缓存时会同步上传非视频图片对象到默认国内 `china_all` 桶

### `POST /api/v1/images/refresh`
批量编排电影图片 CDN purge / refresh。

请求体：
- `movie_ids`：可选；不传时按最近更新影片取 `limit` 条
- `kinds`：可选，默认 `["poster", "backdrop"]`
- `purge`：可选，默认 `true`，生成或执行 CDN purge
- `clear_cache`：可选，默认 `false`，先清理后端本地图片缓存
- `preload`：可选，默认 `true`，执行后端本地图片预热
- `refresh`：可选，默认 `true`，传给预热阶段，强制尝试重新拉取远端图片
- `limit`：可选，默认 `20`，最大 `100`

说明：
- 当前 `CYBER_IMAGE_ASSET_CDN_PURGE_PROVIDER=noop`，不会调用外部 CDN，只返回待 purge 的 `urls`
- 配置 `CYBER_IMAGE_ASSET_CDN_PURGE_PROVIDER=manual` 时语义为外部人工或脚本处理，接口仍返回 URL 清单
- 配置 `CYBER_CDN_PROVIDER=supercdn` 且提供 `CYBER_SUPERCDN_URL/TOKEN` 后，会自动创建并使用 `CYBER_SUPERCDN_BUCKET`，默认 `route_profile=china_all`
- 返回每个图片项的 `purge`、`clear_cache`、`preload`、`cdn` 子结果，以及最终 `before/after` 缓存状态
- `summary.cdn_status_counts` 可用于维护页统计 CDN 上传状态
- 当前明确不上传视频文件；`/api/v1/resources/<id>/stream` 主播放链路保持原样

### `PATCH /api/v1/movies/<id>`
手动修改影视元数据。

当前支持字段：
- `title`
- `original_title`
- `year`
- `rating`
- `description` 或 `overview`
- `cover` 或 `poster_url`
- `background_cover` 或 `backdrop_url`
- `category` / `tags` / `genres`
- `director`
- `actors`
- `country`

说明：
- `category` / `tags` / `genres` 需传字符串数组
- `rating` 当前限制为 `0 ~ 10`
- `year` 需为正整数
- `actors` 支持字符串数组，也支持 `{ "name": "演员名" }` 对象数组；保存时统一归一为演员名列表
- 文本字段会自动 `trim`，空字符串会按 `null` 处理；`title` 不允许为空
- 同一字段不要同时传别名和原字段，例如 `poster_url` 与 `cover`
- 默认会把本次手动修改过的字段加入 `metadata_locked_fields`，后续扫描/刮削不会覆盖这些字段
- 也可显式传 `metadata_locked_fields` / `metadata_unlocked_fields` 控制锁定字段
- 未列出的字段会返回不支持错误

### `POST /api/v1/movies/<id>/metadata/refresh`
按单条影片刷新 TMDB 元数据，不触发全库扫描。

支持请求体：
- `tmdb_id`
- `metadata_unlocked_fields`
- `media_type_hint`

说明：
- 默认使用当前影片已有的 `tmdb_id`
- 若当前是本地占位 `loc-*`，会基于现有标题和年份尝试搜索 TMDB
- 已锁定字段默认不会被刷新覆盖；如需覆盖，可在 `metadata_unlocked_fields` 中显式解锁对应字段

### `POST /api/v1/movies/<id>/metadata/re-scrape`
按单条影片基于当前已入库资源重新走元数据管线，不触发全库扫描。

支持请求体：
- `metadata_unlocked_fields`
- `media_type_hint`

说明：
- 只使用当前影片已有资源，不会扫描其他影片
- 会尝试读取当前影片同目录 sidecar NFO
- 会返回本次 `parse/scrape` 决策信息，适合前端做“重新识别”后的结果展示

### `POST /api/v1/metadata/re-scrape`
按多条影片批量定点重跑元数据管线，不触发全库扫描。

支持请求体：
- `items[]`
  - `id` 或 `movie_id`
  - `media_type_hint`
  - `metadata_unlocked_fields`

说明：
- 每条影片独立执行，返回逐条结果和 summary
- 每条结果会返回 `status`、`changed`、`updated_fields`、`season_metadata_result`
- 成功结果会带 `explanation`，说明本次候选来源、匹配置信度、解析信号和是否仍需人工复核
- 失败结果会带分类后的 `error.category`、`retryable`、`recommended_action`
- `summary` 当前包含 `total`、`succeeded`、`updated`、`unchanged`、`failed`、`status_counts`、`updated_movie_ids`、`failed_movie_ids`
- 适合前端做批量“重新识别 / 补刮削”操作

### `POST /api/v1/metadata/re-scrape/jobs`
后台执行批量定点重跑元数据管线。

说明：
- 请求体与 `POST /api/v1/metadata/re-scrape` 相同
- 返回 HTTP `202` 和 `job`
- `job.type=metadata_re_scrape`
- 任务结果可通过 `GET /api/v1/jobs/<job_id>` 查询
- 当前任务记录保存在后端进程内，服务重启后历史会清空；后续如需审计再升级为持久化任务表

### `POST /api/v1/metadata/re-scrape/plan`
按多条影片预览批量定点重跑元数据管线，不落库。

支持请求体：
- `issue_codes`，默认 `fallback_pipeline_match/poster_missing/low_confidence_resources`
- `movie_ids`，显式指定影片时按指定影片生成计划
- `limit`，默认 `20`，最大 `50`
- `media_type_hint`
- `metadata_unlocked_fields`

说明：
- 返回 `dry_run=true`，不会修改影片、资源或季元数据
- 每条成功计划返回 `preview`、`diff`、`resolution`、`explanation` 和 `entity_context`
- 失败计划返回分类后的 `error.category/recommended_action`
- `apply_payload` 可在用户确认后原样提交给 `POST /api/v1/metadata/re-scrape`
- 当前用于批量处理 `fallback_pipeline_match`、`poster_missing`、`low_confidence_resources`

### `GET /api/v1/jobs`
获取后台任务列表。

支持查询参数：
- `type`，例如 `metadata_re_scrape`
- `limit`，默认 `20`

说明：
- 返回持久化维护任务；`persisted=true` 表示记录来自 `maintenance_jobs`
- 持久化任务结果可能包含 `result_truncated/result_item_count/persisted_item_limit`

### `GET /api/v1/jobs/<job_id>`
获取后台任务详情。

说明：
- 返回 `status=queued/running/succeeded/failed`
- 返回 `progress.current/total/message`
- 成功后 `result` 为任务结果；失败后 `error` 返回异常类型和信息
- 后端重启后仍可查询已持久化任务

### `POST /api/v1/jobs/prune`
按保留天数清理已完成维护任务。

请求体：
- `retention_days`
- `type`
- `dry_run`

### `POST /api/v1/movies/<id>/metadata/preview`
按单条影片预览当前元数据管线的识别结果，不落库。

支持请求体：
- `media_type_hint`
- `metadata_unlocked_fields`

说明：
- 只基于当前影片已有资源做定点预览
- 返回 `current` 和 `preview` 两份结果，适合前端做 diff 弹窗或确认面板
- 返回 `diff`，可直接区分哪些字段会变化、哪些字段被锁阻止覆盖
- 返回 `explanation`，前端可直接展示为什么是 TMDB 严格命中、fallback 候选、本地 NFO、占位或孤儿分组
- 不会修改 `movie`、`resource`、`season metadata`

### `GET /api/v1/metadata/providers`
获取当前后端可用的元数据 provider 能力。

说明：
- 返回 `default_order`、`aliases` 和 `providers`
- 当前 provider 包含 `nfo`、`tmdb`、`bangumi`、`tencent_video`、`local`
- `supports_search=true` 表示可用于候选搜索；当前 `tmdb`、`bangumi`、`tencent_video` 支持
- `tencent_video` 标记为 `manual_only=true`，只允许在单片手动搜索/匹配时显式选择，不进入全库扫描或自动 fallback

### `GET /api/v1/movies/<id>/metadata/search`
按单条影片搜索元数据候选，不触发扫描。

支持查询参数：
- `query`
- `year`
- `limit`
- `media_type_hint`
- `providers` 或 `provider_order`，逗号分隔，例如 `bangumi,tmdb,local` 或手动搜索时的 `tencent_video`

说明：
- 未传 `query` 时，默认使用当前影片的 `original_title` 或 `title`
- 传了 `query` 但没传 `year` 时，不再默认复用当前影片年份，避免旧年份干扰用户关键字搜索；响应会返回 `year_source`
- 返回候选列表，包含 `provider`、`source_key`、`candidate_id`、`tmdb_id`、标题、年份、简介、海报、背景图、评分等；Bangumi 候选的 `candidate_id/tmdb_id` 格式为 `bangumi/<id>`，腾讯视频候选格式为 `tencent_video/<cid>`，并额外带 `source_url`、`episode_count`
- 每个候选会带 `rank` 和 `match_explanation`，说明标题、年份、媒体类型、海报/评分等命中信号，便于前端展示候选解释
- 响应中的 `providers.attempts` 会说明哪些 provider 被跳过、成功或失败；当前 `nfo/local` 不支持在线候选搜索，会标记为 `skipped`

Bangumi 关键字搜索示例：

```http
GET /api/v1/movies/<id>/metadata/search?query=葬送的芙莉莲&providers=bangumi&media_type_hint=tv&limit=8
```

Bangumi subject URL 定点搜索示例：

```http
GET /api/v1/movies/<id>/metadata/search?query=https%3A%2F%2Fbgm.tv%2Fsubject%2F400602&providers=bangumi&media_type_hint=tv
```

腾讯视频手动候选搜索示例：

```http
GET /api/v1/movies/<id>/metadata/search?query=诛仙3&providers=tencent_video&media_type_hint=tv&limit=5
```

前端展示建议：
- 按 `provider/source_key` 分组展示候选来源
- 主提交字段使用 `candidate_id`，不要从 `tmdb_id` 反推来源
- Bangumi 候选可展示 `source_url` 跳转来源页，`episode_count` 用于辅助区分 TV/特别篇/剧场版
- 腾讯视频候选只在用户手动选择 provider 后展示，不要放进自动扫描配置；只使用元数据字段，不使用播放 URL
- `providers.attempts[].status=failed` 且有 warnings 时，展示为该来源暂不可用，不要当成“没有这个作品”

### `POST /api/v1/movies/<id>/metadata/match`
预览或确认应用单条影片的手动元数据匹配，不触发扫描。

支持请求体：
- `candidate_id`
- `external_id`
- `provider` 或 `source_key`
- `tmdb_id`
- `metadata_unlocked_fields`
- `media_type_hint`
- `apply`
- `allow_missing_poster`

说明：
- 默认 `apply=false`，只返回 dry-run 预览，不写库；前端点击候选时应停留在这个阶段
- 预览响应包含 `current`、`preview`、`identity`、`diff`、`warnings`、`apply_method`、`apply_endpoint`、`apply_payload`
- 用户确认“覆盖数据”后，再提交预览里返回的 `apply_payload`；该 payload 会带 `apply=true`
- 如果候选和当前影片最终都没有海报，`apply=true` 会返回 `409`，避免无海报记录变成前端不可见的幽灵数据；确实要写入时需额外传 `allow_missing_poster=true`
- 适用于手动选择搜索候选后的精准匹配
- 新前端建议提交 `candidate_id + provider`，例如 `{"candidate_id": "361761", "provider": "bangumi"}` 或 `{"candidate_id": "tencent_video/mzc00200z195unq", "provider": "tencent_video"}`；`tmdb_id` 仅作为兼容字段保留
- `candidate_id/tmdb_id` 支持 `movie/<id>`、`tv/<id>`、`bangumi/<id>`、Bangumi subject URL，也支持 `imdb/<id>`、`tvdb/<id>`
- 已锁定字段默认不覆盖；如需覆盖，可通过 `metadata_unlocked_fields` 定点解锁

预览请求体：

```json
{
  "candidate_id": "bangumi/400602",
  "provider": "bangumi",
  "media_type_hint": "tv"
}
```

确认应用请求体：

```json
{
  "candidate_id": "bangumi/400602",
  "provider": "bangumi",
  "media_type_hint": "tv",
  "apply": true
}
```

兼容裸 ID 预览请求体：

```json
{
  "candidate_id": "400602",
  "provider": "bangumi",
  "media_type_hint": "tv"
}
```

### 元数据来源展示字段

影片列表和详情现在会返回：
- `scraper_source`
- `metadata_state`

其中 `metadata_state` 适合前端直接做 UI 分层，当前包含：
- `source_group`
- `source_label`
- `is_placeholder`
- `is_local_only`
- `is_external_match`
- `confidence`
- `needs_attention`
- `review_priority`
- `badge_tone`
- `recommended_action`
- `issue_count`
- `issue_codes`
- `primary_issue_code`

影片详情还会返回：
- `metadata_actions`
- `metadata_diagnostics`
- `metadata_issues`

说明：
- `metadata_actions` 适合直接控制按钮显隐，例如“重新识别”“手动匹配”“编辑季信息”
- `metadata_diagnostics` 适合做概览卡片，例如低置信资源数、fallback 命中数、NFO 候选数、锁定字段数和 `episode_diagnostics`
- `metadata_issues` 适合做问题列表、告警面板或批量处理入口

资源详情现在还会返回：
- `metadata_trace`
- `metadata_edit_context`

说明：
- `metadata_trace` 偏后端留痕，适合调试
- `metadata_edit_context` 偏前端编辑场景，适合决定是否突出显示“推断集数”“低置信命中”“本地占位”等状态
- `metadata_state` 和资源分组 summary 里的 `needs_attention/review_priority` 适合直接驱动前端卡片颜色、角标和 CTA

### 列表筛选补充

`GET /api/v1/movies` 现在额外支持：
- `metadata_source_group`
- `metadata_review_priority`
- `metadata_issue_code`
- `needs_attention`

`GET /api/v1/filters` 现在默认也会返回：
- `metadata_source_groups`
- `metadata_review_priorities`
- `metadata_issue_codes`

说明：
- 这两组筛选是给前端元数据工作台直接用的，不需要自己统计
- `/api/v1/movies` 默认按公开影视库返回，会隐藏 `needs_attention=true` 的 raw/占位/缺海报影片
- `needs_attention=true` 适合做“待处理元数据”列表
- `metadata_issue_code` 按条目实际返回的 `metadata_issues[].code` 精确筛选，覆盖 `placeholder_metadata`、`local_only_metadata`、`low_confidence_resources`、`fallback_pipeline_match`、`nfo_candidates_available`、`poster_missing`、`locked_fields_present`、`season_metadata_missing`、`missing_episode_numbers`、`duplicate_episode_numbers`、`episode_number_missing`、`episode_count_mismatch`、`manual_review_required` 等问题类型
- `metadata_source_group` 包含 `bangumi/tmdb/nfo_tmdb/nfo_local/local/manual/unknown`
- `metadata_review_priority=none` 包含 `BANGUMI/TMDB_STRICT/NFO_TMDB` 这类无需复核来源

### `GET /api/v1/metadata/review-taxonomy`
返回审查工作台分类、问题码和动作字典，不触发扫描。

说明：
- 这是前端审查工作台的边界契约，避免前端按 `scraper_source` 自行推断
- 返回 `buckets`：普通影视库、元数据审查、剧集审查、资源治理、目录发布控制
- 返回 `issue_codes`：每个问题码所属分区、列表入口、详情入口、推荐动作和批量动作
- 返回 `metadata_sources`：`BANGUMI/TMDB/NFO/LOCAL_*` 等来源的标准含义和默认目录可见规则
- 返回 `catalog_visibility`：`auto/published/hidden`、blocker 和 warning 的解释
- 普通影视库、首页、推荐和资源库默认不要使用工作台筛选；元数据审查、剧集审查、资源治理应分 tab 或分页面处理

### `GET /api/v1/metadata/overview`
返回元数据工作台总览，不触发扫描。

说明：
- 返回总量统计、来源分组统计、复核优先级统计、推荐动作统计
- 返回问题类型统计 `issues`
- 适合前端做元数据 dashboard 顶部概览卡片

### `GET /api/v1/metadata/quality-summary`
返回资料库质量汇总，不触发扫描。

支持查询参数：
- `sample_size`，每类问题返回多少条样例，默认 `3`

说明：
- 返回 issue 级 `movie_count/affected_count/samples`
- 返回 `actions`，给出下一步处理入口，例如批量重识别 dry-run 和剧集复核队列
- `totals.bulk_reidentify_movie_count` 统计可进入批量重识别的影片数
- `totals.episode_review_movie_count` 统计可进入剧集复核队列的影片数
- 适合作为资料库质量工作台首页入口

### `GET /api/v1/metadata/work-items`
返回适合元数据工作台列表的影片条目，不触发扫描。

支持查询参数：
- `page`
- `page_size`
- `keyword`
- `metadata_source_group`
- `metadata_review_priority`
- `metadata_issue_code`
- `needs_attention`

说明：
- 每个条目都带 `metadata_state`、`metadata_actions`、`metadata_diagnostics`、`metadata_issues`
- 剧集诊断问题会进入 `metadata_issues`，前端可用 `metadata_issue_code=missing_episode_numbers|duplicate_episode_numbers|episode_number_missing|episode_count_mismatch` 直接打开复核列表
- 适合前端直接渲染“待处理元数据列表”，不用自己拼装详情字段
- 当前统计基于已入库影片和资源，不扫描磁盘
- `metadata_issue_code` 与条目自身 `metadata_issues[].code` 使用同一套后端计算逻辑，前端从筛选项点入后不会出现“筛选项有计数但列表无法命中”的来源粗筛偏差

### `GET /api/v1/metadata/episode-review-items`
返回剧集复核队列，不触发扫描。

支持查询参数：
- `page`
- `page_size`
- `metadata_issue_code` 或 `issue_code`

说明：
- 聚合 `missing_episode_numbers`、`duplicate_episode_numbers`、`episode_number_missing`、`episode_count_mismatch` 和 `season_metadata_missing`
- 每条返回 `episode_diagnostics`、需要复核的季号、自动修复数量、人工建议数量和 warning 数量
- `diagnostics_endpoint` 指向单片 `GET /api/v1/movies/<id>/episode-diagnostics`
- `apply_payload` 只包含无冲突的资源季集修复项；前端确认后提交给该条目的 `apply_endpoint`

### `PATCH /api/v1/resources/<id>/metadata`
手动修改单个资源的季/集元数据，不触发扫描。

当前支持字段：
- `season`
- `episode`
- `title`
- `overview`
- `label`

说明：
- `season` / `episode` 需为正整数
- 当前若传 `episode`，必须同时已存在或提交有效 `season`
- 若只修改 `season` / `episode` 且未显式传 `label`，后端会自动重建 `label`
- 资源实际发生变更时，会自动刷新 `metadata_edited_at`

### `PATCH /api/v1/movies/<id>/resources/metadata`
批量修改单条影片下多个资源的季/集元数据，不触发扫描。

请求体格式：
- `items`: 数组

数组元素支持字段：
- `id` 或 `resource_id`
- `season`
- `episode`
- `title`
- `overview`
- `label`

说明：
- 所有资源必须属于当前影片
- 批量更新在单个事务内执行，任一资源校验失败则整批回滚
- 若只修改 `season` / `episode` 且未显式传 `label`，后端会自动重建 `label`
- `title` / `label` 传空字符串会自动按 `null` 处理，便于清空手动填写内容
- 任一资源实际发生变更时，会自动刷新该资源的 `metadata_edited_at`

### `PATCH /api/v1/movies/<id>/seasons/<season>/metadata`
手动修改单季元数据，不触发扫描。

当前支持字段：
- `title`
- `overview`
- `air_date`

说明：
- 仅允许修改当前影片中已存在资源的季
- `air_date` 格式需为 `YYYY-MM-DD`
- 季级元数据实际发生变更时，会自动刷新 `metadata_edited_at`
- 若一季的 `title`、`overview`、`air_date` 全部被清空，会自动删除该季的手动元数据记录，不保留空壳数据

### `GET /api/v1/genres`
旧接口，当前已临时停用，用于观察前端是否仍依赖。

### `GET /api/v1/movies/recommend`
旧式推荐接口，当前已临时停用，用于观察前端是否仍依赖。

---

## 7. 用户历史

观看历史和续播接口保留。影片列表、首页、资源库、详情和资源分组中的 `user_data` 仅表示播放进度上下文，不再返回 `is_played`，前端不应展示“已观看”标签。

### `GET /api/v1/user/history`
分页获取观看历史。

### `POST /api/v1/user/history`
上报播放进度。

核心字段：
- `resource_id`
- `position_sec`
- `total_duration`
- `device_id`（可选）
- `device_name`（可选）

### `DELETE /api/v1/user/history/<resource_id>`
删除单条历史记录。

### `DELETE /api/v1/user/history`
清空历史记录。

---

## 8. 播放

### `GET /api/v1/resources/<id>/stream`
按资源 ID 播放媒体流。

支持：
- Range 请求
- 直接流式代理
- 某些 provider 场景下 302 跳转
- 代理流会按文件扩展名返回 `Content-Type`，例如 `video/mp4`、`video/x-matroska`、`video/mp2t`；无法识别时返回 `application/octet-stream`

---

## 9. 版本收口说明

本文件为接手期概览文档，不替代 OpenAPI。当前 `1.21.0` 已作为 `main` 主干联调基线。

当前必须保持同步的契约文件：

- `backend/openapi/openapi-1.21.0-beta/openapi-1.21.0-beta.json`
- `backend/openapi/openapi-1.21.0-beta/release-notes-1.21.0-beta.md`
