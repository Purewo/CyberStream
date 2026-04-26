# 资源库（Library）设计草案 v1

> 目标：在当前“多存储源（StorageSource）”基础上，引入面向用户的“资源库（Library）”概念，支持多个物理来源统一归组、按库管理、按库扫描、按库展示，为后续接入更多来源（SMB / WebDAV / Local / AList 等）打基础。

---

## 1. 为什么现在要引入 Library

当前项目已经具备：

- `StorageSource`：表示物理存储来源
- `MediaResource.source_id`：资源可追踪来源
- 按存储源管理、预览、扫描、播放的主链路

但还缺少一个更上层、面向前端和业务的逻辑抽象：

- 电影库
- 剧集库
- 动漫库
- 纪录片库
- 儿童库

也就是说，当前更像“多来源接入系统”，还不是完整的“多资源库系统”。

### 当前问题

1. 前端无法自然表达“进入某个库浏览内容”
2. 不同来源难以组合成一个逻辑资源库
3. 后续支持更多 provider 后，来源会越来越多，缺少上层归组会让展示与管理变乱
4. 扫描策略、刮削策略、展示策略目前没地方做库级配置

---

## 2. 核心概念拆分

建议把现有概念明确拆为两层：

### 2.1 StorageSource（物理来源）
表示物理或协议层的数据来源，例如：

- 本地目录（local）
- WebDAV
- SMB
- 后续可扩展：AList / S3 / 115 / CloudDrive

特点：
- 决定怎么连
- 决定怎么列目录
- 决定怎么播放
- 配置偏技术/协议层

### 2.2 Library（逻辑资源库）
表示用户视角下的内容集合，例如：

- 电影库
- 剧集库
- 动漫库
- 纪录片库

特点：
- 决定展示给谁看
- 决定按什么类型组织
- 决定默认扫描哪些来源/路径
- 可附带内容类型、排序策略、刮削策略、封面策略等业务配置

---

## 3. 推荐数据模型

### 3.1 新增 `Library`

建议新增表：`libraries`

核心字段建议：

- `id`
- `name`：库名称，如“电影库”
- `slug`：稳定标识，如 `movies` / `tv` / `anime`
- `description`：说明
- `is_enabled`：是否启用
- `sort_order`：前端展示顺序
- `settings`（JSON）：库级配置扩展位
- `created_at`
- `updated_at`

`settings` 可先预留，后续用于：
- 默认排序方式
- 是否开启推荐
- 刮削偏好
- 封面策略
- 是否显示在首页

### 3.2 新增 `library_sources`

建议新增关联表：`library_sources`

原因：
- 一个 Library 可能绑定多个 StorageSource
- 一个 StorageSource 理论上也可能被多个 Library 复用（虽然业务上未必常用）

推荐字段：
- `id`
- `library_id`
- `source_id`
- `root_path`（可选，库内相对根）
- `content_type`（可选，覆盖库默认类型）
- `scrape_enabled`
- `scan_order`
- `is_enabled`
- `created_at`

这里的 `root_path` 很重要：
- `StorageSource.config.root` / `root_path` 表示来源本身的技术根
- `library_sources.root_path` 表示“该来源在某个库里从哪里开始扫”

这样一个 WebDAV 来源可以很灵活地分配：
- `/影视/电影` -> 电影库
- `/影视/剧集` -> 剧集库

而不用重复建多个几乎一样的 StorageSource。

### 3.3 `Movie` 是否直接挂 `library_id`

建议：**第一阶段先不要强制加。**

原因：
- 当前扫描链路已稳定，先避免重改核心入库链路
- 初期可以通过 `MediaResource -> source_id -> library_sources -> library` 反推所属库
- 等后续业务确定后，再考虑给 `Movie` 增加主库归属字段或多库关系

如果后期需要：
- 可新增 `primary_library_id`
- 或设计 `movie_libraries` 多对多关系

当前维护版已补充第一阶段覆盖规则：
- `library_movie_memberships` 保存资源库与影视条目的显式关系
- `include` 用于把已入库影视手动加入资源库
- `exclude` 用于把自动路径命中的影视从某个资源库排除
- 最终资源库内容为 `(挂载路径自动命中 ∪ 手动 include) - 手动 exclude`
- 挂载路径自动命中只纳入无需人工处理且有海报的公开影视，raw/占位/缺海报影片必须手动 `include`
- 该规则不改变播放链路，也不把 `Movie` 强制绑定到单一资源库

---

## 4. 推荐关系结构

第一阶段推荐这样理解：

```text
Library
  -> library_sources
    -> StorageSource
      -> MediaResource
        -> Movie
```

其中：
- `StorageSource` 是技术连接层
- `Library` 是业务组织层
- `MediaResource` 是文件实体
- `Movie` 是内容实体

