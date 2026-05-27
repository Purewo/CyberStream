; CyberStream PC NSIS Installer
; ----------------------------------------------------------------------------
; 同一份脚本支持 full / lite 两个 variant，通过 /DVARIANT=full|lite 切换。
;
; full  ：捆绑 cyber-backend.exe sidecar（含整套 Python+依赖），开箱即用
; lite  ：纯 Tauri shell，连远程后端
;
; 调用方式（build_setup.sh 会自动设好这些 -D 参数）：
;   makensis /DVARIANT=full /DAPP_VERSION=1.21.1-pc.4 /DSTAGING_DIR=... cyberstream.nsi
; ----------------------------------------------------------------------------

Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma

!ifndef VARIANT
  !define VARIANT "full"
!endif
!ifndef APP_VERSION
  !define APP_VERSION "0.0.0-dev"
!endif
!ifndef STAGING_DIR
  !error "STAGING_DIR not set; run via build_setup.sh"
!endif

!define APP_NAME       "CyberStream"
!define APP_PUBLISHER  "PureWo"
!define APP_IDENTIFIER "com.purewo.cyberstream"
!define APP_EXE        "cyberstream-pc.exe"
!define APP_URL        "https://github.com/Purewo/CyberStream"
!define UNINST_KEY     "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel admin
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "1.21.1.0"
VIAddVersionKey "ProductName"      "${APP_NAME}"
VIAddVersionKey "CompanyName"      "${APP_PUBLISHER}"
VIAddVersionKey "FileVersion"      "${APP_VERSION}"
VIAddVersionKey "ProductVersion"   "${APP_VERSION}"
VIAddVersionKey "FileDescription"  "CyberStream Installer (${VARIANT})"
VIAddVersionKey "LegalCopyright"   "© 2026 ${APP_PUBLISHER}"

; ─── Modern UI 2 ─────────────────────────────────────────────────────────────
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"

; 视觉资源（24-bit BMP3）
!define MUI_ICON "branding\app.ico"
!define MUI_UNICON "branding\app.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "branding\header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "branding\header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP "branding\welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "branding\welcome.bmp"
!define MUI_BGCOLOR "0c0c12"
!define MUI_TEXTCOLOR "f0f0f8"

; 走完安装/卸载默认勾「立即启动 / 浏览 ReadMe」之类，全部关掉保持冷淡赛博
; 朋克风
!define MUI_ABORTWARNING

; ─── 安装页 ──────────────────────────────────────────────────────────────────
!define MUI_WELCOMEPAGE_TITLE "$(WELCOME_TITLE)"
!define MUI_WELCOMEPAGE_TEXT  "$(WELCOME_TEXT)"
!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_COMPONENTS

!define MUI_PAGE_CUSTOMFUNCTION_LEAVE EnsureAppSubdir
!insertmacro MUI_PAGE_DIRECTORY

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "$(FINISH_RUN)"
!define MUI_FINISHPAGE_LINK "$(FINISH_LINK)"
!define MUI_FINISHPAGE_LINK_LOCATION "${APP_URL}"
!insertmacro MUI_PAGE_FINISH

; ─── 卸载页 ──────────────────────────────────────────────────────────────────
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; ─── 文案（中文） ────────────────────────────────────────────────────────────
!insertmacro MUI_LANGUAGE "SimpChinese"
!include "i18n_zh.nsh"

; ─── 组件 ────────────────────────────────────────────────────────────────────
; 主程序是必装的；快捷方式 / 开始菜单是可选项
Section "${APP_NAME} 主程序" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"

  File "${STAGING_DIR}\${APP_EXE}"
  File "${STAGING_DIR}\libmpv-2.dll"

  !if "${VARIANT}" == "full"
    File "${STAGING_DIR}\cyber-backend.exe"
  !endif

  ; 写注册表 + 卸载入口
  WriteRegStr HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\${APP_NAME}" "Variant"    "${VARIANT}"
  WriteRegStr HKLM "Software\${APP_NAME}" "Version"    "${APP_VERSION}"

  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName"     "${APP_NAME}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr HKLM "${UNINST_KEY}" "URLInfoAbout"    "${APP_URL}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1

  ; 估算占用大小
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" "$0"

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "桌面快捷方式" SecDesktop
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
SectionEnd

Section "开始菜单项" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

