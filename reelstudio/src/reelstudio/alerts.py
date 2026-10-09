"""Error alerting: structured log always; optional webhook (RS_ALERT_WEBHOOK_URL)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("reelstudio.alerts")


def notify(level: str, message: str, **ctx: Any) -> None:
    getattr(log, "error" if level == "error" else "warning")(message, extra={"ctx": ctx})
    url = get_settings().alert_webhook_url
    if not url:
        return
    try:
        httpx.post(url, json={"text": f"[reelstudio:{level}] {message}", "ctx": ctx}, timeout=5)
    except httpx.HTTPError as e:  # alerting must never break the pipeline
        log.warning("alert webhook failed", extra={"ctx": {"error": str(e)}})
