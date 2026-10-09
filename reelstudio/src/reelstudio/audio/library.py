"""Audio asset registry, mood/rhythm matching and rights records."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import AudioAsset, Concept, audit
from .beats import analyze_audio
from .rights import RIGHTS_STATUSES, clearance

log = logging.getLogger(__name__)
SLOW = {"slow", "ambient", "sparse", "warm", "soft"}
FAST = {"upbeat", "staccato", "steady", "pulse", "dry"}


def register_audio(s: Session, *, title: str, artist: str = "", source_url: str = "", local_file: str = "",
                   rights_status: str = "unverified", license_ref: str = "", attribution: str = "",
                   allow_offplatform_render: bool = False, allow_commercial_ads: bool = False,
                   allow_automated_publish: bool = False, mood: str = "", notes: str = "",
                   trend_evidence: dict[str, Any] | None = None, analyze: bool = True, actor: str = "owner") -> AudioAsset:
    if rights_status not in RIGHTS_STATUSES:
        raise ValueError(f"rights_status must be one of {RIGHTS_STATUSES}")
    if rights_status in ("licensed", "royalty_free") and not license_ref:
        raise ValueError("licensed/royalty_free audio needs a license_ref (licence id, URL or receipt)")
    a = AudioAsset(title=title, artist=artist, source_url=source_url, local_file=local_file,
                   rights_status=rights_status, license_ref=license_ref, attribution=attribution,
                   allow_offplatform_render=allow_offplatform_render, allow_commercial_ads=allow_commercial_ads,
                   allow_automated_publish=allow_automated_publish, mood=mood, notes=notes,
                   trend_evidence=trend_evidence or {})
    if analyze and local_file and rights_status != "unverified" and Path(local_file).exists():
        res = analyze_audio(Path(local_file))
        a.bpm, a.beats = res["bpm"], res["beats"]
    s.add(a)
    s.flush()
    audit(s, "audio.registered", "audio", a.id, actor, rights_status=rights_status, title=title)
    return a


def _tokens(text: str) -> set[str]:
    return {w.strip(",.;:-").lower() for w in text.split() if len(w) > 2}


def match_audio(s: Session, concept: Concept, purpose: str = "render") -> list[dict[str, Any]]:
    want = _tokens(concept.audio_mood)
    out = []
    for a in s.scalars(select(AudioAsset)):
        ok, reasons = clearance(a, purpose)  # type: ignore[arg-type]
        have = _tokens(a.mood)
        mood_score = len(want & have) / max(len(want | have), 1)
        tempo = 0.0
        if a.bpm:
            if want & SLOW:
                tempo = 1.0 if a.bpm <= 95 else 0.3
            elif want & FAST:
                tempo = 1.0 if a.bpm >= 100 else 0.4
            else:
                tempo = 0.5
        score = 0.65 * mood_score + 0.35 * tempo
        out.append({"audio_id": a.id, "title": a.title, "rights_status": a.rights_status, "cleared": ok,
                    "blockers": reasons, "mood_overlap": round(mood_score, 2), "bpm": a.bpm,
                    "score": round(score, 3) if ok else 0.0,
                    "explanation": f"mood overlap {mood_score:.2f}, tempo fit {tempo:.2f}" if ok else "; ".join(reasons)})
    return sorted(out, key=lambda r: (r["cleared"], r["score"]), reverse=True)
