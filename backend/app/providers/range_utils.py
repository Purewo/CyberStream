from __future__ import annotations


def parse_http_byte_range(range_header, file_size):
    """Parse a single HTTP byte range for local-like streaming providers."""
    size = max(0, int(file_size or 0))
    if not range_header:
        return 0, max(size - 1, -1), 200, size, None

    raw = str(range_header or "").strip()
    if not raw.lower().startswith("bytes="):
        return None, None, 416, 0, f"bytes */{size}"

    spec = raw[6:].strip()
    if "," in spec or "-" not in spec:
        return None, None, 416, 0, f"bytes */{size}"
    if size <= 0:
        return None, None, 416, 0, f"bytes */{size}"

    first, last = spec.split("-", 1)
    first = first.strip()
    last = last.strip()

    try:
        if not first:
            suffix_length = int(last)
            if suffix_length <= 0:
                return None, None, 416, 0, f"bytes */{size}"
            start = max(size - suffix_length, 0)
            end = size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
    except (TypeError, ValueError):
        return None, None, 416, 0, f"bytes */{size}"

    if start < 0 or end < start or start >= size:
        return None, None, 416, 0, f"bytes */{size}"
    end = min(end, size - 1)
    length = end - start + 1
    return start, end, 206, length, f"bytes {start}-{end}/{size}"
