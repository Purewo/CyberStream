# 1.16.0-beta 更新说明

本文档说明 `openapi-1.16.0-beta.json` 对应的本轮接口更新，供前后端联调对照。

## 收口状态

`1.16.0` 已作为当前前后端联调稳定基线收口。后续除必要 bug 修复和联调缺口补丁外，不再向本版本继续塞大功能；下一轮大功能进入后续版本。

最终验收结果：

- OpenAPI JSON 可解析校验通过
- OpenAPI path/method 与运行时路由对齐：`59/59`
- 全量 unittest：`126 tests OK`
- 本地健康检查和关键小流量接口抽样通过
- 公网 HTTPS 资源接口抽样通过，资源技术字段可返回 `UHD Blu-ray Remux`、`HDR10`、`Dolby TrueHD 7.1 Atmos`、`HEVC`

## 本轮重点

本轮把存储源协议从 `local/webdav` 扩展到 SMB / FTP / AList / OpenList，并把未保存来源预览、已保存来源目录浏览、协议能力矩阵、脏数据复核队列统一补进接口基线。

同时补齐首页门户和资源库手动影视规则接口：

- `GET /api/v1/homepage`
- `GET /api/v1/homepage/config`
- `PATCH /api/v1/homepage/config`
- `GET /api/v1/libraries/{id}/movie-memberships`
- `POST /api/v1/libraries/{id}/movie-memberships`
- `POST /api/v1/libraries/{id}/movie-memberships/delete`

库级影片项新增 `library_membership=auto|manual|both`，用于区分挂载路径自动命中、手动加入或两者同时命中。

资源库基础信息已移除 `library_type`。资源库类型不再作为创建、更新或返回字段，前端用资源库名称表达分类即可。

影片列表项新增 `quality_badge`，供前端在海报上展示单一清晰度标签。返回值只包含 `Remux`、`4K`、`HD` 或 `null`，优先级为 `Remux > 4K/2160P > 1080P > null`。首页、全局列表、资源库列表、推荐等复用 `MovieSimple` 的接口都会带该字段。

当前后端稳定支持的存储来源：

- `local`
- `webdav`
- `smb`
- `ftp`
- `alist`
- `openlist`

`alist` 与 `openlist` 当前共用兼容 REST API provider。若 OpenList 后续出现独有字段，再在同一 provider 内补差异分支。

## 首页门户聚合

新增首页聚合接口 `GET /api/v1/homepage`，返回：

- `hero`：超大海报影片，支持指定影片；未指定时自动选择最新且有横幅图的影片
- `sections`：首页分类区块，默认 `科幻` / `动作` / `剧情` / `动画`，每类默认最多 15 个

配套配置接口：

- `GET /api/v1/homepage/config`
- `PATCH /api/v1/homepage/config`

`sections` 支持 `mode=custom|latest`。手动模式只返回配置的影片，不自动补齐；首页会去重，且启用动画分类时，其他分类不会展示动画内容。首页区块按影片条目计数，不返回可展开的 `season_cards`，避免多季动漫突破分类数量限制。

## 资源库手动影视规则

资源库内容现在由三部分组成：

```text
挂载点路径自动命中 + 手动 include - 手动 exclude
```

新增接口：

- `GET /api/v1/libraries/{id}/movie-memberships`
- `POST /api/v1/libraries/{id}/movie-memberships`
- `POST /api/v1/libraries/{id}/movie-memberships/delete`

`POST` 请求体示例：

```json
{
  "mode": "include",
  "movie_ids": ["movie-id-1", "movie-id-2"],
  "sort_order": 0
}
```

说明：

- `include`：把已入库影视手动加入某个资源库
- `exclude`：把自动命中的影视从该资源库隐藏
- 删除 `exclude` 后，如果影视仍命中挂载路径，会重新出现在该资源库中
- 挂载点自动命中只纳入无需人工处理且有海报的公开影视；raw/占位/缺海报/待处理影片必须手动 `include` 才会进入资源库
- 手动规则只影响该资源库，不影响全局影视库和底层播放链路
- `GET /api/v1/libraries/{id}/movies` 已接入后端分页与排序，支持 `page`、`page_size`、`sort_by`、`order`，并返回 `pagination`
- `media_resources` 增加 `(source_id, path)` 唯一约束，防止重刮削或并发扫描产生重复资源

