# 1.18.0-beta 更新说明

本文档记录 `1.18.0-beta` 的接口变化，作为 `main` 主干上的前后端联调基线。

## 当前重点

`1.18.0` 第一阶段先推进字幕配置能力：

- 同目录外挂字幕发现
- 字幕默认项选择
- 播放矩阵字幕字段从占位升级为真实数据
- 字幕流复用现有资源 stream 入口
- 在线字幕搜索、下载与用户确认绑定接口接入
- 电影海报/背景图新增后端稳定缓存资源入口
- 元数据 provider 能力和候选搜索结果开始按来源抽象
- 元数据工作台 `metadata_issue_code` 按条目实际 `metadata_issues[].code` 精确筛选，覆盖低置信资源、锁定字段、缺季资料等复合问题类型
- 总影视库发布状态从元数据来源中解耦，新增显式发布/隐藏控制

## 字幕发现

`Resource.playback.subtitles` 现在会在请求资源列表时尝试发现同目录外挂字幕：

- 当前支持 `.srt`、`.ass`、`.ssa`、`.vtt`、`.sub`、`.sup`
- 仅匹配与当前视频同目录、且文件名前缀匹配当前视频文件名的字幕
- 支持从文件名识别 `zh-Hans`、`zh-Hant`、`zh`、`en`、`ja`、`ko`
- 文件名带 `default` 或 `默认` 时会优先作为默认字幕
- 未显式标记默认时，按语言优先级和格式选择第一条作为默认字幕

新增或变化字段：

- `playback.subtitles.items[]`
- `playback.subtitles.default_subtitle_id`
- `playback.subtitles.web_player_supported`
- `playback.subtitles.discovery`
- `playback.external_player.subtitle_urls`

## 字幕流

字幕下载复用现有资源流入口，不新增独立路由：

- `GET /api/v1/resources/{id}/stream?subtitle_id={subtitle_id}`

安全约束：

- `subtitle_id` 必须来自当前资源 `playback.subtitles.items[].id`
- 后端会重新执行当前资源的字幕发现并校验 ID
- 未发现或不匹配时返回 `404`
- 不允许通过该参数访问任意存储路径

## 在线字幕

新增三个资源级在线字幕接口：

- `GET /api/v1/resources/{id}/subtitles/online/search`
- `POST /api/v1/resources/{id}/subtitles/online/download`
- `POST /api/v1/resources/{id}/subtitles/online/bind`
- `POST /api/v1/resources/{id}/subtitles/upload`
- `DELETE /api/v1/resources/{id}/subtitles/{subtitle_id}`
- `POST /api/v1/resources/{id}/subtitles/{subtitle_id}/default`

当前启用来源：

- `subhd`：默认主力来源，搜索信息较完整，下载时自动处理 SVG 验证码
- `srtku`：备用来源，结果量较大，下载链路会处理 WAF 验证码与多下载入口

搜索接口会按来源返回候选列表，候选数组位于标准响应体的 `data.items`。前端可通过 `keyword` 显式传入一个搜索关键字，也可通过 `keywords` 传入多个候选关键字；旧参数 `query` 继续兼容但优先级更低。每条候选提供扁平字段 `candidate_id` 和 `source_key`，下载/绑定优先使用 `items[].candidate_id`。`limit` 作为每个来源的上限，不再作为全局总数上限；当传入关键字无结果时，后端会继续尝试当前资源的原名、标题、年份、季集号和文件名，提升 SubHD/SrtKu 的命中率。`max_query_attempts` 默认限制每个来源最多尝试 6 个关键字，避免电视剧无结果时接口过慢；响应里的 `query_attempt_candidates` 与 `providers.query_attempts` 可用于前端调试。电视剧资源会优先展示当前季集号匹配结果，再按来源和下载量排序。

已忽略来源：

- `opensubtitles`：因中文字幕覆盖有限且免费下载限额过低，不在接口中实际请求；如果前端传入该来源，后端只会返回 `providers.ignored`

下载接口只接受搜索结果返回的 `candidate_id`，当前格式为 `subhd:<hash>` 或 `srtku:<detail_id>`。

绑定接口用于用户明确选中字幕后的持久化接入。后端要求请求体包含 `confirm: true`，且只绑定前端传入的 `candidate_id`，不会根据搜索排序自动替用户选择。绑定后的字幕保存到后端缓存目录并进入 `playback.subtitles.items`，`source=online_bound`；播放仍复用 `GET /api/v1/resources/{id}/stream?subtitle_id=...`。

已绑定字幕可以继续管理：

- `POST /resources/{id}/subtitles/upload` 支持用户手动上传 `srt/ass/ssa/vtt/sub/sup`，也支持上传 `zip/7z/tar/gzip` 后由后端提取真实字幕；上传结果以 `source=manual_upload` 进入 `playback.subtitles.items`
- `DELETE /resources/{id}/subtitles/{subtitle_id}` 只删除 `source=online_bound` / `source=manual_upload` 的后端缓存字幕，不会删除同目录外挂字幕或原始媒体目录文件
- `POST /resources/{id}/subtitles/{subtitle_id}/default` 只持久化后端缓存字幕的默认选择；同目录外挂字幕默认项仍由文件名里的 `default` / `默认` 标记控制

下载结果会统一归一化：

