"""Text layout: balanced line breaks, auto text-fit inside safe margins, readability checks."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from .fonts import load_font
from .spec import TemplateSpec


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rel_luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = rel_luminance(a), rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def apply_case(text: str, case: str) -> str:
    return text.lower() if case == "lower" else text.upper() if case == "upper" else text


def word_width(font, word: str, tracking: float) -> float:
    if tracking == 0:
        return font.getlength(word)
    return sum(font.getlength(c) + tracking for c in word) - tracking


def greedy_lines(words: list[str], font, max_w: float, tracking: float = 0.0) -> list[list[str]]:
    space = font.getlength(" ") + tracking
    lines: list[list[str]] = [[]]
    cur = 0.0
    for w in words:
        ww = word_width(font, w, tracking)
        add = ww if not lines[-1] else space + ww
        if lines[-1] and cur + add > max_w:
            lines.append([w]); cur = ww
        else:
            lines[-1].append(w); cur += add
    return lines


def balanced_lines(words: list[str], font, max_w: float, tracking: float = 0.0) -> list[list[str]]:
    """Fewest lines (greedy), then the narrowest width that still yields that count -> even rag."""
    base = greedy_lines(words, font, max_w, tracking)
    n = len(base)
    if n == 1:
        return base
    lo = max(word_width(font, w, tracking) for w in words)
    hi = max_w
    for _ in range(18):
        mid = (lo + hi) / 2
        if len(greedy_lines(words, font, mid, tracking)) <= n:
            hi = mid
        else:
            lo = mid
    return greedy_lines(words, font, hi, tracking)


@dataclass
class WordBox:
    text: str
    x0: int
    x1: int
    y0: int
    y1: int


@dataclass
class LineLayout:
    text: str
    visual: list[list[str]]
    height: int
    y: int = 0  # offset inside block (stack mode)


@dataclass
class BlockLayout:
    size: int
    fits: bool
    width: int
    height: int
    lines: list[LineLayout]
    origin_x: int
    origin_y: int
    problems: list[str] = field(default_factory=list)


def compute_layout(spec: TemplateSpec, texts: list[str], scale: float = 1.0) -> BlockLayout:
    W, H = round(spec.canvas.width * scale), round(spec.canvas.height * scale)
    sf = spec.safe
    left, right, top, bottom = (round(v * scale) for v in (sf.left, sf.right, sf.top, sf.bottom))
    avail_w, avail_h = W - left - right, H - top - bottom
    max_w = min(avail_w, W * spec.text.max_width_ratio)
    tr = spec.text.tracking * scale
    stack = spec.animation.mode == "stack"
    cased = [apply_case(t, spec.text.case) for t in texts]

    size = float(spec.text.size * scale)
    floor = spec.text.min_size * scale
    chosen: BlockLayout | None = None
    while True:
        isz = max(round(size), 1)
        font = load_font(spec.text.font, isz)
        lh = round(isz * spec.text.line_spacing)
        lines: list[LineLayout] = []
        ok = True
        for t in cased:
            vis: list[list[str]] = []
            for seg in (t.split("\n") if spec.text.forced_breaks else [t.replace("\n", " ")]):
                words = seg.split()
                if not words:
                    continue
                if max(word_width(font, w, tr) for w in words) > max_w:
                    ok = False
                vis.extend(balanced_lines(words, font, max_w, tr))
            lines.append(LineLayout(t, vis, lh * max(len(vis), 1)))
        gap = round(isz * 0.45)
        if stack:
            y = 0
            for ll in lines:
                ll.y = y
                y += ll.height + gap
            bh = y - gap
        else:
            bh = max(ll.height for ll in lines)
        if bh > avail_h:
            ok = False
        chosen = BlockLayout(isz, ok, round(max_w), bh, lines, 0, 0)
        if ok or isz <= floor:
            break
        size *= 0.96
    assert chosen is not None
    chosen.origin_x = round((W - chosen.width) / 2)
    if spec.text.valign == "upper":
        chosen.origin_y = top
    elif spec.text.valign == "lower":
        chosen.origin_y = H - bottom - chosen.height
    else:
        chosen.origin_y = round(top + (avail_h - chosen.height) / 2)
    if not chosen.fits:
        chosen.problems.append("text does not fit safe area even at minimum size")
    if chosen.size < floor * 0.999 and chosen.size < spec.text.min_size * scale:
        chosen.problems.append("font below minimum readable size")
    return chosen


def render_line_mask(spec: TemplateSpec, layout: BlockLayout, idx: int, tracking_extra: float = 0.0,
                     scale: float = 1.0) -> tuple[np.ndarray, list[WordBox]]:
    """Alpha mask (uint8, block_width x line_height) and word boxes for one concept line."""
    ll = layout.lines[idx]
    font = load_font(spec.text.font, layout.size)
    tr = spec.text.tracking * scale + tracking_extra
    lh = round(layout.size * spec.text.line_spacing)
    img = Image.new("L", (layout.width, ll.height), 0)
    d = ImageDraw.Draw(img)
    space = font.getlength(" ") + tr
    boxes: list[WordBox] = []
    for vi, words in enumerate(ll.visual):
        widths = [word_width(font, w, tr) for w in words]
        total = sum(widths) + space * (len(words) - 1)
        x = (layout.width - total) / 2 if spec.text.align == "center" else 0.0
        y = vi * lh + (lh - layout.size) / 2 - layout.size * 0.12
        for w, ww in zip(words, widths):
            if tr == 0:
                d.text((x, y), w, font=font, fill=255)
            else:
                cx = x
                for ch in w:
                    d.text((cx, y), ch, font=font, fill=255)
                    cx += font.getlength(ch) + tr
            boxes.append(WordBox(w, max(int(x) - 2, 0), min(int(x + ww) + 3, layout.width), vi * lh, (vi + 1) * lh))
            x += ww + space
    return np.asarray(img), boxes


def readability_report(spec: TemplateSpec, layout: BlockLayout, scale: float = 1.0) -> dict:
    fg = hex_to_rgb(spec.text.color)
    bg = hex_to_rgb(spec.background.color)
    if spec.background.type == "footage":
        # worst case: footage brightened up to (1-darken) of white
        lvl = int(255 * (1 - spec.background.darken))
        bg = (lvl, lvl, lvl)
    cr = contrast_ratio(fg, bg)
    checks = {
        "text_fits_safe_area": layout.fits,
        "font_size_ok": layout.size >= round(spec.text.min_size * scale) - 1,
        "contrast_ratio": round(cr, 2),
        "contrast_ok": cr >= spec.min_contrast,
        "final_font_px": layout.size,
        "problems": layout.problems,
    }
    return checks
