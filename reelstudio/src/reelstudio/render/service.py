"""Orchestrates concept -> preview -> final render -> cover -> QA, persisting a Reel row."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..audio.rights import clearance, required_attribution
from ..config import get_settings, load_yaml
from ..db import AudioAsset, Concept, Reel, audit
from ..publishing.media import file_sha256
from .fonts import font_record
from .renderer import plan_render, qa_video, render_cover, render_video
from .spec import load_template, spec_hash


class AudioRightsError(Exception):
    pass


def render_reel(s: Session, concept_id: int, *, template: str | None = None, overrides: dict[str, Any] | None = None,
                audio_id: int | None = None, music_branding: bool = False, preview_only: bool = False,
                out_root: Path | None = None, actor: str = "system", commit_early: bool = False, lines: list[dict[str, Any]] | None = None,
                purpose: str = "organic") -> Reel:
    concept = s.get(Concept, concept_id)
    if concept is None:
        raise KeyError(f"concept {concept_id}")
    voice = load_yaml("voice_guide.yaml")
    style = concept.style or {}
    ov = {**(style.get("overrides") or {}), **(overrides or {})}
    audio = s.get(AudioAsset, audio_id) if audio_id else None
    if audio_id and audio is None:
        raise KeyError(f"audio {audio_id}")

    needs_native = False
    audio_path: Path | None = None
    if audio is not None:
        if audio.rights_status == "instagram_native":
            needs_native = True  # render silent; owner attaches native audio in-app
            audio = None
        else:
            ok, why = clearance(audio, "render")
            if not ok:
                audit(s, "render.audio_blocked", "audio", audio.id, actor, reasons=why)
                raise AudioRightsError("; ".join(why))
            if purpose == "ad":
                ok, why = clearance(audio, "ads")
                if not ok:
                    audit(s, "render.audio_blocked", "audio", audio.id, actor, reasons=why, purpose="ad")
                    raise AudioRightsError("ads: " + "; ".join(why))
            audio_path = Path(audio.local_file)

    if music_branding and concept.category in voice["branding"]["apply_to_categories"]:
        ov = {**ov, "branding": {"enabled": True, "text": voice["branding"]["music_content_credit"]}}
    spec = load_template(template or style.get("template", "midnight_minimal"), ov)

    reel = Reel(concept_id=concept.id, audio_id=audio.id if audio else None, template=spec.name,
                render_status="rendering", needs_native_audio=needs_native, purpose=purpose)
    s.add(reel)
    s.flush()
    if commit_early:  # make "rendering" status visible to the dashboard while FFmpeg runs
        s.commit()
    root = (out_root or get_settings().renders_dir) / f"reel_{reel.id}"
    beats = audio.beats if audio else []
    try:
        full_plan = plan_render(spec, lines or concept.lines, beats, 1.0)
        reel.qa = {"text": full_plan.qa_text}
        if not (full_plan.qa_text["text_fits_safe_area"] and full_plan.qa_text["contrast_ok"]):
            raise ValueError(f"readability check failed: {full_plan.qa_text}")
        prev_plan = plan_render(spec, lines or concept.lines, beats, 0.5)
        reel.preview_path = str(render_video(prev_plan, root / "preview.mp4", audio=audio_path, preview=True))
        reel.qa["preview"] = qa_video(Path(reel.preview_path), spec, 0.5, final=True)
        if not preview_only:
            reel.video_path = str(render_video(full_plan, root / "reel.mp4", audio=audio_path))
            reel.cover_path = str(render_cover(full_plan, root / "cover.jpg"))
            reel.qa["video"] = qa_video(Path(reel.video_path), spec)
            reel.video_sha256 = file_sha256(Path(reel.video_path))
        reel.render_status = "rendered" if not preview_only else "pending"
        cap = concept.caption
        attr = required_attribution(audio)
        reel.caption = " ".join(filter(None, [cap, attr])) + ("\n\n" + " ".join("#" + h for h in concept.hashtags) if concept.hashtags else "")
        reel.render_spec = {
            "template": spec.name, "spec": spec.model_dump(), "lines": full_plan.lines, "beats_used": len(beats),
            "font": {"id": spec.text.font, "license": font_record(spec.text.font)["license"]},
            "audio_id": audio.id if audio else None, "hash": spec_hash(spec, full_plan.lines, audio.local_file if audio else ""),
            "duration": full_plan.duration,
        }
        if not preview_only and not reel.qa["video"]["passed"]:
            reel.render_status = "failed"
            reel.render_error = f"media QA failed: {reel.qa['video']}"
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).exception("render failed")
        reel.render_status, reel.render_error = "failed", str(e)
    audit(s, "render.finished", "reel", reel.id, actor, status=reel.render_status, error=reel.render_error)
    s.flush()
    return reel
