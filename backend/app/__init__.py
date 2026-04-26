from flask import Flask
from flask_cors import CORS
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


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(config)
    if config_overrides:
        app.config.update(config_overrides)

    # 显式配置 CORS：允许所有来源、所有路由、自动处理 Content-Type 和 Authorization
    CORS(app, resources={r"/*": {"origins": "*"}})

    # 使用重命名后的变量进行初始化，彻底避免 AttributeError
    db_ext.init_app(app)

    @app.route('/')
    def health_check():
        from backend.app.utils.response import api_response
        return api_response(data={"status": "up", "version": app.config.get("APP_VERSION", "unknown")}, msg="Pong")

    # 注册路由蓝图
    app.register_blueprint(api_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(libraries_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(homepage_bp)

    # 初始化数据库表
    with app.app_context():
        ensure_sqlite_schema(db_ext.engine)
        db_ext.create_all()

    return app
