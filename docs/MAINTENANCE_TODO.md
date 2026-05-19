# 维护优先级清单

本清单用于正式接手后的长期维护排序。

## A. 绝对不要贸然大改的部分

### 1. `app/services/scanner.py`
原因：
- 规则复杂
- 业务经验沉淀多
- 一旦误改，最容易引发扫描结果异常

维护原则：
- 小步改
- 先补测试样例或最少做人工回归

### 2. `/resources/<id>/stream` 播放链路
原因：
- 涉及本地流、WebDAV、Range、302 跳转
- 前端体验直接受影响

维护原则：
- 每次改动后必须实际点播验证

---

## B. 可以优先动的低风险高收益项

### 1. 启动与运行说明补齐
目标：降低新接手人员踩坑概率。

### 2. 统一版本标识
目标：让接口、文档、实际运行版本保持一致。

### 3. 配置整理
目标：
- 区分历史配置与当前有效配置
- 逐步减少 `config.py` 中的明文敏感信息

### 4. 基础日志规范
目标：
- 替换部分 `print`
- 提升排障效率

### 5. 文档持续补全
目标：
- 保证任何人都能快速接手

---

## C. 中期改造项

### 1. 下一版本候选池

当前 `1.21.0` 已进入 `main` 主干，以下事项作为后续小步迭代候选池。

#### 1.0 1.17.0 今晚攻坚目标

当前优先级：

1. 播放能力矩阵
   - 增加资源级播放能力描述，明确 direct/proxy/redirect、Range、MIME、外部播放器、字幕、转码、FFmpeg 输入等能力。
   - 第一阶段只暴露能力和限制，不改变 `/resources/<id>/stream` 的默认播放行为。
   - 已完成资源对象 `playback` 第一版：外部播放器 URL、字幕占位、网页音频兼容风险、服务端音频转码入口。
   - 已补 `ffmpeg/ffprobe` 用户级运行依赖，并新增实时音频转码流；当前默认单并发、同 session 替换旧流、AList `/d` 输入重试、远程输入 Range 内存缓存、支持 DELETE 主动停止、history watchdog 兜底停止和 `-re` 输入限速，优先保护原始视频直链。
   - 实现细节已记录在 `docs/AUDIO_TRANSCODE_DESIGN_NOTES.md`，前端契约在 `docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md`。
   - 已新增资源级音频转码诊断接口，后续重点验证远程源 seek、缓存命中后的持续流畅性、前端双标签同步策略和真实多用户并发策略。

2. 元数据复核工作台增强
   - 强化失败分类、候选结果解释和批量重识别反馈。
   - 优先围绕 `/metadata/work-items`、`/reviews/resources`、单片 preview/re-scrape/match、批量 re-scrape 演进。
   - 已补单片 preview/re-scrape 解释、候选搜索解释、批量 re-scrape 状态/字段/错误分类反馈；后续可继续做前端工作台交互和真实数据批处理验证。
   - 今晚推进质量汇总、批量重识别 dry-run 和剧集复核队列三个工作台入口。
   - 已新增轻量后台任务注册表，批量重识别可通过 `/metadata/re-scrape/jobs` 异步执行，并用 `/jobs/<job_id>` 查询状态；后续扫描治理、字幕处理和维护任务可逐步接入。

