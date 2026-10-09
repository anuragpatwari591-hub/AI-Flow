"""Background worker: publishing scheduler, token upkeep, insight collection. One process, one loop."""
from __future__ import annotations

import logging
import time

from .analytics.collector import collect_due, token_upkeep
from .config import get_settings
from .db import session_scope
from .instagram.client import IGClient
from .instagram.secrets import TokenCipher
from .publishing.queue import run_due

log = logging.getLogger(__name__)
HEARTBEAT_NAME = "worker.heartbeat"


def heartbeat_path():
    return get_settings().data_dir / HEARTBEAT_NAME


def touch_heartbeat() -> None:
    p = heartbeat_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(time.time()))


def heartbeat_age() -> float | None:
    """Seconds since the worker last completed a loop iteration (None = never)."""
    p = heartbeat_path()
    try:
        return max(time.time() - float(p.read_text()), 0.0)
    except (OSError, ValueError):
        return None


def make_client() -> IGClient:
    st = get_settings()
    return IGClient(st.meta_app_id, st.meta_app_secret, st.meta_redirect_uri, st.graph_version)


def tick(client: IGClient | None = None, cipher: TokenCipher | None = None) -> dict[str, list[int]]:
    client, cipher = client or make_client(), cipher or TokenCipher()
    with session_scope() as s:
        published = run_due(s, client, cipher)
    with session_scope() as s:
        token_upkeep(s, client, cipher)
    with session_scope() as s:
        collected = collect_due(s, client, cipher)
    return {"processed": published, "insights": collected}


def run_forever(interval: float = 30.0) -> None:
    log.info("worker started")
    while True:
        touch_heartbeat()
        try:
            res = tick()
            if any(res.values()):
                log.info("tick", extra={"ctx": res})
        except Exception:  # noqa: BLE001 - keep the loop alive; alert via logs/webhook
            log.exception("worker tick failed")
            from .alerts import notify
            notify("error", "worker tick failed (see logs)")
        time.sleep(interval)
