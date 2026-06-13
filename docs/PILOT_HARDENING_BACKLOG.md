# 托管试点加固清单

本文记录 CyberStream 从个人联调环境转向小范围托管试点时需要补齐的安全与运维工作。当前先启用强制账号登录和个人数据隔离，其余项目在首批试点运行后按反馈推进。

## 当前决策

- 公网后端必须启用 `CYBER_USER_MANAGEMENT_ENABLED=true`，匿名用户不能读取目录、播放资源或调用管理接口。
- 当前已有个人数据归属管理员账号 `pureworld`。
- 播放历史、收藏、成就、个人字幕设置和收藏保险库按账号隔离。
- 影视目录、资源索引和存储挂载仍由管理员统一维护；普通账号通过 library allow/deny 规则获得可见范围。
- 密码只以哈希形式保存在数据库，不在仓库、文档或 systemd 配置中保存明文。
- 当前本地联调前端与公网后端跨站访问，运行环境使用 `CYBER_SESSION_COOKIE_SAMESITE=None`、`CYBER_SESSION_COOKIE_SECURE=true`、`CYBER_CORS_SUPPORTS_CREDENTIALS=true`，并通过 `CYBER_CORS_ORIGINS` 限定允许 Origin。

## 试点后补齐

### P0

- 确认官方 Web 和 PC WebView 的最终实际 Origin，补充到 `CYBER_CORS_ORIGINS`，并移除不再使用的本地联调 Origin。
- 在创建首批普通用户时显式配置 library allow 规则，避免默认继承全部公开影视库。

### P1

- 为 SQLite 建立 systemd timer 定时备份，至少每日执行一次，并保留 7-30 天。
- 将备份同步到本机之外的对象存储或另一台服务器，定期执行恢复演练。
- 为外部播放器和 M3U 播放交接增加短期签名播放凭证，避免依赖浏览器 Cookie。
- 为 nginx 增加登录、聚合搜索、字幕搜索和播放入口的基础速率限制。
- 明确后台扫描和维护任务被进程重启中断后的状态标记与重试流程。

### P2

- 增加服务异常、数据库健康、存储挂载失效、扫描失败和磁盘空间不足告警。
- 增加 PC/Web 客户端最低兼容版本控制和后端 API 兼容窗口。
- 增加审计日志和维护任务记录的自动保留与清理策略。

## 试点发布检查

- 匿名请求访问 `/api/v1/movies`、`/api/v1/storage/sources` 和资源播放入口应返回 `401`。
- 管理员登录后能读取完整目录、播放资源和调用管理接口。
- 两个普通账号之间的历史、收藏、成就和个人字幕设置互不可见。
- 普通账号不能访问未授权 library 中的影片和资源直链。
- `CYBER_SESSION_COOKIE_SECURE=true`，登录 Cookie 仅通过 HTTPS 发送。
- 执行数据库备份并通过 `PRAGMA integrity_check`。
