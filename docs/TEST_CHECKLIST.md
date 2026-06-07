# 测试与验收清单

本文档用于赛博影视后端的日常改动验收，目标是：

- 每次修改后都有最小可执行检查项
- 降低“改一处，坏一片”但没及时发现的风险
- 方便任何接手者快速完成回归

---

## 1. 验收原则

1. 先做本地验收，再做公网验收
2. 每次改动至少覆盖与改动直接相关的模块
3. 涉及扫描、播放、存储源时，必须做针对性回归
4. 修改文档、注释、纯展示文本时，可走简化验收

---

## 2. 基础启动验收（每次改动后建议执行）

### 2.1 启动服务
推荐：

```bash
cd /path/to/CyberStream
./scripts/backend_service.sh restart
```

服务脚本默认优先使用 gunicorn，缺失时回退 Flask 内置服务器。开发前台调试兼容：

```bash
.venv/bin/python -m backend.run
```

当前维护服务器上的仓库路径为 `/root/CyberStream`，但验收命令不依赖固定绝对路径。

### 2.2 端口监听检查

```bash
ss -ltnp | grep ':5004 '
```

预期：
- 存在 Python 进程监听 `5004`

### 2.3 本地健康检查

```bash
curl -i http://127.0.0.1:5004/
curl -i http://127.0.0.1:5004/api/v1/health
./scripts/backend_smoke_check.py --systemd --base-url http://127.0.0.1:5004 --expected-version 1.21.0 --expected-openapi-version 1.21.0-beta --min-storage-sources 1
```

预期：
- HTTP 200
- 返回 JSON
- `data.status = up`
- `data.database.status = ok`
- `data.version = 1.21.0`
- 文档索引 app version = `1.21.0`
- OpenAPI index version = `1.21.0-beta`
- `/` 与 `/api/v1/health` 返回相同健康状态、版本和数据库状态
- smoke check 返回 `OK update_check`，说明官方客户端公开更新检查契约可用
- smoke check 返回 `OK libraries`，说明普通资源库列表契约可用且不混入收藏虚拟库
- smoke check 返回 `OK other_videos`，说明其他视频归档队列、分页、summary 和手工归档动作契约可用
- smoke check 返回 `OK catalog_filters`，说明目录页筛选项 `genres/years/countries` 可用
- smoke check 返回 `OK catalog_movies`，说明主影视列表分页与首条样例关键字段可用
- smoke check 返回 `OK movie_detail`，说明列表到详情页的只读链路与详情关键字段可用
- smoke check 返回 `OK movie_resources`，说明详情页资源面板、播放源分组和主资源 ID 可用
- smoke check 返回 `OK external_playback`，说明 PC/外部播放器播放交接 manifest 和 M3U handoff 契约可用
- smoke check 返回 `OK subtitle_settings`，说明网页播放器字幕显示设置读取契约可用
- smoke check 返回 `OK audio_transcode_diagnostics`，说明实时音频转码诊断读取入口可用且不会泄漏为异常状态
- smoke check 返回 `OK storage_provider_types`，说明存储 provider 类型和挂载表单字段契约可用
- smoke check 返回 `OK storage_capabilities`，说明存储协议能力矩阵和前端挂载表单基础契约可用
- smoke check 返回 `OK featured`，说明首页旧置顶/轮播入口仍返回详情影片契约
- smoke check 返回 `OK homepage_config`，说明首页配置读取契约可用
- smoke check 返回 `OK homepage`，说明首页 hero 与 sections 聚合契约可用
- smoke check 返回 `OK recommendations`，说明发现页推荐流和推荐理由契约可用
- smoke check 返回 `OK movie_context_recommendations`，说明详情页/播放页单片相关推荐契约可用
- smoke check 返回 `OK user_history`，说明历史列表分页和播放进度上下文契约可用
- smoke check 返回 `OK vault_status`，说明保险库入口状态契约可用
- smoke check 全部返回 `OK`

### 2.4 公网健康检查

```bash
curl -i https://cyberstream.gameuniverse.top:40160/
curl -i https://cyberstream.gameuniverse.top:40160/api/v1/health
curl -i https://cyberstream.gameuniverse.top:40160/api/v1/openapi.json
./scripts/backend_smoke_check.py --base-url https://cyberstream.gameuniverse.top:40160 --expected-version 1.21.0 --expected-openapi-version 1.21.0-beta
```

预期：
- HTTP/HTTPS 均能返回 200
- 返回健康检查 JSON
- smoke check 全部返回 `OK`

### 2.5 数据库备份检查

