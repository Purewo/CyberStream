# 架构说明

## 1. 总体结构

```text
backend/
├── app/
│   ├── api/         # HTTP 路由
│   ├── db/          # 数据库适配层
│   ├── metadata/    # 元数据解析与刮削管线
│   ├── providers/   # 存储协议抽象与实现
│   ├── services/    # 扫描、TMDB 等核心服务
│   ├── utils/       # 通用工具
│   ├── __init__.py  # Flask app 工厂
│   ├── extensions.py
│   └── models.py    # ORM 模型
├── config.py        # 配置
└── run.py           # 启动入口
```

## 2. 核心业务链路

### 2.1 存储源管理
- 由 `StorageSource` 模型保存存储源配置
- 由 `provider_factory` 根据类型实例化 provider
- 当前支持 `local`、`webdav`、`smb`、`ftp`、`alist`、`openlist`

### 2.2 扫描入库
1. 扫描器递归遍历目录
2. 过滤无效文件/目录
3. 进入元数据管线解析标题、年份、季、集
4. 按内容实体分组
5. 先走规范格式直刮，再走经验兜底刮削
6. 最后保留 AI 刮削预留层
7. 写入 `Movie` 与 `MediaResource`

### 2.3 播放链路
1. 前端按资源 ID 请求 `/resources/<id>/stream`
2. 后端查询资源与存储源
3. 根据 provider 获取流或重定向地址
4. 返回视频流、206 Range 响应，或 302 跳转

## 3. 模块说明

## 3.1 `app/models.py`
主要模型：

- `StorageSource`：存储源
- `Movie`：影视内容主实体
- `MediaResource`：资源文件实体
- `History`：观看历史

设计上：

- `Movie` 表示内容
- `MediaResource` 表示可播放文件

该拆分是合理的，也是后续扩展多版本资源的基础。

## 3.2 `app/api/routes.py`
该文件当前只保留旧兼容入口位置，新业务接口已按领域拆到：

- `library_routes.py`：影视库、筛选、推荐、详情、元数据工作台
- `libraries_routes.py`：逻辑资源库管理、来源绑定、按库浏览与扫描
- `storage_routes.py`：存储源管理、预览、浏览、指定来源扫描
- `history_routes.py`：观看历史
- `system_routes.py`：扫描状态与全局扫描触发
- `player_routes.py`：流媒体播放

## 3.3 `app/services/scanner.py`
项目最核心模块之一，负责：

- 遍历资源目录
- 调用元数据管线
- 合并实体
- 入库

当前已开始把“路径解析 + 刮削决策”逐步抽离到 `app/metadata/`，后续扫描器应继续收敛为编排层，而不是继续堆规则。

## 3.4 `app/metadata/`
当前新增的元数据管线层，目标是将刮削重塑为三层：

- `strict`
  - 面向规范命名结构的高置信解析与直刮
- `fallback`
  - 复用现有经验规则做兜底
- `ai`
  - 作为后续接入大模型识别的预留层

当前状态：
- `parser.py` 负责 strict/fallback 两层路径解析
- `scraper.py` 负责 structured/fallback/ai 三层刮削决策
- `pipeline.py` 对 scanner 暴露统一入口
- AI 层目前只预留，不启用
## 3.5 `app/providers/`
当前实现：

- `local.py`
- `webdav.py`
- `smb.py`
- `ftp.py`
- `alist.py`（同时承载 `openlist` 兼容模式）

其中 WebDAV 已支持：

- 列目录
- 流式读取
- Range 请求
- 某些场景下 302 跳转透传

AList / OpenList 当前默认返回带域名的 `/d/...` 播放入口，由前端直接使用。SMB / FTP 已完成 provider、配置校验、目录预览、扫描和播放链路接入，真实环境仍建议逐项联调。

## 3.6 `app/db/database.py`
数据库适配层，包含：

- 电影 upsert
- 文件去重
- 存储源删除
- 查询辅助逻辑

## 4. 当前工程判断

优点：

- 业务主链完整
- 存储抽象方向正确
- 扫描器有真实业务经验沉淀

不足：

- 历史配置残留较多
- 敏感信息管理不规范
- 历史文档仍可能有旧路径或旧阶段描述，需要持续收口
- 敏感配置仍需进一步外置化
