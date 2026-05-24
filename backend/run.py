import os
import sys


def _load_env_from_data_dir():
    """冻结模式下从 %LOCALAPPDATA%\\CyberStream\\.env.local 加载环境变量。
    必须在 create_app() 之前调用，因为 backend.config 在导入期就读 os.getenv。

    源码 dev 模式不动 —— dev 用户惯于在仓库根放 .env.local，我们让现有
    的"导出环境变量再启动"流程继续工作；在 NAS 上由 systemd unit / docker
    -compose 注入 env，也用不到 dotenv。
    """
    if not getattr(sys, "frozen", False):
        return
    data_dir = os.path.join(
        os.environ.get("LOCALAPPDATA")
        or os.path.expanduser(r"~\\AppData\\Local"),
        "CyberStream",
    )
    env_path = os.path.join(data_dir, ".env.local")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        # python-dotenv 不在依赖里时静默跳过；spec 已经声明依赖，正常分发
        # 不会走到这里。
        return
    load_dotenv(env_path, override=False)


_load_env_from_data_dir()


try:
    from backend.app import create_app
except ModuleNotFoundError:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from backend.app import create_app

app = create_app()


def _runtime_port(frozen):
    raw = os.getenv("CYBER_PORT")
    if raw:
        try:
            value = int(str(raw).strip())
            if 1 <= value <= 65535:
                return value
        except (TypeError, ValueError):
            pass
    # 桌面单机模式 → 49152（IANA 动态/私有起点，冲突最少）；
    # 源码 dev 模式 → 5004（CLAUDE.md / docs / tests 全部基于这个端口）。
    return 49152 if frozen else 5004


def _runtime_host(frozen):
    explicit = os.getenv("CYBER_HOST")
    if explicit:
        return explicit
    # 打包成桌面应用时只对本机暴露；源码 dev 模式保持 0.0.0.0 方便手机/局域网测试。
    return "127.0.0.1" if frozen else "0.0.0.0"


if __name__ == '__main__':
    frozen = bool(getattr(sys, "frozen", False))
    host = _runtime_host(frozen)
    port = _runtime_port(frozen)

    if frozen:
        # 桌面捆绑：waitress 是 Windows 上的生产级 WSGI 服务器，跟 gunicorn
        # 等价但纯 Python、能在冻结二进制里跑。线程数留默认（4）足够单用户。
        from waitress import serve
        print(f"[cyber-backend] frozen runtime, serving on http://{host}:{port}", flush=True)
        serve(app, host=host, port=port)
    else:
        app.run(debug=True, host=host, port=port)
