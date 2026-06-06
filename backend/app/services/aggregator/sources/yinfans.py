"""Yinfans 资源站 —— 热门片资源丰富，有 JS 门禁验证码。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote, urljoin

from lxml import etree

from .base import (
    BaseSource, SearchResult, DetailResult, MagnetResult,
    clean_text, clean_text_list, first, abs_url,
    make_headers, TIMEOUT,
)


class YinfansSource(BaseSource):
    name = "yinfans"
    base_url = "https://www.yinfans.me"
    priority = 4

    def headers(self, referer: str | None = None) -> dict[str, str]:
        ref = referer or self.base_url + "/"
        return make_headers(ref, extra={
            "Cache-Control": "max-age=0",
            "Sec-CH-UA": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        })

    # ------------------------------------------------------------------
    # 反爬：数学验证码
    # ------------------------------------------------------------------

    def fetch_text(self, url: str, **kwargs: Any) -> str | None:
        headers = kwargs.pop("headers", None) or self.headers(referer=url)
        try:
            r = self.session.get(url, headers=headers, timeout=TIMEOUT)
        except Exception:
            return None

        # 最多 5 轮验证码
        for _ in range(5):
            if not self._is_gate(r.text):
                break
            solved = self._solve_gate(url, r.text)
            if solved is not None:
                r = solved
            if not self._is_gate(r.text):
                break
            time.sleep(1)
            try:
                r = self.session.get(url, headers=headers, timeout=TIMEOUT)
            except Exception:
                return None

        if r.status_code >= 400:
            return None
        return r.text

    @staticmethod
    def _is_gate(html_text: str) -> bool:
        lower = html_text.lower()
        if "搜索人机验证" in html_text:
            return True
        if "result" in lower and re.search(r"\d+\s*[+＋]\s*\d+", html_text):
            return True
        return False

    @staticmethod
    def _find_add_expr(html_text: str) -> tuple[int, int, int] | None:
        m = re.search(r"(\d{1,4})\s*[+＋]\s*(\d{1,4})", html_text)
        if not m:
            return None
        left, right = int(m.group(1)), int(m.group(2))
        return left, right, left + right

    def _solve_gate(self, url: str, html_text: str):
        expr = self._find_add_expr(html_text)
        if not expr:
            return None

        document = etree.HTML(html_text)
        if document is None:
            return None

        forms = document.xpath("//form")
        if not forms:
            return None

        form = forms[0]
        payload: dict[str, str] = {}
        answer_field = ""

        for inp in form.xpath(".//input"):
            name = inp.get("name", "")
            itype = (inp.get("type") or "text").lower()
            if not name or itype in {"submit", "button", "image", "reset"}:
                continue
            payload[name] = inp.get("value", "")
            if name.lower() == "result":
                answer_field = name

        if not answer_field:
            for inp in form.xpath(".//input"):
                name = inp.get("name", "")
                itype = (inp.get("type") or "text").lower()
                if name and itype in {"text", "number"}:
                    answer_field = name
                    break

        if not answer_field:
            return None

        payload[answer_field] = str(expr[2])

        action = form.get("action", "")
        method = (form.get("method") or "post").upper()
        submit_url = urljoin(url, action or url)
        headers = self.headers(referer=url)

        r = self.session.request(
            method, submit_url,
            data=payload if method == "POST" else None,
            params=payload if method == "GET" else None,
            headers=headers, timeout=TIMEOUT,
        )

        if "location.reload" in r.text.lower():
            headers = self.headers(referer=submit_url)
            r = self.session.get(url, headers=headers, timeout=TIMEOUT)

        return r

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

        url = f"{self.base_url}/?s={quote(keyword)}"
        if page > 1:
            url += f"&paged={page}"

        html = self._fetch_html(url)
        if html is None:
            return []

        pairs = list(zip(html.xpath("//h2/a/text()"), html.xpath("//h2/a/@href")))
        if not pairs:
            pairs = list(zip(
                html.xpath("//a[@rel='bookmark']/text()"),
                html.xpath("//a[@rel='bookmark']/@href"),
            ))

        results: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()

        for title, link in pairs:
            ct = clean_text(title)
            cl = abs_url(clean_text(link), self.base_url)
            if not ct or "/movie/" not in cl:
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

        # 元数据
        info_lines = clean_text_list(document.xpath("//div[@id='post_content']/p[2]//text()"))
        if not any("\u25ce" in line for line in info_lines):
            all_p = document.xpath("//div[@id='post_content']/p//text()")
            candidate = clean_text_list(all_p)
            if any("\u25ce" in line for line in candidate):
                info_lines = candidate

        director, actors, description, years, douban_score, imdb_score = \
            self._parse_metadata(info_lines)

        poster = first(clean_text_list(
            document.xpath("//div[@id='post_content']//img[1]/@src")))
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

        if "/movie/" in link:
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

        image = first(clean_text_list(
            html.xpath("//div[@id='post_content']//img[1]/@src")))
        image = abs_url(image, self.base_url)
        file_name = first(clean_text_list(html.xpath("//h1/text()")))
        magnet = first(clean_text_list(
            html.xpath("//a[starts-with(@href,'magnet:?')]/@href")))

        if not magnet:
            return None
        return {"file_name": file_name, "image": image, "magnet": magnet}

    # ------------------------------------------------------------------
    # 私有解析方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_metadata(info_lines: list[str]) -> tuple[str, list[str], list[str], list[str], str, str]:
        director = ""
        actors: list[str] = []
        description: list[str] = []
        years: list[str] = []
        douban_score = ""
        imdb_score = ""

        actor_mode = False
        description_mode = False

        for line in info_lines:
            cl = clean_text(line)
            if not cl:
                continue

            if cl.startswith("◎"):
                actor_mode = False
                if "简" not in cl:
                    description_mode = False

            if cl.startswith("◎导"):
                director = re.sub(r"^◎导\s*演\s*", "", cl).strip()
                actor_mode = False
                description_mode = False
                continue

            if cl.startswith("◎主") or cl.startswith("◎演"):
                actor_mode = True
                description_mode = False
                actors.append(re.sub(r"^◎(?:主|演)\s*(?:演|员)?\s*", "", cl).strip())
                continue

            if cl.startswith("◎年") or cl.startswith("◎上映"):
                years.append(cl)
                continue

            if "◎豆瓣" in cl and ("评分" in cl or "/" in cl):
                m = re.search(r"(\d+(?:\.\d+)?)\s*(?:分\s*)?/", cl)
                if m:
                    douban_score = m.group(1)
                continue

            if ("◎IMDb" in cl or "◎ＩＭＤＢ" in cl or "◎imdb" in cl.lower()) and \
               ("评分" in cl or "分" in cl or "/" in cl):
                m = re.search(r"(\d+(?:\.\d+)?)\s*(?:分\s*)?/", cl)
                if m:
                    imdb_score = m.group(1)
                continue

            if cl.startswith("◎简"):
                description_mode = True
                actor_mode = False
                continue

            if actor_mode and not cl.startswith("◎"):
                actors.append(cl)
                continue

            if description_mode and not cl.startswith("◎"):
                description.append(cl)

        return director, actors, description, years, douban_score, imdb_score

    def _parse_resources(self, document: etree._Element) -> list[dict[str, Any]]:
        rows = document.xpath("//table[@id='cili']//tr")
        resources: list[dict[str, str]] = []

        for row in rows:
            href_list = row.xpath(".//a/@href")
            if not href_list:
                continue

            href = abs_url(clean_text(href_list[0]), self.base_url)
            lower_href = href.lower()
            if not (
                lower_href.startswith("magnet:?")
                or lower_href.startswith("ed2k://")
                or "samfunny.com/download" in lower_href
            ):
                continue

            quality = first(clean_text_list(
                row.xpath(".//span[contains(@class,'label-danger')]/text()")))
            size = first(clean_text_list(
                row.xpath(".//span[contains(@class,'label-warning')]/text()")))
            file_name = first(clean_text_list(row.xpath(".//b//text()")))
            if not file_name:
                file_name = first(clean_text_list(row.xpath(".//a//text()")))

            file_tag_parts: list[str] = []
            if "mores" in (row.get("class") or ""):
                file_tag_parts.append("hidden")
            if "samfunny.com/download" in lower_href:
                file_tag_parts.append("subtitle")

            resources.append({
                "quality": quality or "other",
                "file_size": size,
                "file_name": file_name,
                "final_link": href,
                "file_tag": ",".join(file_tag_parts),
            })

        # 按 quality 分组
        grouped: dict[str, list[dict[str, str]]] = {}
        ordered: list[str] = []

        for r in resources:
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
