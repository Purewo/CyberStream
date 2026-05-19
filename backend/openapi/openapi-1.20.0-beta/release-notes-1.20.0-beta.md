# 1.20.0-beta 更新说明

本文档记录 `1.20.0-beta` 的接口变化，作为 `main` 主干上的用户管理联调基线。

## 用户管理

本版新增可选用户管理，默认关闭，不影响现有站点使用。

新增配置：

- `CYBER_USER_MANAGEMENT_ENABLED=false`
- `CYBER_SESSION_SECRET`
- `CYBER_BOOTSTRAP_ADMIN_USERNAME`
- `CYBER_BOOTSTRAP_ADMIN_PASSWORD`
- `CYBER_SESSION_COOKIE_SECURE`
- `CYBER_SESSION_DAYS`
- `CYBER_LOGIN_RATE_LIMIT_ENABLED`
- `CYBER_LOGIN_RATE_LIMIT_MAX_ATTEMPTS`
- `CYBER_LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `CYBER_LOGIN_RATE_LIMIT_LOCK_SECONDS`

启用后：

- 网页端通过 `POST /api/v1/auth/login` 登录，后端写入 HttpOnly session cookie。
- `CYBER_API_TOKEN` 继续作为管理员后门。
- 用户角色分为 `admin` 和 `user`。
- 管理员拥有全部权限。
- 普通用户只能读取可见影视、播放、维护自己的观看历史和字幕样式。
- 普通用户可见性由资源库规则控制；默认可见全部公开影视，`allow` 规则收窄范围，`deny` 规则优先排除。
- 系统阻止禁用或降级最后一个启用管理员。
- 密码、角色、启用状态变更会递增 `session_version`，旧会话自动失效。
- 登录失败有进程内限流，登录失败、限流和管理员操作会写入审计日志。

新增接口：

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/user/profile`
- `PATCH /api/v1/user/profile`
- `POST /api/v1/user/password`
- `GET /api/v1/admin/users`
- `POST /api/v1/admin/users`
- `GET /api/v1/admin/users/{user_id}`
- `PATCH /api/v1/admin/users/{user_id}`
- `POST /api/v1/admin/users/{user_id}/password`
- `PUT /api/v1/admin/users/{user_id}/library-rules`
- `GET /api/v1/admin/users/{user_id}/visibility-preview`
- `GET /api/v1/admin/audit-logs`

## 审查工作台边界

新增只读接口：

- `GET /api/v1/metadata/review-taxonomy`

用途：

- 返回普通影视库、元数据审查、剧集审查、资源治理和目录发布控制的边界定义。
- 返回 `issue_code` 到列表入口、详情入口、推荐动作和批量 dry-run 动作的稳定映射。
- 前端应使用该接口作为审查工作台字典，不再按 `scraper_source` 自行推断问题标签和按钮。
- `metadata_source_group` 文档补齐 `bangumi`，`metadata_review_priority=none` 现在包含 `BANGUMI`。

配套文档：

- `docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md`

## 个人数据隔离

用户管理开启后：

- `history.user_id` 用于隔离观看历史和播放进度。
- 新增用户级字幕样式设置，优先级为：用户设置 > 资源级设置 > 默认设置。
- 关闭用户管理时继续使用原有全局历史和资源级字幕样式。

## 兼容性

- 默认关闭用户管理，因此 `1.19.0` 现有前端和公网访问不需要立即改造。
- 用户管理开启后，媒体流、图片、字幕、外部播放 manifest 和音频转码都会按登录用户可见性校验，不能通过直连资源 URL 绕过限制。
- OpenAPI `1.20.0-beta` 与运行时路由对齐。
