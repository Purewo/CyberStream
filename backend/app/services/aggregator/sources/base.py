"""影视资源站点抽象基类与公共工具函数。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

import requests


# ---------------------------------------------------------------------------
# 公共工具函数
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    """清理文本：去除换行、制表符、首尾空白。"""
    return str(value).replace("\n", "").replace("\r", "").replace("\t", "").strip()


def clean_text_list(values: list[Any]) -> list[str]:
    """批量清理文本列表，过滤空字符串。"""
    out: list[str] = []
    for v in values:
        t = clean_text(v)
        if t:
            out.append(t)
    return out


def first(values: list[Any], default: str = "") -> str:
    """取列表第一个元素的字符串形式，空列表返回默认值。"""
    return str(values[0]) if values else default


def abs_url(path: str, base_url: str) -> str:
    """将相对路径转为绝对 URL。"""
    if not path:
        return ""
    if path.startswith(("http://", "https://", "magnet:?", "ed2k://")):
        return path
    if path.startswith("//"):
        return "https:" + path
    return base_url + path


def extract_size_text(text: str) -> str:
    """从文本中提取文件大小信息。"""
    value = clean_text(text)
    if not value:
        return ""
    if (value.startswith("(") and value.endswith(")")) or \
       (value.startswith("[") and value.endswith("]")):
        value = value[1:-1].strip()
    return value


def parse_size_from_text(text: str) -> str:
    """从任意文本中正则匹配文件大小（如 12.3GB）。"""
    m = re.search(r"\b\d+(?:\.\d+)?\s?(?:GB|G|MB|TB)\b", text, flags=re.I)
    return m.group(0).upper().replace(" ", "") if m else ""


# ---------------------------------------------------------------------------
# 默认 Headers 生成
# ---------------------------------------------------------------------------

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def make_headers(referer: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """生成通用浏览器 Headers。"""
    h: dict[str, str] = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": referer,
    }
    if extra:
        h.update(extra)
    return h


# ---------------------------------------------------------------------------
# 搜索结果 / 详情 / Magnet 的类型别名
# ---------------------------------------------------------------------------

SearchResult = dict[str, str]
"""搜索结果条目：title, link, category, country, years, overview"""

DetailResult = dict[str, Any]
"""详情结果：director, actors, description, years, poster, file_content, ..."""

MagnetResult = dict[str, str]
"""Magnet 结果：file_name, image, magnet"""


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

TIMEOUT = 12


class BaseSource(ABC):
    """影视资源站点抽象基类。

    每个站点子类需实现 search / get_detail / get_magnet 三个核心方法。
    子类可复用基类提供的 session 管理和公共工具。
    """

    name: str = ""
    """站点标识符，如 "bt7274"。"""

    base_url: str = ""
    """站点根 URL，如 "https://bt7274.cc"。"""

    priority: int = 99
    """站点优先级，数字越小越优先。"""

    def __init__(self) -> None:
        self._session: requests.Session | None = None
        self._proxy: str | None = None

    @property
    def session(self) -> requests.Session:
        """懒加载并复用 requests.Session。"""
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
            if self._proxy:
                self._session.proxies = {
                    "http": self._proxy,
                    "https": self._proxy,
                }
        return self._session

    def set_proxy(self, proxy: str | None) -> None:
        """设置代理地址（如 'http://127.0.0.1:10808'），None 表示清除。"""
        self._proxy = proxy
        if self._session is not None:
            if proxy:
                self._session.proxies = {"http": proxy, "https": proxy}
            else:
                self._session.proxies = {}

    def headers(self, referer: str | None = None) -> dict[str, str]:
        """生成该站点的默认请求 Headers，子类可覆盖。"""
        return make_headers(referer or self.base_url + "/")

    def fetch_text(self, url: str, **kwargs: Any) -> str | None:
        """GET 请求并返回响应文本，失败返回 None。子类可覆盖以处理反爬。"""
        headers = kwargs.pop("headers", None) or self.headers(referer=url)
        try:
            r = self.session.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException:
            return None
        if r.status_code >= 400:
            return None
        return r.text

    @abstractmethod
    def search(self, keyword: str, page: int = 1) -> list[SearchResult]:
        """搜索影片，返回统一格式的搜索结果列表。"""
        ...

    @abstractmethod
    def get_detail(self, url: str) -> DetailResult | None:
        """解析详情页，返回影片信息 + 资源列表。"""
        ...

    @abstractmethod
    def get_magnet(self, link: str) -> MagnetResult | None:
        """解析最终 magnet 链接。"""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} P{self.priority}>"