涉及数据库结构、批量修复、资源治理、扫描策略或大范围元数据改动前，先执行：

```bash
./scripts/db_backup.py verify
./scripts/db_backup.py backup
./scripts/db_backup.py verify backups/<backup-file>.db
./scripts/db_backup.py list
```

预期：
- 当前数据库 integrity check 返回 `ok`
- `backups/` 下生成新的 `cyber_library.<timestamp>.db`
- `backup` 先写入临时文件，校验通过后才发布正式 `.db`
- 自动校验失败时，未确认的备份副本不会留在 `backups/`
- 新备份文件 integrity check 返回 `ok`
- `list` 能看到最新备份文件
- `restore --yes` 会自动校验目标备份；备份损坏时应拒绝恢复且不替换当前数据库
- `restore --yes` 会拒绝把当前数据库路径作为恢复源
- 恢复复制或替换失败时，不应留下 `*.restore_tmp` 临时文件

---

## 3. 接口级基础回归

以下建议在修改 API、模型、配置、启动逻辑后执行。

### 3.1 获取扫描状态

```bash
curl -s http://127.0.0.1:5004/api/v1/scan
```

预期：
- 返回标准 JSON
- 包含 `status`、`phase` 等字段

### 3.2 获取存储源列表

```bash
curl -s http://127.0.0.1:5004/api/v1/storage/sources
```

预期：
- 返回数组或空数组
- 不报 500

### 3.3 获取电影列表

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies?page=1&page_size=5"
```

预期：
- 返回分页结构
- 包含 `items` 与 `pagination`
- 默认不包含 `needs_attention=true` 的 raw/占位/缺海报影片；如需检查处理队列，使用 `?needs_attention=true`

### 3.4 获取筛选项

```bash
curl -s "http://127.0.0.1:5004/api/v1/filters?include=genres,years,countries"
```

预期：
- 返回 `genres` / `years` / `countries`
- 不统计需要人工处理的 raw/占位/缺海报影片
- 没有 500 错误

### 3.5 获取推荐内容

```bash
curl -s "http://127.0.0.1:5004/api/v1/recommendations?limit=3"
```

预期：
- 返回数组
- 不报错
- smoke check 返回 `OK recommendations`，说明影片条目带 `recommendation.primary_reason/reasons/signals`
- smoke check 返回 `OK movie_context_recommendations`，说明单片相关推荐返回 `strategy=context` 且不会推荐锚点影片

### 3.6 获取首页 featured

```bash
curl -s http://127.0.0.1:5004/api/v1/featured
```

预期：
- 返回数组
- 即使条目为空也不应 500
- smoke check 返回 `OK featured`，说明条目仍符合详情影片契约

### 3.7 总影视库发布状态

以下在修改总影视库、推荐、筛选、featured 或影片详情字段后执行。

查看影片详情：

```bash
curl -s http://127.0.0.1:5004/api/v1/movies/<id>
```

预期：
- 返回 `catalog_visibility`
- 默认 `status=auto`
- `is_visible` 能解释该影片是否进入总影视库

手动隐藏：

```bash
curl -s -X PATCH http://127.0.0.1:5004/api/v1/movies/<id>/catalog-visibility \
  -H 'Content-Type: application/json' \
  -d '{"status":"hidden","note":"manual hide"}'
```

预期：
- 返回 `catalog_visibility.status = hidden`
- 默认 `/api/v1/movies` 不再返回该影片

手动发布：

```bash
curl -s -X PATCH http://127.0.0.1:5004/api/v1/movies/<id>/catalog-visibility \
  -H 'Content-Type: application/json' \
  -d '{"status":"published","force":true}'
