# CyberStream PC 客户端目标文档（goal · v1）

> 版本基线：CyberStream 1.21.0
> 决策框架：一次性把边界、决策、迁移阶段锁死，后期只做参数级微调
> 日期：2026-05-20

---

## 1. 为什么做 PC 端

Web 端能力天花板已经基本顶住三条玻璃：

1. **解码上限**：浏览器 H.265/AV1 看运气，Dolby Vision Profile 5、Dolby TrueHD/Atmos passthrough 直接没希望；4K REMUX 经常被中间层卡。
2. **外部协议拦截**：`vlc://` `iina://` 在桌面浏览器越来越多被默认拒绝（你前两天 Chrome 的 VLC 唤起就是这条），handoff 体验劣化。
3. **桌面级交互**：原生文件对话框（选根路径不再盲填）、系统托盘后端健康哨兵、自定义协议 `cyberstream://` 深链、全局热键、PiP 独立窗口——这些没壳做不了。

PC 端的核心承诺是**"榨干显卡 + 外部协议零拦截"**，不是又一个浏览器套壳。这条决定了我们必须自己接管解码层。

---

## 2. 形态边界（已锁死，不再讨论）

| 维度 | 决策 | 关键理由 |
|---|---|---|
| 部署形态 | **纯客户端壳** | 后端继续跑在 NAS/家用服务器；客户端只是把"客户端"做厚。不打包 Python，避免和"自托管"产品定位冲突。 |
| 客户端壳 | **Tauri**（Rust + WebView2） | 复用 100% 现有 React 代码；产物 ~10MB；和"发烧级自托管"调性一致。Electron 的 100MB+ 包体和 Chromium 全套依赖直接放弃。 |
| 播放器引擎 | **libmpv 嵌入** | D3D11VA / DXVA2 / NVDEC / Vulkan 硬解全吃；HEVC/AV1/Dolby Vision Profile 5/HDR 原生支持；libass 字幕渲染上限拉满；TrueHD/Atmos passthrough 可配置。 |
| v1 平台 | **Windows 11 only** | 验证完再补 macOS/Linux。代码签名证书钱、跨平台 CI 矩阵、安装包格式都是真成本，不一次性背。 |
| 字幕边界 | **Web 端继续不碰；PC 端 libass 接管** | Web 版 SRT→WebVTT 链路保持冻结；PC 版直接把字幕文件路径塞给 libmpv，让 libass GPU 渲染，不在 React 层做 ASS 解析。 |

---

## 3. 范围（v1 做什么，v1 不做什么）

### v1 必须做（MVP）

- [x] 决策：Tauri Win 壳 + libmpv 嵌入 + libass
- [ ] **平台抽象层 (Platform Adapter)**：让同一份 React 代码在 Web 和 PC 两种 runtime 下跑，差异点收敛在一处
- [ ] **API_BASE 运行时注入**：PC 端用户能在设置里改后端地址，写到 Tauri Store；Web 端继续用 `constants/index.ts` 常量
- [ ] **libmpv 嵌入播放器**：替换 `Player.tsx` 内部的 `<video>`，对外保持 `PlayerProps` 接口不变
- [ ] **外部协议唤起替换**：`<a href="potplayer://...">` 改走 `tauri-plugin-shell::open`
- [ ] **窗口/全屏/退出**：菜单、关闭确认、F11 全屏、Esc 退出全屏
- [ ] **桌面级热键**：空格暂停、←→ 5s seek、↑↓ 音量、F 全屏、M 静音、, . 帧步进、`[ ]` 倍速
- [ ] **GPU 信息透出**：状态栏/调试面板显示当前硬解 API（D3D11VA/DXVA2/NVDEC）和 GPU vendor，方便用户验证"真硬解"
- [ ] **打包与分发**：MSI/NSIS 安装包；Windows 代码签名（如有证书）；首次启动配置后端 URL 向导
- [ ] **版本号对齐**：客户端版本随 frontend 1.21.0 同步

### v1 故意不做（推到 v2 或更晚）

