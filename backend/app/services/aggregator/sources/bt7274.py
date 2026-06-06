"""BT7274 资源站 —— 无反爬、magnet 直出、元数据最全。"""

from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from .base import (
    BaseSource, SearchResult, DetailResult, MagnetResult,
    TIMEOUT,
)


class BT7274Source(BaseSource):
    name = "bt7274"
    base_url = "https://bt7274.cc"
    priority = 1

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

        url = f"{self.base_url}/search"
        try:
            r = requests.get(url, params={"q": keyword},
                             headers=self.headers(), timeout=TIMEOUT)
            r.raise_for_status()
        except Exception:
            return []

        soup = BeautifulSoup(r.text, "lxml")
        results: list[SearchResult] = []
        seen: set[str] = set()

        for card in soup.select("a[href*='/detail/']"):
            href = card.get("href", "")
            m = re.search(r"/detail/(\d+)", href)
            if not m:
                continue
            douban_id = m.group(1)
            if douban_id in seen:
                continue
            seen.add(douban_id)

            h1 = card.find("h1")
            if not h1:
                continue
            title_text = h1.get_text(strip=True)
            tm = re.match(r"(.+?)\s*\((\d{4})\)", title_text)
            title = tm.group(1) if tm else title_text
            year = tm.group(2) if tm else ""

            results.append({
                "title": title,
                "link": f"{self.base_url}/detail/{douban_id}",
                "category": "",
                "country": "",
                "years": year,
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

        # 支持传入豆瓣 ID 或完整 URL
        if link.isdigit():
            link = f"{self.base_url}/detail/{link}"
        elif not link.startswith("http"):
            link = f"{self.base_url}{link}"

        try:
            r = requests.get(link, headers=self.headers(), timeout=TIMEOUT)
            r.raise_for_status()
        except Exception:
            return None

        soup = BeautifulSoup(r.text, "lxml")

        # 标题 & 年份
        h1 = soup.find("h1")
        title_text = h1.get_text(strip=True) if h1 else ""
        tm = re.match(r"(.+?)\s*\((\d{4})\)", title_text)
        title = tm.group(1) if tm else title_text
        year = tm.group(2) if tm else ""

        # 海报
        poster = self._parse_poster(soup)

        # 详情字段
        info = self._parse_info_fields(soup)

        # 简介
        description = self._parse_description(soup)

        # 评分
        douban_score = self._parse_douban_score(soup)
        imdb_score = self._parse_imdb_score(soup)

        # 资源表格
        file_content = self._parse_resources(soup)

        return {
            "director": info.get("director", ""),
            "writers": info.get("writers", ""),
            "actors": info.get("actors", ""),
            "description": description,
            "years": [year] if year else [],
            "country": info.get("country", ""),
            "language": info.get("language", ""),
            "release_date": info.get("release_date", ""),
            "duration": info.get("duration", ""),
            "tags": info.get("tags", ""),
            "douban_score": douban_score,
            "imdb_score": imdb_score,
            "poster": poster,
            "source": self.name,
            "file_content": file_content,
        }

    # ------------------------------------------------------------------
    # get_magnet
    # ------------------------------------------------------------------

    def get_magnet(self, link: str) -> MagnetResult | None:
        """BT7274 的 magnet 已在详情页直出，final_link 本身就是 magnet URI。"""
        link = (link or "").strip()
        if not link:
            return None
        if link.startswith("magnet:"):
            return {"file_name": "", "image": "", "magnet": link}
        return None

    # ------------------------------------------------------------------
    # 私有解析方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_poster(soup: BeautifulSoup) -> str:
        img = soup.find("img", alt="Movie Poster")
        if img and img.get("src"):
            src = img["src"]
            return src if src.startswith("http") else f"https://bt7274.cc{src}"
        return ""

    @staticmethod
    def _parse_info_fields(soup: BeautifulSoup) -> dict[str, str]:
        info: dict[str, str] = {}
        field_map = {
            "导演": "director", "编剧": "writers", "主演": "actors", "演员": "actors",
            "制片国家/地区": "country", "语言": "language",
            "上映日期": "release_date", "标签": "tags", "片长": "duration",
        }
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            for prefix, key in field_map.items():
                if text.startswith(prefix + ":") or text.startswith(prefix + "\uff1a"):
                    val = re.split(r"[:\uff1a]", text, maxsplit=1)[-1].strip()
                    if val:
                        info[key] = val
                    break
        return info

    @staticmethod
    def _parse_description(soup: BeautifulSoup) -> str:
        synopsis_h2 = soup.find("h2", string=re.compile("剧情简介"))
        if synopsis_h2:
            next_p = synopsis_h2.find_next_sibling("p")
            if next_p:
                return next_p.get_text(strip=True)
        return ""

    @staticmethod
    def _parse_douban_score(soup: BeautifulSoup) -> str:
        for a in soup.find_all("a", href=re.compile(r"movie\.douban\.com")):
            score_text = a.get_text(strip=True)
            ms = re.search(r"([\d.]+)", score_text)
            if ms:
                return ms.group(1)
        return ""

    @staticmethod
    def _parse_imdb_score(soup: BeautifulSoup) -> str:
        imdb_span = soup.find("span", string=re.compile(r"IMDb"))
        if imdb_span:
            for sib in imdb_span.find_all_next(string=True, limit=5):
                mi = re.search(r"([\d.]+)", sib.strip())
                if mi:
                    return mi.group(1)
        return ""

    @staticmethod
    def _parse_resources(soup: BeautifulSoup) -> list[dict[str, Any]]:
        tag_groups: dict[str, list[dict[str, str]]] = {}
        table = soup.find("table")
        if not table:
            return []

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else []

        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            name = tds[1].get_text(strip=True)
            size = tds[2].get_text(strip=True)
            tag = tds[3].get_text(strip=True)
            btn = tds[4].find("button", onclick=True)
            magnet = ""
            if btn:
                mm = re.search(
                    r"copyToClipboard\('(magnet:\?xt=urn:btih:[^']+)'\)",
                    btn.get("onclick", ""),
                )
                if mm:
                    magnet = mm.group(1)
            entry = {
                "file_name": name,
                "file_size": size,
                "final_link": magnet,
                "file_tag": tag,
            }
            tag_groups.setdefault(tag or "未分类", []).append(entry)

        file_content: list[dict[str, Any]] = []
        for quality, files in tag_groups.items():
            file_content.append({
                "quality": quality,
                "number": str(len(files)),
                "file_list": files,
            })
        return file_content
