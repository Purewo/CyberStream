"""Hdzu 资源站 —— 速度快，做兜底。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from lxml import etree

from .base import (
    BaseSource, SearchResult, DetailResult, MagnetResult,
    clean_text, clean_text_list, first, abs_url, parse_size_from_text,
    make_headers, TIMEOUT,
)


class HdzuSource(BaseSource):
    name = "hdzu"
    base_url = "https://www.hdzu.cc"
    priority = 6

    def headers(self, referer: str | None = None) -> dict[str, str]:
        return make_headers(referer or self.base_url + "/")

    # ------------------------------------------------------------------
    # 反爬：403 cookie 握手
    # ------------------------------------------------------------------

    def fetch_text(self, url: str, **kwargs: Any) -> str | None:
        headers = kwargs.pop("headers", None) or self.headers(referer=url)
        try:
            r = self.session.get(url, headers=headers, timeout=TIMEOUT)
        except Exception:
            return None

        # 403 时重试一次（cookie 握手）
        if r.status_code == 403:
            try:
                r = self.session.get(url, headers=headers, timeout=TIMEOUT)
            except Exception:
                return None

        if r.status_code >= 400:
            return None
        return r.text

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _fetch_html(self, url: str) -> etree._Element | None:
        text = self.fetch_text(url)
        if text is None:
            return None
        return etree.HTML(text)

    def _fetch_html_text(self, url: str) -> str:
        text = self.fetch_text(url)
        if text is None:
            raise Exception(f"request failed: source={self.name} url={url}")
        return text

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(self, keyword: str, page: int = 1) -> list[SearchResult]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        url = f"{self.base_url}/movie/filter?act=title&wd={quote(keyword)}"
        if page > 1:
            url += f"&page={page}"

        html = self._fetch_html(url)
        if html is None:
            return []

        pairs = list(zip(html.xpath("//h2/a/text()"), html.xpath("//h2/a/@href")))
        if not pairs:
            pairs = list(zip(
                html.xpath("//a[contains(@href,'/t/')]/text()"),
                html.xpath("//a[contains(@href,'/t/')]/@href"),
            ))

        results: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()

        for title, link in pairs:
            ct = clean_text(title)
            cl = abs_url(clean_text(link), self.base_url)
            if not ct or "/t/" not in cl:
                continue
            key = (ct, cl)
            if key in seen:
                continue
            seen.add(key)

            ym = re.search(r"\b(19\d{2}|20\d{2})\b", ct)
            results.append({
                "title": ct,
                "link": cl,
                "category": "",
                "country": "",
                "years": ym.group(1) if ym else "",
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

        html_text = self._fetch_html_text(link)
        document = etree.HTML(html_text)
        if document is None:
            return None

        info_lines = clean_text_list(
            document.xpath("//div[contains(@class,'movie-info')]//p//text()"))
        director, actors, description, years, douban_score, imdb_score = \
            self._parse_metadata(info_lines)

        poster = first(clean_text_list(document.xpath(
            "//div[contains(@class,'movie-pic')]//img/@src"
            " | //div[contains(@class,'topic-content')]//img/@src"
            " | //meta[@property='og:image']/@content"
        )))
        poster = abs_url(poster, self.base_url)

        file_content = self._parse_resources(document)

        return {
            "director": director,
            "actors": actors,
            "description": description,
            "years": years,
            "file_content": file_content,
            "poster": poster,
            "douban_score": douban_score,
            "imdb_score": imdb_score,
            "source": self.name,
        }

    # ------------------------------------------------------------------
    # get_magnet
    # ------------------------------------------------------------------

    def get_magnet(self, link: str) -> MagnetResult | None:
        link = (link or "").strip()
        if not link:
            return None

        if link.startswith("magnet:?") or link.startswith("ed2k://"):
            return {"file_name": "", "image": "", "magnet": link}

        if "/t/" in link:
            detail = self.get_detail(link)
            if not detail:
                return None
            for group in detail.get("file_content", []):
                for fi in group.get("file_list", []):
                    candidate = fi.get("final_link", "")
                    if candidate.startswith("magnet:?"):
                        return {
                            "file_name": fi.get("file_name", ""),
                            "image": detail.get("poster", ""),
                            "magnet": candidate,
                        }
            return None

        html = self._fetch_html(link)
        if html is None:
            return None

        image = first(clean_text_list(html.xpath(
            "//div[contains(@class,'movie-pic')]//img/@src"
            " | //meta[@property='og:image']/@content"
        )))
        image = abs_url(image, self.base_url)
        file_name = first(clean_text_list(html.xpath("(//h1//text())[1]")))
        magnet = first(clean_text_list(
            html.xpath("//a[starts-with(@href,'magnet:?')]/@href")))

        if not magnet:
            return None
        return {"file_name": file_name, "image": image, "magnet": magnet}

    # ------------------------------------------------------------------
    # 私有解析方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_metadata(lines: list[str]) -> tuple[str, list[str], list[str], list[str], str, str]:
        director = ""
        actors: list[str] = []
        description: list[str] = []
        years: list[str] = []
        douban_score = ""
        imdb_score = ""

        for line in lines:
            cl = clean_text(line)
            if not cl:
                continue
            if "导" in cl and "演" in cl and not director:
                director = cl
            if "演" in cl and "员" in cl:
                actors.append(cl)
            if "年" in cl or "上映" in cl:
                if re.search(r"\b(19\d{2}|20\d{2})\b", cl):
                    years.append(cl)
            if "剧情" in cl or "简介" in cl:
                description.append(cl)
            if "评" in cl and "分" in cl:
                md = re.search(r"豆瓣[:\s]*(\d+(?:\.\d+)?)", cl)
                mi = re.search(r"IMDb[:\s]*(\d+(?:\.\d+)?)", cl, re.IGNORECASE)
                if md:
                    douban_score = md.group(1)
                if mi:
                    imdb_score = mi.group(1)

        return director, actors, description, years, douban_score, imdb_score

    def _parse_resources(self, document: etree._Element) -> list[dict[str, Any]]:
        rows = document.xpath("//div[contains(@class,'movie-url')]//table//tr")
        resources: list[dict[str, str]] = []

        for row in rows:
            href_list = row.xpath(".//a/@href")
            if not href_list:
                continue

            href = abs_url(clean_text(href_list[0]), self.base_url)
            lower = href.lower()
            if not (
                lower.startswith("magnet:?") or lower.startswith("ed2k://")
                or "pan.baidu" in lower or "aliyundrive" in lower
                or "quark" in lower or "115.com" in lower or "download" in lower
            ):
                continue

            quality = first(clean_text_list(
                row.xpath(".//td[contains(@class,'url-label')]//text()")))
            file_title = first(clean_text_list(
                row.xpath(".//a[contains(@class,'open-url')]/@title")))
            file_text = first(clean_text_list(
                row.xpath(".//a[contains(@class,'open-url')]//text()")))

            file_name = file_text or file_title or ""
            source_text = f"{file_text} {file_title} {href}"
            file_size = parse_size_from_text(source_text)

            resources.append({
                "quality": quality or "other",
                "file_size": file_size,
                "file_name": file_name,
                "final_link": href,
                "file_tag": "",
            })

        # 去重
        uniq: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in resources:
            if item["final_link"] in seen:
                continue
            seen.add(item["final_link"])
            uniq.append(item)

        # 按 quality 分组
        grouped: dict[str, list[dict[str, str]]] = {}
        ordered: list[str] = []
        for r in uniq:
            q = r["quality"]
            if q not in grouped:
                grouped[q] = []
                ordered.append(q)
            grouped[q].append({
                "file_name": r["file_name"],
                "file_size": r["file_size"],
                "final_link": r["final_link"],
                "file_tag": r["file_tag"],
            })

        return [{
            "quality": q,
            "number": str(len(grouped[q])),
            "file_list": grouped[q],
        } for q in ordered]