- 直接下载到 `.srt`、`.ass`、`.ssa`、`.vtt`、`.sub`、`.sup` 时，直接返回该字幕文件流
- 下载到 `zip`、`7z`、`tar`、`gzip` 压缩包时，后端会尝试提取其中的真实字幕文件，并通过 `X-Cyber-Subtitle-Extracted` 标记是否经过提取；嵌套压缩包会在受限深度内递归解析
- `rar`、加密压缩包、压缩包内无可用字幕或解析失败时返回 `502` 与明确错误信息
- 文本字幕会尽量根据 BOM/内容探测 `charset`，避免把 UTF-16 字幕误标成 UTF-8

## 图片静态资源缓存

新增电影图片资源接口：

- `GET /api/v1/movies/{id}/images/{kind}`

当前支持：

- `kind=poster`：按电影 `cover/poster_url` 回源并缓存
- `kind=backdrop`：按电影 `background_cover/backdrop_url` 回源并缓存

字段变化：

- `MovieSimple.poster_asset_url`
- `MovieDetailed.backdrop_asset_url`

兼容策略：

- `poster_url` 和 `backdrop_url` 继续保留为原始远端图片 URL
- 前端可以优先使用 `poster_asset_url/backdrop_asset_url`，后续切 CDN 时可保持字段语义稳定
- 图片接口返回图片二进制，不包标准 JSON；错误响应仍走统一 `api_error`
- 接口不接受任意 URL，只读取电影记录里的图片源，避免开放代理风险
- `refresh=true` 会尝试强制刷新；刷新失败且已有缓存时返回旧缓存，并在响应头标记 `X-Cyber-Image-Cache=stale`

## 元数据 Provider 抽象

新增 provider 能力接口：

- `GET /api/v1/metadata/providers`

当前 provider：

- `nfo`：本地 sidecar NFO，支持扫描刮削，不支持在线候选搜索
- `tmdb`：TMDB，支持扫描刮削和在线候选搜索
- `bangumi`：Bangumi / 番组计划，面向动画条目，支持扫描刮削和在线候选搜索；默认不自动启用，需要在 `provider_order` 中显式加入
- `local`：本地占位兜底，支持扫描兜底，不支持在线候选搜索

候选搜索变化：

- `GET /api/v1/movies/{id}/metadata/search` 现在返回 `provider`、`provider_name`、`source_key`、`candidate_id`、`external_id`
- 兼容保留 `tmdb_id`，TMDB 候选为 `movie/<id>` 或 `tv/<id>`；Bangumi 候选为 `bangumi/<id>`
- Bangumi 候选额外返回 `source_url`、`subject_type`、`episode_count`，便于前端展示来源和集数信息
- 响应新增 `providers.order`、`providers.attempts`、`providers.warnings`，前端可解释哪些 provider 被跳过、成功或失败
- 查询参数新增 `providers` / `provider_order`，用于指定候选搜索 provider 顺序，例如 `bangumi,tmdb,local`
- 指定 `query` 但不指定 `year` 时，搜索不会再默认继承当前影片年份；响应新增 `year_source`
- `POST /api/v1/movies/{id}/metadata/match` 支持 `candidate_id + provider`，也兼容 `tmdb_id`；Bangumi 支持 `bangumi/<id>`、裸 subject ID 和 subject URL

## 总影视库发布控制

新增影片级发布状态：

- `auto`：默认规则，保持原有“可信元数据 + 有海报”自动进入总影视库
- `published`：用户手动纳入总影视库
- `hidden`：用户手动从总影视库隐藏

新增接口：

- `PATCH /api/v1/movies/{id}/catalog-visibility`

字段变化：

- `MovieSimple.catalog_visibility`
- `MovieDetailed.catalog_visibility`

说明：

- `published` 在存在 `metadata_needs_attention`、`poster_missing` 等阻塞原因时会返回 `409`；前端应让用户手动确认后带 `force=true` 再提交
- 该状态只影响总影视库、全局推荐、全局筛选和 featured 自动候选
- 资源库仍继续使用 `movie-memberships include/exclude`，与总影视库发布状态分离

扫描策略变化：

- `POST /api/v1/storage/sources/{id}/scan` 支持 `scraper_policy.provider_order`，也支持扁平别名 `provider_order`
- `LibrarySource` 绑定新增 `scraper_policy`；资源库扫描会使用绑定上的 `content_type`、`scrape_enabled` 和 `scraper_policy`
- 动漫库可传 `provider_order: ["nfo", "bangumi", "tmdb", "local"]`，非动漫库建议保持默认顺序

## 边界

本阶段不做字幕转码、不做字幕烧录、不做跨目录递归查找，也不会自动写入媒体目录。在线字幕绑定必须由前端传入用户确认后的 `candidate_id` 与 `confirm: true`；已绑定在线字幕和手动上传字幕支持移除和默认项持久化，后续可继续补播放器侧更细的字幕轨选择体验。图片缓存第一阶段只做按需回源与本地落盘，不做对象存储/CDN 上传、图片裁剪转码、季级独立海报缓存或批量预热；CDN 切换层等待自建 CDN 完工后再继续。元数据 provider 第一阶段已完成 `nfo/tmdb/bangumi/local` 抽象与 TMDB、Bangumi 在线候选搜索；Bangumi 默认不自动启用，需要用户或前端在动漫库中显式选择 `provider_order`。新增在线元数据来源暂缓，豆瓣因缺少稳定公开 API 暂不接；后续如果评估 IMDb/TVDB，继续复用同一 provider 结构。