| 项 | 推迟原因 |
|---|---|
| macOS/Linux 客户端 | Windows 跑通再说；签名/notarization/包格式各一套 |
| 自包含一体机（打包 Flask） | 和"自托管"定位冲突；要么 Python embeddable + 200MB+ 包，要么后端重写，工程量另算 |
| 多窗口（PiP、独立设置窗口） | CustomEvent 总线在单窗口够用；多窗口要迁移到 Tauri event |
| 字幕模块改造 | 用户明令冻结；libmpv 直接消费已绑定字幕文件 |
| 自动更新（auto-updater） | v1 手动下载安装；签名 + update server 是单独的活 |
| 移动端（iOS/Android） | Tauri 移动端还嫩；iOS 提交流程另算 |
| Web 端能力削减 | Web 版仍是一等公民；PC 是"上限"不是"取代" |

---

## 4. 架构（PC 模式 vs Web 模式）

```
                  ┌─────────────────────────────────────────────┐
                  │ React 19 + TypeScript + Vite SPA            │
                  │  features/ + components/ + hooks/ + types/  │
                  │  src/api/* (UI-typed services)              │
                  └─────────────────┬───────────────────────────┘
                                    │ 通过 platform adapter 切换 runtime
                  ┌─────────────────┴───────────────────────────┐
                  │                                             │
        ┌─────────▼──────────┐                       ┌──────────▼──────────┐
        │  Web Runtime       │                       │  PC Runtime (Tauri) │
        │  - 浏览器 fetch    │                       │  - tauri-plugin-http│
        │  - <video> 标签     │                       │  - libmpv 子窗口    │
        │  - <a href> 协议跳 │                       │  - shell.open       │
        │  - localStorage    │                       │  - tauri-store      │
        │  - SRT→WebVTT 转换 │                       │  - libass 直渲      │
        └────────┬───────────┘                       └──────────┬──────────┘
                 │                                              │
                 └──────────────────┬───────────────────────────┘
                                    │ HTTP(S)
                                    ▼
                    ┌──────────────────────────────────┐
                    │ Flask 后端（NAS / 家用服务器）   │
                    │ - 完全不动                        │
                    │ - /api/v1/* 契约不变             │
                    └──────────────────────────────────┘
```

### 关键不变量

- **后端零改动**：所有 PC 端能力都基于现有 OpenAPI 1.21.0-beta 契约
- **single source of truth**：`src/types/index.ts` 仍是 UI 类型唯一来源；`src/api/*` 仍是数据访问唯一入口
- **同一仓库同一分支**：不分叉，PC 用条件编译（Vite `import.meta.env` + Tauri 内置 `__TAURI__` 检测）

---

## 5. 平台抽象层契约（Platform Adapter）

新增 `src/platform/` 目录，导出统一接口。Web 实现走浏览器原生 API，PC 实现走 Tauri plugin。

| 能力 | 接口 | Web 实现 | PC 实现 |
|---|---|---|---|
| 后端地址 | `getApiBase(): string` | 读 `constants.API_BASE` 常量 | 读 `tauri-store` 的 `apiBase` 键，未设置时弹首启向导 |
| 持久存储 | `storage.get/set(key)` | `localStorage` | `tauri-plugin-store`（落到 app data 目录） |
| 设备 ID | `getDeviceId(): string` | 现状 `localStorage + crypto.randomUUID` 不变 | 同 Web，第一次写入后稳定 |
| 剪贴板 | `clipboard.write(text)` | `navigator.clipboard.writeText` | `tauri-plugin-clipboard-manager` |
| 外链跳转 | `shell.open(url)` | `window.open(url, '_blank')` 或 `<a target="_blank">` | `tauri-plugin-shell::open`（自定义协议直接交给 OS） |
| 文件对话框 | `dialog.openDirectory()` | 不支持（PC 端独占特性） | `tauri-plugin-dialog::open({ directory: true })` |
| 内嵌播放器 | `player.create(opts)` | 返回 `<video>` 渲染层 | 返回挂载 libmpv child window 的 React 组件 |

### 已知必须替换的硬编码点（盘点结果）

