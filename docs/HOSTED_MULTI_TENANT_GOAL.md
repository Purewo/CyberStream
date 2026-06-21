# CyberStream 代托管多租户目标文档（goal · v1）

> 版本基线：CyberStream 1.21.0-beta 代托管内测后端
> 决策框架：先完成“注册账号 -> 自助挂载 -> 扫描入库 -> 独立使用”的最小闭环，数据库和接口设计必须能继续扩展到正式托管版
> 日期：2026-06-14

---

## 1. 为什么做这次改造

当前代托管后端已经能给一个固定账号提供登录、片库、刮削、审查工作台、播放和云盘挂载能力，但它本质仍是“单租户 + 用户权限”的模型。小范围测试如果继续沿用这套结构，会遇到三个硬问题：

1. **数据隔离不成立**：不同测试用户的云盘、片库、影视条目、播放历史、收藏、字幕设置必须天然隔离，不能靠前端隐藏。
2. **用户无法自助接入**：新用户必须能注册后自己挂载云盘并启动扫描，否则每个测试用户都要人工配置，测试无法扩大。
3. **后期迁移成本会爆炸**：如果现在只在现有 `users.role` 上临时堆权限，未来再做托管商后台、家庭子账号、套餐、配额、审计时会很难拆。

这次目标不是做完整 SaaS 后台，而是把代托管的账号空间、数据库边界和自助挂载闭环打牢。

---

## 2. 已锁定决策

| 维度 | 决策 | 说明 |
|---|---|---|
| 隔离边界 | **Account/Tenant 是数据隔离边界** | `User` 只是登录身份，所有业务数据必须归属 `account_id`。 |
| 注册模式 | **开放注册** | 内测阶段不做邀请码、邮箱验证、验证码，后续再加注册门禁。 |
| 注册后权限 | **新用户默认成为自己账号的 owner** | owner 只能管理自己账号下的数据，不能修改其他账号，也不是平台超级管理员。 |
| 平台管理员 | **保留现有 `users.role=admin` 作为托管商/平台管理员语义** | 现阶段不做平台综合后台，但不要再把普通注册用户写成平台 admin。 |
| 现有数据归属 | **全部归入 `pureworld` 账号空间** | 当前内测已有数据是 `pureworld` 的私人片库，迁移后必须保持可用。 |
| 自助挂载范围 | **现有托管云盘能力全覆盖** | 光鸭、天翼云盘、115、阿里云盘、百度网盘、123 云盘、夸克 TV、UC TV 等现有 provider 都要纳入账号隔离。 |
| 默认初始化 | **新账号创建默认片库，并引导挂载** | 注册后不能是空白后端，至少要有默认片库和可继续挂载/扫描的状态。 |
| 数据库方向 | **正式代托管使用 PostgreSQL + Alembic/Flask-Migrate** | SQLite 继续服务开发/单人自托管，但代托管上线不能再依赖运行时 patch 表结构。 |
| 图片/CDN | **v1 不做 CDN 和跨账号图片去重** | 海报仍保存外部链接或原始链接，避免多个用户消耗我们的 CDN 流量。 |
| TMDB token | **平台级 token 池轮询** | token 池由后端统一配置，不暴露给普通用户，账号之间共享调用能力但不共享业务数据。 |

---

## 3. v1 必须完成

