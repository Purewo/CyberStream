"""4K指南 (4kzn.com) —— 纯网盘资源站（夸克网盘），无磁力链接。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import (
    BaseSource, SearchResult, DetailResult, MagnetResult,
    TIMEOUT,
)


class FourKZhinanSource(BaseSource):
    name = "4kzhinan"
    base_url = "https://4kzn.com"
    priority = 10  # 网盘资源站，优先级独立于磁力站

    def headers(self, referer: str | None = None) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(self, keyword: str, page: int = 1) -> list[SearchResult]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        url = f"{self.base_url}/?post_type=book&s={quote(keyword)}"
        text = self.fetch_text(url)
        if not text:
            return []

        soup = BeautifulSoup(text, "lxml")
        results: list[SearchResult] = []
        seen: set[str] = set()

        for a in soup.select("a[href*='/book/']"):
            href = a.get("href", "")
            if not href or href in seen:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            seen.add(href)

            results.append({
                "title": title,
                "link": href,
                "category": "",
                "country": "",
                "years": "",
                "overview": "",
            })

        return results

    # ------------------------------------------------------------------
    # get_detail
    # ------------------------------------------------------------------

    def get_detail(self, url: str) -> DetailResult | None:
        link = (url or "").strip()
        if not link:
            return None

        text = self.fetch_text(link)
        if not text:
            return None

        soup = BeautifulSoup(text, "lxml")
        poster = self._parse_poster(soup)
        meta = self._parse_metadata(soup)
        cloud_links = self._parse_cloud_links(soup)

        return {
            "director": meta.get("director", ""),
            "writers": meta.get("writers", ""),
            "actors": meta.get("actors", ""),
            "description": meta.get("description", ""),
            "years": [meta["year"]] if meta.get("year") else [],
            "country": meta.get("country", ""),
            "language": meta.get("language", ""),
            "duration": meta.get("duration", ""),
            "aliases": meta.get("aliases", ""),
            "imdb": meta.get("imdb", ""),
            "genre": meta.get("genre", ""),
            "poster": poster,
            "source": self.name,
            "file_content": [],
            "cloud_links": cloud_links,
        }

    # ------------------------------------------------------------------
    # get_magnet — 纯网盘站，无磁力
    # ------------------------------------------------------------------

    def get_magnet(self, link: str) -> MagnetResult | None:
        return None

    # ------------------------------------------------------------------
    # 私有解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_poster(soup: BeautifulSoup) -> str:
        for img in soup.find_all("img", class_="lazy"):
            ds = img.get("data-src", "")
            if ds and "alicdn" in ds:
                return ds
        for img in soup.find_all("img", attrs={"data-src": True}):
            ds = img["data-src"]
            if ds and "t1.svg" not in ds:
                return ds
        return ""

    @staticmethod
    def _parse_metadata(soup: BeautifulSoup) -> dict[str, str]:
        meta: dict[str, str] = {}

        panel = soup.find("div", class_="panel-body")
        if not panel:
            for p in soup.find_all("p"):
                if "导演" in p.get_text():
                    panel = p.parent
                    break
        if not panel:
            return meta

        field_map = {
            "导演": "director",
            "编剧": "writers",
            "主演": "actors",
            "类型": "genre",
            "制片国家/地区": "country",
            "语言": "language",
            "上映日期": "release_date",
            "片长": "duration",
            "又名": "aliases",
            "IMDb": "imdb",
        }

        all_lines: list[str] = []
        for p in panel.find_all("p"):
            text = p.get_text("\n", strip=True)
            for line in text.split("\n"):
                line = line.strip().lstrip("\u201c\u201d\u300c\u300d\"'")
                if line:
                    all_lines.append(line)

        i = 0
        while i < len(all_lines):
            line = all_lines[i]
            matched = False
            for prefix, key in field_map.items():
                if line.startswith(prefix):
                    val = re.split(r"[:\uff1a]", line, maxsplit=1)
                    value = val[1].strip() if len(val) > 1 else ""
                    if not value and i + 1 < len(all_lines):
                        parts = []
                        j = i + 1
                        while j < len(all_lines):
                            if any(all_lines[j].startswith(p) for p in field_map):
                                break
                            parts.append(all_lines[j])
                            j += 1
                        value = " / ".join(parts) if parts else ""
                        i = j - 1
                    if value:
                        meta[key] = value
                    matched = True
                    break
            if not matched and len(line) > 80 and "description" not in meta:
                meta["description"] = line
            i += 1

        # 类型：从 booktag 链接提取，排除年份和国家
        _country_set = {
            "美国", "中国", "英国", "法国", "日本", "韩国", "德国", "意大利",
            "加拿大", "澳大利亚", "印度", "西班牙", "俄罗斯", "巴西", "墨西哥",
            "泰国", "中国大陆", "中国香港", "中国台湾", "香港", "台湾",
        }
        tags = []
        for a in panel.find_all("a", href=re.compile(r"/booktag/")):
            t = a.get_text(strip=True)
            if t and not t.isdigit() and t not in _country_set:
                tags.append(t)
        if tags:
            meta["genre"] = " / ".join(tags)

        # 年份
        rd = meta.get("release_date", "")
        ym = re.search(r"(\d{4})", rd)
        if ym:
            meta["year"] = ym.group(1)

        return meta

    @staticmethod
    def _parse_cloud_links(soup: BeautifulSoup) -> list[dict[str, str]]:
        cloud_links: list[dict[str, str]] = []

        for a in soup.find_all("a", href=re.compile(r"pan\.quark|quark\.cn")):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if not href:
                continue

            desc = ""
            parent = a.parent
            if parent:
                siblings_text = parent.get_text(strip=True)
                if siblings_text and siblings_text != text:
                    desc = siblings_text

            cloud_links.append({
                "provider": "夸克网盘",
                "url": href,
                "name": text or "夸克网盘",
                "description": desc,
            })

        return cloud_links
