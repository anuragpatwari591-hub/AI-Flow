"""Scheduled insight collection at fixed ages (24h, 48h, 7d) plus token upkeep."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts import notify
from ..db import IGAccount, MetricSnapshot, PublishJob, utcnow
from ..instagram.accounts import AccountError, refresh_if_needed, token_status
from ..instagram.client import IGApiError, IGClient
from ..instagram.insights import collect_insights
from ..instagram.secrets import TokenCipher

COLLECT_AT_HOURS = (24, 48, 168)


def collect_due(s: Session, client: IGClient, cipher: TokenCipher, now: datetime | None = None) -> list[int]:
    now = now or utcnow()
    taken: list[int] = []
    for job in s.scalars(select(PublishJob).where(PublishJob.status == "published", PublishJob.ig_media_id != "")):
        age = (now - job.published_at).total_seconds() / 3600
        have = [m.age_hours for m in s.scalars(select(MetricSnapshot).where(MetricSnapshot.job_id == job.id))]
        for target in COLLECT_AT_HOURS:
            if age >= target and not any(h >= target for h in have):
                try:
                    collect_insights(s, client, cipher, job, now)
                    taken.append(job.id)
                except (IGApiError, AccountError) as e:
                    notify("warning", f"insight collection failed for job {job.id}: {e}", job_id=job.id)
                break  # at most one snapshot per job per pass
    return taken


def token_upkeep(s: Session, client: IGClient, cipher: TokenCipher) -> None:
    for acct in s.scalars(select(IGAccount).where(IGAccount.revoked_at.is_(None))):
        st = token_status(acct)["state"]
        if st == "expiring_soon":
            if not refresh_if_needed(s, client, cipher, acct):
                notify("warning", f"token for @{acct.username} is expiring and refresh failed: reconnect needed", account_id=acct.id)
        elif st == "expired":
            notify("error", f"token for @{acct.username} expired: reconnect required", account_id=acct.id)