```

预期：
- 返回 `catalog_visibility.status = published`
- 默认 `/api/v1/movies` 会返回该影片
- 如果未传 `force` 且存在 `blockers`，应返回 `409`，前端必须让用户确认后再提交

### 3.8 获取首页门户聚合数据

```bash
curl -s http://127.0.0.1:5004/api/v1/homepage
curl -s http://127.0.0.1:5004/api/v1/homepage/config
```

预期：
- 返回 `hero` 与 `sections`
- 默认分类包含 `科幻` / `动作` / `剧情` / `动画`
- 分类区块之间不重复影片
- smoke check 返回 `OK homepage_config` 和 `OK homepage`，说明首页配置、hero 影片详情、section 条目和去重规则可用

### 3.9 元数据 provider 与动漫候选搜索

以下在修改元数据 provider、OpenAPI、手动匹配或前端联调字段后执行。

```bash
curl -s http://127.0.0.1:5004/api/v1/metadata/providers
```

预期：
- 返回 `nfo`、`tmdb`、`anilist`、`bangumi`、`tencent_video`、`local`
- `tmdb`、`anilist`、`bangumi` 与 `tencent_video` 的 `supports_search=true`
- `anilist.default_enabled=false`，不进入默认全库扫描顺序
- `tencent_video.manual_only=true` 且 `supports_scrape=false`
- 默认顺序仍为 `nfo -> tmdb -> local`

批量刮削前建议跑完整 scraper readiness smoke check：

```bash
./scripts/backend_smoke_check.py --systemd --base-url http://127.0.0.1:5004 \
  --openapi-module-json-check \
  --expected-version 1.21.0 \
  --expected-openapi-version 1.21.0-beta \
  --min-storage-sources 1 \
  --storage-health-check \
  --min-storage-health-checks 1 \
  --tmdb-token-check
```

预期：
- `docs_index` 返回 `OK`
- `openapi_modules` 返回 `OK`
- `metadata_providers` 返回 `OK`
- `storage_provider_types` 返回 `OK`，说明存储 provider 类型和挂载表单字段契约可用
- `storage_capabilities` 返回 `OK`，说明存储协议能力矩阵和前端挂载表单基础契约可用
- `storage_sources` 返回 `OK`，且至少包含当前挂载点
- `storage_browse` 返回 `OK`，说明已保存挂载点目录选择器浏览契约可用
- `storage_health` 返回 `OK`，且 `checked>=1`
- `tmdb_token` 返回 `OK`，且 `ready=True status=ok`

AniList 动漫候选搜索：

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=Frieren&providers=anilist&media_type_hint=tv&limit=1"
```

预期：
- 返回标准 JSON，`data.items[0].provider = anilist`
- 返回 `candidate_id = anilist/<id>`、`source_url`、`episode_count`、`format`
- 未显式传 `year` 时，`data.year_source = none`

使用一个已存在的 movie id 做 Bangumi 搜索：

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=葬送的芙莉莲&providers=bangumi&media_type_hint=tv&limit=1"
```

预期：
- 返回标准 JSON，`data.items[0].provider = bangumi`
- 返回 `candidate_id`、`source_key`、`source_url`、`episode_count`
- 未显式传 `year` 时，`data.year_source = none`
- `providers.attempts` 能反映 `ok/skipped/failed`

Bangumi subject URL 定点搜索：

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=https%3A%2F%2Fbgm.tv%2Fsubject%2F400602&providers=bangumi&media_type_hint=tv"
```

预期：
- 返回 `candidate_id = bangumi/400602`

腾讯视频手动候选搜索：

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies/<id>/metadata/search?query=诛仙3&providers=tencent_video&media_type_hint=tv&limit=1"
```

预期：
- 返回 `data.items[0].provider = tencent_video`
- 返回 `candidate_id = tencent_video/<cid>`、`source_url`、`episode_count`
- 该 provider 不应出现在默认 `provider_order`
- 不把失败 warning 当成空结果静默吞掉

### 3.10 图片缓存与预热

以下在修改图片缓存、CDN 前置能力、列表/详情图片字段后执行。

查看单片图片缓存状态：

```bash
curl -s http://127.0.0.1:5004/api/v1/movies/<id>/images/status
```

预期：
- 返回 `poster/backdrop` 的 `cache_state`
- 返回 `source_info.provider/source_type/field/locked/evidence`
- 不触发远端图片下载
- 已缓存项包含缓存文件名、大小、更新时间和 `source_matches_current`
- 新写入缓存的 `cache.source_info` 是写入缓存时的来源快照

验证 CDN/public base URL 配置：

```bash
CYBER_IMAGE_ASSET_PUBLIC_BASE_URL=https://cdn.example.com .venv/bin/python -m backend.run
curl -s http://127.0.0.1:5004/api/v1/movies/<id> | jq '.data.poster_asset_url,.data.backdrop_asset_url'
```

预期：
- `poster_asset_url/backdrop_asset_url` 返回 `https://cdn.example.com/api/v1/movies/<id>/images/<kind>`
- 不配置该环境变量时仍返回 `/api/v1/movies/<id>/images/<kind>`
- 直接访问后端图片接口仍可回源和落盘缓存

清理单片本地图片缓存：

```bash
curl -s -X DELETE http://127.0.0.1:5004/api/v1/movies/<id>/images/poster
```

