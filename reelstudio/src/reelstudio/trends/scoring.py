"""Trend ranking. Missing signals are excluded and lower confidence; they are never filled with guesses."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .models import SIGNAL_NAMES, Signal, TrendCandidate, unavailable

RIGHTS_SCORE = {"original": 1.0, "licensed": 1.0, "royalty_free": 0.9, "instagram_native": 0.5, "unverified": 0.1}


def estimate_signals(c: TrendCandidate, cfg: dict[str, Any], now: datetime | None = None) -> dict[str, Signal]:
    now = now or datetime.now(timezone.utc)
    sig = dict(c.signals)
    if "freshness" not in sig:
        if c.observed_at:
            age_days = max((now - c.observed_at).total_seconds() / 86400, 0)
            half = cfg.get("freshness_half_life_days", 10)
            sig["freshness"] = Signal(0.5 ** (age_days / half), "measured", f"observed {age_days:.1f}d ago")
        else:
            sig["freshness"] = unavailable("no observation date")
    if "audience_relevance" not in sig:
        aud = cfg.get("audience", {})
        text = f"{c.title} {c.description} {' '.join(c.tags)}".lower()
        if any(k in text for k in aud.get("avoid_keywords", [])):
            sig["audience_relevance"] = Signal(0.0, "estimate", "matches avoid-list keyword")
        else:
            hits = [k for k in aud.get("keywords", []) if k in text]
            sig["audience_relevance"] = Signal(min(len(hits) / 2, 1.0), "estimate",
                                               f"keyword overlap with audience profile: {hits or 'none'}")
    if "feasibility" not in sig:
        supported = set(cfg.get("supported_features", []))
        tags = set(c.tags)
        if tags:
            sig["feasibility"] = Signal(len(tags & supported) / len(tags) if tags else 0.5, "estimate",
                                        f"renderer supports {sorted(tags & supported)} of {sorted(tags)}")
        else:
            sig["feasibility"] = Signal(0.7, "estimate", "no format tags; text-led default assumed")
    if "originality" not in sig:
        sig["originality"] = unavailable("needs analyst judgement or similarity data")
    if "rights_clearance" not in sig:
        if c.kind == "audio":
            r = c.rights.get("audio_rights", "unverified")
            sig["rights_clearance"] = Signal(RIGHTS_SCORE.get(r, 0.1), "measured" if r != "unverified" else "estimate",
                                             f"audio rights: {r}")
        else:
            sig["rights_clearance"] = Signal(0.9, "estimate", "non-audio trend; no known third-party asset use")
    for name in SIGNAL_NAMES:
        sig.setdefault(name, unavailable("not collected"))
    return sig


def score_trend(c: TrendCandidate, cfg: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    sig = estimate_signals(c, cfg, now)
    w = cfg["weights"]
    total_w = sum(w.values())
    used = {n: s for n, s in sig.items() if s.value is not None}
    used_w = sum(w[n] for n in used)
    score = sum(w[n] * s.value for n, s in used.items()) / used_w if used_w else 0.0
    # confidence: weight coverage, measured counts fully, estimates half
    cov = sum(w[n] * (1.0 if s.kind == "measured" else 0.5) for n, s in used.items()) / total_w
    # unverified audio is capped regardless of popularity
    if c.kind == "audio" and c.rights.get("audio_rights", "unverified") == "unverified":
        score = min(score, 0.45)
    # audience mismatch veto
    ar = sig["audience_relevance"]
    if ar.value == 0.0 and "avoid-list" in ar.note:
        score = min(score, 0.1)
    return {
        "signals": {n: s.to_dict() for n, s in sig.items()},
        "score": round(score, 4),
        "confidence": round(cov, 3),
        "audience_fit": sig["audience_relevance"].value,
        "breakdown": {n: round(w[n] * s.value, 4) for n, s in used.items()},
        "missing": sorted(n for n in SIGNAL_NAMES if n not in used),
    }


def infer_lifecycle(c: TrendCandidate) -> str:
    """Estimate lifecycle from measured momentum if supplied; otherwise keep the source's label or 'unknown'."""
    m = c.signals.get("momentum")
    if c.lifecycle_stage != "unknown" or not m or m.value is None or m.kind != "measured":
        return c.lifecycle_stage
    v = m.value
    return "emerging" if v > 0.6 else "rising" if v > 0.3 else "peak" if v > 0.05 else "declining"


__all__ = ["score_trend", "estimate_signals", "infer_lifecycle", "math"]