4. 扫描与资源治理
   - 已新增只读资源治理汇总与问题列表：`/resources/governance-summary`、`/resources/governance-items`。
   - 当前覆盖孤儿资源、空壳影片、重复播放资源、有限 live path 检查和大小变化检查。
   - 已新增清理计划和确认执行入口：`/resources/governance/plan`、`/resources/governance/jobs`。
   - 执行范围先限定为低风险资源索引删除；有历史、绑定字幕、影片最后资源或重复主资源时自动跳过，实体文件永不删除；已删除项会返回 `restore_snapshot` 便于人工恢复。
   - `plan` 已支持 `limit` 和 `page/page_size`，避免真实库大计划一次返回过重。
   - 已新增只读后台路径检查：`/resources/governance/live-check/jobs`。
   - 已新增 `maintenance_jobs` 持久化维护任务记录，后端重启后仍可查询 `/jobs`。
   - 已新增资源索引恢复入口：`/resources/governance/restore/plan`、`/resources/governance/restore/jobs`。
   - 已新增维护任务结果瘦身与过期清理：`MAINTENANCE_JOB_RESULT_ITEM_LIMIT`、`MAINTENANCE_JOB_RETENTION_DAYS`、`/jobs/prune`。
   - 后续可继续做前端资源治理工作台和扫描源头重复解释。

3. 推荐观看
   - 补强“推荐观看”能力，综合观看历史、续看、最近入库、评分、质量、类型多样性和可播放性。
   - 返回推荐理由，避免前端只能展示随机列表。
   - 已补全第一版推荐解释：全局与库级推荐都会返回 `recommendation`，`default` 综合续看/最近入库/评分/质量/资源/类型多样性，另支持 `continue_watching`。
   - 已补单片上下文推荐：同系列/同标题族优先，同类型补齐，动漫与非动漫严格隔离；后续可接入 TMDB collection 提升电影系列识别准确度。

#### 1.1 资源副本折叠 / 备用播放源展示
需求：
- 同一影片可能存在同名同大小但不同路径的多个物理副本
- 详情页可考虑默认展示一个主资源，其余折叠为备用播放源

状态：
- 后端已在 `GET /api/v1/movies/<id>/resources` 增加 `groups.playback_sources`、`primary_resource_ids` 与副本统计字段
- 当前只做接口层分组，不删除资源，不改变 `/resources/<id>/stream`

风险：
- 不能直接删除数据库资源，因为不同路径可能是真实可播放副本
- 需要避免影响播放历史、资源分组、手动季集编辑

建议：
- 前端默认展示 `primary_resource_id`，将 `alternate_resource_ids` 作为备用播放源
- 当前 `items` 仍保留全量资源，作为排查入口
- 不在当前稳定版改变默认语义

#### 1.2 SQLAlchemy 2.0 警告清理（已完成）
需求：
- 将 `Query.get()` 逐步迁移为 `db.session.get(Model, id)`

状态：
- 已在 `main` 完成等价迁移
- 全量 unittest 已通过

建议：
- 后续新增代码继续使用 `db.session.get(Model, id)`

#### 1.3 元数据复核工作台增强
需求：
- 继续完善批量重识别、失败分类、候选结果解释
- 增强 raw/占位/缺海报影片的人工处理闭环

建议：
- 优先围绕现有 `/metadata/work-items`、`/reviews/resources`、单片 re-scrape/match 接口演进

#### 1.4 播放能力矩阵
需求：
- 字幕、转码、外部播放器、Direct/Proxy/Redirect 能力展示

风险：
- 涉及播放链路，必须独立测试

建议：
- 先补能力矩阵和前端展示，再考虑真正转码

#### 1.5 用户、角色、权限与运行安全开关
需求：
- 真正的身份验证、角色权限、接口访问控制

当前决策：
- 域名和部署形态尚未最终敲定，当前主干暂不实现运行安全开关

建议：
- 下一版本先设计认证模型和接口契约
- 再分阶段接入 token、角色和资源级权限

#### 1.6 1.18.0 明日计划：字幕配置
需求：
- 为资源补齐字幕发现、字幕关联、默认字幕选择与字幕配置能力
- 已将 `playback.subtitles.items` 从占位空数组推进到第一阶段真实可用数据

边界：
- 第一阶段优先支持与资源同目录的本地/远程外挂字幕识别
- 不在第一天直接做复杂字幕转码或烧录

