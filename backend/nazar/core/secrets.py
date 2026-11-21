"""Camera credentials encrypted at rest (Fernet). The key lives in .env (FERNET_KEY), generated on first use.
Passwords are never returned by the API; URLs are stored without credentials and rebuilt only inside the edge."""
from __future__ import annotations

import logging
import threading
from urllib.parse import quote, urlparse, urlunparse

from .config import ENV_FILE, get_settings

log = logging.getLogger("nazar.secrets")
_lock = threading.Lock()
_fernet = None


def _key() -> bytes:
    from cryptography.fernet import Fernet

    s = get_settings()
    if s.FERNET_KEY:
        return s.FERNET_KEY.encode()
    with _lock:
        key = Fernet.generate_key().decode()
        try:
            text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
            if "FERNET_KEY=" in text and any(ln.startswith("FERNET_KEY=") and ln.strip() != "FERNET_KEY="
                                              for ln in text.splitlines()):
                raise RuntimeError("FERNET_KEY present in .env but not loaded")
            lines = [ln for ln in text.splitlines() if not ln.startswith("FERNET_KEY=")]
            lines.append(f"FERNET_KEY={key}")
            ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
            log.info("generated FERNET_KEY in .env (camera passwords are encrypted with it)")
        except Exception as e:
            log.error("could not persist FERNET_KEY: %s", e)
        get_settings.cache_clear()
        return key.encode()


def fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet

        _fernet = Fernet(_key())
    return _fernet


def encrypt(v: str | None) -> str | None:
    return fernet().encrypt(v.encode()).decode() if v else None


def decrypt(v: str | None) -> str | None:
    return fernet().decrypt(v.encode()).decode() if v else None


def split_credentials(url: str) -> tuple[str, str | None, str | None]:
    """rtsp://user:pass@host/path -> (rtsp://host/path, user, pass)."""
    p = urlparse(url)
    if not p.username and not p.password:
        return url, None, None
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    from urllib.parse import unquote

    return urlunparse(p._replace(netloc=host)), unquote(p.username or "") or None, unquote(p.password or "") or None


def with_credentials(url: str, user: str | None, password: str | None) -> str:
    if not user and not password:
        return url
    p = urlparse(url)
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    auth = quote(user or "", safe="") + (":" + quote(password or "", safe="") if password else "")
    return urlunparse(p._replace(netloc=f"{auth}@{host}"))


def save_camera_credentials(db, camera_id: str, user: str | None, password: str | None) -> None:
    if not user and not password:
        db.execute("DELETE FROM camera_credentials WHERE camera_id=%s", (camera_id,))
        return
    db.execute("INSERT INTO camera_credentials(camera_id, enc_username, enc_password) VALUES (%s,%s,%s) "
               "ON CONFLICT (camera_id) DO UPDATE SET enc_username=EXCLUDED.enc_username, enc_password=EXCLUDED.enc_password",
               (camera_id, encrypt(user), encrypt(password)))


def source_url_for(db, camera_id: str, url: str) -> str:
    """The URL the edge connects to (credentials decrypted in memory only)."""
    row = db.fetch_one("SELECT enc_username, enc_password FROM camera_credentials WHERE camera_id=%s", (camera_id,))
    if not row:
        return url
    return with_credentials(url, decrypt(row["enc_username"]), decrypt(row["enc_password"]))
