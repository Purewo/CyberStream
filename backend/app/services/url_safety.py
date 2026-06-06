from __future__ import annotations

import socket
from ipaddress import ip_address
from urllib.parse import urlparse


PUBLIC_HTTP_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


class UnsafePublicUrlError(ValueError):
    def __init__(self, message: str, *, reason: str):
        super().__init__(message)
        self.reason = reason


def _normalize_hostname(hostname: str | None) -> str:
    return str(hostname or "").strip().lower().rstrip(".")


def _ip_address_from_host(host: str):
    candidate = _normalize_hostname(host)
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    try:
        return ip_address(candidate)
    except ValueError:
        pass

    try:
        return ip_address(socket.inet_aton(candidate))
    except OSError:
        return None


def _is_blocked_ip(host_ip) -> bool:
    return (
        not host_ip.is_global
        or host_ip.is_private
        or host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_multicast
        or host_ip.is_reserved
        or host_ip.is_unspecified
    )


def validate_public_http_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise UnsafePublicUrlError("URL is empty", reason="empty")

    parsed = urlparse(raw)
    if parsed.scheme not in PUBLIC_HTTP_SCHEMES or not parsed.hostname:
        raise UnsafePublicUrlError("URL must be an absolute HTTP(S) URL", reason="invalid")

    host = _normalize_hostname(parsed.hostname)
    if not host:
        raise UnsafePublicUrlError("URL host is invalid", reason="invalid")

    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        raise UnsafePublicUrlError("URL host is not allowed", reason="blocked_host")

    host_ip = _ip_address_from_host(host)
    if host_ip and _is_blocked_ip(host_ip):
        raise UnsafePublicUrlError("URL host is not allowed", reason="blocked_host")

    return raw
