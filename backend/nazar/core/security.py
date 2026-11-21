"""Camera source validation (SSRF guard)."""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

from .config import REPO_ROOT, get_settings

ALLOWED_SCHEMES = {"rtsp", "rtsps", "srt", "rtmp"}
LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")


class SourceError(ValueError):
    pass


def _allowed_file_roots() -> list[Path]:
    d = get_settings().data_dir
    return [(REPO_ROOT / "samples").resolve(), (d / "recordings").resolve(), (d / "uploads").resolve()]


def validate_source(url: str, kind: str | None = None) -> tuple[str, str]:
    """Returns (normalized_url, kind). Raises SourceError with a human message."""
    url = (url or "").strip()
    if not url:
        raise SourceError("source URL is empty")
    p = urlparse(url)
    scheme = (p.scheme or "").lower()
    if scheme in ("http", "https"):
        raise SourceError("http(s) sources are not allowed; use rtsp://, srt:// or rtmp://")
    if scheme in ALLOWED_SCHEMES:
        host = p.hostname or ""
        if not host:
            raise SourceError("URL has no host")
        s = get_settings()
        trusted = {"localhost", "127.0.0.1", "::1", "mediamtx", s.MEDIAMTX_HOST.lower()}
        if host.lower() not in trusted:
            try:
                addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
            except socket.gaierror:
                raise SourceError(f"cannot resolve host {host}")
            for a in addrs:
                ip = ipaddress.ip_address(a.split("%")[0])
                if ip in LINK_LOCAL or ip.is_multicast or ip.is_unspecified:
                    raise SourceError("link-local / metadata addresses are not allowed")
                if (ip.is_private or ip.is_loopback) and not s.ALLOW_LAN_CAMERAS:
                    raise SourceError("private network cameras are disabled on this server (ALLOW_LAN_CAMERAS=false)")
        k = "rtsp" if scheme == "rtsps" else scheme
        if kind == "phone":
            k = "phone"
        return url, k
    if scheme and len(scheme) > 1:
        raise SourceError(f"unsupported scheme {scheme}://")
    path = Path(url).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path)
    path = path.resolve()
    if not any(root == path or root in path.parents for root in _allowed_file_roots()):
        raise SourceError("files must be inside samples/, data/recordings/ or data/uploads/")
    if not path.exists():
        raise SourceError(f"file not found: {path.name}")
    return str(path), "file"
