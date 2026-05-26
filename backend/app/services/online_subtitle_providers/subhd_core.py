"""subhd.tv 字幕搜索与下载模块。

搜索输出格式对齐 srtku skill，包含：
  title, quality, download_number, update_time, language,
  format, file_size, uploader, film_name, detail_url
"""

from __future__ import annotations

import re
import io
import json
import requests
from urllib.parse import quote
from bs4 import BeautifulSoup

BASE = "https://subhd.tv"


# ============================================================
# Session 工厂
# ============================================================

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    })
    return s


# ============================================================
# 搜索
# ============================================================

def search_subtitle(keyword: str, session: requests.Session | None = None) -> list[dict]:
    """搜索字幕，返回结果列表。

    每条结果包含：
      film_name, title, quality, download_number, update_time,
      language, format, file_size, uploader, detail_url, hash
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    s = session or make_session()
    url = f"{BASE}/search/{quote(keyword)}"
    r = s.get(url, timeout=30)
    if r.status_code >= 400:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    results: list[dict] = []
    seen: set[str] = set()

    for div in soup.find_all("div", class_="clearfix"):
        a_tags = div.find_all("a", href=lambda h: h and "/a/" in h)
        if not a_tags:
            continue

        # 提取 hash 和基本信息
        film_name = ""
        title = ""
        sub_hash = ""
        for i, a in enumerate(a_tags):
            href = a["href"]
            text = a.get_text(strip=True)
            h = href.split("/a/")[-1]
            if not sub_hash:
                sub_hash = h
                film_name = text
            elif h == sub_hash and text != film_name:
                title = text

        if sub_hash in seen:
            continue
        seen.add(sub_hash)

        # 提取 spans
        spans = div.find_all("span")
        quality = ""       # 转载精修/原创翻译/官方字幕
        languages = []     # 双语/简体/繁体/英语
        fmt = ""           # ASS/SRT/SUP
        file_size = ""
        download_number = ""
        update_time = ""

        for sp in spans:
            cls = " ".join(sp.get("class", []))
            text = sp.get_text(strip=True)
            if not text:
                continue

            if "text-white" in cls and "rounded" in cls:
                quality = text
            elif "fw-bold" in cls:
                languages.append(text)
            elif "text-secondary" in cls and re.match(r'^[A-Z]{2,4}$', text):
                fmt = text

        # 从 info div 提取文件大小、下载量、时间
        info = div.find("div", class_="pt-2")
        if info:
            info_spans = info.find_all("span", class_="align-text-top")
            svgs = info.find_all("svg")

            for i, svg in enumerate(svgs):
                cls = " ".join(svg.get("class", []))
                # 找 svg 后面最近的 span
                val = ""
                if i < len(info_spans):
                    val = info_spans[i].get_text(strip=True)

                if "file-earmark" in cls:
                    file_size = val
                elif "download" in cls:
                    download_number = val
                elif "clock" in cls:
                    update_time = val

        # 上传者
        uploader = ""
        u_link = div.find("a", href=lambda h: h and "/u/" in h)
        if u_link:
            uploader = u_link.get_text(strip=True)

        results.append({
            "film_name": film_name,
            "title": title or film_name,
            "quality": quality,
            "download_number": download_number,
            "update_time": update_time,
            "language": languages,
            "format": fmt,
            "file_size": file_size,
            "uploader": uploader,
            "detail_url": f"{BASE}/a/{sub_hash}",
            "hash": sub_hash,
        })

    return results


# ============================================================
# SVG 验证码 OCR
# ============================================================

def _bezier_quad(p0, p1, p2, steps=10):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = (1-t)**2 * p0[0] + 2*(1-t)*t * p1[0] + t**2 * p2[0]
        y = (1-t)**2 * p0[1] + 2*(1-t)*t * p1[1] + t**2 * p2[1]
        pts.append((x, y))
    return pts


def _render_path(draw, d, fill, scale):
    cmds = re.findall(r'([MLQCZ])([\d\s.,\-]*)', d, re.I)
    points = []
    cx, cy = 0, 0
    for cmd, args in cmds:
        nums = [float(x) for x in re.findall(r'[\d.\-]+', args)]
        cmd = cmd.upper()
        if cmd == 'M':
            if points and len(points) >= 3:
                draw.polygon(points, fill=fill)
            points = []
            cx, cy = nums[0], nums[1]
            points.append((cx * scale, cy * scale))
        elif cmd == 'L':
            for i in range(0, len(nums), 2):
                cx, cy = nums[i], nums[i+1]
                points.append((cx * scale, cy * scale))
        elif cmd == 'Q':
            for i in range(0, len(nums), 4):
                if i + 3 < len(nums):
                    cpx, cpy = nums[i], nums[i+1]
                    ex, ey = nums[i+2], nums[i+3]
                    for bx, by in _bezier_quad((cx, cy), (cpx, cpy), (ex, ey))[1:]:
                        points.append((bx * scale, by * scale))
                    cx, cy = ex, ey
    if points and len(points) >= 3:
        draw.polygon(points, fill=fill)


def svg_to_png(svg_str: str, scale: float = 5.0) -> bytes:
    from PIL import Image, ImageDraw

    vb = re.search(r'viewBox="([\d,.\s]+)"', svg_str)
    if vb:
        parts = re.findall(r'[\d.]+', vb.group(1))
        w, h = float(parts[2]), float(parts[3])
    else:
        w, h = 150, 50
    img = Image.new("RGB", (int(w * scale), int(h * scale)), "white")
    draw = ImageDraw.Draw(img)
    for m in re.finditer(r'<path\s+fill="([^"]+)"\s+d="([^"]+)"', svg_str):
        _render_path(draw, m.group(2), m.group(1), scale)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_ocr_instance = None

def ocr_svg(svg_str: str) -> str:
    global _ocr_instance
    if _ocr_instance is None:
        import ddddocr
        _ocr_instance = ddddocr.DdddOcr(show_ad=False)
    png = svg_to_png(svg_str)
    return _ocr_instance.classification(png)


# ============================================================
# 下载
# ============================================================

def download_subtitle(
    sub_hash: str,
    session: requests.Session | None = None,
    max_retries: int = 5,
) -> dict:
    """下载字幕文件。

    返回：
      成功: {"success": True, "url": "...", "content": bytes, "ext": "...", "attempts": N}
      失败: {"success": False, "reason": "...", "attempts": N}
    """
    s = session or make_session()

    # 访问详情页和下载页
    s.get(f"{BASE}/a/{sub_hash}", timeout=30)
    r = s.get(f"{BASE}/down/{sub_hash}", timeout=30)
    soup = BeautifulSoup(r.text, "lxml")
    btn = soup.find("button", class_="down")
    sid = btn.get("sid", sub_hash) if btn else sub_hash

    cap = ""
    for attempt in range(max_retries):
        r2 = s.post(
            f"{BASE}/api/sub/down",
            json={"sid": sid, "cap": cap},
            headers={
                "Content-Type": "application/json",
                "Referer": f"{BASE}/down/{sub_hash}",
                "Origin": BASE,
            },
            timeout=30,
        )
        try:
            data = r2.json()
        except ValueError:
            return {
                "success": False,
                "reason": f"invalid_json_status_{r2.status_code}",
                "attempts": attempt + 1,
            }

        if data.get("success") and data.get("pass"):
            url = data["url"]
            r3 = s.get(url, timeout=30)
            if r3.status_code >= 400:
                return {
                    "success": False,
                    "reason": f"download_http_{r3.status_code}",
                    "attempts": attempt + 1,
                }
            ext = url.split(".")[-1]
            return {
                "success": True,
                "url": url,
                "content": r3.content,
                "ext": ext,
                "attempts": attempt + 1,
            }

        if data.get("pass") is False:
            svg = data.get("msg", "")
            if "<svg" in svg:
                cap = ocr_svg(svg)
                continue
            return {"success": False, "reason": "unknown_captcha", "attempts": attempt + 1}

        return {"success": False, "reason": "api_error", "attempts": attempt + 1}

    return {"success": False, "reason": "max_retries", "attempts": max_retries}
