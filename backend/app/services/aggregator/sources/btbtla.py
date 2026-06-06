"""Btbtla 资源站 —— 速度最快、资源量大。"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from lxml import etree

from .base import (
    BaseSource, SearchResult, DetailResult, MagnetResult,
    clean_text, clean_text_list, first, abs_url, extract_size_text,
    TIMEOUT,
)


class BtbtlaSource(BaseSource):
    name = "btbtla"
    base_url = "https://www.btbtla.com"
    priority = 2

    def headers(self, referer: str | None = None) -> dict[str, str]:
        ref = referer or self.base_url + "/"
        h = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
            ),
            "Referer": ref,
        }
        cookie = os.environ.get("COOKIE", "")
        if cookie:
            h["Cookie"] = cookie
        return h

    def _fetch_html(self, url: str) -> etree._Element | None:
        text = self.fetch_text(url)
        if text is None:
            return None
        return etree.HTML(text)

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(self, keyword: str, page: int = 1) -> list[SearchResult]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        url = self.base_url + "/search/" + quote(keyword)
        if page > 1:
            url += f"?page={page}"

        html = self._fetch_html(url)
        if html is None:
            return []

        items = html.xpath("//div[@class='module-list']//div[@class='module-item']")
        results: list[SearchResult] = []

        for item in items:
            title_list = item.xpath(".//div[@class='module-item-pic']/a/@title")
            link_list = item.xpath(".//div[@class='module-item-pic']/a/@href")
            category_list = clean_text_list(item.xpath(".//span[@class='video-class']//text()"))
            country_list = clean_text_list(item.xpath(".//div[@class='module-item-caption']/*[3]//text()"))
            year_list = clean_text_list(item.xpath(".//div[@class='module-item-caption']/*[1]//text()"))
            overview_list = clean_text_list(item.xpath(".//div[contains(@class, 'video-text')]//text()"))

            link = first(link_list)
            results.append({
                "title": first(title_list),
                "link": abs_url(link, self.base_url),
                "category": first(category_list),
                "country": first(country_list),
                "years": first(year_list),
                "overview": first(overview_list),
            })

        return results

    # ------------------------------------------------------------------
    # get_detail
    # ------------------------------------------------------------------

    def get_detail(self, url: str) -> DetailResult | None:
        link = (url or "").strip()
        if not link:
            return None

        html = self._fetch_html(link)
        if html is None:
            return None

        director_list = clean_text_list(
            html.xpath("//*[@id='main']/div/div[1]/div[3]/div[2]/div[1]/div/text()"))
        actors_raw = html.xpath("//*[@id='main']/div/div[1]/div[3]/div[2]/div[2]/div//text()")
        actors = [clean_text(a) for a in actors_raw if clean_text(a) and clean_text(a) != "/"]

        years = clean_text_list(
            html.xpath("//*[@id='main']/div/div[1]/div[3]/div[2]/div[3]//text()"))
        description = clean_text_list(
            html.xpath("//*[@id='main']/div/div[1]/div[3]/div[2]/div[4]/div/span//text()"))

        poster = self._parse_poster(html)
        file_content = self._parse_resources(html)

        return {
            "director": first(director_list),
            "actors": actors,
            "description": description,
            "years": years,
            "poster": poster,
            "source": self.name,
            "file_content": file_content,
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

        html = self._fetch_html(link)
        if html is None:
            return None

        image_list = html.xpath(
            "//div[@class='module-item-cover']//img[contains(@class, 'lazy')]/@src")
        magnet_list = html.xpath(
            "//a[contains(@class, 'btn-important') and contains(@class, 'btn-large')]/@href")
        file_name_list = clean_text_list(html.xpath("//h2[@class='page-title']/text()"))

        image = abs_url(first(image_list), self.base_url)
        magnet = abs_url(first(magnet_list), self.base_url)
        file_name = first(file_name_list)

        return {"file_name": file_name, "image": image, "magnet": magnet}

    # ------------------------------------------------------------------
    # 私有解析方法
    # ------------------------------------------------------------------

    def _parse_poster(self, html: etree._Element) -> str:
        for xpath in [
            "//div[contains(@class,'module-info-poster')]//img/@data-original",
            "//div[contains(@class,'module-info-poster')]//img/@src",
            "//div[contains(@class,'module-item-pic')]//img/@src",
            "//*[@id='main']//img/@src",
        ]:
            vals = [v for v in clean_text_list(html.xpath(xpath))
                    if v and "errorpic" not in v and "w_load" not in v and "logo" not in v]
            if vals:
                return abs_url(vals[0], self.base_url)
        return ""

    def _parse_resources(self, html: etree._Element) -> list[dict[str, Any]]:
        qualities = html.xpath("//div[@class='module-tab-content']/div")
        magnets_tag = html.xpath(
            "//div[contains(@class, 'module-list') and "
            "contains(@class, 'module-player-list') and "
            "contains(@class, 'module-downlist')]"
        )

        file_content: list[dict[str, Any]] = []

        for index, quality in enumerate(qualities):
            q = clean_text_list(quality.xpath(".//text()"))
            if not q:
                continue

            files: dict[str, Any] = {
                "quality": first(q),
                "number": q[1] if len(q) > 1 else "",
                "file_list": [],
            }

            details = []
            if index < len(magnets_tag):
                details = magnets_tag[index].xpath(".//div[@class='module-row-info']")

            for detail in details:
                file_data: dict[str, str] = {
                    "file_name": "",
                    "file_size": "",
                    "final_link": "",
                    "file_tag": "",
                }

                h4 = clean_text_list(detail.xpath(
                    ".//div[@class='module-row-title']/h4//text()"))
                if h4:
                    file_data["file_name"] = h4[0]
                    if len(h4) >= 2:
                        maybe_size = extract_size_text(h4[1])
                        if maybe_size:
                            file_data["file_size"] = maybe_size
                    if len(h4) >= 3:
                        file_data["file_tag"] = h4[-1]

                final_link_list = detail.xpath(
                    ".//a[contains(@class, 'module-row-text')]/@href")
                final_link = first(final_link_list)
                file_data["final_link"] = abs_url(final_link, self.base_url)

                files["file_list"].append(file_data)

            file_content.append(files)

        return file_content