| 文件:行 | 现状 | 处理 |
|---|---|---|
| `src/constants/index.ts:3` | `API_BASE = "https://pw.pioneer.fan:84/api"` | 改为 `getApiBase()` 调用，常量保留作 Web fallback |
| `src/api/core.ts:54-103` | `fetchApi` 用 `fetch(API_BASE + ...)` | 内部改 `fetch(getApiBase() + ...)` |
| `src/api/core.ts:170-179` | `resolveAssetUrl` 拼 `API_BASE` | 同上 |
| `src/api/core.ts:310-317` | `getDeviceId` 直接 localStorage | 走 `platform.storage` |
| `src/components/Player.tsx:575` | `new URL(fullPath, window.location.origin)` | base 改为 `getApiBase()` 起源 |
| `src/features/MovieDetail.tsx:594-606` | `<a href="potplayer://...">` | 改 `<button onClick={() => platform.shell.open(url)}>`，**Web 端也改** —— 浏览器一样吃 `<a>`，但显式 `shell.open` 让 PC/Web 行为一致 |
| `src/App.tsx:121` | `navigator.clipboard.writeText` | 走 `platform.clipboard.write` |
| `src/App.tsx:121` | 用 `window.location.origin` 拼分享 URL | PC 端 origin 是 `tauri.localhost`，必须用 `getApiBase()` 派生公开链接前缀（或直接禁用分享按钮） |
| `src/utils/index.ts:27` | Google Fonts CDN | 字体本地化，打包进 dist |
| `index.html:20,29-38` | Tailwind/ESM CDN（这是历史遗留） | 全走 Vite bundle，清掉 CDN script |
| `vite.config.ts` | 无 `base` 配置 | Tauri profile 下 `base: './'` |

---

## 6. Player 替换契约（最关键）

**对外保持 `PlayerProps = { movie, onBack, initialOptions }` 不变**。`Player.tsx` 不动，新增 `Player.web.tsx` 和 `Player.pc.tsx` 两个实现，由 `src/platform/index.ts` 在编译期决定导入哪个。

### libmpv 实现的能力清单

复用现有 React 状态机和 UI（idle 隐藏、进度条、字幕选择器、源切换、字幕样式面板、在线搜索、心跳上报），但解码层全换：

| 能力 | Web 现状 | PC 实现 |
|---|---|---|
| 加载视频 | `<video src={url}>` | `mpv loadfile {url}` |
| 多源切换 | 改 `videoUrl` state，`<video>` 自然 reload | `mpv loadfile {newUrl}`，记录 `time-pos` 后 seek |
| seek/暂停/速率 | `videoRef.currentTime` 等 | `mpv set time-pos / pause / speed` |
| 字幕挂载 | fetch 文本 → 转 WebVTT → `<track>` | `mpv sub-add {fileUrl}` 或 `--sub-files`，libass 直渲 |
| 字幕样式 | 自渲层 + CSS | `mpv set sub-color/sub-font-size/sub-margin-y` 等 |
| 进度心跳 | `timeupdate` 事件 | mpv `time-pos` property observer 每秒触发 |
| 缓冲态 | `waiting/playing` 事件 | mpv `paused-for-cache` property |
| 全屏 | `requestFullscreen` | Tauri 窗口 fullscreen API |
| 音频转码 | 双 `<audio>+<video>` 同步 | **PC 端不需要**——libmpv 原生解码，Player 内部条件渲染掉这部分 UI |

### Player 内部哪些代码要保留 / 删除

- **保留**：源列表 / 季集分组 / 多源选择器 / 字幕选择器 / 在线字幕搜索绑定 / 字幕样式面板 / 历史心跳节流 / 锁屏 / idle 计时
- **PC 模式禁用**：`playbackMode === 'audio_transcode'` 整套（双标签同步、首包诊断、session 管理）
- **PC 模式新增**：硬解信息显示（vo/hwdec props）、CPU/GPU 占用浮层（mpv `vo-passes-info`）

### 控件实现策略

mpv 通常作为 native child window 渲染（D3D11 surface），React UI 浮在上面。两条选型：

