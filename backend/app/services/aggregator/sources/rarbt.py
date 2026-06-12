"""Rarbt 资源站 —— 资源量最大，有验证码 + 频率限制。"""

from __future__ import annotations

import re
import time
from typing import Any

from lxml import etree

from .base import (
    BaseSource, SearchResult, DetailResult, MagnetResult,
    clean_text, clean_text_list, first, abs_url, parse_size_from_text,
    make_headers, TIMEOUT,
)


class RarbtSource(BaseSource):
    name = "rarbt"
    base_url = "http://www.rarbt.us"
    priority = 1

    @property
    def session(self):
        """rarbt 在部分网络下需代理；显式代理优先，未配置时兼容系统代理。"""
        created = self._session is None
        s = super().session  # 触发懒加载
        if created:
            if self._proxy:
                s.trust_env = False
            else:
                s.trust_env = True
                import urllib.request
                sys_proxies = urllib.request.getproxies()
                if sys_proxies:
                    s.proxies = sys_proxies
        return s

    def set_proxy(self, proxy: str | None) -> None:
        super().set_proxy(proxy)
        if self._session is not None and proxy:
            self._session.trust_env = False

    def headers(self, referer: str | None = None) -> dict[str, str]:
        ref = referer or self.base_url + "/"
        return make_headers(ref)

    # ------------------------------------------------------------------
    # 反爬处理
    # ------------------------------------------------------------------

    def fetch_text(self, url: str, **kwargs: Any) -> str | None:
        """rarbt 专用请求：自动处理验证码和频率限制页面。"""
        from urllib.parse import urlparse
        domain = urlparse(self.base_url).hostname or "www.rarbt.us"
        self.session.cookies.set("searchneed", "ok", domain=domain, path="/")

        max_attempts = kwargs.pop("max_attempts", 8)
        for _ in range(max_attempts):
            headers = self.headers(referer=url)
            try:
                r = self.session.get(url, headers=headers, timeout=TIMEOUT)
            except Exception:
                return None

            html_text = r.text

            if self._is_throttle_page(html_text):
                time.sleep(3.2)
                continue

            if self._is_verify_page(html_text):
                verify_type = self._extract_verify_type(html_text)
                image_content = self._fetch_captcha_image(r.url)
                if not image_content:
                    return None

                verify_value = self._ocr_text(image_content)
                if not verify_value:
                    return None

                code = self._submit_verify(verify_type, verify_value, referer=url)
                time.sleep(3.2 if code == 1 else 0.8)
                continue

            if r.status_code >= 400:
                return None

            return html_text

        return None

    def _page_title(self, html_text: str) -> str:
        m = re.search(r"<title>(.*?)</title>", html_text, flags=re.I | re.S)
        return clean_text(m.group(1)) if m else ""

    def _is_verify_page(self, html_text: str) -> bool:
        title = self._page_title(html_text)
        lower = html_text.lower()
        return ("系统安全验证" in title) or ("verify_submit" in lower and "mac_verify" in lower)

    def _is_throttle_page(self, html_text: str) -> bool:
        title = self._page_title(html_text)
        return ("请不要频繁操作" in title) or ("搜索时间间隔" in title)

    def _extract_verify_type(self, html_text: str) -> str:
        m = re.search(r"verify_check\?type=([a-zA-Z0-9_]+)&verify", html_text)
        return m.group(1) if m else "search"

    def _fetch_captcha_image(self, page_url: str) -> bytes | None:
        image_url = f"{self.base_url}/index.php/verify/index.html?r={time.time()}"
        headers = self.headers(referer=page_url)
        try:
            r = self.session.get(image_url, headers=headers, timeout=TIMEOUT)
        except Exception:
            return None
        if r.status_code >= 400 or not r.content:
            return None
        return r.content

    @staticmethod
    def _ocr_text(image_content: bytes) -> str:
        try:
            import ddddocr
            ocr = ddddocr.DdddOcr(show_ad=False)
            return clean_text(ocr.classification(image_content))
        except Exception:
            return ""

    def _submit_verify(self, verify_type: str, verify_value: str, referer: str) -> int:
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "User-Agent": self.headers(referer=referer).get("User-Agent", "Mozilla/5.0"),
        }
        try:
            r = self.session.post(
                f"{self.base_url}/index.php/ajax/verify_check",
                params={"type": verify_type, "verify": verify_value},
                headers=headers,
                timeout=TIMEOUT,
            )
            data = r.json()
            return int(data.get("code", 0) or 0)
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # 内部 HTML 解析
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

        from urllib.parse import quote
        url = f"{self.base_url}/vod/search.html?wd={quote(keyword)}"
        if page > 1:
            url += f"&page={page}"

        html = self._fetch_html(url)
        if html is None:
            return []

        results: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()

        # 新版 rarbt.lol（迷客电影 maccms 模板）：详情链为 /thread-XXXX.html，
        # 播放链为 /Play_XXXX.html。旧站 rarbt.us 用 /rarbtus-，两种都兼容。
        items = html.xpath("//div[contains(@class,'module-search-item')]")
        for item in items:
            links = item.xpath(".//a[contains(@href,'/thread-') or contains(@href,'/rarbtus-')]")
            href = ""
            title = ""
            for a in links:
                h = clean_text(a.get("href", ""))
                t = clean_text(a.get("title", ""))
                # 排除播放链和"下载"前缀标题，取干净片名
                if h and t and "play_" not in h.lower():
                    href = h
                    title = re.sub(r"^(下载|立刻播放)", "", t).strip()
                    break
            if not href or not title:
                continue

            clean_link = abs_url(href, self.base_url)
            key = (title, clean_link)
            if key in seen:
                continue
            seen.add(key)

            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
            results.append({
                "title": title,
                "link": clean_link,
                "category": "",
                "country": "",
                "years": year_match.group(1) if year_match else "",
                "overview": "",
            })

        if results:
            return results

        # 旧版 fallback：module-card-item
        cards = html.xpath("//div[contains(@class,'module-card-item')]")
        for card in cards:
            href = clean_text("".join(card.xpath(
                "(.//div[contains(@class,'module-card-item-title')]/a/@href"
                " | .//a[contains(@class,'module-card-item-poster')]/@href)[1]"
            )))
            title = clean_text("".join(card.xpath(
                "(.//div[contains(@class,'module-card-item-title')]/a//text()"
                " | .//img/@alt)[1]"
            )))
            if not href or not title:
                continue

            clean_link = abs_url(href, self.base_url)
            key = (title, clean_link)
            if key in seen:
                continue
            seen.add(key)

            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
            results.append({
                "title": title,
                "link": clean_link,
                "category": "",
                "country": "",
                "years": year_match.group(1) if year_match else "",
                "overview": "",
            })

        if results:
            return results

        # 最终 fallback：通用链接匹配
        for node in html.xpath("//a[contains(@href,'/rarbtus-') or contains(@href,'/movie/') or contains(@href,'/vod/detail')]"):
            href = clean_text(node.get("href", ""))
            title = clean_text(node.get("title", ""))
            if not title:
                title = clean_text("".join(node.xpath(".//text()")))
            if not href or not title or "play_" in href:
                continue

            clean_link = abs_url(href, self.base_url)
            key = (title, clean_link)
            if key in seen:
                continue
            seen.add(key)

            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
            results.append({
                "title": title,
                "link": clean_link,
                "category": "",
                "country": "",
                "years": year_match.group(1) if year_match else "",
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

        director, actors, description, years = self._parse_meta(document)
        poster = self._parse_poster(document)
        douban_score, imdb_score = self._parse_scores(document)
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

        if "/movie/" in link or "/vod/detail" in link or "/rarbtus-" in link:
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
            "//meta[@property='og:image']/@content"
            " | //div[contains(@class,'module-info-poster')]//img/@data-original"
            " | //div[contains(@class,'module-item-pic')]//img/@data-original"
            " | //img/@src"
        )))
        image = abs_url(image, self.base_url)

        file_name = first(clean_text_list(html.xpath(
            "//h1//text() | //h2//text() | //title/text()"
        )))

        magnet = first(clean_text_list(html.xpath(
            "//a[starts-with(@href,'magnet:?')]/@href"
            " | //a[contains(@class,'btn-copyurl')]/@data-clipboard-text"
            " | //a[contains(@class,'btn-down') and starts-with(@href,'magnet:?')]/@href"
        )))

        if not magnet:
            return None

        return {"file_name": file_name, "image": image, "magnet": magnet}

    # ------------------------------------------------------------------
    # 私有解析方法
    # ------------------------------------------------------------------

    def _parse_meta(self, document: etree._Element) -> tuple[str, list[str], list[str], list[str]]:
        info_nodes = clean_text_list(document.xpath(
            "//div[contains(@class,'module-info-item')]//text()"
            " | //div[contains(@class,'module-info-introduction')]//text()"
            " | //div[contains(@class,'video-info')]//text()"
            " | //div[contains(@class,'module-info-content')]//text()"
        ))

        director = ""
        actors: list[str] = []
        description: list[str] = []
        years: list[str] = []

        for line in info_nodes:
            if not line:
                continue
            if "导演" in line and not director:
                director = line
            if "主演" in line:
                actor_raw = re.split(r"[：:]", line, maxsplit=1)
                actor_text = actor_raw[1] if len(actor_raw) > 1 else line
                for name in re.split(r"[、,/，]\s*", actor_text):
                    cn = clean_text(name)
                    if cn and cn not in actors:
                        actors.append(cn)
            if ("年份" in line) or ("上映" in line) or ("首播" in line) or \
               re.search(r"\b(19\d{2}|20\d{2})\b", line):
                years.append(line)
            if "简介" in line or line.startswith("◎"):
                description.append(line)

        seen: set[str] = set()
        uniq: list[str] = []
        for line in description:
            if line not in seen:
                seen.add(line)
                uniq.append(line)

        return director, actors, uniq, years

    _POSTER_BLACKLIST = ("w_load.png", "errorpic", "lol_black.png", "logo")

    def _parse_poster(self, document: etree._Element) -> str:
        for xpath in [
            "//meta[@property='og:image']/@content",
            "//div[contains(@class,'module-info-poster')]//img/@data-original",
            "//div[contains(@class,'module-info-poster')]//img/@src",
            "//img[contains(@class,'lazyload')]/@data-original",
            "//img[contains(@class,'lazy')]/@data-original",
            "//img/@src",
        ]:
            vals = [v for v in clean_text_list(document.xpath(xpath))
                    if v and not any(b in v for b in self._POSTER_BLACKLIST)]
            if vals:
                return abs_url(vals[0], self.base_url)
        return ""

    def _parse_scores(self, document: etree._Element) -> tuple[str, str]:
        douban_score = ""
        imdb_score = ""
        for a in document.xpath('//a[@class="douban"]'):
            span = a.xpath('.//span[@class="imdb-rating"]/text()')
            if span:
                douban_score = clean_text(span[0])
                break
        for a in document.xpath('//a[@class="imdb"]'):
            span = a.xpath('.//span[@class="imdb-rating"]/text()')
            if span:
                imdb_score = clean_text(span[0])
                break
        return douban_score, imdb_score

    def _parse_one_resource(self, block: etree._Element, quality: str) -> dict[str, str] | None:
        file_name = clean_text("".join(
            block.xpath(".//a[contains(@class,'module-row-text')]/@title")))
        if file_name:
            file_name = file_name.replace("下载地址", "").replace("下载", "").strip(" -：:")
        if not file_name:
            file_name = clean_text("".join(
                block.xpath(".//div[contains(@class,'module-row-title')]//text()")))

        source_url = abs_url(
            clean_text("".join(block.xpath(".//a[contains(@class,'module-row-text')]/@href"))),
            self.base_url,
        )

        final_link = clean_text("".join(
            block.xpath(".//a[contains(@class,'btn-copyurl')]/@data-clipboard-text")))
        if not final_link:
            final_link = clean_text("".join(
                block.xpath(".//a[contains(@class,'btn-down')]/@href")))
        if not final_link:
            final_link = clean_text("".join(
                block.xpath(".//p[contains(text(),'magnet:?')]/text()")))
        if not final_link:
            final_link = source_url

        final_link = abs_url(final_link, self.base_url)
        if not final_link or final_link.startswith("javascript:"):
            return None

        row_text = clean_text(" ".join(block.xpath(".//text()")))
        file_size = parse_size_from_text(f"{file_name} {row_text}")

        return {
            "quality": quality or "暂未分类",
            "file_name": file_name,
            "file_size": file_size,
            "final_link": final_link,
            "file_tag": "",
        }

    @staticmethod
    def _dedupe_resources(items: list[dict[str, str]]) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in items:
            link = item.get("final_link", "")
            if not link or link in seen:
                continue
            seen.add(link)
            output.append(item)
        return output

    def _parse_resources(self, document: etree._Element) -> list[dict[str, Any]]:
        quality_tags: list[tuple[str, str]] = []
        seen_tags: set[str] = set()
        for node in document.xpath(
            "//div[contains(@class,'downtab-item') and @data-dropdown-value]"
        ):
            quality = clean_text(node.get("data-dropdown-value", ""))
            if not quality:
                quality = clean_text("".join(node.xpath("./span/text()")))
            if not quality or quality in seen_tags:
                continue
            seen_tags.add(quality)
            expected = clean_text("".join(node.xpath("./small/text()")))
            quality_tags.append((quality, expected))

        file_content: list[dict[str, Any]] = []
        row_groups = document.xpath("//div[contains(@class,'module-row-one')]")

        if row_groups:
            for idx, row in enumerate(row_groups):
                quality = "暂未分类"
                expected = ""
                if idx < len(quality_tags):
                    quality = quality_tags[idx][0]
                    expected = quality_tags[idx][1]

                group_items: list[dict[str, str]] = []
                for block in row.xpath(".//div[contains(@class,'module-row-info')]"):
                    parsed = self._parse_one_resource(block, quality=quality)
                    if parsed is not None:
                        group_items.append(parsed)

                group_items = self._dedupe_resources(group_items)
                if not group_items:
                    continue

                file_content.append({
                    "quality": quality,
                    "number": expected or str(len(group_items)),
                    "file_list": [{
                        "file_name": item["file_name"],
                        "file_size": item["file_size"],
                        "final_link": item["final_link"],
                        "file_tag": item["file_tag"],
                    } for item in group_items],
                })

        if not file_content:
            fallback: list[dict[str, str]] = []
            for block in document.xpath("//div[contains(@class,'module-row-info')]"):
                parsed = self._parse_one_resource(block, quality="暂未分类")
                if parsed is not None:
                    fallback.append(parsed)
            fallback = self._dedupe_resources(fallback)
            if fallback:
                file_content.append({
                    "quality": "暂未分类",
                    "number": str(len(fallback)),
                    "file_list": [{
                        "file_name": item["file_name"],
                        "file_size": item["file_size"],
                        "final_link": item["final_link"],
                        "file_tag": item["file_tag"],
                    } for item in fallback],
                })

        return file_content
