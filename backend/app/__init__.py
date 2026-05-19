from flask import Flask
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from backend import config
from backend.app.extensions import db as db_ext
from backend.app.db.schema import ensure_sqlite_schema
from backend.app.api.routes import api_bp
from backend.app.api.system_routes import system_bp
from backend.app.api.library_routes import library_bp
from backend.app.api.libraries_routes import libraries_bp
from backend.app.api.history_routes import history_bp
from backend.app.api.storage_routes import storage_bp
from backend.app.api.player_routes import player_bp
from backend.app.api.homepage_routes import homepage_bp
from backend.app.api.auth_routes import auth_bp
from backend.app.api.docs_routes import docs_bp
from backend.app.security import require_api_token
from backend.app.services.users import bootstrap_admin


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(config)
    if config_overrides:
        app.config.update(config_overrides)

    if app.config.get("USER_MANAGEMENT_ENABLED") and not app.config.get("SESSION_SECRET"):
        raise RuntimeError("CYBER_SESSION_SECRET is required when user management is enabled")

    if app.config.get("TRUST_PROXY_HEADERS"):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=int(app.config.get("PROXY_FIX_X_FOR", 1) or 0),
            x_proto=int(app.config.get("PROXY_FIX_X_PROTO", 1) or 0),
            x_host=int(app.config.get("PROXY_FIX_X_HOST", 1) or 0),
            x_port=int(app.config.get("PROXY_FIX_X_PORT", 1) or 0),
            x_prefix=int(app.config.get("PROXY_FIX_X_PREFIX", 1) or 0),
        )

    app.secret_key = app.config.get("SECRET_KEY")
    app.config["SESSION_COOKIE_NAME"] = app.config.get("SESSION_COOKIE_NAME", "cyberstream_session")
    app.config["SESSION_COOKIE_HTTPONLY"] = app.config.get("SESSION_COOKIE_HTTPONLY", True)
    app.config["SESSION_COOKIE_SECURE"] = app.config.get("SESSION_COOKIE_SECURE", False)
    app.config["SESSION_COOKIE_SAMESITE"] = app.config.get("SESSION_COOKIE_SAMESITE", "Lax")
    app.config["PERMANENT_SESSION_LIFETIME"] = app.config.get("PERMANENT_SESSION_LIFETIME")

    # 显式配置 CORS：允许所有来源、所有路由、自动处理 Content-Type 和 Authorization
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=bool(app.config.get("CORS_SUPPORTS_CREDENTIALS", False)),
    )

    # 使用重命名后的变量进行初始化，彻底避免 AttributeError
    db_ext.init_app(app)

    @app.route('/')
    def health_check():
        from backend.app.utils.response import api_response
        return api_response(data={"status": "up", "version": app.config.get("APP_VERSION", "unknown")}, msg="Pong")

    app.before_request(require_api_token)

    # 注册路由蓝图
    app.register_blueprint(api_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(libraries_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(homepage_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(docs_bp)

    # 初始化数据库表
    with app.app_context():
        ensure_sqlite_schema(db_ext.engine)
        db_ext.create_all()
        bootstrap_admin(app)

    return app