状态：
- 第一阶段已完成：同目录外挂字幕发现、默认字幕选择、播放矩阵字幕字段和受校验的字幕流入口已接入 `1.18.0`
- 当前支持 `srt/ass/ssa/vtt/sub/sup`，字幕流复用 `/api/v1/resources/<id>/stream?subtitle_id=...`
- 在线字幕搜索/下载/绑定/移除/设默认接口已接入 `subhd` 与 `srtku`；手动上传字幕已支持直接字幕文件与压缩包提取；`opensubtitles` 因中文覆盖和下载限额问题暂不接入；绑定接口必须由用户确认后传 `confirm: true`

建议：
- 下一步补手动字幕关联和播放器选择逻辑
- 后续再评估字幕转码、烧录和跨目录字幕索引

#### 1.7 1.18.0 已完成第一阶段：静态资源优化存储与 CDN
需求：
- 对图片海报、背景海报建立更稳定的缓存与存储策略
- 后续接入用户自建 CDN，避免前端长期直接依赖 TMDB 图片地址

边界：
- 第一阶段先处理 `poster/backdrop` 两类静态图
- 优先保证 URL 稳定、回源可控、缓存可失效

状态：
- 已新增 `GET /api/v1/movies/<id>/images/<kind>`，`kind=poster|backdrop`
- `MovieSimple` 新增 `poster_asset_url`，`MovieDetailed` 新增 `backdrop_asset_url`，原 `poster_url/backdrop_url` 继续保留为远端源 URL
- 缓存落盘到 `CACHE_DIR/images/movies/<movie_id>/`，接口只读取数据库里的 `cover/background_cover`，不接受任意外部 URL
- 支持 `refresh=true` 强制刷新；刷新失败且存在旧缓存时返回旧缓存，并通过 `X-Cyber-Image-Cache=stale` 标记

决策：
- 自建 Super CDN 已开始接入；当前只正式替换海报层，视频播放链路保持原样
- Super CDN asset bucket 的稳定 `/a/{bucket}/...` URL 当前会代理返回 `200/206`，底层 `storage_url/cdn_url` 才会 302 到豆包/飞书下载流；赛博影视继续只暴露稳定 `public_url`，不直接暴露签名网盘直链
- 背景图、字幕等后续静态资源迁移暂缓，等待 Super CDN 开发侧明确并修复 `/a/...` redirect 策略后再继续

#### 1.7.1 CDN 前置准备项
Super CDN 已按国内主访问场景接入第一阶段，以下缓存治理能力继续作为维护入口。

优先级：

0. 图片资产 public base URL
   - 已新增 `CYBER_IMAGE_ASSET_PUBLIC_BASE_URL`
   - 未配置时 `poster_asset_url/backdrop_asset_url` 继续返回后端相对路径
   - 配置后列表、详情和状态接口返回 CDN/public base 下的绝对 URL
   - 启用 Super CDN 后，已上传的图片资产会优先返回 `/a/{bucket}/...` CDN URL

1. 图片缓存状态接口
   - 返回单片 `poster/backdrop` 是否有源 URL、源 URL 是否有效、是否已有本地缓存、缓存是否与当前源 URL 一致
   - 暴露缓存文件名、大小、更新时间、缓存年龄和失败原因，供前端或维护页展示

2. 图片批量预热接口
   - 支持按 `movie_ids` 和 `kinds=poster/backdrop` 批量拉取缓存
   - 支持 `refresh=true` 强制刷新
   - 返回逐项 `cached/failed/skipped` 结果与汇总统计

3. 图片缓存清理与刷新策略
   - 已新增单片清理接口 `DELETE /api/v1/movies/<id>/images/<kind>`
   - 当前只清理后端本地缓存文件和缓存元数据，不修改数据库图片源
   - 后续按维护页需要再补批量清理接口
   - CDN 接入后复用同一入口做 purge / refresh 编排

