# PROJECT_PROGRESS

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
   - 准备对接自建 CDN，避免长期直接依赖第三方图片地址。

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
  - 只刷新单条影片的 TMDB 元数据
  - 不触发全库扫描
  - 若影片当前是 `loc-*` 占位 ID，会先按标题/年份尝试搜索 TMDB
  - 已锁定字段默认不覆盖，可通过 `metadata_unlocked_fields` 定点解锁后再刷新
- 新增手动匹配链路：
  - `GET /api/v1/movies/<id>/metadata/search`：搜索单条影片的 TMDB 候选
  - `POST /api/v1/movies/<id>/metadata/match`：将影片匹配到指定 `tmdb_id`
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
