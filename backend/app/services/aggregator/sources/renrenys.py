"""Renrenys (人人影视) 资源站 —— 独有云盘链接，magnet 直出。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

from lxml import etree

from .base import (
    BaseSource, SearchResult, DetailResult, MagnetResult,
    TIMEOUT,
)


class RenrenysSource(BaseSource):
    name = "renrenys"
    base_url = "https://www.rrys100.vip"
    priority = 5

    def headers(self, referer: str | None = None) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    # ------------------------------------------------------------------
    # 反爬：加减法验证码
    # ------------------------------------------------------------------

    def _solve_captcha(self, url: str, max_rounds: int = 5):
        """处理搜索验证码（加减法，可能多轮 + reload）。"""
        r = self.session.get(url, headers=self.headers(), timeout=TIMEOUT)
        for _ in range(max_rounds):
            if "人机验证" not in r.text and "erphp-search-captcha" not in r.text:
                return r
            m = re.search(r"(\d+)\s*([+\-])\s*(\d+)\s*=", r.text)
            if not m:
                return r
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            ans = a + b if op == "+" else a - b
            ph = {
                **self.headers(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.base_url,
                "Referer": url,
            }
            r = self.session.post(url, headers=ph, data={"result": str(ans)},
                                  timeout=TIMEOUT, allow_redirects=True)
            if "location.reload()" in r.text:
                time.sleep(2)
                r = self.session.get(url, headers=self.headers(), timeout=TIMEOUT)
        return r

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(self, keyword: str, page: int = 1) -> list[SearchResult]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        url = f"{self.base_url}/?s={quote(keyword)}"
        r = self._solve_captcha(url)
        doc = etree.HTML(r.text)
        results: list[SearchResult] = []

        for a in doc.xpath("//h2/a"):
            title = "".join(a.xpath(".//text()")).strip()
            href = a.get("href", "")
            if not href or not title:
                continue
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

        try:
            r = self.session.get(link, headers={
                **self.headers(), "Referer": self.base_url + "/"
            }, timeout=TIMEOUT)
        except Exception:
            return None

        doc = etree.HTML(r.text)

        # 海报
        poster = self._parse_poster(doc)

        # 元数据文本
        ctx_divs = doc.xpath('//div[@class="context"]')
        ctx_text = "".join(ctx_divs[0].xpath(".//text()")) if ctx_divs else ""

        year = self._extract_meta(ctx_text, r"\u5e74\s*\u4ee3") or \
               self._extract_meta(ctx_text, "\u4e0a\u6620")
        ym = re.search(r"(\d{4})", year)
        year = ym.group(1) if ym else year

        director = self._extract_meta(ctx_text, r"\u5bfc\s*\u6f14") or \
                   self._extract_meta(ctx_text, "\u5bfc\u6f14")
        actors = self._parse_actors(ctx_text)
        douban_score, imdb_score = self._parse_scores(ctx_text)
        description = self._parse_description(ctx_text)

        # magnet
        file_content = self._parse_magnets(doc)

        # 云盘链接
        cloud_links = self._parse_cloud_links(doc, ctx_divs)

        result: DetailResult = {
            "director": director,
            "writers": "",
            "actors": actors[:200] if actors else "",
            "description": description[:500] if description else "",
            "years": [year] if year else [],
            "country": "",
            "language": "",
            "release_date": "",
            "duration": "",
            "tags": "",
            "douban_score": douban_score,
            "imdb_score": imdb_score,
            "poster": poster,
            "source": self.name,
            "file_content": file_content,
        }
        if cloud_links:
            result["cloud_links"] = cloud_links
        return result

    # ------------------------------------------------------------------
    # get_magnet
    # ------------------------------------------------------------------

    def get_magnet(self, link: str) -> MagnetResult | None:
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
    def _extract_meta(ctx_text: str, key: str) -> str:
        m = re.search(rf"\u25ce{key}\s*[\uff1a\u3000]*\s*(.+?)(?:\n|\u25ce|$)", ctx_text)
        if m:
            return m.group(1).strip()
        key_simple = re.sub(r"\\s\*", "", key)
        m = re.search(rf"{key_simple}\s*[\uff1a:]\s*(.+?)(?:\n|$)", ctx_text)
        if m:
            return m.group(1).strip()
        return ""

    @staticmethod
    def _parse_poster(doc: etree._Element) -> str:
        for img in doc.xpath('//div[@class="context"]//img'):
            src = img.get("src", "")
            if src and "smilies" not in src and "avatar" not in src:
                return src
        return ""

    @staticmethod
    def _parse_actors(ctx_text: str) -> str:
        m = re.search(
            r"(?:\u25ce\u4e3b\s*\u6f14|\u4e3b\u6f14[\uff1a:])\s*(.+?)"
            r"(?=\u25ce|\u7c7b\u578b|\u5730\u533a|\u8bed\u8a00|\u4e0a\u6620|"
            r"\u7247\u957f|\u53c8\u540d|\u8bc4\u5206|\u7b80\u4ecb|\u6807\u8bed|\u83b7|$)",
            ctx_text, re.DOTALL,
        )
        return re.sub(r"\s+", " ", m.group(1).strip()) if m else ""

    @staticmethod
    def _parse_scores(ctx_text: str) -> tuple[str, str]:
        dm = re.search(r"\u8c46\u74e3\s*(?:\u8bc4\u5206)?\s*[\uff1a\u3000]?\s*([\d.]+)", ctx_text)
        im = re.search(r"(?:IMDb|IMDB)\s*(?:\u8bc4\u5206)?\s*([\d.]+)", ctx_text)
        return (dm.group(1) if dm else "", im.group(1) if im else "")

    @staticmethod
    def _parse_description(ctx_text: str) -> str:
        m = re.search(
            r"(?:\u25ce\u7b80\s*\u4ecb|\u7535\u5f71\u4ecb\u7ecd|\u5267\u60c5\u7b80\u4ecb)\s*(.+?)"
            r"(?=\u25ce\u83b7\u5956|\u25ce\u4e0b\u8f7d|\u8d44\u6e90\u4e0b\u8f7d|WEB[\uff1a:]|720P|1080P|\u78c1\u529b|$)",
            ctx_text, re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    @staticmethod
    def _parse_magnets(doc: etree._Element) -> list[dict[str, Any]]:
        magnets: list[dict[str, str]] = []
        for a in doc.xpath('//a[starts-with(@href,"magnet:")]'):
            name = "".join(a.xpath(".//text()")).strip()
            href = a.get("href", "").replace("&amp;", "&")
            if not href:
                continue
            size = ""
            sm = re.search(r"\[?([\d.]+\s*[GMTK]B)\]?", name)
            if sm:
                size = sm.group(1)
            magnets.append({
                "file_name": name, "file_size": size,
                "final_link": href, "file_tag": "",
            })

        if not magnets:
            return []
        return [{
            "quality": "全部资源",
            "number": str(len(magnets)),
            "file_list": magnets,
        }]

    @staticmethod
    def _parse_cloud_links(doc: etree._Element, ctx_divs) -> list[dict[str, str]]:
        cloud_domains = [
            "pan.quark", "pan.xunlei", "pan.baidu", "www.alipan",
            "www.aliyundrive", "cloud.189", "www.123pan", "drive.uc",
        ]
        provider_map = {
            "quark": "夸克网盘", "xunlei": "迅雷云盘", "baidu": "百度网盘",
            "alipan": "阿里云盘", "aliyundrive": "阿里云盘",
            "189": "天翼云盘", "123pan": "123盘", "drive.uc": "UC网盘",
        }

        cloud_links: list[dict[str, str]] = []
        ctx_anchors = doc.xpath('//div[@class="context"]//a') if ctx_divs else []

        for a in ctx_anchors:
            href = a.get("href", "")
            atext = "".join(a.xpath(".//text()")).strip()
            if not any(d in href for d in cloud_domains):
                continue

            pwd = ""
            pwd_m = re.search(r"pwd=([^&#\s]+)", href)
            if pwd_m:
                pwd = pwd_m.group(1)

            provider = "网盘"
            for key, name in provider_map.items():
                if key in href:
                    provider = name
                    break

            # 尝试从父 <p> 获取描述
            desc = ""
            p = a
            for _ in range(5):
                p = p.getparent()
                if p is None or p.tag == "p":
                    break
            if p is not None and p.tag == "p":
                p_text = "".join(p.xpath(".//text()")).strip()
                desc = re.sub(rf"\s*[\uff1a:]*\s*{re.escape(atext)}\s*$", "", p_text).strip()

            entry: dict[str, str] = {"provider": provider, "url": href, "name": atext or provider}
            if desc:
                entry["description"] = desc
            if pwd:
                entry["password"] = pwd
            cloud_links.append(entry)

        return cloud_links