预期：
- 只删除后端本地缓存文件和缓存元数据
- 返回 `status=cleared` 或 `status=missing`
- 返回 `before/after` 缓存状态，不修改 `cover/background_cover` 源 URL

小批量预热：

```bash
curl -s -X POST http://127.0.0.1:5004/api/v1/images/preload \
  -H 'Content-Type: application/json' \
  -d '{"movie_ids":["<id>"],"kinds":["poster","backdrop"],"refresh":false}'
```

预期：
- 返回逐项 `cached/stale/skipped/failed`
- 缺图片源返回 `skipped + missing_source`
- 远端失败且无旧缓存返回 `failed`

批量 CDN purge / refresh 编排：

```bash
curl -s -X POST http://127.0.0.1:5004/api/v1/images/refresh \
  -H 'Content-Type: application/json' \
  -d '{"movie_ids":["<id>"],"kinds":["poster"],"purge":true,"clear_cache":false,"preload":true,"refresh":true}'
```

预期：
- 默认 `noop` provider 不调用外部 CDN，只返回 `purge.urls`
- 返回逐项 `refreshed/planned/cleared/skipped/failed`
- `clear_cache=true` 时先清本地缓存，再按 `preload/refresh` 重新预热
- `summary.purge_status_counts` 与 `summary.preload_status_counts` 可用于维护页统计

验证 Super CDN 国内全线路非视频资产桶：

```bash
CYBER_CDN_PROVIDER=supercdn \
CYBER_SUPERCDN_ENABLED=true \
CYBER_SUPERCDN_URL=https://qwk.ccwu.cc \
CYBER_SUPERCDN_TOKEN=<token> \
CYBER_SUPERCDN_BUCKET=hd-wallpapers \
CYBER_SUPERCDN_BUCKET_ALLOWED_TYPES=image \
CYBER_SUPERCDN_ROUTE_PROFILE=china_all \
CYBER_SUPERCDN_AUTO_UPLOAD_IMAGES=true \
CYBER_SUPERCDN_AUTO_UPLOAD_SUBTITLES=false \
CYBER_SUPERCDN_SERVE_ASSET_URLS=true \
.venv/bin/python -m backend.run

curl -s -X POST http://127.0.0.1:5004/api/v1/images/refresh \
  -H 'Content-Type: application/json' \
  -d '{"movie_ids":["<id>"],"kinds":["poster"],"purge":false,"preload":true,"refresh":true}' \
  | jq '.data.items[0].after.asset_url,.data.items[0].after.cdn,.data.summary.cdn_status_counts'
```

预期：
- 当前正式海报层使用公网已有图片桶 `hd-wallpapers`
- 桶 `route_profile` 为 `china_all`
- 桶允许类型为 `image`，不包含 `video`
- 已上传图片的 `asset_url` 返回 `https://.../a/hd-wallpapers/images/...`
- 详情和状态接口返回 CDN -> 后端本地图片入口 -> 原始元数据 URL 的 fallback 链
- 视频播放接口 `/api/v1/resources/<id>/stream` 不发生变化

当前海报层配置不上传字幕；以后重新启用 `CYBER_SUPERCDN_AUTO_UPLOAD_SUBTITLES=true` 时再验证绑定字幕上传 Super CDN：

```bash
curl -s -X POST http://127.0.0.1:5004/api/v1/resources/<resource_id>/subtitles/upload \
  -F 'file=@/path/to/subtitle.srt' \
  | jq '.data.subtitle.url,.data.subtitle.web_player.url,.data.subtitle.cdn'
```

预期：
- `subtitle.url` 指向 Super CDN 原始字幕对象
- `subtitle.web_player.url` 指向 Super CDN WebVTT 对象
- `subtitle.cdn.route_profile=china_all`
- `sub/sup` 等不可转 WebVTT 格式只上传原文，`webvtt` 资产返回 `skipped`

### 3.11 剧集完整性诊断

以下在修改资源分组、季集编辑、复核工作台或剧集识别逻辑后执行。

```bash
curl -s http://127.0.0.1:5004/api/v1/movies/<id>/seasons \
  | jq '.data.items[].episode_diagnostics,.data.summary.episode_diagnostics'

curl -s http://127.0.0.1:5004/api/v1/movies/<id>/episode-diagnostics \
  | jq '.data.dry_run,.data.apply_endpoint,.data.apply_payload,.data.seasons[].suggestions'

curl -s "http://127.0.0.1:5004/api/v1/metadata/work-items?metadata_issue_code=missing_episode_numbers" \
  | jq '.data.items[].metadata_issues'
```

