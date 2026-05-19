# 赛博影视

赛博影视是一个基于 Flask 的影视媒体库后端项目，核心能力包括：

- 本地 / WebDAV / SMB / FTP / AList / OpenList 存储源挂载
- 影视资源扫描与入库
- 基于 NFO / TMDB / Bangumi / Local fallback 的元数据刮削
- 电影/剧集列表、筛选、详情接口
- 视频流播放
- 观看历史记录

## 当前状态

当前仓库为已接手维护版本，已确认本地可运行。当前 `main` 即最新版主干，暂不再维护长期开发分支。

- 项目目录：`/home/pureworld/赛博影视`
- 当前统一版本：`1.21.0`
- 本地调试端口：`5004`
- 公网入口：`https://pw.pioneer.fan:84`

### 1.21.0 当前主干

当前主干已在 `1.16.0` 稳定基线之上继续补强以下能力：

- 首页门户聚合与首页配置
- 逻辑资源库、挂载点绑定、手动 include/exclude 规则
- 公开影视库过滤，默认隐藏 raw/占位/缺海报待处理影片
- 影视列表与资源库列表分页、排序、质量标签
- 资源详情技术信息结构化，覆盖 `REMUX`、`4K`、`HDR10`、`Dolby Atmos`、`HEVC`、`UHD Blu-ray Remux`、`Dolby TrueHD 7.1 Atmos`
- 资源播放能力矩阵、外部播放器链接、音频转码入口与诊断信息
- PC/外部播放器 handoff manifest 与 M3U 播放列表，不改变现有 stream 主链路
- 同目录外挂字幕发现，播放矩阵返回真实 `playback.subtitles.items` 和外部播放器字幕 URL
- 在线字幕搜索/下载接口接入 `subhd` 与 `srtku`，暂不接入 `opensubtitles`
- 单 token API 鉴权、SQLite 备份/恢复脚本和 gunicorn 优先的后端服务脚本已接入
- 可选用户管理已接入，默认关闭；开启后支持管理员/普通用户、Cookie 会话、用户资源库可见性限制、个人观看历史、个人字幕样式、登录限流、session 失效和审计日志
- TMDB token、Super CDN token、API token 等敏感配置通过 `.env.local` 或环境变量注入
- 图片缓存状态、来源追踪、批量预热、单片清理、CDN public base URL 与 purge/refresh 编排，作为后续 CDN 接入前置能力
- 元数据 provider 抽象已接入 `nfo/tmdb/bangumi/local`，Bangumi 面向动画候选搜索、扫描刮削和手动匹配
- 动漫库可显式配置 `provider_order: ["nfo", "bangumi", "tmdb", "local"]`，默认仍保持 `nfo -> tmdb -> local`
- 影片资源播放源分组，支持同名同大小副本折叠为备用播放源
- 全局、资源库级和单片上下文推荐，并返回可解释推荐理由
- 元数据工作台失败分类、候选解释和批量重识别反馈
- 元数据工作台 `metadata_issue_code` 按条目实际 `metadata_issues[].code` 精确筛选
- 审查工作台边界字典已接入，前端可通过 `/api/v1/metadata/review-taxonomy` 区分元数据审查、剧集审查、资源治理和目录发布
- 新增其他视频归档接口：`/api/v1/other-videos`、`/api/v1/movies/manual`、`/api/v1/movies/{movie_id}/resources/attach`
- 存储源目录预览、已保存来源浏览、扫描入口与播放链路
- 观看历史保留，但列表/详情不再返回 `is_played` 给前端展示“已观看”标签
- OpenAPI `1.21.0-beta` 与运行时路由对齐

## 快速启动

推荐启动方式：

```bash
cd /home/pureworld/赛博影视
cp .env.local.example .env.local
# 填入 CYBER_SUPERCDN_TOKEN、TMDB_TOKEN、CYBER_API_TOKEN 等本机私密配置后：
# 如需启用用户管理，再设置 CYBER_USER_MANAGEMENT_ENABLED、CYBER_SESSION_SECRET 和初始管理员账号。
./scripts/backend_service.sh start
```

常用服务命令：

```bash
./scripts/backend_service.sh status
./scripts/backend_service.sh restart
./scripts/backend_service.sh stop
```

开发调试时也可以前台启动：

```bash
/home/pureworld/赛博影视/.venv/bin/python -m backend.run
```

服务脚本会自动加载 `.env.local`。默认优先使用 `.venv/bin/gunicorn`，缺失时回退 Flask 内置服务器。

## 文档索引

- `docs/PROJECT_HANDOVER.md`：项目接手说明
- `docs/ARCHITECTURE.md`：架构与模块说明
- `docs/API_OVERVIEW.md`：主要接口概览
- `docs/FRONTEND_REVIEW_WORKBENCH_INTEGRATION.md`：审查工作台和非标准资源前端对接指南
- `docs/FRONTEND_USER_MANAGEMENT_INTEGRATION.md`：用户管理前端平滑接入指南
- `docs/RUNBOOK.md`：运行、排障、联调说明
- `docs/CONFIG_REFERENCE.md`：配置项与历史残留说明
- `docs/TEST_CHECKLIST.md`：测试与回归验收清单
- `docs/VERSIONING.md`：版本管理规范
- `docs/STORAGE_CONFIG_FLOW.md`：存储源配置流说明
- `docs/MAINTENANCE_TODO.md`：正式维护优先级清单
- `backend/openapi/openapi-1.21.0-beta/release-notes-1.21.0-beta.md`：当前 OpenAPI 联调基线更新说明

## 技术栈

- Python 3.10
- Flask
- Flask-SQLAlchemy
- SQLite
- requests
- webdavclient3

## 存储协议支持

当前真正已实现并接入主流程的协议：

- `local`
- `webdav`
- `smb`
- `ftp`
- `alist`
- `openlist`
