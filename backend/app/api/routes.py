"""Legacy compatibility routes.

说明：
- 本模块仅保留历史兼容接口，避免新增业务逻辑继续堆回旧 `routes.py`。
- 新增功能应优先落到按领域拆分后的模块：
  - `system_routes.py`
  - `library_routes.py`
  - `storage_routes.py`
  - `player_routes.py`
"""

import logging

from flask import Blueprint, jsonify

from backend.app.extensions import db
from backend.app.models import Movie

logger = logging.getLogger(__name__)

api_bp = Blueprint('legacy_api', __name__, url_prefix='/api/v1')


# 临时注释：用于排查前端是否仍依赖旧接口 `/api/v1/movies/recommend`
#
# @api_bp.route('/movies/recommend', methods=['GET'])
# def recommend():
#     """旧兼容接口：随机返回 6 部影片详情。"""
#     movies = Movie.query.order_by(db.func.random()).limit(6).all()
#     return jsonify([m.to_detail_dict() for m in movies])