预期：
- 每个 season 返回 `episode_diagnostics.status`
- dry-run 接口返回 `dry_run=true`，并给出可确认后提交的 `apply_payload`
- `apply_payload.items` 只包含无冲突的补齐建议；解析结果与现有集号冲突时只出现在人工复核建议和 `warnings`
- 缺集返回 `missing_episode_numbers`
- 已登记但未播出的未来集不进入 `missing_episode_numbers`
- 重复集号返回 `duplicate_episode_numbers`
- 完整季内同集多版本片源返回 `alternate_episode_numbers`，且不进入 `duplicate_episode_numbers`
- 季内资源缺集号时返回 `episode_number_missing`
- `metadata_issue_code` 能按剧集诊断问题筛进元数据工作台
- 诊断与 dry-run 建议只读，不会修改资源、季元数据或扫描结果

### 3.12 资料库质量工作台入口

以下在修改元数据工作台、批量重识别或剧集复核队列后执行。

```bash
curl -s "http://127.0.0.1:5004/api/v1/metadata/quality-summary?sample_size=2" \
  | jq '.data.totals,.data.issues[:5],.data.actions'

curl -s -X POST http://127.0.0.1:5004/api/v1/metadata/re-scrape/plan \
  -H 'Content-Type: application/json' \
  -d '{"issue_codes":["fallback_pipeline_match","poster_missing","low_confidence_resources"],"limit":5}' \
  | jq '.data.dry_run,.data.summary,.data.apply_payload'

curl -s -X POST http://127.0.0.1:5004/api/v1/metadata/re-scrape/jobs \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"id":"<movie_id>"}]}' \
  | jq '.data.job.id,.data.job.type,.data.job.status'

curl -s http://127.0.0.1:5004/api/v1/jobs/<job_id> \
  | jq '.data.status,.data.progress,.data.result.summary'

curl -s "http://127.0.0.1:5004/api/v1/metadata/episode-review-items?page_size=5" \
  | jq '.data.summary,.data.items[].diagnostics_endpoint,.data.items[].apply_payload'

./scripts/backend_smoke_check.py --base-url http://127.0.0.1:5004 --min-storage-sources 1
```

预期：
- smoke check 返回 `OK metadata_review_workbench`，说明复核工作台分类、动作、质量汇总 issue/sample 契约可用
- smoke check 返回 `OK catalog_filters`，说明目录页筛选项字段和计数契约可用
- smoke check 返回 `OK catalog_movies`，说明普通影视库列表分页、可见性和样例条目关键字段可用
- smoke check 返回 `OK movie_detail`，说明影视详情页主信息、背景图资产、元数据操作/诊断字段可用
- smoke check 返回 `OK movie_resources`，说明资源面板 items/groups/summary 与播放源主资源 ID 契约可用
- smoke check 返回 `OK metadata_work_items_contract`，说明复核工作台列表分页与样例条目关键字段可用
- smoke check 返回 `OK metadata_reidentify_plan`，说明批量重识别 dry-run 计划和提交 payload 契约可用
- smoke check 返回 `OK episode_review`，说明剧集复核队列分页、summary 和样例条目关键字段可用
- smoke check 返回 `OK background_jobs`，说明后台任务列表和前端轮询入口可用
- 质量汇总返回 issue 计数、样例和建议动作
- 批量重识别计划返回 `dry_run=true`，且不修改影片元数据
- `re-scrape/plan.apply_payload` 可在用户确认后提交到 `POST /api/v1/metadata/re-scrape`
- `re-scrape/jobs` 返回 HTTP `202` 和 `metadata_re_scrape` job，可通过 `/jobs/<job_id>` 追踪结果
- 剧集复核队列返回每片的单片诊断入口和无冲突自动修复 payload

### 3.13 API token 鉴权回归

以下在修改 `backend/app/security.py`、`backend/config.py`、服务脚本或反代配置时执行。

未设置 `CYBER_API_TOKEN` 时：

```bash
curl -i http://127.0.0.1:5004/api/v1/storage/sources
```

预期不因鉴权返回 401/403。

设置 token 后：

```bash
curl -i http://127.0.0.1:5004/api/v1/storage/sources
curl -i http://127.0.0.1:5004/api/v1/storage/sources \
  -H "Authorization: Bearer $CYBER_API_TOKEN"
curl -i http://127.0.0.1:5004/api/v1/storage/sources \
  -H "X-Cyber-API-Token: $CYBER_API_TOKEN"
./scripts/backend_smoke_check.py --base-url http://127.0.0.1:5004 \
  --api-token "$CYBER_API_TOKEN" \
  --min-storage-sources 1
```

