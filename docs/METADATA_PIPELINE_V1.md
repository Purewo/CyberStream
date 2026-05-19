# 元数据刮削重塑说明 V1

本文档用于说明当前元数据刮削层的重塑方向，目标是把原来堆在 `scanner.py` 里的解析和刮削逻辑拆成清晰的三层。

## 目标分层

### 1. 规范格式直刮
适用场景：
- `Show/Season 01/S01E01.mkv`
- `Show S01/Show.S01E02.mkv`
- `Movie (2010)/Movie.2010.1080p.mkv`
- `国漫/凡人修仙传/第12集.mp4`

特点：
- 结构明显
- 置信度高
- 优先走严格匹配和严格 TMDB 查询

### 2. 经验规则兜底
适用场景：
- 目录结构不标准
- 标题混入大量噪音
- 只能从父目录、祖父目录、文件名局部信息做推断

特点：
- 复用旧扫描器里积累的经验规则
- 仍然保留，但不再继续和主流程耦在一起
- 当前作为 fallback 层存在

### 3. AI 刮削预留层
适用场景：
- 规范层和经验层都无法稳定识别
- 名称极脏、目录极乱、需要语义理解

当前状态：
- 已在元数据管线中预留 AI 层入口
- 当前默认不启用，只记录 `not_enabled`

## 当前已落地结构

- `backend/app/metadata/parser.py`
  - 负责路径解析
  - 已拆为 `strict + fallback`
- `backend/app/metadata/scraper.py`
  - 负责刮削命中决策
  - 已拆为 `nfo + structured + fallback + ai`
- `backend/app/metadata/ai.py`
  - AI 层独立预留入口
  - 后续接大模型时只应改这里，不回写 `scanner.py`
- `backend/app/metadata/nfo.py`
  - NFO 层预处理入口
  - 当前已能识别 sidecar NFO 候选，并支持消费预加载的 NFO 文本
  - 默认不主动读取远端 NFO 内容，避免扫描阶段性能退化
- `backend/app/metadata/pipeline.py`
  - 对扫描器暴露统一入口
- `backend/app/services/scanner.py`
  - 现在主要负责扫描编排，不再继续直接堆解析/刮削规则
  - 当前会把 `parse/scrape` 留痕写入资源 `tech_specs.metadata_trace`

## 当前留痕字段

扫描入库时，资源层会补充：

- `tech_specs.metadata_trace.parse_layer`
- `tech_specs.metadata_trace.parse_strategy`
- `tech_specs.metadata_trace.confidence`
- `tech_specs.metadata_trace.media_type_hint`
- `tech_specs.metadata_trace.scrape_layer`
- `tech_specs.metadata_trace.scrape_strategy`
- `tech_specs.metadata_trace.scrape_reason`

前端或调试接口可直接读取 `resource.metadata_trace`，不用再只靠后端日志判断本次命中属于 strict、fallback 还是后续 AI 层。

## 当前分流约定

- 识别出 `season/episode/SxxExx/第xx集` 的，优先标记 `media_type_hint=tv`
- 明显电影目录或带年份单文件，优先标记 `media_type_hint=movie`
- TMDB 查询会优先走对应 `/search/tv` 或 `/search/movie`，而不是一律 `search/multi`
- 动漫库可通过 `provider_order: ["nfo", "bangumi", "tmdb", "local"]` 显式启用 Bangumi 优先；默认顺序仍为 `nfo -> tmdb -> local`

## 当前 NFO 状态

- Scanner 已会为每个视频条目收集同目录 sidecar NFO 候选
- 这些候选会进入 entity context 和 `ParsedMediaInfo.extras`
- 当前默认只做候选识别和留痕，不额外读取远端 NFO 文件内容
- 现在已经补上 provider 级“轻量文本读取”能力，只会对同组 sidecar NFO 定点读取
- 仍然禁止为 NFO 做额外目录扫描，读取范围只限当前实体候选文件
- 如果 NFO 里带 `tmdbid` 或 `uniqueid(type=tmdb)`，当前会优先用该 ID 拉 TMDB 详情，再用 NFO 对缺字段做补齐
- 如果 NFO 没有 TMDB ID，则退回 `NFO_LOCAL`，只使用本地解析出的标题/年份/演员/类型等信息
- 如果 NFO 只有 `imdbid` 或 `uniqueid(type=imdb/tvdb)`，当前会先通过 TMDB `/find` 转成 `movie/<id>` 或 `tv/<id>` 再拉详情

## 当前手动修复联动

- `GET /api/v1/metadata/providers` 返回当前 provider 注册表、默认顺序、别名和能力；当前为 `nfo/tmdb/bangumi/local`
- `GET /api/v1/movies/{id}/metadata/search` 支持 `providers` / `provider_order`，可按 `media_type_hint=movie|tv` 过滤候选
- 搜索候选统一返回 `provider`、`source_key`、`candidate_id`、`external_id`；`tmdb_id` 继续作为兼容字段
- Bangumi 候选 ID 为 `bangumi/<id>`，支持关键字、裸 subject ID、`bangumi/<id>` 和 `https://bgm.tv/subject/<id>` 定点搜索
- 指定 `query` 但不指定 `year` 时，不再继承当前影片年份；响应会返回 `year_source`
- `POST /api/v1/movies/{id}/metadata/match` 建议传 `candidate_id + provider`，同时兼容 `tmdb_id`、`imdb/<id>`、`tvdb/<id>`、`movie/<id>`、`tv/<id>` 和 `bangumi/<id>`；默认只返回 dry-run 预览，前端确认覆盖时需带 `apply=true`
- `POST /api/v1/movies/{id}/metadata/match` 在候选和当前影片最终都没有海报时会拒绝直接应用，避免无海报项目在前端变成不可见幽灵数据；确需写入可显式传 `allow_missing_poster=true`
- `POST /api/v1/movies/{id}/metadata/refresh` 支持 `candidate_id/external_id + provider`，也兼容旧 `tmdb_id`
- 影片详情和列表现在会返回 `scraper_source`，便于前端识别 `TMDB_STRICT`、`NFO_TMDB`、`NFO_LOCAL` 等来源

## 当前原则

- 新增规则，优先判断它属于 strict 还是 fallback
- 不再把新的命名经验直接堆回 `scanner.py`
- AI 接入时，必须作为第三层独立能力接入，不能污染 strict/fallback 规则
- `scraper_source` 应表达真实来源语义，而不是笼统写成 `TMDB` / `Local`
  - 当前约定：`TMDB_STRICT`、`TMDB_FALLBACK`、`LOCAL_FALLBACK`、`LOCAL_ORPHAN`
