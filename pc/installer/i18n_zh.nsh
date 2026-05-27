; CyberStream installer · 简体中文文案
; 跟主脚本拆开方便后续多语言扩展。所有 LangString 都要先 !define 给 MUI 用，
; 再 LangString 一遍给宏 / 函数读 ${LANG_SIMPCHINESE}。

LangString WELCOME_TITLE ${LANG_SIMPCHINESE} "欢迎使用 CyberStream"
LangString WELCOME_TEXT ${LANG_SIMPCHINESE} "即将安装 ${APP_NAME} ${APP_VERSION}（${VARIANT}）。$\r$\n$\r$\n这是一个自托管的个人媒体库系统。点击「下一步」开始，或随时退出。"

LangString FINISH_RUN ${LANG_SIMPCHINESE} "立即启动 ${APP_NAME}"
LangString FINISH_LINK ${LANG_SIMPCHINESE} "访问 GitHub 项目主页"

LangString COMP_DESC_MAIN ${LANG_SIMPCHINESE} "主程序、libmpv 渲染内核及（完整版）后端服务，必装"
LangString COMP_DESC_DESKTOP ${LANG_SIMPCHINESE} "在桌面创建 ${APP_NAME} 快捷方式"
LangString COMP_DESC_STARTMENU ${LANG_SIMPCHINESE} "在开始菜单创建 ${APP_NAME} 文件夹与卸载入口"

LangString UNINST_WIPE_PROMPT ${LANG_SIMPCHINESE} "是否同步清空用户数据？$\r$\n$\r$\n选择「是」会删除：$\r$\n  · %LOCALAPPDATA%\${APP_NAME}（数据库 / TMDB Token / 缓存）$\r$\n  · %APPDATA%\${APP_IDENTIFIER}（WebView2 localStorage / 代理设置）$\r$\n$\r$\n此操作不可撤销。仅在彻底放弃当前媒体库时勾「是」。"
LangString UNINST_DATA_WIPED ${LANG_SIMPCHINESE} "用户数据已清空。"
LangString UNINST_KILL_RUNNING ${LANG_SIMPCHINESE} "正在结束 CyberStream 相关进程..."

LangString ERR_NEEDS_X64 ${LANG_SIMPCHINESE} "${APP_NAME} 仅支持 64 位 Windows。当前系统看起来是 32 位，安装中止。"
LangString EXISTING_INSTALL_PROMPT ${LANG_SIMPCHINESE} "检测到 ${APP_NAME} 已安装。是否先静默卸载旧版本再装新版？$\r$\n$\r$\n旧版本的用户数据（数据库 / 配置）不会被清除。"