预期：
- 不带 token 返回 401
- 错误 token 返回 403
- Bearer token 和 `X-Cyber-API-Token` 均可访问管理类 API
- 带 `--api-token` 的 smoke check 全部返回 `OK`
- `/`、`/resources/<id>/stream`、影片 poster/backdrop 图片 GET 默认仍可公开读取

### 3.14 用户管理回归

以下在修改用户、权限、资源库可见性、历史或字幕样式时执行：

```bash
.venv/bin/python -m unittest tests.test_user_management
```

预期：
- `CYBER_USER_MANAGEMENT_ENABLED=false` 时不改变现有行为
- 开启后可通过 Cookie 会话登录；仅当 `CYBER_AUTH_ENABLED=true` 时，`CYBER_API_TOKEN` 可作为管理员后门
- `CYBER_AUTH_ENABLED=false` 时，即使环境中残留 `CYBER_API_TOKEN`，也不能绕过 Cookie 登录获得管理员权限
- 普通用户不能访问存储源、扫描、元数据修改、资源库管理等管理员接口
- 普通用户的资源库 allow/deny 规则会过滤列表、详情、资源和播放流
- 管理员可通过 `/api/v1/admin/users/<id>/visibility-preview` 预览目标用户可见资源库、可见影片数和样例影片
- 观看历史和字幕样式按用户隔离
- 不能禁用或降级最后一个启用管理员
- 管理员重置密码后目标用户旧会话失效；普通用户可自助修改密码
- 登录失败限流会返回 429，并写入审计日志；管理员可查询 `/api/v1/admin/audit-logs`

---

## 4. 存储源相关回归

以下在修改 provider、存储源接口、配置结构时必须执行。

### 4.1 存储源预览
使用一个已知可用的本地或 WebDAV 配置请求：

```bash
curl -s -X POST http://127.0.0.1:5004/api/v1/storage/preview \
  -H 'Content-Type: application/json' \
  -d '{"type":"local","config":{"root_path":"/tmp"},"target_path":"/"}'
```

预期：
- 返回目录项数组或空数组
- 不报 500

### 4.2 存储源新增/修改/删除
如有前端配合或测试数据环境，可做完整 CRUD 回归。

重点关注：
- `name`
- `type`
- `config`
- 删除时 `keep_metadata` 行为

---

## 5. 扫描相关回归

以下在修改扫描器、TMDB、路径解析逻辑时必须执行。

### 5.1 触发扫描

```bash
curl -i -X POST http://127.0.0.1:5004/api/v1/scan
```

预期：
- 返回 `202` 或成功受理状态
- 扫描状态变为 scanning
- 如果已有扫描任务在运行，应返回 `429`，不能并发启动第二个扫描

### 5.2 观察扫描状态变化

```bash
curl -s http://127.0.0.1:5004/api/v1/scan
```

预期：
- `status` / `phase` / `processed_items` 有合理变化

### 5.3 扫描结果抽查
检查：
- 新资源是否入库
- 标题是否异常
- 电影/剧集识别是否错乱
- 季集标签是否合理

### 5.4 资源治理检查

以下在修改扫描、资源入库、存储源删除或重复资源分组后执行。

```bash
curl -s "http://127.0.0.1:5004/api/v1/resources/governance-summary?sample_size=2" \
  | jq '.data.dry_run,.data.totals,.data.issues[:5],.data.actions'

curl -s "http://127.0.0.1:5004/api/v1/resources/governance-items?issue_code=duplicate_playback_resource&page_size=5" \
  | jq '.data.summary,.data.items[].resource_ids'

curl -s "http://127.0.0.1:5004/api/v1/resources/governance-summary?live_check=true&live_check_limit=20&sample_size=2" \
  | jq '.data.totals,.data.issues[] | select(.code=="invalid_path" or .code=="size_mismatch" or .code=="source_unavailable")'

curl -s -X POST http://127.0.0.1:5004/api/v1/resources/governance/plan \
  -H 'Content-Type: application/json' \
  -d '{"issue_codes":["duplicate_playback_resource","detached_source_resource"],"live_check":false,"limit":20}' \
  | jq '.data.summary,.data.returned_summary,.data.pagination,.data.apply_payload.items[:5]'

curl -s -X POST http://127.0.0.1:5004/api/v1/resources/governance/jobs \
  -H 'Content-Type: application/json' \
  -d '{"items":[]}' \
  | jq '.code,.msg'

curl -s -X POST http://127.0.0.1:5004/api/v1/resources/governance/live-check/jobs \
  -H 'Content-Type: application/json' \
  -d '{"live_check_limit":50,"issue_code":"invalid_path","page_size":10}' \
  | jq '.data.job.id,.data.job.status,.data.job.progress'

curl -s "http://127.0.0.1:5004/api/v1/jobs?type=resource_governance_live_check&limit=1" \
  | jq '.data.items[0].id,.data.items[0].persisted,.data.items[0].status'

curl -s -X POST http://127.0.0.1:5004/api/v1/jobs/prune \
  -H 'Content-Type: application/json' \
  -d '{"retention_days":30,"dry_run":true}' \
  | jq '.data.dry_run,.data.matched,.data.status_counts'
```

