"""聚合搜索（外部影视资源站）服务包。

把原 pc/aggregator skill 整合进后端：film_resource_core 暴露 search/detail/magnet
三个能力，sources/ 下是各资源站的抓取实现。由 backend/app/api/aggregator_routes.py
包成 /api/v1/aggregator/* 接口，不再单独起 bridge 端口。
"""

from .film_resource_core import (
    search_film,
    get_detail,
    get_magnet,
)
from .sources import SOURCE_NAMES, SOURCE_PRIORITY, get_source, all_sources

__all__ = [
    "search_film",
    "get_detail",
    "get_magnet",
    "get_source",
    "all_sources",
    "SOURCE_NAMES",
    "SOURCE_PRIORITY",
]