3.1 CDN purge / refresh 编排入口
   - 已新增 `POST /api/v1/images/refresh`
   - 当前 `CYBER_IMAGE_ASSET_CDN_PURGE_PROVIDER=noop`，只返回待 purge URL，不调用外部 CDN
   - 支持按 `movie_ids/kinds/limit` 批量处理，并可选择 `purge/clear_cache/preload/refresh`
   - 已新增 Super CDN provider，当前正式海报层使用 `hd-wallpapers` 桶，`route_profile=china_all`
   - 当前正式运行只上传海报，背景图和绑定字幕迁移暂缓，明确不上传视频文件

4. 图片来源追踪
   - 已在列表、详情和图片状态接口返回 `poster_source_info/backdrop_source_info/source_info`
   - 第一阶段基于 `scraper_source`、图片 URL host 和字段锁状态推断来源：TMDB、Bangumi、NFO、manual、external、local、none
   - 新写入的缓存元数据会保存 `cache.source_info` 来源快照
   - 后续如果需要审计级字段 lineage，再补持久化字段来源表或 metadata trace

#### 1.8 1.18.0 已完成第一阶段：多刮削器支持
需求：
- 当前只有 TMDB，复杂影视数据、部分地区内容与多季/多版本场景覆盖不够
- 需要引入多刮削器 provider、优先级、fallback 和字段来源追踪

边界：
- 第一阶段先完成 scraper provider 抽象，不追求一次接很多来源
- 优先支持“主刮削器 + fallback 刮削器”的最小闭环

状态：
- 已有 provider 注册表和能力接口 `GET /api/v1/metadata/providers`
- 当前 provider 为 `nfo/tmdb/bangumi/local`，默认顺序为 `nfo -> tmdb -> local`
- 元数据候选搜索已改为 provider 抽象结构，候选返回 `provider/source_key/candidate_id/external_id`，并带 `providers.attempts/warnings`
- `bangumi` 已作为动漫友好 provider 接入，支持关键字搜索、subject URL 定点查询、扫描刮削和手动匹配 `candidate_id + provider`；默认不自动启用
- 存储源扫描和资源库绑定支持 `scraper_policy.provider_order`
- 资源库扫描已使用绑定上的 `content_type/scrape_enabled/scraper_policy`

建议：
- 新增在线元数据来源暂缓；当前 `TMDB + Bangumi + NFO + local` 已够前端联调和第一阶段使用
- 后续如果确实需要再评估 IMDb/TVDB，继续复用当前 provider 结构；豆瓣因没有稳定公开 API 暂不接
- 返回结果继续补字段级来源追踪，方便解释某个字段来自 TMDB、NFO 还是本地兜底
- 多刮削器与静态资源缓存继续一起设计，避免后续图片来源与元数据来源割裂

#### 1.9 1.18.0 明日计划：总影视库显式发布接口
需求：
- 当前总影视库是否可见，仍过度依赖 `scraper_source` 和海报是否存在
- 后续接入多刮削器、自定义元数据、用户手工维护数据后，TMDB 不应再成为是否能进入总影视库的硬门槛
- 资源库与总影视库的可见性规则需要拆开：总影视库要求更严格，资源库允许更宽松

边界：
- 不把“是否公开展示”继续绑定在 `TMDB/TMDB_STRICT/NFO_TMDB` 这类来源枚举上
- 仍保持“标题、简介、海报不达标时默认不进总影视库”的产品约束
- 对用户自录视频、自定义内容、课程资源等，允许只出现在某个资源库，不强行进入总影视库

状态：
- 已新增影片级 `catalog_visibility_status`，默认 `auto` 保持原有公开规则
- 已新增 `PATCH /api/v1/movies/<id>/catalog-visibility`
- 支持 `auto`、`published`、`hidden`，其中 `published` 在存在阻塞原因时需要用户确认后传 `force=true`
- `MovieSimple/MovieDetailed` 返回 `catalog_visibility`，前端可展示有效状态、阻塞原因和是否需要确认

