"""Collect per-reel metrics. Metrics the API doesn't return are recorded as unavailable, never estimated."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..db import MetricSnapshot, PublishJob, audit, utcnow
from ..instagram.accounts import get_token
from ..instagram.client import IGApiError, IGClient
from ..instagram.secrets import TokenCipher

# Names follow Meta's documented Reels media-insights metrics; availability varies by account/app/version.
REEL_METRICS = ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]


def collect_insights(s: Session, client: IGClient, cipher: TokenCipher, job: PublishJob,
                     now: datetime | None = None) -> MetricSnapshot:
    if job.status != "published" or not job.ig_media_id:
        raise ValueError("job has no published Instagram media id (manually published reels need manual metrics)")
    now = now or utcnow()
    token = get_token(job.account, cipher)
    metrics: dict[str, Any] = {}
    unavailable: list[dict[str, str]] = []
    for m in REEL_METRICS:
        try:
            v = client.media_insight(job.ig_media_id, token, m)
            if v is None:
                unavailable.append({"metric": m, "reason": "not returned"})
            else:
                metrics[m] = v
        except IGApiError as e:
            unavailable.append({"metric": m, "reason": f"{e.kind}: {e}"[:160]})
            if e.kind == "token":
                break
    followers = None
    try:
        followers = client.me(token).get("followers_count")
    except IGApiError:
        pass
    snap = MetricSnapshot(job_id=job.id, taken_at=now, age_hours=round((now - job.published_at).total_seconds() / 3600, 2),
                          metrics=metrics, unavailable=unavailable, followers=followers)
    s.add(snap)
    audit(s, "insights.collected", "job", job.id, got=sorted(metrics), missing=[u["metric"] for u in unavailable])
    s.flush()
    return snap