- [ ] 新增 Account/Tenant 数据模型，把账号空间作为业务数据的强隔离边界。
- [ ] 新增开放注册接口：注册成功自动创建 `User`、`Account`、`AccountMembership(owner)` 和默认片库。
- [ ] 重构权限语义：`users.role` 表示平台身份；账号内 owner/member 权限来自 membership。
- [ ] 所有片库、影视、资源、挂载、扫描、审查、播放历史、收藏、字幕设置等接口按当前账号隔离。
- [ ] 现有 `pureworld` 数据迁移到 `pureworld` account，迁移前后片库、资源、审查工作台和播放能力不丢。
- [ ] 代托管模式允许账号 owner 自助添加/认证云盘、绑定默认片库、启动自己账号的扫描。
- [ ] AList/OpenList 继续共用后端运行实例，但所有 mount path、storage id 关联、清理动作必须带账号边界。
- [ ] PostgreSQL 连接配置、迁移脚本和本地开发 SQLite 兼容路径都要明确。
- [ ] 新版 OpenAPI、release notes、前端接入文档、配置文档、运行文档必须随代码同步更新。
- [ ] 补齐隔离、注册、迁移、自助挂载、扫描、OpenAPI 合同测试。

---

## 4. v1 明确不做

| 项 | 暂不做原因 |
|---|---|
| 托管商综合后台 | 工程量大，后续单独做 platform admin 面板。 |
| 家庭子账号管理 | 账号 owner 创建子账号、儿童权限、家人共享等后续再做。 |
| 邀请码/邮箱验证/短信验证/验证码 | 小范围灰测先开放注册，后续根据滥用情况补。 |
| 套餐、配额、计费、设备数限制 | 商业化能力后置。 |
| 跨账号共享影视条目或海报资产 | v1 数据完全隔离，宁可重复存链接。 |
| CDN 上传和图片去重 | 目前关闭 CDN，避免流量成本不可控。 |
| 平台管理员跨账号代操作 UI | 后端数据结构预留，界面和操作流后续再做。 |
| 前端正式改造 | 本 goal 以后端和接口契约为主；前端只需要拿到清晰文档自行对接。 |

---

## 5. 核心模型设计

### 5.1 User / Account / Membership

新增 `accounts`：

| 字段 | 说明 |
|---|---|
| `id` | UUID 字符串主键，对外可暴露。 |
| `name` | 账号空间展示名，默认用用户名派生。 |
| `slug` | 可读短标识，账号内唯一显示用；不要作为安全边界。 |
| `status` | `active` / `disabled` / `pending_delete`。 |
| `settings` | JSON，保存默认片库、未来配额、偏好等账号级配置。 |
| `created_at` / `updated_at` | 时间戳。 |

新增 `account_memberships`：

| 字段 | 说明 |
|---|---|
| `id` | 自增主键。 |
| `account_id` | 归属账号。 |
| `user_id` | 登录用户。 |
| `role` | v1 只需要 `owner`，预留 `member`。 |
| `status` | `active` / `disabled`。 |
| `created_at` / `updated_at` | 时间戳。 |

唯一约束：

- `account_memberships(account_id, user_id)` 唯一。
- v1 注册用户默认只有一个 active membership。
- 后端内部仍要通过 `current_account` 上下文取账号，不能让客户端传任意 `account_id` 决定数据范围。

### 5.2 平台角色和账号角色

`users.role` 保留，但语义收窄：

| 字段值 | 新语义 |
|---|---|
| `admin` | 平台/托管商管理员。当前 `pureworld` 可继续是平台 admin，但默认操作自己的 account。 |
| `user` | 普通登录身份。注册用户都使用这个角色。 |

账号内权限来自 `account_memberships.role`：

| 账号角色 | v1 权限 |
|---|---|
| `owner` | 管理自己账号下片库、云盘挂载、扫描、审查、影视元数据、播放相关个人数据。 |
| `member` | 预留给家庭子账号，v1 不开放创建。 |

关键原则：

- 普通注册用户即使是自己账号 owner，也不能获得 `users.role=admin`。
- `admin` 不等于可以绕过所有账号隔离直接读写业务数据；v1 没有平台后台时，平台 admin 默认也只进入自己的 current account。
- 后续做平台后台时，再为平台 admin 增加显式的跨账号查询/代操作接口，并单独审计。

### 5.3 需要账号化的现有表

以下表必须增加或推导 `account_id`，并在查询和写入时强制过滤：

