"""Reel renderer: Pillow draws the animated text layer, FFmpeg composites background/grain and encodes."""
from __future__ import annotations

import json
import logging
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .fonts import font_record
from .layout import BlockLayout, compute_layout, hex_to_rgb, readability_report, render_line_mask
from .pacing import snap_to_beats, total_duration
from .spec import TemplateSpec

log = logging.getLogger(__name__)


class RenderError(Exception):
    pass


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _ease(x: float) -> float:
    x = _clamp(x)
    return x * x * (3 - 2 * x)


@dataclass
class RenderPlan:
    spec: TemplateSpec
    lines: list[dict[str, Any]]
    duration: float
    beats: list[float]
    scale: float
    layout: BlockLayout
    qa_text: dict[str, Any]


def plan_render(spec: TemplateSpec, lines: list[dict[str, Any]], beats: list[float] | None = None,
                scale: float = 1.0) -> RenderPlan:
    beats = beats or []
    timed = snap_to_beats(lines, beats, spec.animation.beat_snap_window) if spec.animation.snap_to_beats else lines
    layout = compute_layout(spec, [l["text"] for l in timed], scale)
    return RenderPlan(spec, timed, total_duration(spec, timed), beats, scale, layout,
                      readability_report(spec, layout, scale))


class TextAnimator:
    """Produces the RGBA text layer for any time t."""

    def __init__(self, plan: RenderPlan) -> None:
        self.p, self.spec = plan, plan.spec
        s = plan.scale
        self.W, self.H = round(self.spec.canvas.width * s), round(self.spec.canvas.height * s)
        self.layout = plan.layout
        self._mask_cache: dict[tuple[int, int], tuple[np.ndarray, list]] = {}
        rgb = hex_to_rgb(self.spec.text.color)
        self.buf = np.zeros((self.H, self.W, 4), dtype=np.uint8)
        self.buf[..., 0], self.buf[..., 1], self.buf[..., 2] = rgb
        self._dirty: tuple[slice, slice] | None = None
        self._brand: tuple[slice, slice, np.ndarray] | None = self._make_brand()

    def _make_brand(self):  # optional music-content credit (off unless the service enables it)
        b = self.spec.branding
        if not (b.enabled and b.text):
            return None
        from PIL import ImageDraw
        from .fonts import load_font
        size = max(round(b.size * self.p.scale), 8)
        font = load_font(self.spec.text.font, size)
        w = int(font.getlength(b.text)) + 8
        img = Image.new("L", (w, size * 2), 0)
        ImageDraw.Draw(img).text((4, size // 2), b.text, font=font, fill=int(255 * b.opacity))
        y1 = self.H - round(self.spec.safe.bottom * self.p.scale) + size * 2
        x0 = (self.W - w) // 2
        return slice(y1 - size * 2, y1), slice(x0, x0 + w), np.asarray(img)

    def _mask(self, idx: int, tracking_q: int):
        key = (idx, tracking_q)
        if key not in self._mask_cache:
            self._mask_cache[key] = render_line_mask(self.spec, self.layout, idx, tracking_q * 0.5 * self.p.scale, self.p.scale)
        return self._mask_cache[key]

    def _line_state(self, i: int, t: float) -> tuple[float, list[float] | None, int]:
        """(line alpha, per-word alpha factors or None, tracking quantum)."""
        a = self.spec.animation
        lines = self.p.lines
        s, e = lines[i]["start"], lines[i]["end"]
        if t < s:
            return 0.0, None, 0
        age = t - s
        words = sum(len(v) for v in self.layout.lines[i].visual)
        wf: list[float] | None = None
        tq = 0
        alpha = 1.0
        if a.in_style == "fade":
            alpha = _ease(age / max(a.in_duration, 1e-3))
        elif a.in_style == "word_reveal":
            wf = [_ease((age - k * a.word_stagger) / max(a.in_duration, 1e-3)) for k in range(words)]
            alpha = 1.0
        elif a.in_style == "tracking":
            p = _ease(age / max(a.in_duration, 1e-3))
            alpha = p
            tq = round(a.tracking_from * (1 - p) * 2 / self.p.scale / 1.0) if p < 1 else 0
            tq = int(round(tq / 2) * 2) if tq else 0
        last = i == len(lines) - 1
        if a.mode == "stack":
            if not last:
                nxt = lines[i + 1]["start"]
                alpha *= 1 - (1 - a.dim_previous) * _ease((t - nxt) / 0.4)
        else:
            if not last and a.out_style == "fade" and t > e - a.out_duration:
                alpha *= _clamp((e - t) / max(a.out_duration, 1e-3))
            elif not last and t >= e:
                alpha = 0.0
        return alpha, wf, tq

    def frame(self, t: float) -> bytes:
        a = self.spec.animation
        T = self.p.duration
        lay = self.layout
        block = np.zeros((lay.height, lay.width), dtype=np.uint8)
        stack = a.mode == "stack"
        for i in range(len(self.p.lines)):
            alpha, wf, tq = self._line_state(i, t)
            if alpha <= 0.003 and not wf:
                continue
            mask, boxes = self._mask(i, tq)
            m = mask.astype(np.float32) * alpha
            if wf is not None:
                fac = np.zeros(mask.shape[1], dtype=np.float32)
                for k, bx in enumerate(boxes):
                    fac[bx.x0:bx.x1] = np.maximum(fac[bx.x0:bx.x1], wf[k] if k < len(wf) else 1.0)
                # rows outside a word's visual line keep full factor of that line via per-line handling
                m = np.zeros_like(m)
                for k, bx in enumerate(boxes):
                    seg = mask[bx.y0:bx.y1, bx.x0:bx.x1].astype(np.float32) * alpha * (wf[k] if k < len(wf) else 1.0)
                    m[bx.y0:bx.y1, bx.x0:bx.x1] = np.maximum(m[bx.y0:bx.y1, bx.x0:bx.x1], seg)
            y0 = lay.lines[i].y if stack else 0
            h = m.shape[0]
            if not stack:  # centre single line vertically in block
                y0 = (lay.height - h) // 2
            region = block[y0:y0 + h]
            np.maximum(region, m[: region.shape[0]].astype(np.uint8), out=region)
        # global fade-out
        gfo = a.global_fade_out
        if gfo > 0 and t > T - gfo:
            block = (block.astype(np.float32) * _clamp((T - t) / gfo)).astype(np.uint8)
        # slow push + beat pulse
        sc = 1.0 + a.zoom * (t / max(T, 1e-3))
        if a.beat_pulse and self.p.beats:
            past = [b for b in self.p.beats if b <= t]
            if past:
                sc += a.beat_pulse * math.exp(-(t - past[-1]) / 0.12)
        if abs(sc - 1.0) > 1e-4:
            nw, nh = max(round(lay.width * sc), 1), max(round(lay.height * sc), 1)
            block_img = Image.fromarray(block).resize((nw, nh), Image.BILINEAR)
            block = np.asarray(block_img)
        bh, bw = block.shape
        cx = lay.origin_x + lay.width / 2
        cy = lay.origin_y + lay.height / 2
        x0, y0 = round(cx - bw / 2), round(cy - bh / 2)
        # clear previous alpha and paste (with clipping)
        if self._dirty:
            self.buf[self._dirty[0], self._dirty[1], 3] = 0
        sx0, sy0 = max(x0, 0), max(y0, 0)
        sx1, sy1 = min(x0 + bw, self.W), min(y0 + bh, self.H)
        if sx1 > sx0 and sy1 > sy0:
            self.buf[sy0:sy1, sx0:sx1, 3] = block[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
            self._dirty = (slice(sy0, sy1), slice(sx0, sx1))
        else:
            self._dirty = None
        self._branding(t)
        return self.buf.tobytes()

    def _branding(self, t: float) -> None:
        if self._brand:
            ys, xs, a = self._brand
            fade = _clamp(t / 0.8)
            region = self.buf[ys, xs, 3]
            np.maximum(region, (a * fade).astype(np.uint8), out=region)


def _ffmpeg_cmd(plan: RenderPlan, out: Path, audio: Path | None, fps: int, crf: int, preset: str) -> list[str]:
    spec = plan.spec
    W, H = round(spec.canvas.width * plan.scale), round(spec.canvas.height * plan.scale)
    T = plan.duration
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin"]
    # input 0: background
    if spec.background.type == "footage":
        if not spec.background.footage or not Path(spec.background.footage).exists():
            raise RenderError("footage background selected but file missing")
        cmd += ["-stream_loop", "-1", "-i", spec.background.footage]
        bg = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},"
              f"eq=brightness={-spec.background.darken:.2f}:saturation=0.7,setsar=1[bg]")
    else:
        color = spec.background.color.lstrip("#")
        cmd += ["-f", "lavfi", "-i", f"color=c=0x{color}:s={W}x{H}:r={fps}"]
        bg = "[0:v]setsar=1[bg]"
    # input 1: raw text frames
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0"]
    # input 2: audio (real or silent)
    if audio:
        cmd += ["-i", str(audio)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    chain = [bg, "[1:v]format=rgba[txt]", "[bg][txt]overlay=format=auto[v0]"]
    last = "v0"
    if spec.background.vignette:
        chain.append(f"[{last}]vignette=PI/4[v1]"); last = "v1"
    if spec.grain.enabled and spec.grain.strength > 0:
        chain.append(f"[{last}]noise=alls={spec.grain.strength}:allf=t:all_seed={spec.grain.seed}[v2]"); last = "v2"
    chain.append(f"[{last}]format=yuv420p[vout]")
    fade_d = min(1.2, T / 4)
    afilter = f"atrim=0:{T},asetpts=PTS-STARTPTS,afade=t=in:d=0.25,afade=t=out:st={max(T - fade_d, 0):.2f}:d={fade_d:.2f},aresample=44100"
    chain.append(f"[2:a]{afilter}[aout]")
    cmd += ["-filter_complex", ";".join(chain), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{T}", "-r", str(fps),
            "-c:v", "libx264", "-profile:v", "high", "-preset", preset, "-crf", str(crf), "-maxrate", spec.canvas.maxrate, "-bufsize", spec.canvas.bufsize, "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-c:a", "aac", "-b:a", spec.canvas.audio_bitrate, "-ac", "2",
            str(out)]
    return cmd


def render_video(plan: RenderPlan, out: Path, *, audio: Path | None = None, preview: bool = False,
                 progress=None) -> Path:  # noqa: ANN001
    spec = plan.spec
    fps = max(spec.canvas.fps // 2, 12) if preview else spec.canvas.fps
    crf = 30 if preview else spec.canvas.crf
    preset = "veryfast" if preview else spec.canvas.preset
    out.parent.mkdir(parents=True, exist_ok=True)
    anim = TextAnimator(plan)
    cmd = _ffmpeg_cmd(plan, out, audio, fps, crf, preset)
    n = int(round(plan.duration * fps))
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err)
        assert proc.stdin
        try:
            for k in range(n):
                proc.stdin.write(anim.frame(k / fps))
                if progress and k % fps == 0:
                    progress(k / n)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        rc = proc.wait()
        if rc != 0:
            err.seek(0)
            raise RenderError(f"ffmpeg failed ({rc}): {err.read().decode(errors='replace')[-800:]}")
    return out


def render_cover(plan: RenderPlan, out: Path, hook_index: int = 0) -> Path:
    """Cover = hook line fully revealed on the template background, kept inside the 3:4 grid-crop centre."""
    spec = plan.spec
    lay = compute_layout(spec, [plan.lines[hook_index]["text"]], plan.scale)
    W, H = round(spec.canvas.width * plan.scale), round(spec.canvas.height * plan.scale)
    mask, _ = render_line_mask(spec, lay, 0, 0.0, plan.scale)
    bg = Image.new("RGB", (W, H), hex_to_rgb(spec.background.color))
    fg = Image.new("RGB", (mask.shape[1], mask.shape[0]), hex_to_rgb(spec.text.color))
    bg.paste(fg, (lay.origin_x, lay.origin_y + (lay.height - mask.shape[0]) // 2), Image.fromarray(mask))
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.save(out, quality=92)
    return out


def probe(path: Path) -> dict[str, Any]:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,duration:format=duration,size",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def qa_video(path: Path, spec: TemplateSpec, expected_scale: float = 1.0, final: bool = True) -> dict[str, Any]:
    info = probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    checks = {
        "resolution": f'{v["width"]}x{v["height"]}',
        "resolution_ok": (v["width"], v["height"]) == (round(spec.canvas.width * expected_scale), round(spec.canvas.height * expected_scale)),
        "aspect_9_16": abs(v["width"] / v["height"] - 9 / 16) < 0.002,
        "video_codec_ok": v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p",
        "audio_codec_ok": bool(a and a["codec_name"] == "aac"),
        "duration_s": round(float(info["format"]["duration"]), 2),
        "fps": round(num / den, 2),
        "size_mb": round(int(info["format"]["size"]) / 1e6, 2),
    }
    checks["duration_ok"] = 3 <= checks["duration_s"] <= 90
    checks["size_ok"] = checks["size_mb"] <= 100
    checks["passed"] = all(v for k, v in checks.items() if k.endswith("_ok") or k == "aspect_9_16") and (not final or checks["resolution_ok"])
    return checks
