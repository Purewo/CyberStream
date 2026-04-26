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

- `POST /api/v1/movies/{id}/metadata/match` 支持传入 `imdb/<id>`、`tvdb/<id>` 或原有 `movie/<id>`、`tv/<id>`
- `POST /api/v1/movies/{id}/metadata/refresh` 在本地占位条目重匹配时支持 `media_type_hint`
- `GET /api/v1/movies/{id}/metadata/search` 返回 `media_type_hint`，并可按 `media_type_hint=movie|tv` 过滤候选
- 影片详情和列表现在会返回 `scraper_source`，便于前端识别 `TMDB_STRICT`、`NFO_TMDB`、`NFO_LOCAL` 等来源

## 当前原则

- 新增规则，优先判断它属于 strict 还是 fallback
- 不再把新的命名经验直接堆回 `scanner.py`
- AI 接入时，必须作为第三层独立能力接入，不能污染 strict/fallback 规则
- `scraper_source` 应表达真实来源语义，而不是笼统写成 `TMDB` / `Local`
  - 当前约定：`TMDB_STRICT`、`TMDB_FALLBACK`、`LOCAL_FALLBACK`、`LOCAL_ORPHAN`