| 表 | 处理 |
|---|---|
| `storage_sources` | 增加 `account_id`；同一用户只能看到和操作自己账号的源。 |
| `libraries` | 增加 `account_id`；`name` / `slug` 唯一约束改为账号内唯一。 |
| `library_sources` | 通过 `library_id` 和 `source_id` 双重校验同账号；必要时冗余 `account_id` 方便过滤。 |
| `library_movie_memberships` | 通过 `library_id` / `movie_id` 校验同账号；唯一约束不得跨账号冲突。 |
| `homepage_settings` | 改为账号级首页配置，一个 account 一份。 |
| `movies` | 增加 `account_id`；`tmdb_id` 不能再全局唯一，允许不同账号有同一 TMDB 影片。 |
| `media_resources` | 增加 `account_id`；唯一约束调整为账号内/源内路径唯一。 |
| `movie_metadata_locks` | 跟随 movie 账号，写入时校验。 |
| `movie_season_metadata` | 跟随 movie 账号，写入时校验。 |
| `resource_subtitles` | 跟随 resource 账号，写入时校验。 |
| `resource_subtitle_settings` | 跟随 resource 账号，写入时校验。 |
| `user_subtitle_settings` | 增加 `account_id`；用户和资源都必须属于当前账号上下文。 |
| `history` | 增加 `account_id`；播放历史按账号 + 用户隔离。 |
| `user_favorites` | 增加 `account_id`；收藏按账号 + 用户隔离。 |
| `user_achievements` | 增加 `account_id`；成就按账号隔离，避免不同账号 scope_key 冲突。 |
| `user_vault_secrets` | 增加 `account_id`；保险箱数据不能跨账号。 |
| `user_library_rules` | 预留账号字段或通过 library 校验账号，后续家庭子账号用。 |
| `maintenance_jobs` | 增加 nullable `account_id`；扫描/刮削 job 必须绑定账号，平台 job 可为空。 |
| `audit_logs` | 增加 nullable `account_id`；登录可为空，账号内操作必须写 account。 |

唯一约束调整原则：

- 所有业务唯一性都要从“全局唯一”改成“账号内唯一”。
- `movies.tmdb_id` 当前全局唯一必须取消或改成 `account_id + tmdb_id` 唯一。
- `libraries.slug`、`libraries.name` 当前全局唯一必须改成账号内唯一。
- `media_resources(source_id, path)` 可保留源内唯一，但必须保证 source 本身属于当前 account；更稳妥是增加 `account_id, source_id, path` 唯一索引。

---

## 6. 请求上下文和权限设计

新增账号上下文加载逻辑：

1. 认证用户通过 session/API token 进入请求。
2. 后端查 active membership。
3. v1 如果只有一个 membership，自动设为 `current_account`。
4. 后续多账号时再支持显式切换 current account。
5. 所有账号内接口从 `current_account.id` 取范围，不信任客户端传入的 `account_id`。

`GET /api/v1/auth/me` 必须扩展返回：

```json
{
  "authenticated": true,
  "role": "user",
  "current_account": {
    "id": "uuid",
    "name": "pureworld",
    "slug": "pureworld",
    "status": "active"
  },
  "account_role": "owner",
  "permissions": {
    "admin": false,
    "read_catalog": true,
    "manage_catalog": true,
    "manage_storage": true,
    "manage_account_users": false,
    "manage_server_config": false,
    "personal_history": true,
    "personal_favorites": true,
    "personal_vault": true,
    "personal_subtitle_settings": true
  }
}
```

权限原则：

- `manage_server_config` 在代托管模式下继续为 false，普通用户不能改 TMDB token、代理、CDN、服务端运行配置。
- `manage_storage` 只允许账号 owner 管理自己账号下的托管云盘源。
- `manage_catalog` 只允许账号 owner 管理自己账号下片库、审查工作台、影视元数据和扫描。
- 旧 `/admin/users` 系列接口在 hosted v1 不作为账号 owner 的用户管理入口；家庭子账号后续另做账号级接口。