建议：
- 前端把 `hidden/published` 做成用户显式操作，不要自动替用户设置
- 资源库继续保留当前 `movie-memberships include/exclude` 能力；总影视库发布控制只影响全局 catalog

### 2. 前端反馈待办池
来源：前端侧影视管理 UI 已基本闭环后提出的后端缺口。当前先记录，不立即打乱现阶段节奏。

#### 2.1 影片删除 / 文件销毁接口
需求：
- 提供类似 `DELETE /api/v1/movies/<id>` 的影片删除能力
- 需要明确是“仅删除数据库元数据”，还是“同时删除底层硬盘/WebDAV 文件”

风险：
- 真正删除物理文件属于高风险操作，必须先设计安全保护
- 需要处理多资源、多清晰度、多来源、库绑定、播放历史、图片缓存等关联数据

建议：
- 先实现软删除或“仅移出媒体库”
- 再设计带二次确认、dry-run、权限校验、审计日志的物理删除

#### 2.2 硬件转码与字幕流能力
需求：
- 补齐真正的串流转码控制
- 支持实时字幕流注入或字幕轨选择

风险：
- 涉及 FFmpeg、硬件加速、Range、WebDAV 直连、缓存策略，容易影响播放链路稳定性

建议：
- 先保持当前直连/代理播放稳定
- 后续单独拆出播放能力矩阵，再逐步接入转码任务控制

#### 2.3 用户、角色与权限隔离
需求：
- 真正的身份验证
- 系统角色与接口权限控制
- 多用户隔离

风险：
- 会影响所有接口调用方式，前后端都需要统一鉴权契约

建议：
- 先定义认证模型和角色边界
- 再分阶段接入登录、token、角色鉴权和资源级权限

### 3. SMB / FTP / AList / OpenList 真实环境联调
当前状态：provider、配置校验、目录预览、扫描和播放链路已接入；仍需要在真实存储环境下逐项验证目录浏览、Range 读取、播放直链和异常提示。

### 4. 播放链路继续完善
当前状态：播放接口已按扩展名返回 `Content-Type`。后续可继续补字幕、转码、缓存和外部播放器能力。

### 5. 扫描规则增强
例如：
- 更复杂目录命名支持
- 更稳定的电影/剧集识别
- NFO / 本地元数据利用

### 6. 配置外置化
将敏感配置迁移至环境变量或独立配置文件。

---

## D. Emby 对标差距与长期超越路线

本节记录长期方向，避免后续开发只按临时功能点堆叠。

### 1. 当前定位

赛博影视当前优先定位仍是个人向私有媒体库。多用户、权限隔离和公网运营能力不是当前第一优先级，先把个人主路径做到稳定、可控、可解释。

### 2. 与 Emby/Jellyfin 类产品的主要差距

当前还需要长期打磨的差距：

- 真实存储环境验证：`SMB/FTP/AList/OpenList` 已接入代码主流程，但仍要在真实 NAS、FTP、AList、OpenList 环境下验证目录浏览、扫描、Range 播放、跳转播放和异常提示。
- 播放体验：网页端播放天然受浏览器解码能力限制。后续主攻 PC 端，优先借助成熟开源播放器内核或原生 Windows 播放能力，网页播放保留为轻量入口和兜底能力。
- PC 播放契约：已新增 `GET /api/v1/resources/<id>/external-playback`，返回外部播放器 handoff manifest；`format=m3u` 可生成 M3U 播放列表。当前只包装现有 stream/subtitle URL，不改变视频流行为，后续 PC 客户端可直接复用该契约。
- 资料库质量：这是最难、最需要长期打磨的部分，包括电影/剧集识别、季集归并、演员/导演实体化、系列/合集、字段来源追踪、手动修正和复核工作台。
- 多用户能力：账号、角色、权限、观看历史隔离和资源级权限后置；当前阶段不应过早引入复杂鉴权影响个人使用主链路。
- 运维发布能力：SQLite 备份/恢复脚本已补第一版；Docker、安装包、迁移脚本、日志诊断、版本 release 和升级说明会随项目成熟逐步补齐。

