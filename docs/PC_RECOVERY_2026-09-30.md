# Windows PC 恢复记录（2026-09-30）

## 为什么缺失

`main` 的提交同步不等于所有开发目录已合并。当前仓库的原生播放器停留在
2026-05-31 的实现；用户使用过的后续开发位于已删除的
`CyberStream-frontend-hosted-beta/pc/`。本次以安装版 `1.21.1-pc.7`、Claude
成功编辑记录和历史读取片段恢复，不再以版本号或目录是否有 Git 判断完整性。

## 保全与恢复依据

- 安装版原件仍位于 `E:\apps\CyberStream`，本次未覆盖。
- `recovery/installed-pc-20260930/`：EXE/DLL 副本、SHA-256、12 个提取资源。
- `recovery/pre-pc-repair-20260930/`：恢复前 Web/PC 源码和 PC 构建配置备份。
- `recovery/pc-source-candidate/`：独立历史候选、逐条来源和缺口记录。
- 原生部分以 Git `d853118` 为基线重放 57 条 hosted 分支成功编辑；72 个历史
  Read 片段验证一致。9 个原生文件都有候选，不把失败工具调用当作完成。
- 原生历史恢复覆盖到 2026-06-24；已审阅记录中没有随后到 7 月 8 日的新增 PC Rust 编辑。
- 部分前端大文件没有完整历史原文，采用成功补丁和安装包功能证据整合，保留当前 WIP。
  这些文件不宣称逐字节还原；安装包没有 source map，不能用它证明完整源代码谱系。

## 已恢复/修复

- 播放器设置齿轮：亮度、对比度、饱和度、Gamma、画面比例、字幕样式、同步、倍速、
  A-B、睡眠定时和截图；字幕/音轨独立弹层和详细字幕信息。
- 播放票据、清晰度及字幕地址、外播字幕失败提示、观看历史心跳和 `last_watched` 排序。
- 票据按后端和登录会话隔离，禁止向第三方 CDN 附带；登出/切后端时失效。
- 修复字幕相对路径丢 `/api`、异步字幕结果串集、切集残留 A-B、原生异步命令悬空指针。
- 设置属性由 mpv 实际值回推，拒绝设置时不显示假成功；字幕置于视频区域而非控制栏下面。
- 弹层滚动到底部后保持视口高度；主题本地持久化；排序切换重置分页；空专辑创建按钮；
  海报有界重试保留多来源回退。
- PC 恢复为纯客户端启动，不自动拉起旧 Python sidecar。PC 后端地址仍独立可编辑，
  接受根 HTTPS 地址并自动补 `/api`，保留合法 localhost。
- 生产页面移除阻塞加载的 Tailwind CDN 脚本和 esm.sh importmap；改用本地 Tailwind 3
  构建 CSS，嵌入应用。动态 Google 字体是可回退的呈现依赖，不再阻塞 React 入口。

Web 和 PC 使用共享 React 文件，上述排序、图片及本地偏好改动同时影响 Web；
Android 未启动，后端实现未修改。

## 验证

- 前端类型检查与生产构建通过；8 个 focused PC 前端测试通过。
- Rust `cargo test --lib --no-default-features`：10 passed，包含真实 libmpv 属性读写及观察事件。
- 独立真实 Chrome 组件验收：排序/翻页/切库、空态创建、图片失败重试和换源取消。
- 主浏览器实际访问服务器：首页 60 张海报加载，首页/认证态/历史/资源库 API 返回 200。
- Windows WebView2 检测到 Tauri、已保存的后端 `https://pioneer.fan:884/api`，实际显示片库。
- 原生 Windows 播放本地 H.264/AAC 测试片及 SRT，通过窗口点击与 mpv IPC 双重验证：
  初始字号 38 与 UI 一致；亮度 25、对比度 55、饱和度 -62、Gamma 30；字号 53、位置 20、
  黄色字幕；字幕偏移 -2.6s、音频偏移 2.7s；倍速 1.5；A=20.625、B=50。
- 睡眠定时可开启/取消；未等待完整 15 分钟到期。截图按钮实际生成 `recovery/mpv-shot0001.jpg`。
- 测试参数仅属于临时本地播放会话，关闭测试播放器后不保存为用户默认。
- 证据位于 `recovery/native-final-*.png`、`recovery/mpv-final-*.json`、
  `recovery/audit-20260930/`。真实在线字幕来源、每种云盘和第三方播放器未逐一全覆盖。

## 后端交接项

