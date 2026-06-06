"""影视资源统一入口 —— 对外暴露 search_film / get_detail / get_magnet。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from .sources import get_source, all_sources, SOURCE_NAMES, SOURCE_PRIORITY


def _prepare_source(source: str, proxy: str | None = None):
    """获取 source 实例并按需设置代理。"""
    s = get_source(source)
    s.set_proxy(proxy)
    return s


def _normalize_source_link(source_obj, link: str, *, allow_magnet: bool = False) -> str:
    raw = (link or "").strip()
    if not raw:
        raise ValueError("link required")

    lower = raw.lower()
    if lower.startswith(("magnet:?", "ed2k://")):
        if allow_magnet:
            return raw
        raise ValueError("magnet and ed2k links are only accepted by the magnet endpoint")

    if source_obj.name == "bt7274" and raw.isdigit():
        return raw

    if raw.startswith("//"):
        normalized = f"https:{raw}"
    else:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise ValueError("only http and https links are supported")
        normalized = raw if parsed.scheme else urljoin(source_obj.base_url.rstrip("/") + "/", raw)

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("invalid source link")
    if host not in source_obj.allowed_hosts:
        raise ValueError(f"link host is not allowed for source {source_obj.name}")
    return normalized


def search_film(keyword: str, page: int = 1, source: str = "rarbt", proxy: str | None = None) -> list[dict[str, str]]:
    """搜索影片。"""
    return _prepare_source(source, proxy).search(keyword, page=page)


def get_detail(url: str, source: str = "rarbt", proxy: str | None = None) -> dict[str, Any] | None:
    """获取影片详情。"""
    source_obj = _prepare_source(source, proxy)
    return source_obj.get_detail(_normalize_source_link(source_obj, url))


def get_magnet(link: str, source: str = "rarbt", proxy: str | None = None) -> dict[str, str] | None:
    """解析 magnet 链接。"""
    source_obj = _prepare_source(source, proxy)
    return source_obj.get_magnet(_normalize_source_link(source_obj, link, allow_magnet=True))


__all__ = [
    "search_film",
    "get_detail",
    "get_magnet",
    "get_source",
    "all_sources",
    "SOURCE_NAMES",
    "SOURCE_PRIORITY",
]
