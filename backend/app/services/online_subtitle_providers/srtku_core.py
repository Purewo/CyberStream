"""srtku.com 字幕搜索与下载模块。

从 6 个 v4 脚本合并而来，接口对齐 subhd_core.py。
主要函数：
  - search_film(keyword, page, session) → 搜索影视条目
  - search_subtitle(list_url, session) → 获取字幕列表
  - get_download_links(detail_url, session) → 获取下载入口
  - download_subtitle(download_url, outdir, session, ...) → 下载字幕文件
  - make_session() → 创建预配置 Session
"""

from __future__ import annotations

import base64
import html as _html
import json
import os
import re
import tarfile
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests
from lxml import etree

BASE = "https://srtku.com"

# ============================================================
# Headers 配置
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0"
    ),
    "Referer": f"{BASE}/",
}


def make_session() -> requests.Session:
    """创建预配置 Session：禁用系统代理。"""
    s = requests.Session()
    s.trust_env = False
    return s


# ============================================================
# WAF 验证码处理
# ============================================================

def _str_to_hex(s: str) -> str:
    return "".join(format(ord(c), "x") for c in s)


def _is_waf_page(response: requests.Response) -> bool:
    if "security_verify_img" in response.text:
        return True
    if "YunsuoAutoJump" in response.text:
        return True
    if re.search(r'src="data:image/bmp;base64,', response.text):
        return True
    return False


_ocr_instance = None


def _solve_waf(
    session: requests.Session,
    target_url: str,
    headers: dict,
    max_retries: int = 3,
    initial_response: requests.Response | None = None,
) -> requests.Response:
    global _ocr_instance
    if _ocr_instance is None:
        import ddddocr
        _ocr_instance = ddddocr.DdddOcr(show_ad=False)

    h = dict(headers)
    h["Referer"] = target_url

    r2 = None
    for attempt in range(1, max_retries + 1):
        if initial_response is not None and attempt == 1:
            r = initial_response
        else:
            r = session.get(target_url, headers=h, timeout=20)

        if not _is_waf_page(r):
            return r

        m = re.search(r'src="data:image/bmp;base64,([^"]+)"', r.text)
        if not m:
            return r

        ssv = r.cookies.get("security_session_verify", "")
        img_data = base64.b64decode(m.group(1))
        code = _ocr_instance.classification(img_data)

        srcurl_hex = _str_to_hex(target_url)
        code_hex = _str_to_hex(code)
        submit_url = f"{target_url}?security_verify_img={code_hex}"

        h2 = dict(headers)
        h2["Referer"] = target_url
        h2["Cookie"] = h2.get("Cookie", "") + f"; srcurl={srcurl_hex}; security_session_verify={ssv}"
        session.get(submit_url, headers=h2, timeout=20, allow_redirects=True)

        h3 = dict(headers)
        h3["Referer"] = target_url
        all_cookies = {k: v for k, v in session.cookies.items()}
        if all_cookies:
            extra = "; ".join(f"{k}={v}" for k, v in all_cookies.items())
            existing = h3.get("Cookie", "")
            h3["Cookie"] = f"{existing}; {extra}" if existing else extra

        r2 = session.get(target_url, headers=h3, timeout=20)
        if not _is_waf_page(r2):
            return r2

    return r2


def _fetch(session: requests.Session, url: str) -> requests.Response:
    """GET 请求，自动处理 WAF。"""
    h = dict(HEADERS)
    h["Referer"] = url
    r = session.get(url, headers=h, timeout=20)
    if _is_waf_page(r):
        r = _solve_waf(session, url, HEADERS, initial_response=r)
    return r


# ============================================================
# 搜索影视条目
# ============================================================