## 公开影视库可见性

`GET /api/v1/movies` 作为前端“全部影视”默认只返回无需人工处理且有海报的公开影视，避免无海报 raw/占位影片混入普通影视库。

处理队列入口保持可用：

- `GET /api/v1/movies?needs_attention=true`
- `GET /api/v1/metadata/work-items`

`GET /api/v1/filters` 的 `genres/years/countries` 也按公开影视库统计，避免待处理或缺海报影片污染普通筛选项。

## 存储协议新增

新增 / 补齐 provider：

- `backend/app/providers/alist.py`
- `backend/app/providers/smb.py`
- `backend/app/providers/ftp.py`

接入链路：

- `ProviderFactory`
- `source_registry`
- `StorageSource.to_dict()` 的能力与脱敏配置返回
- `GET /api/v1/storage/capabilities`
- `GET /api/v1/storage/sources/{id}/browse`
- `POST /api/v1/storage/preview`
- `GET /api/v1/reviews/resources`
- 扫描链路
- 播放链路

同时补齐了 OpenAPI 中 `StoragePreviewRequest`、`StorageSource`、`StorageSourceRequest`、`StorageProviderType`、`StoragePreviewData` 对 `smb/ftp` 的协议枚举，以及 `ConfigSMB` / `ConfigFTP` 的默认值与字段约束。

## AList / OpenList 配置

推荐 token 模式：

```json
{
  "type": "alist",
  "config": {
    "base_url": "https://alist.example.com",
    "token": "alist-token",
    "root": "/movies"
  }
}
```

推荐账号密码模式：

```json
{
  "type": "openlist",
  "config": {
    "host": "openlist.local",
    "port": 5244,
    "secure": true,
    "username": "admin",
    "password": "secret",
    "root": "/movies"
  }
}
```

关键字段：

- `base_url` 与 `host` 至少提供一个
- `token` 优先；没有 token 时用 `username/password` 调 `/api/auth/login`
- `root` 表示 AList/OpenList 内部技术根目录
- `path_password` 用于目录密码
- AList/OpenList 播放接口直接返回带域名的 `/d/...` 播放入口，由 AList/OpenList 在前端访问时自行刷新上游直链
- `proxy_stream` 当前仅保留为兼容字段；AList/OpenList 播放默认不做后端中转

## 预览返回结构变化

`POST /api/v1/storage/preview` 当前返回：

```json
{
  "storage_type": "alist",
  "current_path": "/",
  "parent_path": null,
  "items": [
    {
      "name": "Movies",
      "path": "Movies",
      "type": "dir",
      "size": 0
    }
  ]
}
```

说明：

- `dirs_only` 默认 `true`
- `target_path` 用于继续浏览子目录
- `items[].type` 固定为 `dir` 或 `file`
- `capabilities` 会一并返回，前端可据此决定是否展示路径校验、范围播放等能力
- 前端目录选择器可以对 `local/webdav/smb/ftp/alist/openlist` 使用同一套结构

## 预览目录与扫描联动

`POST /api/v1/storage/sources/{id}/scan` 现在支持直接携带预览选择结果：

```json
{
  "root_path": "/电影/华语",
  "content_type": "movie",
  "scrape_enabled": true
}
```

说明：

- `root_path` 用于限定本次扫描的起始目录
- `target_path` 作为兼容别名也可传入，便于前端直接复用预览选择器返回值
- 未传目录时，仍按存储源配置的根目录扫描
- 这样即使还没建立资源库绑定，前端也可以先在“存储源维度”只扫描用户刚刚选择的子目录
- 全量扫描、指定存储源扫描、资源库扫描现在共用同一个运行锁；已有扫描任务执行中时，新触发请求返回 `429`，避免并发扫描重复入库或互相覆盖进度。

## 复核队列与清洗分析

新增 `GET /api/v1/reviews/resources`，返回路径清洗阶段标记 `needs_review` 的资源分页列表，核心字段包括：

- `path_cleaning.title_hint/year_hint/parse_mode/parse_strategy/needs_review`
- `scraping.provider/confidence/matched_id/final_title_source/final_year_source/provider_order`

