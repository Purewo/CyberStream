# CyberStream Android 恢复交接 — 2026-10-20

## 先看结论

已生成可独立安装的源码重建测试版，并从本机旧手机模拟器取回两个真实旧 APK。旧 APK、重建源码和测试版均已保留，不需要卸载平板上的旧应用。

测试版：`CyberStream-Android-recovery-20261020.apk`

- 应用名：CyberStream 恢复测试
- 包名：`com.purewo.cyberstream.recovery`
- 版本：`1.21.1-recovery-20261020`，versionCode `1021017`
- 最低 Android 7.0 / API 24；包含 arm64-v8a、armeabi-v7a、x86、x86_64
- 默认后端：`https://pioneer.fan:884/api`
- 后端修改入口：右上角头像 → 系统配置 → 后端服务器。恢复测试版只接受 HTTPS，保存后刷新。
- 不覆盖旧的 `com.purewo.cyberstream` 或 `com.purewo.cyberstream.debug`，数据也不共享。
- 调试签名，只用于此次恢复验收；自动安装更新已禁用，未发布到 GitHub。

## 真实旧 APK 已找回

来源：本机 `Medium_Phone_API_36.1` 模拟器。使用 `-read-only -no-snapshot-save -no-snapshot-load` 启动，先导出旧包，再安装独立恢复包；未卸载、清数据或覆盖旧应用。

| 文件 | 原包名 | 版本 | SHA-256 |
| --- | --- | --- | --- |
| CyberStream-original-debug.apk | com.purewo.cyberstream.debug | 1.21.1-debug-nativeaudio / 1021017 | AFF93BF2C009FA974B3C14CF3ED8B80BAF46F1F30A0DD8977C1CEEA98C0E5CE9 |
| CyberStream-original-release.apk | com.purewo.cyberstream | 1.21.1 / 1021001 | 8BC5E1E4A11E628838A9232CB34E9F5B3607F18ED59EF1C3959DF9191C00C9BA |

两个 APK 的 v2 签名均通过验证。文件名中的 release 仅区分无后缀包名，不代表已验证正式发布证书。

旧包仍使用历史后端 `https://apicyber.gameuniverse.top:40162/api`。请优先安装恢复测试版；不要为了安装旧包而卸载平板上的现存应用。明天平板上的 APK 仍值得导出比对，不能假定它与模拟器版本完全一样。

## 源码恢复依据与边界

1. 原 Codex 会话：`019f48c8-07b3-77c2-91ef-4deb1b6da6f7`，记录覆盖 2026-07-09 至 2026-07-17。
2. 只将成功文件补丁当作数据解析；没有执行历史命令。严格上下文回放得到 73 个历史涉及文件，其中有 34 次补丁因缺失/不同前端基线未整段套用；它们保留在 `project-replay-audit.json`，没有伪装成全部成功。
3. 原生 Kotlin、XML、Gradle 配置以历史回放为主。自动连播的历史修改不在补丁事件中，另从会话第 9197 行的文件读回结果恢复 `switchEpisodeBy`、`handlePlaybackEnded` 和播放器结束回调。
4. 共享 React 界面以现存前端为基线，逐片段恢复 Android 会话 v2、选集/季索引、技术信息、票据、字幕搜索/预览/绑定、按需云清晰度和原生播放入口。已人工整合恢复冲突，仍不能声称是原目录逐字完整复原。
5. 原 APK 的 59 项应用资产/DEX/原生库已无修改导出至 `original-debug-unpacked/`。没有 source map，因此原包保留了真实编译产物，但不能由此声称已取回全部原始 TSX 源码。
6. 对照原调试 APK 与重建 APK：应用自己的 410 个非合成原生方法签名全部匹配，无缺失/新增。此检查只证明方法结构对应，不证明方法实现完全相同。
7. 原 FFmpeg AAR 从 WSL 构建环境找回，SHA-256 与历史记录一致：`8721422B552D0BEAE9222B265B6BE580EC2C6215493602D51195E361C8719916`。

此次恢复额外修正了 API 相对路径丢失 `/api`、重复点击播放器、慢健康探测阻塞播放、特别篇季号 0、Android 后端地址不可修改和错误推荐 Windows 更新包等问题。取消前端打包配置中的环境 API key 注入，未添加任何新凭据。

