from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import config


_TEXT_BLOCK_RE = re.compile(r"```text\s*(?P<body>.*?)```", re.S)
_SIZE_SUFFIX_RE = re.compile(r"\s+\[[^\]]+\]$")
VIDEO_EXTENSIONS = tuple(ext.lower() for ext in config.VIDEO_EXTENSIONS)


def load_video_paths_from_markdown(markdown_path: Path) -> list[str]:
    content = markdown_path.read_text(encoding="utf-8")
    return extract_video_paths_from_markdown(content)


def extract_video_paths_from_markdown(markdown_text: str) -> list[str]:
    match = _TEXT_BLOCK_RE.search(markdown_text)
    if not match:
        raise ValueError("未找到 ```text 代码块，无法解析目录导出")

    stack: list[str] = []
    video_paths: list[str] = []

    for raw_line in match.group("body").splitlines():
        if not raw_line.strip():
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        depth = indent // 2
        entry = _SIZE_SUFFIX_RE.sub("", raw_line.strip())
        is_directory = entry.endswith("/")
        name = entry[:-1] if is_directory else entry

        if depth == 0:
            stack = [name]
            continue

        stack = stack[:depth]
        if is_directory:
            stack.append(name)
            continue

        full_path = "/".join(stack + [name])
        if name.lower().endswith(VIDEO_EXTENSIONS):
            video_paths.append(full_path)

    return video_paths


def build_scanner_file_items(paths: list[str]) -> list[dict]:
    return [
        {
            "name": Path(path).name,
            "path": path,
            "size": 1,
            "isdir": False,
        }
        for path in paths
    ]
