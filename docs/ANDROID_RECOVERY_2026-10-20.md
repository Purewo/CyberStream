# Android 恢复入口

本次工作隔离在 `recovery/android-20261020/`，没有改动现有 Web、PC、后端代码；没有提交或推送 Git。

- 可编辑工程：`recovery/android-20261020/project/`
- 完整恢复交接、构建方法、验证边界：`recovery/android-20261020/RESTORATION.md`
- 原 APK：`recovery/android-20261020/original-apks/`
- 原调试包无修改解包：`recovery/android-20261020/original-debug-unpacked/`
- 桌面交付：`C:\Users\28788\Desktop\CyberStream-安卓恢复-20261020`
- 测试安装包：`CyberStream-Android-recovery-20261020.apk`，包名 `com.purewo.cyberstream.recovery`，不覆盖原 release/debug。
- 测试包 SHA-256：`572B57E4A85373F17D861249227603D224FEB7EABD239731C8C98D63E732B3E3`

关键新证据：旧手机模拟器仍保留无后缀包 `1021001` 和调试包 `1021017`，已先导出、验证签名并保存。此前把 `CyberStream-frontend-hosted-beta` 当作冗余目录的判断不成立，目录中确实存在独立安卓实现。不要继续把“GitHub 已同步”等同于这些未提交客户端改动已备份。

原生源码通过历史补丁和文件读回重建，FFmpeg AAR 从 WSL 找回；前端以现存 React 为基线整合。与原调试 APK 的 410 个非合成应用原生方法签名全部对应，但没有 source map，不能宣称所有原始 TSX/视觉优化已完整恢复。

已验证：前端恢复测试 7 项、模拟器仪器测试 18 项（含 11 种音频样本）、构建和签名、真实安卓 WebView 后端连接与片库展示、独立浏览器设置保存。模板 JVM 单测 1 项另计。真机、真实网盘播放及在线字幕业务仍待用户验收。

默认后端以用户本次指定的 `https://pioneer.fan:884/api` 为准，2026-10-20 实测鉴权 HTTP 200，允许 `https://localhost`。服务端由另一个 Codex 负责。

保留平板旧应用，等用户取回其 APK 后再比较版本/签名/资产。不要卸载旧包或使用恢复测试签名覆盖旧身份。