这部分对应当前后端已经落地的脏数据清洗与复核队列能力，供后续人工复核工作台和重新刮削入口直接复用。

## 资源原始信息结构收口

资源对象新增 `resource_info`，作为文件原始信息与媒体技术信息的统一入口：

- `resource_info.file`：文件名、相对路径、大小、容器、存储源
- `resource_info.display`：展示标题、展示标签、季集、排序信息
- `resource_info.technical`：分辨率、编码、HDR、音频、片源和质量层级

为避免前端继续混用旧结构，资源对象改为只输出当前结构：

- `id`
- `resource_info`
- `metadata.trace`
- `metadata.analysis`
- `metadata.edit_context`

以下旧兼容字段已从资源响应中移除：

- `quality_label`
- `media_info`
- `media_features`
- `media_profile`
- `tech_specs`
- 顶层重复展示字段，例如 `filename`、`relative_path`、`display_label`、`season`、`episode`

资源接口也同步去重：

- `GET /api/v1/movies/<id>` 不再内嵌 `resources`
- `GET /api/v1/movies/<id>/resources` 只在 `items` 中返回一份资源对象
- `groups.standalone.resource_ids` 与 `groups.seasons[].resource_ids` 只保存资源 ID，不再重复嵌入资源对象

- 电影/剧集条目的 `tags` 仍表示内容分类；资源额外标签统一改读 `resource_info.technical.extra_tags`
- `4K`、`HDR10`、`Dolby Vision`、`Atmos`、`REMUX` 等已结构化字段不再重复作为标签输出，例如 `4K` 由 `video_resolution_bucket = "4k"` 推导
- OpenAPI 已将 `resource_info.technical` 改为完全扁平的一层强类型字段，覆盖 `video_resolution_*`、`video_codec_*`、`video_dynamic_range_*`、`video_bit_depth_*`、`audio_*`、`source_*`、`quality_*`、`flag_*` 和 `extra_tags`，每个字段均带说明，便于前端生成类型和对接。
- 动态范围不再把“未检测到 HDR”默认写成 SDR；只有文件名/路径明确出现 SDR 时才返回 `video_dynamic_range_code = "sdr"`，无法确认时返回 `unknown`。
- 资源技术信息继续细化：普通 `HDR` 规范为 `HDR10`；`UHD BluRay REMUX` 返回 `source_code = "uhd_bluray_remux"` / `source_label = "UHD Blu-ray Remux"`；`TrueHD7.1 Atmos` 返回 `audio_summary_label = "Dolby TrueHD 7.1 Atmos"`、`audio_channels_label = "7.1"`、`audio_is_lossless = true`。这些纠偏会结合文件名完成，历史已入库资源无需重新刮削即可受益。

## 已观看标记移除

观看历史和续播功能保留，`/api/v1/user/history` 相关接口继续可用。列表、首页、资源库、影片详情和资源分组仍返回 `user_data` 作为播放进度上下文，但 `PlaybackUserData` 不再返回 `is_played`，前端不要再据此展示“已观看”标签。

## 接口契约收口

- OpenAPI 已补齐运行时存在的全局 `GET /api/v1/featured` 与 `GET /api/v1/recommendations`。
- OpenAPI 已移除未实现的 `GET /api/v1/resources/{id}/subtitles` 和 `Subtitle` schema，避免前端按不存在接口生成调用。
- 播放接口 `GET /api/v1/resources/{id}/stream` 会按资源扩展名返回 `Content-Type`，支持 `video/mp4`、`video/x-matroska`、`video/webm`、`video/mp2t`、`video/quicktime`、`video/x-msvideo`，无法识别时返回 `application/octet-stream`。
- 本轮新增 OpenAPI 路由漂移测试，确保运行时已注册路由和 `openapi-1.16.0-beta.json` 的 path/method 保持一致。

## 联调基线

- OpenAPI：`backend/openapi/openapi-1.16.0-beta/openapi-1.16.0-beta.json`
- 接口概览：`docs/API_OVERVIEW.md`
- 测试清单：`docs/TEST_CHECKLIST.md`
- 当前版本状态：稳定收口；下一版本再继续大功能
