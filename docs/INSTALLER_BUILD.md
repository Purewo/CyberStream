# 桌面安装包构建流程（NSIS）

> CyberStream 桌面客户端通过 NSIS 打成自定义赛博朋克主题的 setup.exe，
> 取代之前 Tauri 自带的 MSI bundler。一次构建产出 lite 和 full 两个 variant：
> lite 是纯 webview 壳（连远程 NAS 后端），full 把 PyInstaller 后端 sidecar
> 一起捆绑。

## 总体流程

```
backend/run.py
    │  py -3.10 -m PyInstaller backend/cyber-backend.spec --clean --noconfirm
    ▼
dist/cyber-backend.exe (PyInstaller onefile, ~32 MB)
    │  cp → pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe
    ▼
Tauri shell sidecar slot (NOT bundled into MSI any more)
    │  cd pc/src-tauri && cargo tauri build
    ▼
pc/src-tauri/target/release/cyberstream-pc.exe + libmpv-2.dll
    │  bash pc/installer/scripts/build_setup.sh full|lite <version>
    ▼
pc/installer/dist/CyberStream_<ver>_<variant>_x64_setup.exe
```

## 前置依赖

构建机要求：
- Windows 11，Rust ≥ 1.77，Node ≥ 22，cargo-tauri 2.x
- Python 3.10，已安装 `requirements.txt` 全部依赖（含 PyInstaller、waitress）
- WebView2 Runtime（Win11 自带）
- `pc/vendor/mpv-dev/` 下放好 libmpv 头 + lib 文件（用于 cargo build 期）
- **NSIS 3.x**（`makensis` 可在 PATH 里调用）— [下载](https://nsis.sourceforge.io/Download)

## Step 1 · 后端 PyInstaller exe

从仓库根：

```bash
py -3.10 -m PyInstaller backend/cyber-backend.spec --clean --noconfirm
cp dist/cyber-backend.exe pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe
```

冒烟测试：

```bash
dist/cyber-backend.exe &
curl -s http://127.0.0.1:49152/    # {"code":200,"data":{"status":"up",…}}
```

冻结后端运行时差异：
- 端口 **49152**（dev 是 5004）
- 监听 **127.0.0.1**（dev 是 0.0.0.0）
- WSGI 服务器 **waitress**（dev 是 Flask app.run debug=True）
- 数据目录 **%LOCALAPPDATA%\CyberStream\**
- 只读资源（openapi/、docs/）从 `sys._MEIPASS` 解出

## Step 2 · Tauri Rust shell

```bash
cd pc/src-tauri
cargo tauri build
```

注意：`tauri.conf.json` 的 `bundle.targets` 已设为 `[]`，**Tauri 不会再产
出 MSI**，只编译 Rust shell + 打包前端 + 把 libmpv-2.dll 拷到 release/。
NSIS 在下一步从 `target/release/` 拿这些产物。

## Step 3 · NSIS setup.exe

```bash
# 完整版（含 sidecar）
bash pc/installer/scripts/build_setup.sh full 1.21.1-pc.4

# 轻量版（纯 webview 壳）
bash pc/installer/scripts/build_setup.sh lite 1.21.1-pc.4
```

`build_setup.sh` 做的事：
1. 把需要的产物（`cyberstream-pc.exe`、`libmpv-2.dll`，full 还要 sidecar）
   stage 到 `pc/installer/.staging-<variant>/`
2. 调 `makensis` 编译 `pc/installer/cyberstream.nsi`，传入 `-DVARIANT`、
   `-DAPP_VERSION`、`-DSTAGING_DIR`、`-DOUT_FILE`
3. 输出到 `pc/installer/dist/CyberStream_<ver>_<variant>_x64_setup.exe`

预期体积：
- lite：~12 MB（exe + libmpv）
- full：~50 MB（lite + sidecar）

注意这跟之前 MSI 的 93 / 286 MB 差距是因为旧 MSI 把 `pc/vendor/mpv/` 下整套
mpv 桌面版（112 MB）当资源打了进去，那一坨从未被运行时引用过。NSIS 路径
只装真正用到的二进制。

## NSIS 视觉资源

`pc/installer/branding/`：
- `welcome.bmp`（164×314 BMP3 24-bit）— 安装/卸载向导左侧大图
- `header.bmp`（150×57 BMP3 24-bit）— 内页右上角横幅
- `app.ico` — 安装器和卸载器使用

视觉走 CYBER 主题（青 #00f3ff / 紫 #bc13fe / 黑 #050505）。如果要重新生成：

```bash
powershell -ExecutionPolicy Bypass -File pc/installer/scripts/gen_branding.ps1
```

PS 脚本通过 `System.Drawing` 直出 BMP3，不依赖 ImageMagick。

## Step 4 · 安装器冒烟测试

先卸载旧版本（设置 → 应用 → CyberStream），再双击新 setup.exe：

1. 安装路径默认 `C:\Program Files\CyberStream\`，可改
2. 组件页可勾选「桌面快捷方式 / 开始菜单项」
3. 完成页可勾「立刻启动」
4. full 包：启动后看 `%LOCALAPPDATA%\CyberStream\` 出现 `cyber_library.db`
   = sidecar 起来了
5. 关闭应用 → `tasklist | findstr cyber-backend` 应该没了 = sidecar 被 kill

卸载流程会问「是否同步清空 %LOCALAPPDATA% 和 %APPDATA% 下的 CyberStream
数据？」，避免脏数据残留。

## 故障排查

- **`makensis: command not found`**：NSIS 没装，或安装目录没进 PATH。装在
  默认 `C:\Program Files (x86)\NSIS\` 里，把这个目录加到 PATH 即可。
- **NSIS 报「Invalid bitmap file」**：`branding/*.bmp` 不是 BMP3。重跑
  `gen_branding.ps1` 即可（System.Drawing 默认就是 BMP3）。
- **打开后转圈不响应（full 包）**：sidecar 启动失败。看 `%LOCALAPPDATA%\
  CyberStream\` 没有 `cyber_library.db` 多半是 PyInstaller hidden-imports
  漏了。在 `backend/cyber-backend.spec` 的 `hiddenimports=` 里加。
- **MSI 体积异常大**：检查 `frontend/dist` 有没有把 `node_modules` 误打
  进去；vendor 目录是否含 debug 符号文件。

## 数字签名（TODO）

当前安装器**未数字签名**，Win SmartScreen 会弹「未知发布者」警告。
之后接入商业代码签名证书时：

1. `signtool.exe sign /f cert.pfx /p PASSWORD /t http://timestamp.sectigo.com /fd sha256 setup.exe`
2. 在 `build_setup.sh` 末尾加一段 signtool 调用
3. 参考 https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool

## 用户自定义后端地址

桌面单机版 full 默认 API_BASE = `http://127.0.0.1:49152/api`。lite 默认空字符串
（首启自动跳到「设置 → 后端服务器」）。两种 variant 都允许在 UI 里改：

- 改完会写 localStorage `cyber_pc_api_base`
- 重启 webview 生效
- 改回空（删除 key）就回到默认本地后端

实现：`frontend/src/platform/pc.ts:42` 的 `readApiBase()`。