def search_film(keyword: str, page: int = 1, session: requests.Session | None = None) -> dict:
    """搜索影视条目，返回 titles + list_urls。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"keyword": keyword, "page": page, "titles": [], "list_urls": []}

    s = session or make_session()
    url = f"{BASE}/search?q={quote(keyword)}&p={max(1, page)}"
    r = _fetch(s, url)
    if r.status_code >= 400:
        return {"keyword": keyword, "page": page, "titles": [], "list_urls": []}

    tree = etree.HTML(r.text)
    titles = [t.strip() for t in tree.xpath("//div[@class='title']//p[contains(@class, 'tt')]//text()") if t and t.strip()]
    links = [u.strip() for u in tree.xpath("//div[@class='title']//p[contains(@class, 'tt')]/a/@href") if u and u.strip()]

    list_urls: list[str] = []
    for u in links:
        if u.startswith("//"):
            list_urls.append("https:" + u)
        elif u.startswith("/"):
            list_urls.append(BASE + u)
        elif u.startswith("http"):
            list_urls.append(u)
        else:
            list_urls.append(BASE + "/" + u.lstrip("/"))

    list_urls = [u.replace("zimuku.org", "srtku.com") for u in list_urls]
    return {"keyword": keyword, "page": page, "titles": titles, "list_urls": list_urls}


# ============================================================
# 获取字幕列表
# ============================================================

def search_subtitle(list_url: str, session: requests.Session | None = None) -> list[dict]:
    """获取字幕列表，返回详细信息。"""
    list_url = (list_url or "").strip()
    if not list_url:
        return []

    s = session or make_session()
    r = _fetch(s, list_url)
    if r.status_code >= 400:
        return []

    tree = etree.HTML(r.text)
    trs = tree.xpath("//tbody//tr")
    results: list[dict] = []

    for tr in trs:
        t = tr.xpath(".//td[@class='first']/a/@title")
        d_url = tr.xpath(".//td[@class='first']/a/@href")
        language = tr.xpath(".//td[contains(@class, 'lang')]//img//@title")
        download_number = tr.xpath(".//td[contains(@class, 'tac') and contains(@class, 'hidden-xs')]/text()")
        update_time = tr.xpath(".//td[contains(@class, 'last')]/text()")
        q = tr.xpath(".//td//i[contains(@class, 'rating-star')]/@title")

        title = _html.unescape(t[0]).strip() if t else ""
        detail_url = ""
        if d_url:
            last = d_url[0].split("/")[-1]
            detail_url = f"{BASE}/detail/{last}"

        dn = "".join(download_number).strip()
        ut = "".join(update_time).strip()
        if re.match(r"^\d{2}-\d{2}-\d{2}$", ut):
            ut = "20" + ut

        quality = _html.unescape(q[0]).strip() if q else ""
        langs = [_html.unescape(x).strip() for x in language if x and x.strip()]

        if title or detail_url:
            results.append({
                "title": title,
                "quality": quality,
                "download_number": dn,
                "update_time": ut,
                "language": langs,
                "detail_url": detail_url,
            })

    return results


# ============================================================
# 获取下载入口
# ============================================================

def get_download_links(detail_url: str, session: requests.Session | None = None) -> list[dict]:
    """获取下载入口链接列表。"""
    detail_url = (detail_url or "").strip()
    if not detail_url:
        return []

    dld_url = detail_url.replace("/detail/", "/dld/")
    s = session or make_session()
    r = _fetch(s, dld_url)
    if r.status_code >= 400:
        return []

    tree = etree.HTML(r.text)
    providers = tree.xpath("//li")
    results: list[dict] = []

    for provider in providers[:-1]:
        server = provider.xpath(".//a/text()")
        download_link = provider.xpath(".//a/@href")
        if not download_link:
            continue
        link = download_link[0].strip()
        full = link if link.startswith("http") else BASE + link
        results.append({
            "provider": server[0].strip() if server else "",
            "download_links": full,
        })

    return results


# ============================================================
# 下载字幕文件
# ============================================================

ARCHIVE_SUFFIXES = {".7z", ".zip", ".tar", ".gz", ".bz2", ".xz", ".tgz"}
SUBTITLE_SUFFIXES = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".sup"}


def _guess_filename(download_url: str, response: requests.Response) -> str:
    cd = response.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, flags=re.IGNORECASE)
    if m:
        return unquote(m.group(1)).strip().strip('"')
    m = re.search(r"filename=([^;]+)", cd, flags=re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    path = urlparse(download_url).path
    name = unquote(Path(path).name)
    return name if name and "." in name else "subtitle_download"


def _is_archive(path: Path) -> bool:
    lower = path.name.lower()
    if lower.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return True
    return path.suffix.lower() in ARCHIVE_SUFFIXES


def _find_subtitles(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUBTITLE_SUFFIXES]


def _pick_best(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    rank = {".ass": 0, ".ssa": 1, ".srt": 2, ".sub": 3, ".vtt": 4}
    return sorted(paths, key=lambda p: (rank.get(p.suffix.lower(), 99), len(p.name)))[0]


def _extract(archive: Path, outdir: Path) -> list[Path]:
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(outdir)
        return _find_subtitles(outdir)
    if archive.suffix.lower() == ".7z":
        import py7zr
        with py7zr.SevenZipFile(archive, mode="r") as zf:
            zf.extractall(path=outdir)
        return _find_subtitles(outdir)
    if archive.suffix.lower() in {".tar", ".gz", ".bz2", ".xz", ".tgz"}:
        with tarfile.open(archive, mode="r:*") as tf:
            tf.extractall(path=outdir)
        return _find_subtitles(outdir)
    raise RuntimeError(f"不支持的压缩格式: {archive.suffix}")


def _follow_redirect(download_url: str, session: requests.Session) -> requests.Response:
    h = dict(HEADERS)
    h["Referer"] = download_url
    for k, v in session.cookies.items():
        h["Cookie"] = h.get("Cookie", "") + f"; {k}={v}"

    r = session.get(download_url, headers=h, timeout=30, allow_redirects=False)
    if _is_waf_page(r):
        _solve_waf(session, download_url, HEADERS, initial_response=r)
        h2 = dict(HEADERS)
        h2["Referer"] = download_url
        for k, v in session.cookies.items():
            h2["Cookie"] = h2.get("Cookie", "") + f"; {k}={v}"
        r = session.get(download_url, headers=h2, timeout=30, allow_redirects=False)

    if r.status_code == 301:
        loc = r.headers.get("Location", "")
        if loc.startswith("//"):
            loc = "https:" + loc
        if loc:
            return requests.get(loc, timeout=30, stream=True)
    return r


def download_subtitle(
    download_url: str,
    outdir: str = ".",
    session: requests.Session | None = None,
    filename: str | None = None,
    retries: int = 5,
    auto_extract: bool = True,
    remove_archive: bool = True,
) -> dict:
    """下载字幕文件，自动处理重定向/WAF/解压。"""
    download_url = (download_url or "").strip()
    if not download_url:
        return {"ok": False, "error": "empty download_url", "attempts": 0}

    out_path = Path(outdir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    s = session or make_session()

    last_err = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            r = _follow_redirect(download_url, s)
            if r.status_code >= 400:
                raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)

            ctype = (r.headers.get("Content-Type") or "").lower()
            if "text/html" in ctype:
                raise ValueError("anti-bot html page returned")

            real_name = filename.strip() if filename and filename.strip() else _guess_filename(download_url, r)
            if real_name.startswith("[zmk.pw]"):
                real_name = real_name[8:]
            real_name = unquote(real_name)
            save_to = out_path / real_name

            total = 0
            with open(save_to, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)

            if total < 100:
                raise ValueError(f"too small ({total} bytes)")

            result = {
                "ok": True,
                "saved_path": str(save_to),
                "filename": real_name,
                "bytes": total,
                "is_archive": _is_archive(save_to),
                "extracted": False,
                "subtitle_files": [],
                "selected_subtitle": "",
                "archive_removed": False,
            }

            if auto_extract and result["is_archive"]:
                subs = _extract(save_to, out_path)
                result["extracted"] = True
                result["subtitle_files"] = [str(p) for p in subs]
                best = _pick_best(subs)
                result["selected_subtitle"] = str(best) if best else ""
                if remove_archive:
                    save_to.unlink(missing_ok=True)
                    result["archive_removed"] = True

            return result

        except Exception as e:
            last_err = str(e)
            if attempt < retries:
                time.sleep(min(2 * attempt, 6))

    return {"ok": False, "error": last_err or "unknown", "attempts": retries}
