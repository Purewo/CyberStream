# CyberStream PC 1.21.1-pc.4

跟 1.21.1-pc.3 比，本次是**安装器整体迁移**版本——抛弃 Tauri 自带的 WiX MSI bundler，换成自定义的 NSIS 安装向导。顺便把"刚装完一进来就被无法连接 toast 刷脸"、全屏退出按钮失效之类的小坑一起收掉。

## 下载选哪个？

| 安装包 | 适合谁 | 大小 |
|---|---|---|
| **`CyberStream_1.21.1-pc.4_lite_x64_setup.exe`** | 已有自部署后端（NAS / VPS / docker）的用户 | ~37 MB |
| **`CyberStream_1.21.1-pc.4_full_x64_setup.exe`** | 想开箱即用、单机自用 | ~227 MB |

`full` 把后端 PyInstaller onefile 一起打进来，双击安装就有本地后端。`lite` 是纯 webview shell，连远程 API。

体积对比上一版（MSI）：lite 93MB → 37MB，full 286MB → 227MB。瘦身的来源是发现 `pc/vendor/mpv/` 下整套 mpv 桌面版（112MB）从未被运行时引用过 —— 旧 MSI 把它当资源打了进去，纯白送了用户硬盘几百兆。NSIS 路径只装真正用到的二进制（`cyberstream-pc.exe` + `libmpv-2.dll` + 可选 sidecar）。

## 主要变化

### 自定义 NSIS 安装向导

替代了 Tauri 的 WiX MSI 方案。新向导：

- **Modern UI 2 主题**：暗色背景（#0c0c12）+ 青/紫双色径向辉光 + Segoe UI Variable 字体。极简的现代风格，没有 90 年代的网格线和 L 型边角
- **自动追加子目录**：用户把目录改成 `E:\apps\` 这种公共目录时，向导自动追加 `\CyberStream`，避免卸载时把别的程序的文件一起带走
- **进程清理**：安装/卸载开始时自动 `taskkill` 掉残留的 `cyber-backend.exe` / `cyberstream-pc.exe`，避免文件锁导致写入失败或卸载残留
- **可选清空用户数据**：卸载向导会问要不要顺便清掉 `%LOCALAPPDATA%\CyberStream`（数据库 / Token / 缓存）和 `%APPDATA%\com.purewo.cyberstream`（webview localStorage / 代理设置）。默认不勾，避免误删
- **`RMDir /r /REBOOTOK` 兜底**：卸载结束前递归清理整个安装目录，捕获 PyInstaller 解出来的 _MEI 临时文件等遗漏

构建脚本在 `pc/installer/scripts/build_setup.sh`，可同一份脚本通过 `/DVARIANT=full|lite` 切换两个变体。详细文档见 `docs/INSTALLER_BUILD.md`。

### 启动期不刷"无法连接"toast

`full` 包冷启动时 PyInstaller onefile sidecar 要解 `_MEI` + 起 waitress，需要 3-5 秒；这期间前端首屏挂载就开始 fetch 数据，每个失败请求都弹一条红色 toast，用户体感"刚进来就出了一堆错"。

修复在 `frontend/src/api/core.ts`：启动后 8 秒窗口内的网络错误只走 `console.error`，不弹 toast。窗口外再失败才上报，那时大概率是真的后端挂了，值得告警。

### 全屏退出按钮失效修复

之前播放器全屏后右下角显示的还是"进入全屏"图标，点击也无效。原因是状态只追了本地 React state，没追浏览器/webview 的 `fullscreenchange` 事件。这版改成监听 `fullscreenchange`，图标根据真实状态在 Maximize/Minimize 间切换，点击调对应 API。

### 字幕图标换成 Captions 而非 MessageSquare

之前用 lucide 的 MessageSquare（聊天气泡感），跟 PC 端原生播放器的字幕图标视觉不一致。改成 Captions 图标，跟 PC 端一致。

### 离线存储源直接出删除按钮

资源台的存储源卡片在 `health.status === "offline"` 时，右上角直接渲染红色垃圾桶按钮（之前只显示锁图标，用户没法救济无效源）。点击走 `deleteSource(keepMetadata=false)` 级联清理，把孤儿元数据一起带走。

### AList 路径必填

PC 端挂载 AList 时不填路径会让后端拿到空字符串去查 → 404。新增的客户端验证：路径字段为空或仅 `/` 时直接 toast.error 拦下，不发请求。

### 模态框点击外部不再 dismiss

添加/编辑存储源、添加媒体库的弹窗之前点蒙层会无差别关掉，正在填到一半的内容全没。这版去掉了背景 onClick 关闭逻辑，必须明确点 X 或取消按钮才关。

## 已知坑

- `full` 包冷启动仍需等 sidecar 起来（3-5 秒），但启动期 toast 已经静音；窗口可能短暂"看着空空的"，几秒后内容自动填进来
- 安装器**未数字签名**，Win SmartScreen 会弹"未知发布者"警告，点「更多信息 → 仍要运行」继续
- 升级流程：旧版本（pc.3 及以前）的 MSI uninstall.exe 没有 kill 进程逻辑，先手动从设置卸载老版再装这版即可

## 升级指南

1. **从 pc.3 升级**：先用 Win 设置 → 应用 → 卸载旧 MSI → 双击新 setup.exe。卸载向导问要不要清空用户数据时**选否**，库就保留下来
2. **全新安装**：直接双击 `_full_x64_setup.exe`
3. **从 lite 切 full / 反向切**：先卸载再装另一个 variant；用户数据共享（`%LOCALAPPDATA%\CyberStream`），媒体库不会丢