1. **`mpv-player-node` / `node-mpv` 风格的 IPC** —— Tauri 起 mpv 子进程，通过 named pipe 控制；优点零依赖嵌入、缺点要管理子进程生命周期
2. **Rust 直接 link libmpv** —— 用 `libmpv-sys` crate；优点深度可控、缺点 Rust 端复杂度上升

**v1 推荐方案 1（IPC）**：实现简单、libmpv 二进制下载即可、出问题易诊断。性能差距 < 1%（mpv 自身渲染线程独立）。如果 v1 实测 IPC 延迟扎眼再切方案 2。

---

## 7. 仓库与文件改动地图

```
CyberStream/                          (后端 monorepo 根)
├── frontend/                         (React SPA — 现有，继续维护)
│   ├── src/
│   │   ├── platform/                 ★ 新增
│   │   │   ├── index.ts              ★ 平台 adapter 入口（运行时探测 __TAURI__）
│   │   │   ├── web.ts                ★ Web 实现
│   │   │   └── pc.ts                 ★ PC 实现（动态 import @tauri-apps/*）
│   │   ├── components/
│   │   │   ├── Player.tsx            修改：解构成内部 PlayerCore + 外壳
│   │   │   ├── Player.web.tsx        ★ <video> 实现
│   │   │   └── Player.pc.tsx         ★ libmpv IPC 实现
│   │   ├── api/core.ts               修改：API_BASE 改 getApiBase()
│   │   ├── constants/index.ts        修改：API_BASE 仅作 Web fallback
│   │   ├── App.tsx:121               修改：clipboard 走 platform
│   │   └── features/MovieDetail.tsx  修改：外链按钮 onClick → platform.shell.open
│   ├── index.html                    修改：清理 CDN script
│   ├── vite.config.ts                修改：Tauri profile base: './'
│   └── public/fonts/                 ★ 新增：本地化 Orbitron/Rajdhani/JetBrains Mono
│
└── pc/                               ★ 全新顶层目录
    ├── src-tauri/                    Rust 壳
    │   ├── tauri.conf.json           窗口/权限/打包配置
    │   ├── Cargo.toml
    │   └── src/
    │       ├── main.rs               入口
    │       ├── mpv.rs                ★ libmpv IPC bridge（spawn + named pipe）
    │       ├── settings.rs           ★ apiBase 等持久化
    │       └── window.rs             ★ 全屏/置顶/PiP（v2）
    ├── README.md                     PC 端构建说明
    └── icons/                        应用图标
```

**关键决策**：PC 壳放在 monorepo 根的 `pc/` 而不是 `frontend/src-tauri/`，让前端目录保持纯 web 工程；Tauri 在 `tauri.conf.json` 里指 `frontendDist = ../frontend/dist`、`devUrl = http://localhost:3000`。

---

## 8. 关键技术决策与拒绝项

### 已决策

- **不分仓库**：PC 和 Web 共一个 git 仓库，避免代码漂移
- **不引入 Electron**：包体 / 调性 / Rust 收益不允许
- **不重写后端**：v1 全程零后端改动；如果发现协议不够用，先在前端 platform adapter 适配再说
- **不做 Web 能力裁剪**：PC 是上限不是取代，Web 用户可能用平板/浏览器登录
- **首启向导走极简**：只问后端 URL + token；不要再做账号系统
- **签名方面**：v1 如无证书就发未签名版 + 文档教用户绕过 SmartScreen；不为这个先停工

### 显式拒绝

| 项 | 拒绝原因 |
|---|---|
| Electron 壳 | 包体 / 调性不符 |
| WebCodecs API 替代 libmpv | DV/Atmos/HDR 没希望，工程上前进不到极限 |
| 把后端塞进客户端 | 自托管定位 + 工程量都不允许，永远不做 |
| 自动更新 | v1 不做；先稳住手动版本 |
| 移除外部播放器 handoff | 仍保留作为备选；用户可能更信任老朋友 |
| 多窗口（PiP/独立设置） | v2 再说，事件总线先不重构 |
| 在 Player 里写 mpv libc 绑定 | v1 走 IPC 简单，v2 看延迟决定是否上 native bind |
| 改字幕模块 | 用户冻结，libmpv 直接吃绑定后的字幕 URL |

