"""Licensed font registry. Unlicensed or unknown fonts are refused."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import ImageFont

from ..config import load_yaml

REQUIRED = ("license", "source", "path")


class FontError(Exception):
    pass


def registry() -> dict[str, dict[str, Any]]:
    return load_yaml("fonts.yaml")["fonts"]


SEARCH_ROOTS = ("/usr/share/fonts", "/usr/local/share/fonts")


def _resolve(path: str) -> Path | None:
    """Registered path first; otherwise find the same file name under the system font dirs (distros differ,
    e.g. liberation vs liberation2). The licence record still comes from the registry entry."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[3] / p
    if p.exists():
        return p
    for root in SEARCH_ROOTS:
        if Path(root).is_dir():
            hit = next(Path(root).rglob(p.name), None)
            if hit:
                return hit
    return None


def font_record(font_id: str) -> dict[str, Any]:
    reg = registry()
    if font_id not in reg:
        raise FontError(f"font '{font_id}' is not in config/fonts.yaml (no license on record)")
    rec = reg[font_id]
    missing = [k for k in REQUIRED if not rec.get(k)]
    if missing:
        raise FontError(f"font '{font_id}' missing license metadata: {missing}")
    p = _resolve(rec["path"])
    if p is None:
        raise FontError(f"font file not found: {rec['path']} (also searched {SEARCH_ROOTS} for the same file name)")
    return {**rec, "path": str(p)}


@lru_cache(maxsize=64)
def load_font(font_id: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_record(font_id)["path"], size)


def license_table() -> list[dict[str, str]]:
    out = []
    for fid, rec in registry().items():
        out.append({"id": fid, "family": rec.get("family", ""), "license": rec.get("license", "MISSING"),
                    "source": rec.get("source", ""), "available": str(_resolve(rec["path"]) is not None)})
    return out
