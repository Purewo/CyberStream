# 赛博影视

赛博影视是一个基于 Flask 的影视媒体库后端项目，核心能力包括：

- 本地 / WebDAV / SMB / FTP / AList / OpenList 存储源挂载
- 影视资源扫描与入库
- 基于 TMDB 的元数据刮削
- 电影/剧集列表、筛选、详情接口
- 视频流播放
- 观看历史记录

## 速览
<img width="2017" height="1098" alt="2efe0139ddf88073488b548002db4977" src="https://github.com/user-attachments/assets/78e454c4-1845-4fb7-8de7-735d863192df" />

<img width="2017" height="1097" alt="adb91f776747a30502a18bc60580eb42" src="https://github.com/user-attachments/assets/65c2cf4f-9d15-4f8e-8513-1d44d90c653e" />

<img width="2021" height="1101" alt="b3b5985a1a9c7d49b5093586a0779884" src="https://github.com/user-attachments/assets/aa1a5904-62c2-4901-b4f6-8d23c3f387b7" />

<img width="2011" height="1100" alt="106362f2d287782cfe941f88ea932290" src="https://github.com/user-attachments/assets/5ba7eee8-cc9d-4fc7-82c9-7555a0ba6609" />

## 当前状态

当前仓库为已接手维护版本，已确认本地可运行。当前 `main` 即最新版主干，暂不再维护长期开发分支。

- 项目目录：`/home/pureworld/赛博影视`
- 当前统一版本：`1.17.0`
- 本地调试端口：`5004`
- 公网调试入口：`http://pw.pioneer.fan:84`
- 公网 HTTPS 入口：`https://pw.pioneer.fan:84`

### 1.17.0 当前主干

当前主干已在 `1.16.0` 稳定基线之上继续补强以下能力：

- 首页门户聚合与首页配置
- 逻辑资源库、挂载点绑定、手动 include/exclude 规则
- 公开影视库过滤，默认隐藏 raw/占位/缺海报待处理影片
- 影视列表与资源库列表分页、排序、质量标签
- 资源详情技术信息结构化，覆盖 `REMUX`、`4K`、`HDR10`、`Dolby Atmos`、`HEVC`、`UHD Blu-ray Remux`、`Dolby TrueHD 7.1 Atmos`
- 资源播放能力矩阵、外部播放器链接、音频转码入口与诊断信息
- 影片资源播放源分组，支持同名同大小副本折叠为备用播放源
- 全局、资源库级和单片上下文推荐，并返回可解释推荐理由
- 元数据工作台失败分类、候选解释和批量重识别反馈
- 存储源目录预览、已保存来源浏览、扫描入口与播放链路
- 观看历史保留，但列表/详情不再返回 `is_played` 给前端展示“已观看”标签
- OpenAPI `1.17.0-beta` 与运行时路由对齐

## 快速启动

推荐启动方式：

```bash
cd /home/pureworld/赛博影视
/home/pureworld/赛博影视/.venv/bin/python -m backend.run
```

当前也兼容直接执行：

```bash
/home/pureworld/赛博影视/.venv/bin/python backend/run.py
```

后台启动示例：

```bash
nohup /home/pureworld/赛博影视/.venv/bin/python -m backend.run > /home/pureworld/赛博影视/backend_server.log 2>&1 &
```

## 文档索引

- `docs/PROJECT_HANDOVER.md`：项目接手说明
- `docs/ARCHITECTURE.md`：架构与模块说明
- `docs/API_OVERVIEW.md`：主要接口概览
- `docs/RUNBOOK.md`：运行、排障、联调说明
- `docs/CONFIG_REFERENCE.md`：配置项与历史残留说明
- `docs/TEST_CHECKLIST.md`：测试与回归验收清单
- `docs/VERSIONING.md`：版本管理规范
- `docs/STORAGE_CONFIG_FLOW.md`：存储源配置流说明
- `docs/MAINTENANCE_TODO.md`：正式维护优先级清单
- `backend/openapi/openapi-1.17.0-beta/release-notes-1.17.0-beta.md`：当前 OpenAPI 联调基线更新说明

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