### 3. 差异化优势方向

赛博影视不应只复制 Emby 的传统媒体库路径，长期核心差异化是：

- PC 客户端优先，把播放体验交给更强的本地播放器和系统解码能力。
- 后端继续提供稳定的资料库、扫描、字幕、元数据、图片缓存和播放能力矩阵。
- 未来与 `skill`、OpenClaw 类 agent 深度集成，让 agent 参与识别、整理、字幕匹配、元数据修复、质量诊断、批量任务规划。
- agent 只能提供建议、候选、解释、dry-run 和自动化执行入口；涉及发布、删除、覆盖元数据、绑定字幕等关键动作必须保留用户显式确认。

#### 后期计划：剧集审查 skill

等项目主路径基本稳定、常规 bug 收口后，再考虑做面向 Codex/Claude/OpenClaw 等 agent 的剧集审查 skill。该能力不新增专门的 AI 审查后端接口，而是复用现有确定性 API，由 skill 负责编排、分析和生成建议。

目标边界：
- 后端继续只负责查询、诊断和执行用户确认后的 PATCH，不把复杂 AI 判断写进扫描器。
- skill 读取 OpenAPI、剧集诊断、资源列表、季信息和元数据搜索结果，判断正片、特别篇、前瞻篇、缺集、误匹配和集号修正。
- agent 只输出 dry-run 方案、解释和可提交的 `apply_payload`，不直接写库。
- 用户确认后再调用现有 `PATCH /api/v1/movies/<id>/resources/metadata`、`PATCH /api/v1/movies/<id>/seasons/<season>/metadata`、`POST /api/v1/movies/<id>/metadata/match` 等接口。

建议纳入 skill 的关键接口：
- `GET /api/v1/openapi.json`
- `GET /api/v1/docs`
- `GET /api/v1/metadata/episode-review-items`
- `GET /api/v1/movies/{id}/episode-diagnostics`
- `GET /api/v1/movies/{id}/resources`
- `GET /api/v1/movies/{id}/seasons`
- `PATCH /api/v1/movies/{id}/resources/metadata`
- `PATCH /api/v1/movies/{id}/seasons/{season}/metadata`
- `GET /api/v1/movies/{id}/metadata/search`
- `POST /api/v1/movies/{id}/metadata/match`

明确不做：
- 不在全库扫描中自动启用 AI 判断。
- 不为了个别剧集继续堆复杂自动解析规则。
- 不让 agent 自动删除资源、强行覆盖元数据或把特别篇硬塞进正片集号。
- 不新增一个只服务 AI 的平行审查接口，避免后端契约膨胀。

### 4. 推荐推进顺序

近期：
- 完成前端联调收口。
- 做真实环境协议联调和播放抽样验证。
- 保持 OpenAPI、文档、测试与运行态一致。

中期：
- 推进 PC 端播放方案和外部播放器/原生播放器调用契约。
- 持续增强资料库复核工作台、剧集识别、季集编辑和字段来源追踪。
- 补齐 release、部署和迁移基础能力。

长期：
- 再进入多用户、权限、审计和公网安全模型。
- 建立 agent/skill 编排层，把媒体库维护从手工操作升级为“候选生成 + 用户确认 + 可追踪执行”的智能工作流。

---

## E. 不建议当前阶段做的事

### 1. 推倒重写
没有必要，风险远大于收益。

### 2. 大规模架构重构
当前应先稳住功能和文档，再逐步收口历史包袱。

### 3. 同时改扫描、存储、播放三大模块
这会让问题定位变得非常困难。

---

## F. 接手后的推荐节奏

1. 先补文档
2. 再整理启动与配置
3. 再做低风险工程性修补
4. 最后再做协议扩展与核心功能增强