---

## 9. 迁移阶段（按风险递增排）

每个阶段独立可验证，跑通后再进下一阶段。

### M0 · 准备 · 1 天

- 创建 `pc/` 目录骨架（空 Tauri 工程能 `cargo tauri dev` 起一个空白窗口）
- 验证 Windows 上 `mpv.exe` 能用 `--input-ipc-server=\\.\pipe\mpv` 起来
- 不改前端代码

**验收**：`cargo tauri dev` 起白窗 + cmd 起 mpv 用 IPC 发 `loadfile` 能播

### M1 · 平台抽象层 · 2-3 天

- 新增 `src/platform/` 三件套，所有现有代码改走 adapter
- API_BASE / clipboard / shell.open / device id 全部抽象
- Web 端行为零变化（`npm run dev` 跑通且 lint 过）
- PC 壳能跑，但仍是 webview 包浏览器，没新增能力

**验收**：Web 版回归无差异；PC 版能加载 webview 显示首页（fetch 用同一个后端）

### M2 · 外部协议 + 桌面化交互 · 1-2 天

- `MovieDetail.tsx` 外链按钮全部走 `shell.open`
- 窗口菜单、关闭确认、F11 全屏
- 首启 apiBase 向导（设置里也能改）

**验收**：PC 端点 PotPlayer/IINA/VLC 全唤得起；改后端 URL 走配置面板生效

### M3 · libmpv 嵌入（核心） · 5-7 天

- Rust 侧 `mpv.rs` 实现 spawn + IPC 命令封装（loadfile/seek/pause/speed/sub-add/property observer）
- 前端 `Player.pc.tsx` 实现：通过 `invoke('mpv_*')` 控制；React UI 仍渲染在 webview 里、libmpv 渲染在另一个 child window，前端定位/resize child window
- 字幕：`sub-add {url}` 直接挂；样式 → `set sub-*` 系列 property
- 历史心跳：监听 `time-pos` 改 `reportHistory` 节流逻辑
- 多源切换：复用现有 state，调用 `loadfile` 替代修改 src

**验收**：4K HEVC REMUX 用 D3D11VA 顺播；ASS 字幕 libass 渲染；多源切换不黑屏；进度同步到后端

### M4 · 桌面级打磨 · 2-3 天

- 桌面热键（空格/方向键/F/M/逗号点/方括号）
- 状态栏显示硬解 API + GPU 名 + 当前 codec/profile
- 错误处理：mpv 崩溃自动重启 + toast 通知
- 安装包打 MSI/NSIS

**验收**：MSI 装到一台干净机器能直接跑；硬解信息正确显示；ALL hot key 正常

### M5 · 发布 · 1 天

- 写 `pc/README.md` 安装文档
- README 主文档加 PC 入口
- GitHub Release 1.21.0-pc.0
- 更新顶层 `README.md` 截图墙加一张 PC 播放截图

**验收**：从 GitHub Releases 下载安装包能跑

总工期估算：**12-17 个工作日**（不含证书购买等行政时间）

---

## 10. 端到端验证清单

```
□ M0  Tauri 空壳 + mpv IPC 自验
□ M1  Web 版本 npm run dev 回归通过
□ M1  PC webview 版本能加载首页 + 列表
□ M2  PC 端 PotPlayer/IINA/VLC 唤起
□ M2  apiBase 配置面板生效（重启后保持）
□ M3  PC 播放 4K HEVC REMUX
        - 任务管理器看到 GPU vendor 占用上升、CPU 解码线程低
        - mpv stats 显示 hwdec=d3d11va 或 nvdec
□ M3  PC 播放 Dolby Vision Profile 5（应直出或 mapping）
□ M3  PC 播放含 ASS 特效字幕（libass 渲染对比 Web 提升）
□ M3  PC 多源切换（1080p ↔ 4K REMUX）进度无丢失
□ M3  历史心跳上报 - 跨设备续播验证
□ M4  PC 全屏 / 退出全屏 / 锁屏热键
□ M4  PC 错误注入：mpv 进程被 kill 后能恢复
□ M5  MSI 在干净 Win11 安装即用
□ M5  Web 端首页打开 PC 端推广入口指向 GitHub Release
```

