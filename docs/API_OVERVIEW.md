# API 概览

当前后端蓝图前缀为：`/api/v1`

## 0. 当前基线

当前版本：`1.17.0`

当前 OpenAPI 联调基线：

- `backend/openapi/openapi-1.17.0-beta/openapi-1.17.0-beta.json`
- `backend/openapi/openapi-1.17.0-beta/release-notes-1.17.0-beta.md`

当前 `main` 即最新版主干，后续小步提交直接进入 `main`。

## 1. 健康检查

### `GET /`
返回服务状态与版本信息。

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
- `scan_order`
- `is_enabled`

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

说明：
- 与全量扫描、资源库扫描共用同一个运行锁；已有扫描任务执行中时返回 `429`

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
- 不传 `needs_attention` 且不传元数据工作台筛选时，只返回无需人工处理且有海报的公开影视
- `needs_attention=true` 返回待人工处理的影片，包含 raw/占位/缺海报条目，适合做处理队列入口
- 显式传 `metadata_source_group`、`metadata_review_priority`、`metadata_issue_code` 时按工作台筛选语义返回，不额外强制公开库过滤

### `GET /api/v1/movies/<id>`
获取影视详情。

说明：
- 只返回影片主体、元数据状态、观看状态、季卡片摘要等详情页主信息
- 不再内嵌资源列表；资源面板统一调用 `GET /api/v1/movies/<id>/resources`

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
  - `playback`：播放能力矩阵、外部播放器链接、字幕占位、网页音频兼容和转码状态
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
- `playback.external_player.subtitle_urls` 与 `playback.subtitles.items` 当前为占位空数组，后续接入字幕发现/下载后再填充
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

### `GET /api/v1/movies/<id>/metadata/search`
按单条影片搜索 TMDB 候选，不触发扫描。

支持查询参数：
- `query`
- `year`
- `limit`
- `media_type_hint`

说明：
- 未传 `query` 时，默认使用当前影片的 `original_title` 或 `title`
- 返回候选列表，包含 `tmdb_id`、标题、年份、简介、海报、背景图、评分等
- 每个候选会带 `rank` 和 `match_explanation`，说明标题、年份、媒体类型、海报/评分等命中信号，便于前端展示候选解释

### `POST /api/v1/movies/<id>/metadata/match`
将单条影片手动匹配到指定 TMDB 结果，不触发扫描。

支持请求体：
- `tmdb_id`
- `metadata_unlocked_fields`
- `media_type_hint`

说明：
- 适用于手动选择搜索候选后的精准匹配
- `tmdb_id` 现在支持 `movie/<id>`、`tv/<id>`，也支持 `imdb/<id>`、`tvdb/<id>`
- 已锁定字段默认不覆盖；如需覆盖，可通过 `metadata_unlocked_fields` 定点解锁

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
- `metadata_diagnostics` 适合做概览卡片，例如低置信资源数、fallback 命中数、NFO 候选数、锁定字段数
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

### `GET /api/v1/metadata/overview`
返回元数据工作台总览，不触发扫描。

说明：
- 返回总量统计、来源分组统计、复核优先级统计、推荐动作统计
- 返回问题类型统计 `issues`
- 适合前端做元数据 dashboard 顶部概览卡片

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
- 适合前端直接渲染“待处理元数据列表”，不用自己拼装详情字段
- 当前统计基于已入库影片和资源，不扫描磁盘

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

本文件为接手期概览文档，不替代 OpenAPI。当前 `1.17.0` 已作为 `main` 主干联调基线。

当前必须保持同步的契约文件：

- `backend/openapi/openapi-1.17.0-beta/openapi-1.17.0-beta.json`
- `backend/openapi/openapi-1.17.0-beta/release-notes-1.17.0-beta.md`