预期：
- smoke check 返回 `OK resource_governance_plan`，说明资源治理 dry-run 计划和提交 payload 契约可用
- smoke check 返回 `OK background_jobs_prune`，说明后台任务清理 dry-run 不删除记录且统计契约可用
- 接口返回 `dry_run=true`
- 默认调用不访问存储源，只返回数据库层治理问题和 `live_check_skipped`
- `live_check=true` 时只检查有限数量资源，不触发扫描、不删除资源、不修改数据库
- `plan` 只生成计划；安全跳过有播放历史、已绑定字幕、影片最后一个资源和重复资源主资源
- `plan` 传 `limit` 或 `page/page_size` 时，`apply_payload.items` 只包含当前返回范围内的可执行项
- `jobs` 必须 `confirm=true` 且 `items` 非空，未确认时返回 400
- 执行 job 时只删除资源索引，不删除实体文件，并在已删除项里返回 `restore_snapshot`
- `live-check/jobs` 是只读后台任务，适合较大 `live_check_limit` 的真实存储检查
- `/jobs` 返回 `persisted=true`，后端重启后仍可查询已持久化的维护任务
- 持久化结果会截断过长 `result.items`，并返回 `result_truncated/result_item_count/persisted_item_limit`
- `/jobs/prune` 只清理过期 `succeeded/failed`，`dry_run=true` 不删除任何记录
- 需要恢复资源索引时，先将清理 job 的 `result.items[].restore_snapshot` 提交到 `/resources/governance/restore/plan`，确认后再提交 `/resources/governance/restore/jobs`

---

## 6. 播放链路回归

以下在修改 `/resources/<id>/stream`、provider 流式读取、WebDAV 鉴权逻辑时必须执行。

### 6.1 获取某个资源详情
先从电影详情中拿一个 `resource.id`。

### 6.2 直接请求播放接口

```bash
curl -i "http://127.0.0.1:5004/api/v1/resources/<resource_id>/stream"
```

预期之一：
- 200 / 206 流式响应
- 或 302 跳转到上游播放地址
- 若 provider 返回本机、私网、链路本地、保留地址或非 HTTP(S) Location，应返回 `502`，不能把该 Location 透传给客户端
- 代理流的 `Content-Type` 应匹配资源扩展名，例如 `.mp4` 为 `video/mp4`、`.mkv` 为 `video/x-matroska`、`.ts/.m2ts` 为 `video/mp2t`

### 6.3 Range 请求验证

```bash
curl -i -H 'Range: bytes=0-1023' "http://127.0.0.1:5004/api/v1/resources/<resource_id>/stream"
```

预期：
- 返回 206
- 存在 `Content-Range`
- `Content-Type` 与直接请求保持一致

### 6.4 前端实际点播验证
如果有前端页面，应至少实际播放一次，确认：
- 能起播
- 不秒退
- 拖动进度条基本正常
- 如果资源有字幕，前端 HTML5 `<track>` 使用 `playback.subtitles.items[].web_player.url`，不要直接使用原始 `url`

### 6.5 字幕 WebVTT 转换验证

当资源存在 `srt/ass/ssa` 字幕时，抽样请求网页播放器字幕 URL：

```bash
curl -i "http://127.0.0.1:5004/api/v1/resources/<resource_id>/stream?subtitle_id=<subtitle_id>&format=vtt"
```

预期：
- 返回 200
- `Content-Type` 为 `text/vtt; charset=utf-8`
- 响应体以 `WEBVTT` 开头

### 6.6 在线字幕候选验证

当修改在线字幕搜索/下载/绑定时，抽样验证：
- `GET /api/v1/resources/<resource_id>/subtitles/online/search?keyword=<keyword>` 的候选中，`srt/ass/ssa/vtt` 文本字幕排在 `sub/sup` 位图字幕前
- 候选包含 `format_normalized` 和 `web_player`；`sub/sup` 应返回 `web_player.supported=false`
- 字幕大小默认不限制；显式配置大小上限后，超限下载应返回 413，不应伪装为远端下载 502
- 下载到 RAR 等后端不支持的压缩包时应返回 415，前端提示用户换一个候选

