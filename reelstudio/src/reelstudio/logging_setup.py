"""Structured (JSON-lines) logging."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone


_SECRET = re.compile(r"(access_token|client_secret|fb_exchange_token|code)=([^&\s\"']+)", re.I)


def redact(text: str) -> str:
    return _SECRET.sub(r"\1=[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "ctx", None)
        if extra:
            payload["ctx"] = extra
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore"):  # their INFO lines contain full request URLs (incl. access_token)
        logging.getLogger(noisy).setLevel(logging.WARNING)
