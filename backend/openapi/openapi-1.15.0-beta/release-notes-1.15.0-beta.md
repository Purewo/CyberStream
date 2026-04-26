# 1.15.0-beta 更新说明

本文档用于说明 `openapi-1.15.0-beta.json` 对应的本轮接口更新，供前后端联调时快速对照。

## 本轮重点

本轮重点不是继续堆更多存储协议，而是先把现有存储源能力规范化，给后续接入 SMB / FTP / SFTP / AList 预留稳定结构。

同时，元数据编辑链路现在开始补齐“前端可直接消费的来源语义”，避免前端只能靠 `scraper_source` 原始值硬编码 UI。

当前后端稳定支持的来源仍只有：
- `local`
- `webdav`

## 新增和补强的接口能力

- 新增 `GET /api/v1/storage/provider-types`
  - 返回后端当前真正支持的协议、显示名、能力标记、配置字段定义
  - 前端应基于该接口动态生成来源类型下拉和配置表单，不再硬编码
- 新增 `GET /api/v1/storage/sources/<id>`
  - 用于编辑页拉取单条来源详情
- 新增 `GET /api/v1/storage/sources/<id>/health`
  - 单独做实时连通性检查，不再把健康探测塞进列表接口
- `POST /api/v1/storage/sources`
- `PATCH /api/v1/storage/sources/<id>`
- `POST /api/v1/storage/preview`
  - 以上接口已接入统一的 `type/config` schema 校验

## 返回结构变化

存储源列表和详情现在都会返回以下补充字段：
- `display_name`
- `config_valid`
- `config_error`
- `capabilities`
- `config`
- `actions`
- `usage`
- `guards`

说明：
- `config` 为脱敏后的配置摘要，敏感字段如 `password` 只返回 `***`
- `actions` 供前端直接判断是否展示预览、扫描、播放入口
- `usage` 和 `guards` 供前端在编辑、删除、迁移前直接做判断

`GET /api/v1/storage/sources/<id>/health` 额外返回：
- `health.status`
- `health.reason`
- `health.message`

其中 `health.reason` 为机器可读原因，常见值包括：
- `ok`
- `dns_resolution_failed`
- `auth_failed`
- `permission_denied`
- `root_not_found`
- `timeout`

## 前端联调注意点

- 列表接口默认不做实时网络探测，实时状态请单独调用 `health`
- 当前 `PATCH` 更新 `config` 仍是整对象替换，前端提交时必须带完整配置
- `local.path` 作为历史别名仍兼容，但新表单应统一提交 `root_path`
- 已被资源或资源库绑定的来源，后端会禁止直接修改 `type`
- 仍有关联资源的来源，删除时必须显式传 `keep_metadata=true`

元数据编辑相关新增约定：
- 影片列表/详情新增 `metadata_state`
- 影片详情新增 `metadata_actions`、`metadata_diagnostics`
- 影片列表/详情新增问题语义：`metadata_issues`、`issue_count`、`primary_issue_code`
- 资源详情新增 `metadata_trace` 和 `metadata_edit_context`
- `metadata_state` 用于直接驱动 UI 徽标、提示色、操作引导
- `metadata_actions` 用于直接驱动按钮显隐和主 CTA
- `metadata_diagnostics` 用于直接驱动问题概览卡片
- `metadata_issues` 用于直接驱动问题清单、告警条和批量处理入口
- `metadata_edit_context` 用于资源编辑页区分“规范命中 / 经验兜底 / NFO / 本地占位”
- 资源分组 summary 新增 `needs_attention`、`review_priority`
- 新增 `POST /api/v1/movies/{id}/metadata/re-scrape`，支持单条影片定点重跑元数据管线
- 新增 `POST /api/v1/metadata/re-scrape`，支持元数据工作台批量定点重跑
- 新增 `POST /api/v1/movies/{id}/metadata/preview`，支持前端在不落库情况下预览识别结果
- `metadata/preview` 现在还会返回字段级 `diff`，前端可直接做“将更新 / 被锁定阻止”的确认 UI
- 影片列表支持 `metadata_source_group`、`metadata_review_priority`、`needs_attention` 筛选
- 影片列表/工作台列表额外支持 `metadata_issue_code` 筛选
- `GET /api/v1/filters` 默认返回 `metadata_source_groups`、`metadata_review_priorities`、`metadata_issue_codes`
- 新增 `GET /api/v1/metadata/overview`，用于元数据工作台总览统计
- `metadata/overview` 现在还包含问题类型聚合 `issues`
- 新增 `GET /api/v1/metadata/work-items`，用于元数据工作台列表
- 手动匹配和刷新支持 `media_type_hint=movie|tv`
- 手动匹配支持外部 ID：`imdb/<id>`、`tvdb/<id>`

## 联调基线

- OpenAPI：`backend/openapi/openapi-1.15.0-beta/openapi-1.15.0-beta.json`
- 接口概览：`docs/API_OVERVIEW.md`
