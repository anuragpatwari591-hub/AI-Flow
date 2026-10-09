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


def font_record(font_id: str) -> dict[str, Any]:
    reg = registry()
    if font_id not in reg:
        raise FontError(f"font '{font_id}' is not in config/fonts.yaml (no license on record)")
    rec = reg[font_id]
    missing = [k for k in REQUIRED if not rec.get(k)]
    if missing:
        raise FontError(f"font '{font_id}' missing license metadata: {missing}")
    p = Path(rec["path"])
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[3] / p
    if not p.exists():
        raise FontError(f"font file not found: {p}")
    return {**rec, "path": str(p)}


@lru_cache(maxsize=64)
def load_font(font_id: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_record(font_id)["path"], size)


def license_table() -> list[dict[str, str]]:
    out = []
    for fid, rec in registry().items():
        out.append({"id": fid, "family": rec.get("family", ""), "license": rec.get("license", "MISSING"),
                    "source": rec.get("source", ""), "available": str(Path(rec["path"]).exists())})
    return out
