# CyberStream PC 1.21.1-pc.1

跟 1.21.0-pc.0 比，本次发布带来三件大事：**新增完整桌面捆绑版**、扫描安全护栏、UI 内 TMDB 配置入口。

## 下载选哪个？

| 安装包 | 适合谁 | 大小 |
|---|---|---|
| **`CyberStream_1.21.1-pc.1_lite_x64.msi`** | 已经有自部署后端（NAS / VPS / docker）的用户 | ~14 MB |
| **`CyberStream_1.21.1-pc.1_full_x64.msi`** | 想开箱即用的小白用户、单机自用 | ~120 MB |

`full` 把后端打成 sidecar 进程一起捆绑进来，双击安装就有完整本地后端，不需要单独装 Python / 配 systemd。`lite` 跟之前的 `1.21.0-pc.0` 一样，纯 webview shell，连远程 API。

两种装出来都能在 「设置 → 后端服务器」 改后端地址，互相切换；`full` 关了主程序 sidecar 后端就停。

## 主要变化

### 桌面捆绑版（M1/M2/M3）

- 后端 `cyber-backend.exe` 通过 PyInstaller 打成单 exe（28 MB），Tauri sidecar API 启动 / 探活 / 退出时干净 kill
- 冻结模式默认监听 `127.0.0.1:49152`（IANA 动态/私有起点，跟 dev 5004 隔开），WSGI 用 waitress 而非 dev 用的 Flask app.run
- DB / 缓存落到 `%LOCALAPPDATA%\CyberStream\`；TMDB token 等也写进同目录的 `.env.local`，下次启动自动 load_dotenv 加载
- 前端 PC runtime 默认 `API_BASE = http://127.0.0.1:49152/api`，用户在设置里改过的地址优先；切换后端要重启窗口才生效

### 扫描安全护栏

之前 `POST /v1/scan`（全盘扫描）不要任何参数也不检查任何绑定关系，云盘场景下分分钟扫几万个文件。这次加了三道护栏：

- **`POST /v1/scan`** 在没有 `enabled library_sources` 绑定时直接返 40013，前端 toast 引导用户去「资源库」绑定具体目录
- **`POST /v1/storage/sources/{id}/scan`** 没传 `root_path` 且这个 source 没被任何 library 绑定时同样拒绝；保留传了 `root_path` 时手动指定子目录扫描的能力
- **scanner 异常透传**：`scan_source` 异常 / 索引到 0 文件时把消息推到 `recent_errors`，前端 ScanProgressBar 直接显示「未发现媒体文件 / 扫描失败：xxx」，不再静默秒结束让用户摸不着头脑

前端 `scanLibrary` / `scanSource` 改用 `fetchApiRaw`，toast 透传后端 msg。

### UI 内 TMDB 配置

桌面单机分发场景下用户没法手改 NAS 的 `.env.local`，必须能在 UI 里配 TMDB token + 代理。

- 后端：`GET / PUT /api/v1/system/tmdb-config`，写 `.env.local`，同步刷新 `current_app.config + backend.config + os.environ`，**下次扫描立刻读到新值无需重启**
- 安全：GET 永远不回明文 token，只回 `token_set: bool`
- 前端：Profile → SYSTEM → 「TMDB 元数据」卡片
  - Token 输入框 password 模式，可切显隐；已配置时 placeholder「已配置（输入新值可覆盖）」
  - 代理开关 + URL（http/https/socks5），跟应用代理 / 视频代理形态一致

国内访问 themoviedb.org 一般要走代理，新装的小白用户配完 token + 代理就能正常刮削，不再卡在「兜底元数据 → catalog_visibility 自动隐藏 → 库列表空白」的死链。

## 已知坑

- `lite` 包不带后端 sidecar；如果用户没在「设置」里配置自己的后端地址，就会卡在加载页（前端默认指向 `127.0.0.1:49152`，那个端口没东西）。下版本会改成首次启动检测到本地无后端时弹引导。
- `full` 包冷启动需要等 sidecar PyInstaller 解包 + Flask init + DB schema 初始化（约 6-8 秒），期间窗口空白。第二次起会更快（OS 缓存）。

## 升级指南

从 `1.21.0-pc.0` 升级：直接装新 MSI 即可，配置（后端地址 / 代理 / TMDB）以 webview localStorage + `.env.local` 为准，不会丢。

从源码部署：拉 main 分支重启后端 + 重打前端。后端首次启动会自动加 `_normalize_proxy_url` 等新 helpers，已有 DB 兼容。
