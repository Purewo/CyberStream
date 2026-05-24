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
# - collect_all('ddddocr'/'OpenCC')：这两个库带本地模型/字典文件，
#   PyInstaller 静态分析看不到 .onnx / .json 资源，必须 collect-all 兜底。
# - datas 显式包了 backend/openapi/ 和 docs/，docs_routes 运行时按 BASE_DIR
#   读它们；冻结时 BASE_DIR == sys._MEIPASS（spec 把这两个目录放进去后
#   PyInstaller 会自动解到 _MEIPASS 下保留原相对路径）。

# ruff: noqa: F821 — Analysis/PYZ/EXE 等都是 PyInstaller 在 spec 上下文注入的内置名

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules


# spec 文件不一定跟 cwd 对齐；用 SPECPATH（PyInstaller 注入）兜回仓库根。
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ENTRY = os.path.join(REPO_ROOT, "backend", "run.py")


# 带模型/字典数据的库 → 整库收
ddddocr_datas, ddddocr_binaries, ddddocr_hidden = collect_all("ddddocr")
opencc_datas, opencc_binaries, opencc_hidden = collect_all("OpenCC")

# 后端自己的子模块全部显式收一遍——provider/factory 是 static import，但
# 后端有动态 importlib 用法（online_subtitles 加载用户安装的 skill 脚本，
# 那个不在 bundle 里；不过保险起见也把整个 backend.app 子模块树都列出
# 来，避免 PyInstaller 漏掉某个 lazy import 的服务模块）。
backend_submodules = collect_submodules("backend")

datas = [
    # docs_routes 运行时按 BASE_DIR/backend/openapi/ 读规范；冻结后 BASE_DIR
    # = sys._MEIPASS，所以这里路径必须保持相对仓库根的层级一致。
    (os.path.join(REPO_ROOT, "backend", "openapi"), "backend/openapi"),
    (os.path.join(REPO_ROOT, "docs"), "docs"),
]
datas += ddddocr_datas + opencc_datas

binaries = ddddocr_binaries + opencc_binaries

hiddenimports = (
    backend_submodules
    + ddddocr_hidden
    + opencc_hidden
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
    "matplotlib",   # ddddocr 偶尔会拉它；后端没用到，砍掉省 30+MB
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
