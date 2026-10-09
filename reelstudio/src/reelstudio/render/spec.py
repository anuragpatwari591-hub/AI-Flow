"""Validated, fully configurable render specification (template YAML + per-reel overrides)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from ..config import get_settings


class Canvas(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 18
    preset: str = "medium"
    audio_bitrate: str = "192k"
    maxrate: str = "10M"          # VBV cap: grain is incompressible, keep Reels uploads small
    bufsize: str = "20M"


class Background(BaseModel):
    type: Literal["solid", "footage"] = "solid"
    color: str = "#000000"
    footage: str = ""            # path to licensed/own footage when type == footage
    darken: float = 0.45         # 0..1 brightness reduction applied to footage
    vignette: bool = False


class TextStyle(BaseModel):
    font: str = "inter_medium"
    size: int = 74
    min_size: int = 48
    color: str = "#f2f2f2"
    line_spacing: float = 1.25
    align: Literal["center", "left"] = "center"
    case: Literal["lower", "upper", "as_is"] = "lower"
    max_width_ratio: float = 0.8
    tracking: float = 0.0
    valign: Literal["center", "upper", "lower"] = "center"
    forced_breaks: bool = True   # honour "\n" inside lines


class Safe(BaseModel):
    """Instagram UI covers parts of a Reel: keep text out of top/bottom/right UI zones (1080x1920 px)."""
    top: int = 260
    bottom: int = 440
    left: int = 90
    right: int = 150


class Animation(BaseModel):
    in_style: Literal["fade", "word_reveal", "tracking", "none"] = "fade"
    in_duration: float = 0.7
    word_stagger: float = 0.14
    tracking_from: float = 14.0   # px at 1080 width
    out_style: Literal["fade", "none"] = "fade"
    out_duration: float = 0.4
    zoom: float = 0.03            # total slow push over the reel (fractional)
    beat_pulse: float = 0.0       # scale bump on beats
    mode: Literal["stack", "replace"] = "stack"
    dim_previous: float = 0.5
    global_fade_out: float = 0.8
    snap_to_beats: bool = True
    beat_snap_window: float = 0.35


class Grain(BaseModel):
    enabled: bool = True
    strength: int = 8
    seed: int = 1234


class Branding(BaseModel):
    enabled: bool = False
    text: str = ""
    size: int = 30
    opacity: float = 0.7


class TemplateSpec(BaseModel):
    name: str = "custom"
    description: str = ""
    canvas: Canvas = Canvas()
    background: Background = Background()
    text: TextStyle = TextStyle()
    safe: Safe = Safe()
    animation: Animation = Animation()
    grain: Grain = Grain()
    branding: Branding = Branding()
    min_contrast: float = Field(7.0, description="WCAG-style contrast floor vs effective background")
    outro_seconds: float = 0.8
    min_duration: float = 5.0
    duration_override: float | None = None

    @field_validator("min_contrast")
    @classmethod
    def _c(cls, v: float) -> float:
        if v < 3:
            raise ValueError("min_contrast below 3 is not allowed")
        return v


def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_template(name: str, overrides: dict[str, Any] | None = None, config_dir: Path | None = None) -> TemplateSpec:
    path = (config_dir or get_settings().config_dir) / "templates" / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if overrides:
        data = deep_merge(data, overrides)
    return TemplateSpec.model_validate(data)


def list_templates(config_dir: Path | None = None) -> list[str]:
    return sorted(p.stem for p in ((config_dir or get_settings().config_dir) / "templates").glob("*.yaml"))


def spec_hash(spec: TemplateSpec, lines: list[dict[str, Any]], audio_sha: str = "") -> str:
    blob = json.dumps({"spec": spec.model_dump(), "lines": lines, "audio": audio_sha}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()