---

## 11. 风险与开放问题

### 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| libmpv child window 与 webview 在同一 HWND 下渲染叠加问题（Win11 高 DPI） | 控件错位 | M0 阶段必须验通；不行就降级方案：mpv 渲染到 OpenGL/D3D 离屏 + 把 frame 发到 webview canvas（性能损失但能跑） |
| 后端流地址带 token query 参数 + mpv 的 referer/cookie 行为 | 鉴权失败 | mpv 通过 `--http-header-fields=Authorization: Bearer xxx` 注入；token 从 webview 取后 invoke 到 Rust 一并启动 |
| Windows SmartScreen 对未签名 exe 拦截 | 用户难装 | v1 文档教绕过；v2 想办法搞 EV 证书 |
| 字幕在 sidecar URL 是后端内部路径（需鉴权） | mpv 拉不下来 | `sub-add` 时同样注入 `http-header-fields`；或前端先 fetch 后存临时文件再 sub-add file:// |
| Tauri webview2 在不同 Win11 build 行为差异 | 前端样式碎掉 | v1 测 22H2 + 23H2 + 26H2；锁定最低 webview2 版本 |

### 开放问题（这些回答会决定后续 PR）

1. **打包包含 mpv.exe 还是首启下载？**
   - 包含：包体多 ~50MB，首装即用，对自托管玩家更友好
   - 下载：包体小但首启慢、断网装不上
   - **倾向：打包**
2. **代码签名证书要不要现在搞？**
   - 不搞：v1 发未签名版本，文档教绕 SmartScreen
   - 搞：EV 证书一年 ~3000 元，OV 便宜但 SmartScreen 仍要"刷信誉"
   - **倾向：v1 不搞，v2 视用户量决定**
3. **PC 客户端要不要支持配置多个后端实例切换？**
   - 当前问题：玩家可能同时有家里 NAS + 公司服务器
   - **倾向：v1 单实例；v2 加 profile**

---

## 12. 关联文件参考索引

```
现有文件（迁移基线）
─ frontend/src/components/Player.tsx               1972 行 · 状态机/字幕/音频转码主入口
─ frontend/src/api/core.ts                         API_BASE 注入点 + resolveAssetUrl
─ frontend/src/constants/index.ts:3                API_BASE 硬编码
─ frontend/src/features/MovieDetail.tsx:594-606    外部播放器 URL scheme 拼接
─ frontend/src/types/index.ts                      Movie/Resource/PlaybackUserData 单一来源
─ frontend/src/hooks/useAppRouting.ts              hand-rolled state 路由
─ frontend/index.html:20,29-38                     CDN script 历史遗留

新增文件（v1 范围）
─ frontend/src/platform/                           平台 adapter（web/pc 双实现）
─ frontend/src/components/Player.web.tsx           Web 版 video 实现
─ frontend/src/components/Player.pc.tsx            PC 版 mpv 实现
─ pc/src-tauri/                                    Tauri Rust 壳
─ pc/src-tauri/src/mpv.rs                          libmpv IPC bridge
```

---

## 13. 为什么这一版必须"一次到位"

按用户原话："尽量做到一次就迁移好，后面再做微调即可"。

这要求：

1. **平台抽象一次设计到位**：所有未来可能差异化的接口（存储、剪贴板、shell、文件对话框、播放器）现在就抽，后续加移动端只填实现不改接口
2. **Player 的双实现切割面要清晰**：M3 落地后，Web 实现和 PC 实现互不影响，加 codec / GPU 信息 / 倍速等等不需要碰对方
3. **后端契约不松动**：v1 不动后端；如果某个 PC 能力前端自己接不出来，先记问题，攒一批再回头改后端协议（避免来回往返）
4. **包体决策、签名决策、自动更新决策**这三件事 v1 都先 punt，专注在核心体验

照这份文档执行，v2 应该只剩 macOS port + 自动更新 + 多 profile 这种"加法"，不会出现"核心架构推倒重来"的局面。