未修改原仓库的 Web/PC/后端实现；安卓改动隔离在 `recovery/android-20261020/project/`。没有 Git commit/push。旧 PC 恢复物不动。

## 已验证

- TypeScript 检查、Vite 正式构建、Capacitor Android 同步成功。
- 新增 7 项前端恢复回归测试全部通过。
- Android `assembleDebug`、`assembleDebugAndroidTest`、`testDebugUnitTest` 成功。JVM 单测只有模板示例 1 项，不作为播放器功能覆盖。
- 安卓模拟器：应用入口与 FFmpeg 扩展 2 项、播放器界面/行为 15 项、音频格式测试 1 项全部通过，共 18 项。
- 音频测试内部覆盖 AAC、AC-3、E-AC-3、E-AC-3 JOC、DTS、DTS-HD MA、DTS:X、TrueHD 5.1、FLAC 24-bit、Opus 5.1、Vorbis。验证了解码器初始化及预期 FFmpeg 回退，不证明 Atmos/DTS:X 对象音频输出、多声道透传或真机听感。
- 真实安卓 WebView：`https://localhost`，平台 android，CyberPlayer 插件可用，当前后端鉴权 HTTP 200，真实片库首页正常展示。
- 独立 Chrome 页面检查：手机尺寸登录页、首页、系统配置页可显示；后端输入可编辑，保存及刷新成功；检查期间无页面异常或失败网络请求。
- `chrome-devtools` MCP 因现有配置目录被占用无法连接，未关闭用户浏览器；使用独立 Playwright Chrome 和安卓 WebView CDP 完成上述检查，不将其冒称为 MCP 验收。
- APK v2 签名校验通过，包名已实查为 `.recovery`；包内 44 个构建资源与本次 `dist` 完全一致。

测试过程曾有两个环境问题：并行模拟器导致 Java 虚拟内存不足，降低并发/错开构建后通过；音频样本初放外部目录被 Android 权限拒绝，改放恢复包自己的内部文件目录后 11 种样本全部通过，未扩大应用权限。

## 尚未验证

- 用户平板/手机的硬件解码、HDR、长时播放、蓝牙、多声道、后台/PiP 在各厂商系统上的表现。
- 真实网盘资源端到端播放、在线字幕提供商的搜索/下载/绑定、登录账号跨站 Cookie 保持。原生自动化主要使用公开短片和测试数据，不等于这些线上业务验收。
- 原目录所有前端视觉优化是否逐一恢复；明天继续用真实旧 APK 和用户反馈比对。
- 原发布私钥未恢复；本次没有尝试签名升级原应用。

## 给用户的自测顺序

1. 只安装 `CyberStream-Android-recovery-20261020.apk`，确认桌面名字为“CyberStream 恢复测试”。保留旧图标、旧包和数据。
2. 首页能否加载；进入一部电影并播放，检查拖动、音轨、字幕样式/颜色/延迟、横竖屏。
3. 找一部剧检查选季、选集、下一集和跨季连播。
4. 分别尝试普通音频与 DTS/TrueHD；再检查清晰度和在线字幕。某项失败时记录影片、来源、设备型号、Android 版本和界面截图。
5. 平板旧包找到后请导出，不要先卸载。现有模拟器旧包已另存，不再是仅靠聊天历史重建的状态。

## 继续开发 / 复建

恢复源码 ZIP 内 `project/` 是独立 Android 工程。使用 Node、JDK 21、Android SDK 36：

```powershell
cd project
.\build-recovery.ps1 -InstallDependencies
# 本机需要代理下载 Gradle/Maven 时可显式追加 -ProxyPort 10808
```

脚本按顺序运行前端测试、构建、同步和 Android 编译，限制 Gradle 并发，不修改全局代理或开发工具配置。依赖由 package-lock 锁定；AAR 与构建说明一并保存。原始会话不是源码 ZIP 的必要运行依赖。

`original-debug-unpacked/` 与原始回放证据保留在工作区；源码 ZIP 不含 node_modules、编译缓存、会话全文、设备账号数据、`.env` 或任何签名私钥。