---

## 5. 接口设计建议

建议分两批做。

### 5.1 第一批：只做库管理与展示，不先重改扫描器

#### Library 管理
- `GET /api/v1/libraries`
- `POST /api/v1/libraries`
- `PATCH /api/v1/libraries/<id>`
- `DELETE /api/v1/libraries/<id>`

#### Library 绑定来源
- `GET /api/v1/libraries/<id>/sources`
- `POST /api/v1/libraries/<id>/sources`
- `PATCH /api/v1/libraries/<id>/sources/<binding_id>`
- `DELETE /api/v1/libraries/<id>/sources/<binding_id>`

#### 面向前端浏览
- `GET /api/v1/libraries/<id>/movies`
- `GET /api/v1/libraries/<id>/featured`
- `GET /api/v1/libraries/<id>/recommendations`
- `GET /api/v1/libraries/<id>/filters`

#### Library 手动影视规则
- `GET /api/v1/libraries/<id>/movie-memberships`
- `POST /api/v1/libraries/<id>/movie-memberships`
- `POST /api/v1/libraries/<id>/movie-memberships/delete`

这个阶段先做到：
- 可以建资源库
- 可以把来源归到库里
- 可以把单个已入库影视手动加入/排除某个资源库
- 前端可以按库浏览

### 5.2 第二批：再做库级扫描

建议新增：
- `GET /api/v1/libraries/<id>/scan`
- `POST /api/v1/libraries/<id>/scan`

行为：
- 扫描该库绑定的所有有效来源/子路径
- 可按 `scan_order` 顺序执行
- 逐一调用现有 source 扫描能力或抽出新的扫描入口

---

## 6. 扫描策略建议

### 第一阶段
先保持当前扫描主逻辑稳定：

- 全量扫描：仍支持 `/api/v1/scan`
- 指定来源扫描：仍支持 `/api/v1/storage/sources/<id>/scan`

新增 Library 后：
- Library 主要先用于组织和展示
- 不马上重写 scanner 主流程

### 第二阶段
再逐步过渡为：
- 可以按库扫描
- 可以按库配置刮削策略
- 可以按库定义默认内容类型（movie/tv）

这样风险最低。

---

## 7. 前端展示建议

当引入 Library 后，前端可形成更自然的结构：

### 首页层级
- 电影库
- 剧集库
- 动漫库
- 纪录片库

### 进入某个库后
展示：
- 轮播内容
- 推荐内容
- 筛选项
- 列表内容

### 前端收益
1. 用户认知更清晰
2. 不需要直接理解 WebDAV / SMB / local
3. 更方便做首页分区
4. 更方便后续做多库权限、排序、主题展示

---

## 8. 与当前架构的兼容策略

### 8.1 不替换 StorageSource
Library 不是替代 StorageSource，而是建在其上层。

### 8.2 不急着改播放链路
播放仍然走：
- `MediaResource -> source -> provider`

这条链路现在稳定，不建议因为引入 Library 而改动。

### 8.3 不急着改 Movie 主表结构
初期先避免给 `Movie` 强绑定 `library_id`，降低迁移风险。

### 8.4 兼容现有前端
即便新增 Library，也可以保留当前全局接口：
- `/movies`
- `/featured`
- `/recommendations`

后续再逐渐补库级接口。

---

## 9. 推荐实施顺序

### Phase 1：文档与模型设计（当前阶段）
- 明确概念边界
- 确认表结构
- 确认接口草案

### Phase 2：新增库管理模型与基础 API
- 新增 `Library`
- 新增 `library_sources`
- 完成 CRUD 与绑定关系 API

### Phase 3：前端按库浏览
- 新增按库列表/筛选/推荐接口
- 前端增加库切换入口

### Phase 4：库级扫描与策略
- 按库扫描
- 按库刮削
- 按库内容规则

---

## 10. 当前建议结论

如果你的目标是“支持很多数据来源，并让系统长期可扩展”，那么：

### 最推荐的方向是
- **保留 `StorageSource` 作为物理来源层**
- **新增 `Library` 作为逻辑资源库层**

而不是继续让前端直接围绕 `StorageSource` 工作。

这是因为：
- `StorageSource` 更像技术细节
- `Library` 才是用户真正感知的产品概念

---

## 11. v1 最小落地建议

如果只做最小可用版本，建议先实现：

1. `libraries` 表
2. `library_sources` 表
3. `GET/POST/PATCH/DELETE /api/v1/libraries`
4. `GET/POST/DELETE /api/v1/libraries/<id>/sources`
5. `GET /api/v1/libraries/<id>/movies`

先把“库”的壳搭起来，再逐步接扫描与推荐。

---

## 12. 当前版本备注

本设计草案形成时，项目当前统一版本为：`1.16.0`
