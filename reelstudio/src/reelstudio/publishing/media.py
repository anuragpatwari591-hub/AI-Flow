"""Media hashing and signed public URLs (Instagram must fetch video_url over public HTTPS)."""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import httpx

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


class MediaUnreachable(Exception):
    """The signed public media URL is not servable the way Instagram needs it."""


def verify_public_media(url: str, expected_size: int, kind_prefix: str, http: httpx.Client | None = None) -> None:
    """Fetch the PUBLIC URL (no redirects, ranged GET) and check status, content-type and total size.

    This proves the file is reachable over the public internet path from this server. It cannot prove Instagram's
    own fetcher succeeds (that is only confirmed when the container reaches FINISHED)."""
    http = http or httpx.Client(timeout=20, follow_redirects=False)
    try:
        r = http.get(url, headers={"Range": "bytes=0-0"})
    except httpx.HTTPError as e:
        raise MediaUnreachable(f"public media URL not reachable ({type(e).__name__})") from e
    if r.status_code not in (200, 206):
        raise MediaUnreachable(f"public media URL returned HTTP {r.status_code}")
    ctype = r.headers.get("content-type", "")
    if not ctype.startswith(kind_prefix):
        raise MediaUnreachable(f"public media URL served content-type '{ctype}', expected {kind_prefix}*")
    total = None
    cr = r.headers.get("content-range", "")
    if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
        total = int(cr.rsplit("/", 1)[1])
    elif r.status_code == 200 and r.headers.get("content-length", "").isdigit():
        total = int(r.headers["content-length"])
    if total is not None and total != expected_size:
        raise MediaUnreachable(f"public media size {total} != rendered file size {expected_size}")
