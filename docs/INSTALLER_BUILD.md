# 桌面安装包构建流程

> CyberStream 桌面单机版（Tauri MSI 安装器）的构建步骤。最终产物是
> 一个双击即装的 `.msi`，安装后用户点击桌面图标就能用，自带捆绑的
> 后端服务，不需要单独部署 NAS。

## 总体流程

构建 = 三阶段串联，每一段产物喂给下一段：

```
backend/run.py
    │  py -3.10 -m PyInstaller backend/cyber-backend.spec --clean
    ▼
dist/cyber-backend.exe  (28 MB · 单 exe · waitress + Flask)
    │  cp → pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe
    ▼
Tauri externalBin
    │  cd pc/src-tauri && cargo tauri build
    ▼
pc/src-tauri/target/release/bundle/msi/CyberStream_<ver>_x64.msi
```

## 前置依赖

构建机要求：
- Windows 11，Rust ≥ 1.77，Node ≥ 22，cargo-tauri 2.x
- Python 3.10，已安装 `requirements.txt` 全部依赖（含 PyInstaller、waitress）
- WebView2 Runtime（Win11 自带）
- `pc/vendor/mpv/` 下放好 libmpv 二进制（参考 `pc/CLAUDE.md`）

> **为啥锁 Python 3.10？** PyInstaller 6.x + 当前依赖矩阵在 3.10 下验证过；
> 3.13/3.14 偶尔会因为 `cffi`/`cryptography` ABI 漂移构建失败。要换版本前
> 先在干净 venv 里跑通 `pyinstaller backend/cyber-backend.spec` 再说。

## Step 1 · 后端 PyInstaller exe

从仓库根：

```bash
py -3.10 -m PyInstaller backend/cyber-backend.spec --clean --noconfirm
```

成功后产物在 `dist/cyber-backend.exe`，约 28 MB。

冒烟测试（双击即可，或：）：

```bash
dist/cyber-backend.exe &
curl -s http://127.0.0.1:49152/    # 应返回 {"code":200,"data":{"status":"up",…}}
```

冻结后端的运行时差异：
- 端口 **49152**（dev 是 5004，但 dev 不通过这个 spec）
- 监听 **127.0.0.1**（dev 是 0.0.0.0）
- WSGI 服务器 **waitress**（dev 是 Flask app.run debug=True）
- 数据目录 **%LOCALAPPDATA%\CyberStream\**（DB / cache 落这里）
- 只读资源（openapi/、docs/）从 `sys._MEIPASS` 解出

## Step 2 · 把 exe 复制到 Tauri sidecar 目录

Tauri 2 要求 sidecar 二进制名带 rustc target triple 后缀：

```bash
cp dist/cyber-backend.exe pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe
```

> 这一步没自动化的原因：每个开发机的 target triple 可能不同（ARM
> Windows 上是 `aarch64-pc-windows-msvc`），写死成 shell 别名容易踩坑；
> 真要 CI 自动化时拿 `rustc -vV | grep host:` 提取后再 cp。

## Step 3 · Tauri MSI 构建

```bash
cd pc/src-tauri
cargo tauri build
```

Tauri 会自动：
- 跑 `npm --prefix ../frontend run build`（vite 产 `frontend/dist/`）
- 把 sidecar exe 打进 MSI（声明在 `tauri.conf.json` 的 `bundle.externalBin`）
- 把 `pc/vendor/mpv/*` 也打进 MSI（声明在 `bundle.resources`）
- 输出 `pc/src-tauri/target/release/bundle/msi/CyberStream_<ver>_x64.msi`

完整 MSI 体积 = Tauri shell + frontend dist + libmpv + cyber-backend.exe，
预计 200-300 MB。

## Step 4 · 安装器冒烟测试

先卸载旧版本（Win 设置 → 应用 → CyberStream），再双击新 MSI：

1. 安装路径默认 `C:\Program Files\CyberStream\`
2. 启动后桌面应用窗口出现前会先拉起 sidecar 后端，看 `%LOCALAPPDATA%\CyberStream\`
   下出现 `cyber_library.db` = 后端起来了
3. 应用窗口出现 → 首页能加载 = 前端拿到 `http://127.0.0.1:49152/api`
   返回的数据
4. 关闭应用 → `tasklist | findstr cyber-backend` 应该没了 = sidecar 被
   正确 kill 掉

## 故障排查

- **MSI 安装报"无法访问 49152 端口"**：用户机器上有进程占着这个端口
  （常见：游戏服务、其他自托管 app）。当前实现是 fail-fast，需要改默认
  端口或改 `backend/run.py` 加退让逻辑。
- **打开后转圈不响应**：后端启动失败。开 `%LOCALAPPDATA%\CyberStream\`
  没有 `cyber_library.db` 多半是 PyInstaller hidden-imports 漏了（Python
  里某个库 raise ModuleNotFoundError）。在 spec 的 `hiddenimports=` 里加。
- **MSI 体积异常大**：检查 `frontend/dist` 有没有把 `node_modules` 误打
  进去；`pc/vendor/mpv/` 是否含 debug 符号文件。
- **WebView2 报代理错误**：`pc/src-tauri/src/proxy.rs` 维护的 `proxy.json`
  在 `%APPDATA%\com.purewo.cyberstream\`，删掉重启即可重置。

## 用户自定义后端地址

桌面单机版默认 API_BASE = `http://127.0.0.1:49152/api`，但用户仍能在
设置页改成自己的 NAS：

- 改完会写 localStorage `cyber_pc_api_base`
- 重启 webview 生效
- 改回空（删除 key）就回到默认本地后端

实现：`frontend/src/platform/pc.ts:31` 的 `readApiBase()`。