LangString DESC_SecMain      ${LANG_SIMPCHINESE} "$(COMP_DESC_MAIN)"
LangString DESC_SecDesktop   ${LANG_SIMPCHINESE} "$(COMP_DESC_DESKTOP)"
LangString DESC_SecStartMenu ${LANG_SIMPCHINESE} "$(COMP_DESC_STARTMENU)"

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain}      $(DESC_SecMain)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop}   $(DESC_SecDesktop)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} $(DESC_SecStartMenu)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ─── 卸载 ────────────────────────────────────────────────────────────────────
; 默认只删 Program Files 下的程序文件。卸载向导会问要不要顺便清空用户数据
; （%LOCALAPPDATA% + %APPDATA%），勾选后才动那俩目录 —— 避免误删数据库。

Var WipeUserData

Function un.PromptWipeData
  MessageBox MB_YESNO|MB_ICONQUESTION "$(UNINST_WIPE_PROMPT)" /SD IDNO IDYES wipe_yes IDNO wipe_no
  wipe_yes:
    StrCpy $WipeUserData "1"
    Goto done
  wipe_no:
    StrCpy $WipeUserData "0"
  done:
FunctionEnd

Section "Uninstall"
  Call un.PromptWipeData

  ; 先把可能还在跑的进程杀掉，否则 exe 文件被锁住，Delete 静默失败 → 残留
  ; /F 强杀，/T 连子进程一起带走（sidecar 可能 fork 出 ffmpeg / waitress worker）
  DetailPrint "$(UNINST_KILL_RUNNING)"
  nsExec::ExecToLog 'taskkill /F /IM "${APP_EXE}" /T'
  nsExec::ExecToLog 'taskkill /F /IM "cyber-backend.exe" /T'
  nsExec::ExecToLog 'taskkill /F /IM "cyber-backend-x86_64-pc-windows-msvc.exe" /T'
  ; 给系统 1.5s 释放文件句柄
  Sleep 1500

  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\libmpv-2.dll"
  Delete "$INSTDIR\cyber-backend.exe"
  Delete "$INSTDIR\cyber-backend-x86_64-pc-windows-msvc.exe"
  Delete "$INSTDIR\uninstall.exe"

  ; 兜底：把整个安装目录递归删掉，捕获任何遗漏的临时文件 / sidecar 解出来的
  ; PyInstaller 临时目录（_MEI*）。/REBOOTOK 表示如果还有占用就排队下次重启删。
  RMDir /r /REBOOTOK "$INSTDIR"

  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  DeleteRegKey HKLM "${UNINST_KEY}"
  DeleteRegKey HKLM "Software\${APP_NAME}"

  ${If} $WipeUserData == "1"
    ; 后端 sidecar 数据：DB / .env.local / 缓存
    RMDir /r "$LOCALAPPDATA\${APP_NAME}"
    ; WebView2 + Tauri shell 数据：localStorage / 代理配置 / cookie
    RMDir /r "$APPDATA\${APP_IDENTIFIER}"
    DetailPrint "$(UNINST_DATA_WIPED)"
  ${EndIf}
SectionEnd

Function un.onInit
  StrCpy $WipeUserData "0"
FunctionEnd

; ─── 安装初始化 ──────────────────────────────────────────────────────────────
Function EnsureAppSubdir
  ; 用户在 directory 页选完目录后调一次：如果最后一段不是 APP_NAME，
  ; 自动追加。避免用户把程序装进 E:\apps\ 这种"装满别的程序"的根目录里、
  ; 卸载时连无关文件一起带走。
  Push $0
  Push $1
  StrCpy $0 $INSTDIR
  ${GetFileName} $0 $1
  ${If} $1 != "${APP_NAME}"
    StrCpy $INSTDIR "$INSTDIR\${APP_NAME}"
  ${EndIf}
  Pop $1
  Pop $0
FunctionEnd

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "$(ERR_NEEDS_X64)"
    Abort
  ${EndIf}

  ; 先把当前可能在跑的进程统统杀掉，避免新安装写文件时被旧 sidecar / shell
  ; 锁住报「无法打开要写入的文件」。这一步无论有没有旧安装都要做 —— 用户
  ; 可能从快捷方式启动了应用，或者上次安装的 uninstall.exe 没有 kill 逻辑。
  nsExec::ExecToLog 'taskkill /F /IM "${APP_EXE}" /T'
  nsExec::ExecToLog 'taskkill /F /IM "cyber-backend.exe" /T'
  nsExec::ExecToLog 'taskkill /F /IM "cyber-backend-x86_64-pc-windows-msvc.exe" /T'
  Sleep 1500

  ; 检测旧版本，触发静默卸载
  ReadRegStr $0 HKLM "${UNINST_KEY}" "UninstallString"
  ${If} $0 != ""
    MessageBox MB_YESNO|MB_ICONQUESTION "$(EXISTING_INSTALL_PROMPT)" /SD IDYES IDNO done
    ExecWait '"$0" /S _?=$INSTDIR'
  ${EndIf}
  done:
FunctionEnd