### 6.7 外部播放器播放清单验证

当修改播放矩阵、字幕 URL 或外部播放器契约时，抽样验证：

```bash
curl -s "http://127.0.0.1:5004/api/v1/resources/<resource_id>/external-playback"
curl -i "http://127.0.0.1:5004/api/v1/resources/<resource_id>/external-playback?format=m3u"
```

预期：
- JSON 返回 `stream.url`、`handoff.playlist_url` 和 `player_profiles`
- 资源有默认字幕时返回 `subtitles.default_url`
- `format=m3u` 返回 `Content-Type: audio/x-mpegurl; charset=utf-8`
- M3U 内容包含现有 `/stream` URL；有默认字幕时包含 `#EXTVLCOPT:sub-file=...`

---

## 7. 历史记录回归

以下在修改历史记录、播放心跳、设备字段时必须执行。

### 7.1 上报进度

```bash
curl -i -X POST http://127.0.0.1:5004/api/v1/user/history \
  -H 'Content-Type: application/json' \
  -d '{"resource_id":"<resource_id>","position_sec":120,"total_duration":3600,"device_id":"test-device","device_name":"Test Device"}'
```

预期：
- 返回成功 JSON

### 7.2 获取历史列表

```bash
curl -s http://127.0.0.1:5004/api/v1/user/history
```

预期：
- 能看到对应记录
- `device_name`、`progress` 字段正常
- smoke check 返回 `OK user_history`，说明历史条目不回传 `is_played`

---

## 8. 文档改动的最小验收

如果本次只修改文档或注释，至少检查：

- 文档路径是否正确
- 文档索引（如 README）是否同步更新
- 文档内容与当前实际行为一致
- OpenAPI release notes 是否同步标记版本状态
- 涉及 OpenAPI 或前端契约时，运行 `./scripts/backend_smoke_check.py --base-url http://127.0.0.1:5004 --openapi-module-json-check`

当前主干包含 pytest 自动化测试。后端代码改动至少运行直接相关测试；交付前建议运行：

```bash
.venv/bin/python -m pytest -q
```

2026-06-07 维护基线：`747 passed, 9 skipped, 16 subtests passed`。

---

## 9. 1.16.0 收口验收基线

截至 2026-04-25，`1.16.0` 已作为稳定联调基线收口，最后确认项：

- OpenAPI JSON 可解析校验通过
- OpenAPI path/method 与运行时路由对齐：`59/59`
- 全量 unittest：`126 tests OK`
- 本地健康检查 `GET http://127.0.0.1:5004/` 返回 `200`
- 小流量推荐接口 `GET /api/v1/recommendations?limit=1` 返回 `200`
- 资源库分页接口 `GET /api/v1/libraries/1/movies?page=1&page_size=1` 返回 `200`，包含 `pagination`
- Avatar 资源接口已验证可返回 `UHD Blu-ray Remux`、`HDR10`、`Dolby TrueHD 7.1 Atmos`、`HEVC` 等技术字段

该基线作为历史回归参考保留。当前主干版本为 `1.21.0`，发布前仍应优先执行本清单中的健康检查、OpenAPI 校验与全量 unittest。

---

## 10. 每次发布前建议人工确认的问题

1. 本地 5004 是否正常
2. 当前公网入口 `https://cyberstream.gameuniverse.top:40160` 是否正常
3. 扫描状态接口是否正常
4. 电影列表是否正常
5. 至少一个资源是否能播放
6. 本次修改涉及的文档是否同步更新

---

## 11. 当前已确认通过的基础项（接手阶段）

截至 2026-06-07，已确认：

- 服务可在本地 `5004` 启动
- `GET /` 本地访问正常
- `GET /` 公网访问正常：当前入口为 `https://cyberstream.gameuniverse.top:40160`
- 公网接口返回的后端生成 URL 应与实际入口 scheme 一致；当前入口统一返回 `https://...`
- nginx 将公网 `40160` HTTPS 映射到本机 `5004`
- `cyberstream-backend`、`nginx`、`cyberstream-alist`、`cyberstream-openlist`、`ddns-go` 均为 `active`
- `backend/run.py` 已兼容直接执行，不再因包导入路径报错

后续每次功能开发后，应在本文件中按需补充新的已验证项。
