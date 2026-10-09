"""Dynamic pacing: snap line starts to musical beats and compute total duration."""
from __future__ import annotations

from typing import Any

from .spec import TemplateSpec


def snap_to_beats(lines: list[dict[str, Any]], beats: list[float], window: float) -> list[dict[str, Any]]:
    """Move each line start to the nearest beat within `window` seconds, preserving order and min spacing."""
    if not beats or len(lines) < 2:
        return [dict(l) for l in lines]
    out = [dict(l) for l in lines]
    prev_start = -1.0
    for i, l in enumerate(out):
        if i == 0:
            prev_start = l["start"]
            continue
        cands = [b for b in beats if abs(b - l["start"]) <= window and b >= prev_start + 1.0]
        if cands:
            l["start"] = min(cands, key=lambda b: abs(b - l["start"]))
        l["start"] = round(max(l["start"], prev_start + 1.0), 3)
        prev_start = l["start"]
    # contiguous ends; last line keeps its original hold length
    for i in range(len(out) - 1):
        out[i]["end"] = out[i + 1]["start"]
    hold = lines[-1]["end"] - lines[-1]["start"]
    out[-1]["end"] = round(out[-1]["start"] + hold, 3)
    return out


def total_duration(spec: TemplateSpec, lines: list[dict[str, Any]]) -> float:
    if spec.duration_override:
        return float(spec.duration_override)
    return round(max(lines[-1]["end"] + spec.outro_seconds, spec.min_duration), 2)
