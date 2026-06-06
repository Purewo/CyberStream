"""影视资源统一入口 —— 对外暴露 search_film / get_detail / get_magnet。"""

from __future__ import annotations

from typing import Any

from .sources import get_source, all_sources, SOURCE_NAMES, SOURCE_PRIORITY


def _prepare_source(source: str, proxy: str | None = None):
    """获取 source 实例并按需设置代理。"""
    s = get_source(source)
    s.set_proxy(proxy)
    return s


def search_film(keyword: str, page: int = 1, source: str = "rarbt", proxy: str | None = None) -> list[dict[str, str]]:
    """搜索影片。"""
    return _prepare_source(source, proxy).search(keyword, page=page)


def get_detail(url: str, source: str = "rarbt", proxy: str | None = None) -> dict[str, Any] | None:
    """获取影片详情。"""
    return _prepare_source(source, proxy).get_detail(url)


def get_magnet(link: str, source: str = "rarbt", proxy: str | None = None) -> dict[str, str] | None:
    """解析 magnet 链接。"""
    return _prepare_source(source, proxy).get_magnet(link)


__all__ = [
    "search_film",
    "get_detail",
    "get_magnet",
    "get_source",
    "all_sources",
    "SOURCE_NAMES",
    "SOURCE_PRIORITY",
]
