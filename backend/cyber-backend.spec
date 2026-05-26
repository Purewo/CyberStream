# cyber-backend.spec — PyInstaller spec for CyberStream backend.
#
# Build: from repo root run
#   py -3.10 -m PyInstaller backend/cyber-backend.spec --clean --noconfirm
# 产物 dist/cyber-backend.exe 双击即可启动；冻结模式下端口默认 49152，
# 数据目录 %LOCALAPPDATA%\CyberStream\。Tauri sidecar 会复制成
# pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe。
#
# 设计决策：
# - onefile：分发简单（一个 exe），代价是每次启动 PyInstaller 解压 ~15s
#   的首启延迟（第二次起命中 _MEIPASS 缓存会快）。后续若启动慢可以改 onedir。
# - 在线字幕 provider 现在随后端一起打包。SubHD/SrtKu 的验证码/WAF 路径
#   需要 ddddocr/Pillow/onnxruntime，完整版必须收进去，否则 PC 端会能搜但
#   绑定/下载字幕不稳定。代价是 exe 明显增大。
# - datas 显式包了 backend/openapi/ 和 docs/，docs_routes 运行时按 BASE_DIR
#   读它们；冻结时 BASE_DIR == sys._MEIPASS（spec 把这两个目录放进去后
#   PyInstaller 会自动解到 _MEIPASS 下保留原相对路径）。

# ruff: noqa: F821 — Analysis/PYZ/EXE 等都是 PyInstaller 在 spec 上下文注入的内置名

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules


# spec 文件不一定跟 cwd 对齐；用 SPECPATH（PyInstaller 注入）兜回仓库根。
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ENTRY = os.path.join(REPO_ROOT, "backend", "run.py")


# 后端自己的子模块全部显式收一遍——provider/factory 是 static import；
# online_subtitles 默认加载项目内置 provider，也保留 GET_SUBTITLES_SKILL_DIR
# 作为开发调试 override。这里把整个 backend.app 子模块树列出来，避免
# PyInstaller 漏掉某个 lazy import 的服务模块。
backend_submodules = collect_submodules("backend")
ddddocr_datas, ddddocr_binaries, ddddocr_hiddenimports = collect_all("ddddocr")

datas = [
    # docs_routes 运行时按 BASE_DIR/backend/openapi/ 读规范；冻结后 BASE_DIR
    # = sys._MEIPASS，所以这里路径必须保持相对仓库根的层级一致。
    (os.path.join(REPO_ROOT, "backend", "openapi"), "backend/openapi"),
    (os.path.join(REPO_ROOT, "docs"), "docs"),
    (
        os.path.join(REPO_ROOT, "backend", "app", "services", "online_subtitle_providers"),
        "backend/app/services/online_subtitle_providers",
    ),
    *ddddocr_datas,
]

binaries = [*ddddocr_binaries]

hiddenimports = (
    backend_submodules
    + ddddocr_hiddenimports
    + [
        # waitress 通过 setuptools entry-point 加载；PyInstaller 静态分析
        # 时偶尔漏掉，显式列出以防万一。
        "waitress",
        # python-dotenv 在 backend/run.py 里 lazy import，PyInstaller 静态
        # 分析容易遗漏。
        "dotenv",
        # cryptography 的后端是 cffi 编译的子模块，PyInstaller 6.x 通常
        # 自带 hook 能收，列在这里只是兜底说明。
        "cryptography.hazmat.backends.openssl",
    ]
)


excludes = [
    "tkinter",      # 后端不用 GUI 工具包
    "matplotlib",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "gunicorn",     # Linux-only 的 dev 服务器，冻结路径走 waitress
    "pytest",
    "pytest_mock",
    "ipython",
    "notebook",
    "jupyter",
    "OpenCC",
    "opencc",
]


a = Analysis(
    [ENTRY],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cyber-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX 压缩 + Windows 杀毒 = 误报概率拉满，关掉
    upx_exclude=[],
    runtime_tmpdir=None, # 用默认 %TEMP%，避免 onefile 解到奇怪位置
    console=True,        # 留 console 方便看 Flask / waitress 日志；
                         # M2 接入 Tauri 后改成 False 再切到 windowed 模式
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
