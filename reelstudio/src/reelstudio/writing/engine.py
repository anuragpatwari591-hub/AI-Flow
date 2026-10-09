"""Concept generation cycle: trends + voice guide -> provider -> validate -> timing -> score -> persist."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import load_yaml
from ..db import Concept, PublishedLine, Trend, audit
from .providers import LocalSeedProvider
from .scoring import normalize, score_concept
from .types import AIProvider, ConceptRequest

log = logging.getLogger(__name__)


def assign_timing(lines: list[dict[str, Any]], timing: dict[str, Any]) -> list[dict[str, Any]]:
    t = timing["intro_seconds"]
    out = []
    for i, l in enumerate(lines):
        words = max(len(l["text"].split()), 1)
        dur = max(words / timing["words_per_second"], timing["min_line_seconds"])
        if i == len(lines) - 1:
            dur += timing["last_line_hold_seconds"] - timing["min_line_seconds"] * 0.5
        out.append({"text": l["text"], "start": round(t, 2), "end": round(t + dur, 2)})
        t += dur
    return out


def make_caption(c: dict[str, Any], voice: dict[str, Any]) -> tuple[str, list[str]]:
    cat = c["category"]
    tags = voice["hashtags"]["by_category"].get(cat, [])[: voice["hashtags"]["max"]]
    cap = c.get("caption") or c["lines"][-1]["text"]
    return cap.lower(), tags


def normalise(raw: dict[str, Any], voice: dict[str, Any], category: str) -> dict[str, Any] | None:
    """Validate a provider item into the canonical concept shape; None if unusable."""
    try:
        lines = [{"text": (l["text"] if isinstance(l, dict) else str(l)).strip()} for l in raw["lines"]]
        lines = [l for l in lines if l["text"]]
        if not 2 <= len(lines) <= voice["voice"]["max_lines"]:
            return None
        cat = voice["categories"][raw.get("category", category)]
        c = {
            "category": raw.get("category", category), "hook": raw.get("hook") or lines[0]["text"],
            "lines": assign_timing(lines, voice["timing"]), "payoff": raw.get("payoff", ""),
            "loop_strategy": raw.get("loop_strategy", ""), "rationale": raw.get("rationale", ""),
            "audio_mood": raw.get("audio_mood") or cat["mood"],
            "style": raw.get("style") or {"template": cat["template"]},
            "caption": raw.get("caption", ""),
        }
        if c["lines"][-1]["end"] > voice["timing"]["max_duration_seconds"]:
            return None
        c["caption"], c["hashtags"] = make_caption(c, voice)
        return c
    except (KeyError, TypeError, AttributeError):
        return None


def previous_lines(s: Session) -> list[str]:
    return [r for r in s.scalars(select(PublishedLine.text))]


def record_published_lines(s: Session, concept: Concept) -> None:
    for l in concept.lines:
        s.add(PublishedLine(text=l["text"], normalized=normalize(l["text"]), concept_id=concept.id))


def run_cycle(s: Session, provider: AIProvider | None = None, *, categories: list[str] | None = None,
              per_category: int = 2, top_trends: int = 5, account_insights: dict[str, Any] | None = None,
              own_history_n: int = 0, allocation: dict[str, int] | None = None) -> list[Concept]:
    voice = load_yaml("voice_guide.yaml")
    provider = provider or LocalSeedProvider()
    cycle_id = uuid.uuid4().hex[:12]
    trends = list(s.scalars(select(Trend).order_by(Trend.score.desc()).limit(top_trends)))
    tdicts = [{"id": t.id, "title": t.title, "description": t.description, "kind": t.kind, "tags": [],
               "score": t.score, "confidence": t.confidence, "lifecycle": t.lifecycle_stage} for t in trends]
    avoid = previous_lines(s)
    cycle_seed = s.query(Concept).count()
    created: list[Concept] = []
    for cat in (list(allocation) if allocation else categories or list(voice["categories"])):
        n_cat = allocation[cat] if allocation else per_category
        req = ConceptRequest(cat, n_cat + 1, tdicts, voice, avoid, account_insights or {}, cycle_seed)
        try:
            raws = provider.generate_concepts(req)
        except Exception as e:  # provider errors must not kill the cycle
            log.error("provider failed", extra={"ctx": {"category": cat, "error": str(e)}})
            audit(s, "writing.provider_error", "concept", None, category=cat, error=str(e))
            continue
        kept = 0
        for raw in raws:
            c = normalise(raw, voice, cat)
            if not c:
                continue
            res = score_concept(c, voice, avoid, trends[0].score if trends else None, own_history_n)
            if res["blocked"]:
                audit(s, "writing.concept_blocked", "concept", None, category=cat, flags=res["flags"])
                continue
            if provider.name == "local_seed":
                res["confidence"] = round(min(res["confidence"], 0.4), 3)
                res["flags"].append("offline seed writer: use an AI provider for fresher material")
            rationale = c["rationale"] or "No provider rationale."
            if trends:
                rationale += f" Trend context: '{trends[0].title}' (score {trends[0].score}, confidence {trends[0].confidence})."
            else:
                rationale += " No trend data ingested; relevance unassessed."
            row = Concept(cycle_id=cycle_id, trend_id=trends[0].id if trends else None, category=cat,
                          hook=c["hook"], lines=c["lines"], payoff=c["payoff"], loop_strategy=c["loop_strategy"],
                          caption=c["caption"], hashtags=c["hashtags"], audio_mood=c["audio_mood"], style=c["style"],
                          rationale=rationale, confidence=res["confidence"], score=res["score"],
                          score_breakdown={"breakdown": res["breakdown"], "flags": res["flags"], "basis": res["basis"]},
                          provider=provider.name)
            s.add(row)
            created.append(row)
            avoid.extend(l["text"] for l in c["lines"])
            kept += 1
            if kept >= n_cat:
                break
    s.flush()
    audit(s, "writing.cycle", "concept", None, cycle_id=cycle_id, created=len(created), provider=provider.name)
    return created