---

## 7. 注册与账号初始化

新增接口：

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "username": "new_user",
  "password": "password",
  "display_name": "optional"
}
```

行为要求：

- 校验用户名唯一、格式合法、密码最小长度。
- 创建 `users.role=user` 的普通用户。
- 创建同名或派生名称的 `accounts`。
- 创建 `account_memberships(role=owner, status=active)`。
- 创建默认片库，例如 `默认片库` / `default`。
- 初始化账号级首页设置。
- 注册成功后建议直接建立登录 session，并返回和 `/auth/me` 一致的状态结构。
- 注册失败必须返回稳定错误码，前端可区分用户名占用、密码不合法、注册关闭等情况。

配置项：

| 配置 | 默认 | 说明 |
|---|---|---|
| `CYBER_REGISTRATION_ENABLED` | hosted 内测 true | 是否允许开放注册。 |
| `CYBER_DEFAULT_ACCOUNT_LIBRARY_NAME` | `默认片库` | 新账号默认片库名称。 |
| `CYBER_DEFAULT_ACCOUNT_LIBRARY_SLUG` | `default` | 新账号默认片库 slug。 |

---

## 8. 自助挂载和扫描闭环

目标流程：

1. 用户注册并登录。
2. 后端返回 current account 和 owner 权限。
3. 前端展示云盘挂载入口。
4. 用户选择 provider 并完成扫码、短信、OAuth 或账号登录。
5. 后端在共享 AList/OpenList 实例内创建账号隔离的 storage/mount。
6. 后端创建当前 account 下的 `storage_sources`。
7. 后端将 storage source 绑定到默认片库，或返回可绑定的账号内片库列表。
8. 用户启动扫描。
9. 扫描、刮削、审查工作台只产生当前 account 下的数据。

挂载路径约定：

```text
/cyberstream/accounts/{account_id}/sources/{source_id}
```

要求：

- AList/OpenList 可以继续是平台共享进程，但 mount path 必须带 account 前缀。
- provider runtime storage id 必须记录在当前 account 的 source config 内。
- 删除 source 时只能删除对应 runtime storage，不能误删其他 account 的挂载。
- OAuth state、二维码 poll、短信验证等临时状态必须能映射回当前 account/source。
- 所有 provider 的 start/restart/poll/verify/complete 接口都必须做账号校验。
- 扫描 job 必须记录 `account_id`，异步执行时也不能丢失账号上下文。

provider 范围：

- `guangyapan`
- `tianyicloud`
- `115cloud`
- `aliyundrive`
- `baidunetdisk`
- `123pan`
- `quarktv`
- `uctv`

---

## 9. PostgreSQL 和迁移策略

### 9.1 配置

新增或标准化数据库配置优先级：

1. `CYBER_DATABASE_URL`
2. `DATABASE_URL`
3. 现有 SQLite `DB_PATH` fallback

示例：

```env
CYBER_DATABASE_URL=postgresql+psycopg://cyberstream:password@127.0.0.1:5432/cyberstream_hosted
```

### 9.2 迁移框架

- 引入 Alembic/Flask-Migrate，迁移文件纳入仓库。
- 停止为正式 hosted 数据库依赖 `backend/app/db/schema.py` 的运行时 SQLite patch。
- SQLite 仍可用于开发和单人自托管，但多租户迁移必须通过正式 migration 管理。
- 测试要覆盖 SQLite fallback 和 PostgreSQL URL 配置解析。

### 9.3 现有数据迁移

迁移脚本必须：

1. 创建 `pureworld` account。
2. 找到现有 `pureworld` 用户并加入 owner membership。
3. 如果 `pureworld` 用户不存在，明确失败，不静默创建错误归属。
4. 给所有现有业务数据补 `account_id=pureworld_account_id`。
5. 调整唯一索引前先检查冲突。
6. 迁移前备份 SQLite 数据库或要求运维完成备份。
7. 迁移后验证影视数量、资源数量、片库绑定数量、审查工作台数量一致。

迁移不可接受行为：

- 不能把现有数据分配给新注册用户。
- 不能把普通注册用户写成平台 `admin`。
- 不能为了迁移方便清空审查工作台、历史、收藏或字幕设置。

---

## 10. API 和前端契约

### 10.1 新增/变化接口

必须在 OpenAPI 中体现：

- `POST /api/v1/auth/register`
- `GET /api/v1/auth/me` 新增 `current_account`、`account_role`、`permissions.manage_storage`、`permissions.manage_account_users`
- `POST /api/v1/auth/login` 返回结构如有变化必须同步
- `POST /api/v1/auth/logout` 维持 cookie session 清理
- `GET /api/v1/storage/sources` 只返回当前账号 storage sources
- `POST /api/v1/storage/sources` 在 hosted 模式下允许账号 owner 创建账号内 source
- 所有 `/api/v1/storage/managed/**` 接口按账号上下文创建和校验 source
- `POST /api/v1/storage/sources/{id}/scan` 只扫描当前账号 source
- 片库、审查工作台、影视详情、元数据编辑、字幕、播放历史、收藏接口均按 current account 隔离

前端原则：

- 前端不需要也不应该在普通业务接口传 `account_id`。
- 前端启动、登录、注册、401 后都以 `/auth/me` 为准。
- 前端用 `permissions.manage_storage` 控制云盘挂载入口。
- 前端用 `permissions.manage_catalog` 控制片库、扫描、审查、元数据编辑入口。
- 前端不要把 `users.role=user` 理解成“没有管理自己片库的权限”；账号 owner 权限看 `account_role` 和 permissions。

### 10.2 错误码要求

至少需要稳定区分：

| 场景 | 建议错误 |
|---|---|
| 未登录 | `401` |
| 登录但没有 active account | `403` 或专用业务码 |
| 登录但不是当前 account owner | `403` |
| 请求的 library/source/movie/resource 不属于当前 account | `404` 优先，避免泄露存在性 |
| 用户名已存在 | `409` 或稳定业务码 |
| 注册已关闭 | `403` |
| provider 登录流程过期 | `400` + 稳定业务码 |
| provider 已创建但绑定默认片库失败 | 返回可恢复状态，不能留下不可见脏数据 |

---

## 11. 文档和 OpenAPI 必须同步

这部分是 v1 的硬性交付，不是实现后的补充说明。

### 11.1 OpenAPI 版本

- 新建版本目录，不覆盖旧版本：

```text
backend/openapi/openapi-1.22.0-beta/
  openapi-1.22.0-beta.json
  release-notes-1.22.0-beta.md
```

- `backend/openapi/README.md` 更新当前版本说明。
- `GET /api/v1/openapi.json` 必须返回新版本。
- `GET /api/v1/openapi/modules` 的模块拆分要包含新增注册、账号、storage hosted flow 变化。
- OpenAPI contract test 必须覆盖新增路径、关键 schema、模块化文档入口。

### 11.2 前端对接文档

必须更新或新增：

| 文档 | 要求 |
|---|---|
| `docs/FRONTEND_HOSTED_BACKEND_INTEGRATION.md` | 更新注册、`auth/me` 新字段、账号权限、storage 自助挂载入口、401/403 处理。 |
| `docs/FRONTEND_USER_MANAGEMENT_INTEGRATION.md` | 明确平台用户管理和未来账号子用户管理的边界，避免前端误用 `/admin/users`。 |
| `docs/API_OVERVIEW.md` | 更新认证、账号上下文、OpenAPI 当前版本入口。 |
| `docs/CONFIG_REFERENCE.md` | 补充 PostgreSQL、注册开关、默认片库、hosted 模式相关配置。 |
| `docs/RUNBOOK.md` | 补充 PostgreSQL 部署、迁移、备份、回滚、systemd 环境变量。 |
| `docs/TEST_CHECKLIST.md` | 补充多租户隔离、自助挂载、扫描、迁移、OpenAPI 验收项。 |

如 docs 路由有白名单机制，必须同步暴露新的/更新后的文档入口。

### 11.3 Release notes 必须包含

- 新增接口列表。
- 变更字段列表。
- 前端必须调整的权限判断。
- 代托管模式下哪些服务端配置仍然不可见。
- 迁移注意事项。
- 和 1.21.0-beta 的兼容/不兼容点。

---

## 12. 实施阶段

### M0 · Goal 落地与基线确认

- 写入本 goal 文件。
- 确认当前未提交内测变更，不混入无关代码。
- 记录当前后端地址、CORS、TMDB token pool、CDN disabled 状态。

验收：

- goal 文件存在，范围和非范围明确。

### M1 · 数据库连接和迁移框架

- 增加 PostgreSQL 依赖和 `CYBER_DATABASE_URL` / `DATABASE_URL` 配置。
- 引入 Alembic/Flask-Migrate。
- 生成当前 schema baseline。
- 保持 SQLite dev fallback 可运行。

验收：

- SQLite 测试仍可跑。
- PostgreSQL 空库可初始化。
- migration 命令文档可执行。

### M2 · Account 模型和权限上下文

- 新增 `Account`、`AccountMembership` 模型。
- 增加 current account 加载 helper。
- 扩展 `/auth/me`。
- 梳理 `users.role` 和 account role 权限映射。

验收：

- 登录用户能拿到 current account。
- 普通注册用户不会成为平台 admin。
- 无 active account 时返回清晰错误。

### M3 · 多租户字段和现有数据迁移

- 给业务表增加 `account_id`。
- 调整全局唯一约束为账号内唯一。
- 迁移现有数据到 `pureworld` account。
- 补 account 级首页和默认片库状态。

验收：

- 现有 `pureworld` 片库、资源、审查工作台、播放历史、收藏仍可用。
- 不同 account 可拥有相同 `tmdb_id` 的 movie。

### M4 · 查询和写入隔离

- 所有列表、详情、创建、更新、删除接口加 current account 过滤。
- 直接通过 id 访问其他账号资源时返回 404/403。
- 异步扫描、刮削、审查操作传递 account context。

验收：

- A 用户不能列表看到 B 用户数据。
- A 用户拿 B 用户 movie/source/resource id 请求也不能读写成功。
- 测试覆盖常用直接 id 攻击路径。

### M5 · 注册和默认账号初始化

- 实现 `POST /auth/register`。
- 注册后创建 account、owner membership、默认片库、首页设置。
- 注册成功返回登录状态。

验收：

- 新用户注册后刷新 `/auth/me` 有 current account。
- 新用户默认有空片库和挂载入口权限。

### M6 · 自助挂载全 provider 账号化

- 改造所有 `/storage/managed/**` flow。
- AList/OpenList mount path 带 account 前缀。
- storage source 创建、重启、poll、verify、complete、delete 全部校验账号。
- 默认片库绑定和扫描入口打通。

验收：

- 新注册用户可独立挂载一个 provider 并看到自己的 source。
- 另一个用户看不到该 source，也不能操作其登录流程。
- 删除 source 不影响其他 account 的 AList/OpenList mount。

### M7 · 扫描、刮削和审查工作台账号化

- 扫描 job 写入 `account_id`。
- media resource、movie、library membership 全部写当前账号。
- 审查工作台只读写当前账号影视。
- TMDB token pool 继续平台级轮询。

验收：

- 新用户扫描后只增加自己账号影视。
- `pureworld` 原片库数量不被新用户扫描影响。
- 审查工作台不会混入其他账号条目。

### M8 · 文档、OpenAPI 和前端联调说明

- 新建 OpenAPI `1.22.0-beta` 版本目录。
- 更新 release notes。
- 更新前端代托管接入文档、配置文档、运行文档、测试清单。
- 更新 docs route 白名单和 docs route 测试。

验收：

- `/api/v1/openapi.json` 返回新版本 contract。
- `/api/v1/docs/frontend-hosted-backend` 能看到新对接说明。
- 前端可只看文档完成注册、登录、挂载、扫描入口对接。

### M9 · 部署和回归

- 在 40162 hosted dev 后端完成迁移和重启。
- 保持服务常驻 dev 模式。
- 跑后端测试和关键手工联调。
- 验证 CORS、Cookie、HTTPS、TMDB token pool、CDN disabled 状态没有回退。

验收：

- `pureworld` 可以正常登录和使用现有数据。
- 新注册账号可以完成最小闭环。
- 后端 40162 可供前端持续联调。

---

## 13. 测试要求

必须新增或更新测试：

- 注册成功、用户名重复、密码不合法、注册关闭。
- `/auth/me` 未登录、登录无 account、普通 owner、平台 admin。
- Account A/B 隔离：movies、resources、libraries、storage_sources、history、favorites、subtitles。
- 直接 id 越权访问返回 404/403。
- 同一 TMDB 影片可在两个 account 中分别存在。
- 默认片库创建和 slug 冲突处理。
- 每个 managed provider 的账号上下文校验。
- AList/OpenList mount path 带 account 前缀。
- 删除 source 只清理当前 account runtime storage。
- 扫描 job 保留 account_id。
- 现有 `pureworld` 数据迁移脚本的 dry-run/验证逻辑。
- OpenAPI contract 包含新增 endpoint/schema。
- docs routes 暴露新版文档。

建议至少保留一次完整测试：

```text
pytest
```

如果 PostgreSQL 集成测试耗时较高，至少提供可单独运行的 marker 或脚本，并在 RUNBOOK 写清楚。

---

## 14. 风险和处理原则

| 风险 | 处理 |
|---|---|
| 账号隔离漏过滤 | 优先封装 account-scoped query/helper，并用直接 id 越权测试覆盖。 |
| 唯一索引迁移失败 | migration 前先做冲突检查，失败时中止并给出修复建议。 |
| provider 临时状态串账号 | OAuth state / QR state / source_id 都要绑定 account，poll 时复核。 |
| AList/OpenList mount 删除误伤 | mount path 和 runtime storage id 必须记录 account/source，delete 只操作精确项。 |
| SQLite 和 PostgreSQL 行为差异 | hosted 以 PostgreSQL 为准，SQLite 只保证开发可用；关键约束测试尽量覆盖两边。 |
| 前端误判权限 | 文档明确 `users.role` 和 `account_role` 的区别，并在 `auth/me` 给足 permissions。 |
| OpenAPI 滞后 | M8 是硬验收，contract test 不过不能算完成。 |

---

## 15. 最终验收标准

本 goal 完成时必须同时满足：

1. 现有 `pureworld` 账号登录后能看到并管理原有片库。
2. 新用户可开放注册，注册后自动拥有自己的 account 和默认片库。
3. 新用户可自助完成至少一个真实 provider 挂载，并能启动自己账号的扫描。
4. 两个账号之间影视、资源、片库、挂载源、历史、收藏、字幕设置互不可见、不可直接 id 访问。
5. `users.role=admin` 不再被普通注册用户复用；普通用户靠 account owner 权限管理自己的数据。
6. PostgreSQL 配置和迁移路径清晰，SQLite fallback 不被破坏。
7. TMDB token pool、CORS、HTTPS、CDN disabled/original image link 策略不回退。
8. OpenAPI 新版本、release notes、前端对接文档、配置文档、运行文档和测试清单全部同步。
9. 40162 hosted dev 后端可持续在线，供前端继续联调。
