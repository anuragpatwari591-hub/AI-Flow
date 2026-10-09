"""Reference library. Only inspected material may carry observations.

Measurements come from tooling run on supplied files (ffprobe/ffmpeg). Human observations must state
`inspected=True` and cite what was inspected; otherwise they are rejected, so nothing is invented about
videos nobody has looked at.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..db import ReferenceItem, audit


class UninspectedObservation(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def measure_video(path: Path) -> dict[str, Any]:
    """Objective measurements only: duration, size, fps, scene-cut count, mean luminance, dark-frame ratio."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    out: dict[str, Any] = {
        "width": v["width"], "height": v["height"], "fps": round(num / den, 3) if den else None,
        "duration_s": float(v.get("duration") or 0), "has_audio": any(s["codec_type"] == "audio" for s in streams),
    }
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-vf", "fps=4,scale=108:-2,signalstats,metadata=print",
         "-an", "-f", "null", "-"], capture_output=True, text=True)
    yavg = [float(x) for x in re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", r.stderr)]
    r2 = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-vf", "scale=108:-2,select='gt(scene,0.3)',showinfo",
         "-an", "-f", "null", "-"], capture_output=True, text=True)
    cuts = len(re.findall(r"Parsed_showinfo.*\bn:", r2.stderr))
    if yavg:
        out["mean_luma_0_255"] = round(sum(yavg) / len(yavg), 2)
        out["dark_frame_ratio"] = round(sum(1 for y in yavg if y < 40) / len(yavg), 3)
    out["scene_cuts_detected"] = cuts
    out["measured_by"] = "ffprobe+ffmpeg signalstats @4fps"
    return out


def add_reference(s: Session, *, account: str = "", source_url: str = "", local_file: str | None = None,
                  notes: str = "", measure: bool = True) -> ReferenceItem:
    item = ReferenceItem(account=account, source_url=source_url, notes=notes)
    if local_file:
        p = Path(local_file)
        item.local_file, item.file_sha256 = str(p), sha256_file(p)
        if measure:
            item.measurements = measure_video(p)
    s.add(item)
    s.flush()
    audit(s, "reference.added", "reference", item.id, source_url=source_url, has_file=bool(local_file))
    return item


def add_observation(s: Session, item_id: int, text: str, *, inspected: bool, evidence: str,
                    author: str = "analyst") -> ReferenceItem:
    """Attach a qualitative observation. Requires explicit inspected=True and non-empty evidence."""
    item = s.get(ReferenceItem, item_id)
    if item is None:
        raise KeyError(item_id)
    if not inspected or not evidence.strip():
        raise UninspectedObservation("observations require inspected=True and a note on what was inspected")
    if not item.local_file and not item.notes:
        raise UninspectedObservation("no supplied file or accessible-content note on this item")
    item.observations = [*item.observations, {
        "text": text, "evidence": evidence, "author": author,
        "at": datetime.now(timezone.utc).isoformat(), "inspected": True}]
    audit(s, "reference.observation", "reference", item.id, author=author)
    return item


def principles_summary(s: Session) -> dict[str, Any]:
    """Aggregate only measured facts + inspected observations across the library."""
    items = s.query(ReferenceItem).all()
    meas = [i.measurements for i in items if i.measurements]
    def avg(k: str) -> float | None:
        vals = [m[k] for m in meas if m.get(k) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None
    return {"items": len(items), "inspected_videos": len(meas),
            "avg_duration_s": avg("duration_s"), "avg_dark_frame_ratio": avg("dark_frame_ratio"),
            "avg_cuts": avg("scene_cuts_detected"),
            "observations": [o for i in items for o in i.observations],
            "note": "empty when nothing has been supplied/inspected; no observations are assumed"}
