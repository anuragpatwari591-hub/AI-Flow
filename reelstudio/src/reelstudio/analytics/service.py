"""Performance analytics against the account's OWN baseline, with sample-size and age safeguards.

Principles: never fabricate missing metrics; compare at matched age; use robust statistics (median/MAD);
declare nothing a "winner" without enough comparable reels; keep exploring so one format isn't repeated blindly.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import MetricSnapshot, PublishJob

MIN_BASELINE = 5
MIN_GROUP = 3
TARGET_AGE_H = 48.0
AGE_TOLERANCE = 0.5  # snapshots within +-50% of the target age are comparable


def hook_style(hook: str) -> str:
    h = hook.strip().lower()
    if h.startswith(("me:", "me at", "you:")) or h.startswith(("'", '"')):
        return "dialogue"
    if h.endswith("?"):
        return "question"
    if ":" in h:
        return "label_colon"
    return "statement"


def length_bucket(duration: float) -> str:
    return "short<8s" if duration < 8 else "mid8-11s" if duration < 11 else "long>=11s"


def derive(metrics: dict[str, Any], followers: int | None) -> dict[str, float | None]:
    reach = metrics.get("reach")
    inter = [metrics.get(k) for k in ("likes", "comments", "shares", "saved")]
    have = [x for x in inter if x is not None]
    out: dict[str, float | None] = {
        "reach": reach,
        "engagement_rate": (sum(have) / reach) if reach and len(have) == 4 else None,  # only if all four are known
        "save_rate": (metrics["saved"] / reach) if reach and metrics.get("saved") is not None else None,
        "share_rate": (metrics["shares"] / reach) if reach and metrics.get("shares") is not None else None,
        "reach_per_1k_followers": (reach / followers * 1000) if reach and followers else None,
        "avg_watch_time_ms": metrics.get("ig_reels_avg_watch_time"),
    }
    return out


def _nearest_snapshot(snaps: list[MetricSnapshot], target: float = TARGET_AGE_H) -> MetricSnapshot | None:
    ok = [s for s in snaps if abs(s.age_hours - target) <= target * AGE_TOLERANCE]
    return min(ok, key=lambda s: abs(s.age_hours - target)) if ok else None


def reel_rows(s: Session) -> list[dict[str, Any]]:
    rows = []
    for job in s.scalars(select(PublishJob).where(PublishJob.status == "published").order_by(PublishJob.published_at)):
        snaps = list(s.scalars(select(MetricSnapshot).where(MetricSnapshot.job_id == job.id).order_by(MetricSnapshot.taken_at)))
        reel, concept = job.reel, job.reel.concept
        snap = _nearest_snapshot(snaps)
        latest = snaps[-1] if snaps else None
        first, last = (snaps[0], snaps[-1]) if len(snaps) >= 2 else (None, None)
        rows.append({
            "job_id": job.id, "reel_id": reel.id, "published_at": job.published_at, "permalink": job.permalink,
            "category": concept.category, "hook": concept.hook, "hook_style": hook_style(concept.hook),
            "length": length_bucket(reel.render_spec.get("duration", 0)), "template": reel.template,
            "audio": ("native/manual" if reel.needs_native_audio else "none" if not reel.audio_id else f"asset:{reel.audio_id}"),
            "snapshots": len(snaps), "latest_age_h": latest.age_hours if latest else None,
            "latest": derive(latest.metrics, latest.followers) if latest else None,
            "matched": derive(snap.metrics, snap.followers) if snap else None,
            "matched_age_h": snap.age_hours if snap else None,
            "unavailable": latest.unavailable if latest else [],
            "followers_delta": (last.followers - first.followers) if first and last and first.followers is not None and last.followers is not None else None,
            "followers_delta_note": "confounded by other activity; not attributable to this reel alone",
        })
    return rows


def _robust(vals: list[float]) -> tuple[float, float]:
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals]) * 1.4826
    return med, mad


def assess(rows: list[dict[str, Any]], row: dict[str, Any], metric: str = "engagement_rate") -> dict[str, Any]:
    """Compare one reel to prior reels at matched age. Returns a verdict only with enough baseline."""
    if not row["matched"] or row["matched"].get(metric) is None:
        return {"verdict": "no_data", "reason": f"{metric} not available at ~{TARGET_AGE_H:.0f}h"}
    prior = [r["matched"][metric] for r in rows if r["published_at"] < row["published_at"] and r["matched"]
             and r["matched"].get(metric) is not None]
    if len(prior) < MIN_BASELINE:
        return {"verdict": "insufficient_baseline", "n_prior": len(prior), "needed": MIN_BASELINE}
    med, mad = _robust(prior)
    v = row["matched"][metric]
    ratio = v / med if med else None
    z = (v - med) / mad if mad else None
    verdict = "typical"
    if ratio is not None and z is not None:
        if ratio >= 1.3 and z >= 1.0:
            verdict = "above_baseline"
        elif ratio <= 0.7 and z <= -1.0:
            verdict = "below_baseline"
    return {"verdict": verdict, "value": v, "baseline_median": med, "ratio": ratio, "robust_z": z, "n_prior": len(prior),
            "note": "matched-age, own-history comparison; correlation not causation"}


def breakdown(rows: list[dict[str, Any]], dimension: str, metric: str = "engagement_rate") -> list[dict[str, Any]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["matched"] and r["matched"].get(metric) is not None:
            groups[str(r[dimension])].append(r["matched"][metric])
    allv = [v for g in groups.values() for v in g]
    overall = statistics.median(allv) if allv else None
    out = []
    for k, vals in sorted(groups.items()):
        med = statistics.median(vals)
        out.append({"group": k, "n": len(vals), "median": med,
                    "vs_overall": (med / overall) if overall else None,
                    "reliable": len(vals) >= MIN_GROUP,
                    "caveat": None if len(vals) >= MIN_GROUP else f"only {len(vals)} reel(s); below the {MIN_GROUP}-reel minimum"})
    return out


def declare_winners(rows: list[dict[str, Any]], dimension: str, metric: str = "engagement_rate") -> dict[str, Any]:
    br = [b for b in breakdown(rows, dimension, metric) if b["reliable"]]
    if len(br) < 2:
        return {"winner": None, "reason": "need at least two groups with >=3 matched-age reels each"}
    br.sort(key=lambda b: b["median"], reverse=True)
    top, nxt = br[0], br[1]
    if nxt["median"] and top["median"] / nxt["median"] >= 1.2:
        return {"winner": top["group"], "margin": round(top["median"] / nxt["median"], 2),
                "caveat": "tentative: small sample, keep testing alternatives"}
    return {"winner": None, "reason": "no group leads by >=20%; treat as tie"}


def recommend_mix(rows: list[dict[str, Any]], categories: list[str], total: int = 6,
                  max_share: float = 0.4, explore_floor: int = 1) -> dict[str, Any]:
    """Allocate concept slots across categories: shrunk relative performance + guaranteed exploration."""
    br = {b["group"]: b for b in breakdown(rows, "category")}
    overall = [r["matched"]["engagement_rate"] for r in rows if r["matched"] and r["matched"].get("engagement_rate") is not None]
    base = statistics.median(overall) if overall else None
    weights: dict[str, float] = {}
    notes: dict[str, str] = {}
    for c in categories:
        b = br.get(c)
        if not b or not base:
            weights[c], notes[c] = 1.0, "no data: neutral weight (exploration)"
            continue
        k = 4  # shrinkage prior strength
        rel = b["vs_overall"] or 1.0
        shrunk = (b["n"] * rel + k * 1.0) / (b["n"] + k)
        weights[c] = max(shrunk, 0.25)
        notes[c] = f"n={b['n']}, raw x{rel:.2f}, shrunk x{shrunk:.2f}"
    tw = sum(weights.values())
    alloc = {c: max(explore_floor, round(total * w / tw)) for c, w in weights.items()}
    cap = max(int(total * max_share), 1)
    alloc = {c: min(n, cap) for c, n in alloc.items()}
    return {"allocation": alloc, "notes": notes, "basis_reels": len(overall),
            "caveat": "recommendation, not a guarantee; every category keeps a minimum slot"}


def adaptive_plan(s: Session, categories: list[str], total: int = 6) -> dict[str, Any]:
    """Feed analytics back into the writing cycle: returns allocation + insights for `run_cycle`."""
    rows = reel_rows(s)
    mix = recommend_mix(rows, categories, total)
    comparable = [r for r in rows if r["matched"] and r["matched"].get("engagement_rate") is not None]
    insights = {"category_mix_notes": mix["notes"], "hook_styles": breakdown(rows, "hook_style"),
                "lengths": breakdown(rows, "length"), "basis_reels": len(comparable)}
    return {"allocation": mix["allocation"], "account_insights": insights, "own_history_n": len(comparable)}
