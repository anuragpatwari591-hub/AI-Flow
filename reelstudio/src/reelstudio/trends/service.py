"""Trend research service: run sources, score, persist, rank."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import load_yaml
from ..db import Trend, audit
from .scoring import infer_lifecycle, score_trend
from .sources import SourceUnavailable, TrendSource

log = logging.getLogger(__name__)


def dedupe_key(kind: str, title: str, source: str) -> str:
    return hashlib.sha256(f"{kind}|{' '.join(title.lower().split())}|{source}".encode()).hexdigest()[:40]


def run_research(s: Session, sources: list[TrendSource], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_yaml("trends.yaml")
    report: dict[str, Any] = {"ingested": 0, "updated": 0, "sources": {}}
    for src in sources:
        try:
            cands = src.fetch()
        except SourceUnavailable as e:
            report["sources"][src.name] = {"status": "unavailable", "reason": str(e)}
            log.warning("trend source unavailable", extra={"ctx": {"source": src.name, "reason": str(e)}})
            continue
        n = 0
        for c in cands:
            res = score_trend(c, cfg)
            key = dedupe_key(c.kind, c.title, c.source)
            row = s.scalar(select(Trend).where(Trend.dedupe_key == key))
            fields = dict(
                kind=c.kind, title=c.title, description=c.description, source=c.source, source_url=c.source_url,
                signals=res["signals"], evidence=c.evidence + [{"type": "raw_metrics", "ref": c.raw_metrics}] if c.raw_metrics else c.evidence,
                confidence=res["confidence"], lifecycle_stage=infer_lifecycle(c), audience_fit=res["audience_fit"],
                rights=c.rights or {"note": "no third-party assets implied; verify before use"},
                score=res["score"], score_breakdown={"weights_applied": res["breakdown"], "missing": res["missing"]},
            )
            if row:
                for k, v in fields.items():
                    setattr(row, k, v)
                report["updated"] += 1
            else:
                s.add(Trend(dedupe_key=key, discovered_at=c.observed_at or datetime.now(timezone.utc), **fields))
                report["ingested"] += 1
            n += 1
        report["sources"][src.name] = {"status": "ok", "count": n}
    audit(s, "trends.research_run", "trend", None, report=report)
    s.flush()
    return report


def ranked_trends(s: Session, limit: int = 20, kind: str | None = None) -> list[Trend]:
    q = select(Trend).order_by(Trend.score.desc(), Trend.confidence.desc())
    if kind:
        q = q.where(Trend.kind == kind)
    return list(s.scalars(q.limit(limit)))
