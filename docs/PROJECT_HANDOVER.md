# 项目接手说明

## 1. 项目定位

赛博影视是一个私有影视媒体库后端，目标是对接本地或远程影视资源目录，完成扫描、刮削、入库、检索与播放。

它更接近轻量级的家庭影视库后端，而不是视频网站后端。

## 2. 本次接手结论

已确认：

- 项目代码可运行
- 本地 `5004` 端口可正常启动服务
- 公网 `http://pw.pioneer.fan:84` 与 `https://pw.pioneer.fan:84` 可访问健康检查接口
- 已完成原项目目录备份，避免误改后无法回滚

## 3. 当前运行事实

- 启动方式必须使用模块方式：`python -m backend.run`
- 默认监听端口：`5004`
- 当前数据库：项目根目录下 `cyber_library.db`
- 当前日志：项目根目录下 `backend_server.log`
- Lucky 已用于将公网 `84` 端口映射到本机 `5004`
- 当前统一版本：`1.17.0`（以 `backend/config.py` 的 `APP_VERSION` 为单一版本源）

## 4. 已知风险

### 4.1 历史包袱
项目中同时存在：

- 旧的全局单存储配置思路（`config.py` 中的 `STORAGE_MODE` 等）
- 新的多存储源数据库驱动思路（`StorageSource` + `provider_factory`）

后续修改时需避免误以为所有配置都只走一套逻辑。

### 4.2 敏感配置明文存在
`backend/config.py` 中包含：

- WebDAV 凭证
- TMDB Token

后续应逐步迁移到环境变量或单独配置机制。

### 4.3 历史版本管理曾不一致
该问题已完成收口，当前根路由健康检查返回版本与 `backend/config.py` 中的 `APP_VERSION` 保持一致，当前为 `1.17.0`。

## 5. 维护原则

1. 先保证现有能力不退化
2. 优先补文档、启动说明、配置说明
3. 优先修复低风险高收益问题
4. 涉及扫描器、播放链路、存储源抽象的改动必须小步推进
5. 每次修改后做本地验收，再做公网验收

## 5.1 当前主干基线

截至 2026-04-27，`1.17.0` 已作为当前 `main` 主干联调基线。`1.16.0` 保留为历史稳定标签。

已确认的稳定能力：

- 首页门户聚合与首页配置
- 逻辑资源库、挂载点绑定、手动 include/exclude 规则
- 公开影视库过滤、分页、排序、影片级质量标签
- 资源详情技术信息结构化，覆盖 `UHD Blu-ray Remux`、`HDR10`、`Dolby TrueHD 7.1 Atmos` 等展示字段
- 播放能力矩阵、实时音频转码入口、诊断接口和备用播放源分组
- 推荐观看接口，包含全局推荐、库级推荐和单片上下文推荐理由
- 元数据工作台解释型字段、失败分类和批量重识别反馈
- 存储源目录预览、已保存来源浏览、扫描与播放链路
- 观看历史保留，但不再返回 `is_played` 给前端展示“已观看”标签
- OpenAPI `1.17.0-beta` 与运行时路由对齐

当前项目暂按单主干维护，后续小步提交直接进入 `main`。

## 6. 回滚参考

- 当前工作目录：`/home/pureworld/赛博影视`

## 7. 接手后基础文档

当前已补齐的基础维护文档：

- `README.md`
- `docs/PROJECT_HANDOVER.md`
- `docs/ARCHITECTURE.md`
- `docs/API_OVERVIEW.md`
- `docs/RUNBOOK.md`
- `docs/CONFIG_REFERENCE.md`
- `docs/TEST_CHECKLIST.md`
- `docs/VERSIONING.md`
- `docs/STORAGE_CONFIG_FLOW.md`
- `docs/MAINTENANCE_TODO.md`

## 8. 2026-04-03 最新进展（便于次日续接）

### 8.1 配置与运行
- `backend/config.py` 已完成第一轮配置收口：支持“环境变量优先、默认值回退”的兼容模式。
- 已同步更新 `docs/CONFIG_REFERENCE.md`，明确环境变量支持与历史单存储配置的兼容定位。
- 后端已重新启动并验证本地健康检查：`http://127.0.0.1:5004/` 返回正常。
- 当前统一版本已推进到 `1.17.0`。

### 8.2 日志规范第一轮
已为以下模块接入 `logging` 并替换一批 `print` / `traceback.print_exc()`：
- `backend/app/utils/common.py`
- `backend/app/services/tmdb.py`
- `backend/app/db/database.py`
- `backend/app/providers/local.py`
- `backend/app/providers/webdav.py`
- `backend/app/api/routes.py`
- `backend/app/services/scanner.py`

### 8.3 API 层去业务化与路由拆分
已新增 helper / route 模块：
- `backend/app/api/helpers.py`
- `backend/app/api/library_helpers.py`
- `backend/app/api/library_routes.py`
- `backend/app/api/history_routes.py`
- `backend/app/api/storage_routes.py`

`backend/app/__init__.py` 已注册：
- `library_bp`
- `history_bp`
- `storage_bp`

当前旧 `backend/app/api/routes.py` 已主要收缩为：
- `system`
- `player`
- 旧兼容接口 `/movies/recommend`

已迁出的领域：
- `library`
- `history`
- `storage`

### 8.4 下一步推荐顺序
1. 继续拆 `system_routes.py`
2. 谨慎拆 `player_routes.py`
3. 再继续代码规范化与新增功能开发