任务内直连 smoke 57 项中 54 通过：健康/数据库/1.21.0、OpenAPI 1.21.0-beta 的 11 模块、
Range 302、外播/字幕契约、存储健康和 TMDB token 校验均通过。
失败 3 项：fallback 待复核 71、episode 待复核 2（均超脚本默认阈值 0），以及
limit=500 的资源治理 live-check 超过 8 秒。没有批量发布、清理或修改队列。

`GET /api/v1/user/preferences` 实测 404；云端偏好、个人主页配置和相关托管版业务需要
服务器端契约支持。历史代码已保全，本次只启用本地偏好，不把个人操作改写成全局设置。
原 smoke 继承 Windows 系统代理导致缓慢；验证 wrapper 仅本次强制直连，不改系统代理。

**独立 PC 连后端仍需要服务端 CORS 配置：** 用嵌入生产资源的 Windows WebView2 实测
`location.origin = http://tauri.localhost`，携带 Cookie 的 `/api/v1/auth/me` 请求报
`TypeError: Failed to fetch`。同 Origin 的直接 HTTP 探测返回 200，但没有
`Access-Control-Allow-Origin` / `Access-Control-Allow-Credentials`。
服务器端 Codex 需要将 `http://tauri.localhost` 加入可信来源，并回显具体 Origin 和
`Access-Control-Allow-Credentials: true`，同时覆盖预检和实际响应。
不能以开发地址 `127.0.0.1:41731` 联调通过宣称独立发行版联调已通过；本次未绕过浏览器安全检查。

## 继续开发与发布边界

从仓库运行 `powershell -ExecutionPolicy Bypass -File pc/scripts/dev.ps1`。
默认复用本仓库的 `127.0.0.1:41731` Vite；若被其它应用占用则拒绝，不停止其它服务。
关闭 PC 后保留 Web 热更新。安装版及用户数据库不被脚本覆盖。

调试专用的 `CYBER_DEVTOOLS_PORT` 和 `CYBER_MPV_TEST_PIPE` 仅存在于 debug 构建且默认关闭，
release 不提供测试端点。恢复版保持 `1.21.1`/`pc.7` 历史标识，不代表新的官方发布。

本次源码是本地未提交恢复成果，尚未推送 GitHub；不能再把 `HEAD=origin/main` 解释为
工作目录和全部历史成果已备份。清理任何恢复目录或旧开发目录前，必须核对文件内容和备份。

## 同日补充：恢复遗漏的 6 月 12 日按钮交互

用户指出加减按钮和字幕真彩色块缺失。重新核对成功 Edit 记录后确认：先前重放的是
6 月 21–24 日 hosted 版本，遗漏了 6 月 12 日另一条开发线的界面优化，不能因记录较早而排除。

本次合入到当前已修复的播放器：

- 画面四项改为左右减/加（每次 5、限制 -100..100），提供“全部重置”。
- 字幕/音频同步改为 -1/-0.5/+0.5/+1 秒增量按钮。
- 字号用 A-/A+ 调节 `sub-scale`（每次 0.1、范围 0.3..3），提供重置。
- 位置上移/下移（每次 5），颜色用真实白/黄/绿/青色块及选中标记。
- 恢复描边粗细（每次 0.5）和半透明黑色背景开关。
- 保留 PGS/VobSub 禁用样式、ASS 显式强制覆盖、mpv 属性真值回推和全部播放修复。

背景需要配合 `sub-border-style=background-box`，只设置颜色原本只会影响阴影；依据
[mpv 手册](https://mpv.io/manual/master/#options-sub-border-style) 修正了此行为。
真机验收还发现 `sub-border-size` 旧别名的观察事件会漏后续更新，改用规范属性
`sub-outline-size`；新增“先接收初始值，再修改/复位”的真实 libmpv 回归，先失败后修复通过。
快速连点加号还暴露了旧的全屏手势冲突：原逻辑只排除底栏/侧栏，没有排除弹层。
现设置/音轨/字幕弹层打开时不将双击解释为全屏，连续两次加描边实测由 1.65 到 2.65，
窗口保持 1264×681 客户区。弹层高度通过显式最小视口固定，滚动/重开不再逐步变矮。

Rust 回归更新为 11 passed。真实 Windows 点击验证了字号1.1倍、字幕上移到95、黄色字幕、
同步+0.5/-0.5秒、描边和背景、画面各项±5及全部归零。测试使用独立进程/临时视频，
未操作用户原来打开的影片。截图与参数证据位于 `recovery/ui-controls-20260930/`。

界面补充后的源码备份为 `recovery/CyberStream-PC-recovered-source-20260930-ui-controls.zip`；
先前 `-final.zip` 保留为第一轮历史恢复快照，不代表此次补充后的最终源码。
