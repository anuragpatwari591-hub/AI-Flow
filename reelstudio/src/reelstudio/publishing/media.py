"""Media hashing and signed public URLs (Instagram must fetch video_url over public HTTPS)."""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from ..config import get_settings
from ..instagram.secrets import SecretsError


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sig(reel_id: int, kind: str, sha: str) -> str:
    secret = get_settings().secret_key
    if not secret:
        raise SecretsError("RS_SECRET_KEY is not set; refusing to sign media URLs")
    key = secret.encode()
    return hmac.new(key, f"{reel_id}|{kind}|{sha}".encode(), hashlib.sha256).hexdigest()[:32]


def sign_media(reel_id: int, kind: str, sha: str) -> str:
    return _sig(reel_id, kind, sha)


def verify_media(reel_id: int, kind: str, sha: str, sig: str) -> bool:
    return hmac.compare_digest(_sig(reel_id, kind, sha), sig)


def public_url(reel_id: int, kind: str, sha: str, base: str | None = None) -> str:
    base = (base if base is not None else get_settings().public_base_url).rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("RS_PUBLIC_BASE_URL must be a public https:// URL for Instagram to fetch media")
    return f"{base}/media/{reel_id}/{kind}/{sign_media(reel_id, kind, sha)}"
