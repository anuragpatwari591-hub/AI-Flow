"""Transparent 0-100 rubric (25/25/15/15/10/10). Heuristic: it ranks, a human decides."""
import re

AUDIENCE = ["hindi", "hinglish", "romantic", "love", "pyaar", "ishq", "indie", "poetry", "shayari", "aesthetic",
            "couple", "heartbreak", "lyrics", "song", "music", "reel", "cinematic", "late night", "dil", "tum", "tu "]
MOODS = {
    "romantic": ["romantic", "love", "pyaar", "ishq", "couple", "date", "propose", "crush"],
    "poetry": ["poetry", "shayari", "poem", "kavita", "quote", "lines", "lyrics"],
    "heartbreak": ["heartbreak", "sad", "breakup", "miss", "judai", "alone"],
    "latenight": ["late night", "midnight", "3am", "raat", "night"],
    "cinematic": ["cinematic", "aesthetic", "edit", "vlog", "scene", "golden hour", "frame"],
    "rec_request": ["recommend", "suggest", "any song", "which song", "song name", "playlist", "new music", "underrated"],
}
NEGATIVE = ["giveaway", "politics", "prank", "roast", "controvers", "death", "accident", "funeral", "rip ", "tragedy"]


def detect_moods(text):
    t = text.lower()
    return [m for m, ws in MOODS.items() if any(w in t for w in ws)]


def _hits(text, words):
    t = text.lower()
    return sum(1 for w in words if w in t)


def score(c):
    """c: dict(title, description, top_comments(list[str]), creator_subs, comment_count, age_days, language_hint)"""
    text = f"{c.get('title','')} {c.get('description','')}"
    comments = " ".join(c.get("top_comments", []))
    moods = detect_moods(text)
    hindi = bool(re.search(r"[ऀ-ॿ]", text + comments)) or "hindi" in text.lower() or c.get("language_hint") == "hi"
    aud = min(25, 6 + 3 * _hits(text + " " + comments, AUDIENCE) + (6 if hindi else 0))
    rel = min(25, 5 + 7 * len(moods) + (4 if "rec_request" in moods else 0))
    n = c.get("comment_count", 0)
    age = c.get("age_days", 30)
    conv = (5 if 5 <= n <= 800 else 2) + (5 if age <= 14 else 2 if age <= 60 else 0) + min(5, len(c.get("top_comments", [])))
    curiosity = min(15, 4 + 4 * len([m for m in moods if m in ("romantic", "cinematic", "latenight", "rec_request")]) + (3 if hindi else 0))
    subs = c.get("creator_subs", 0)
    fit = 10 if 500 <= subs <= 300_000 else 6 if subs < 500 else 4   # small/mid creators read & reply
    promo = min(10, 3 + (4 if "rec_request" in moods else 0) + (2 if "romantic" in moods else 0) + (1 if hindi else 0))
    neg = _hits(text, NEGATIVE)
    parts = dict(audience=aud, relevance=rel, conversation=conv, curiosity=curiosity, creator_fit=fit, promo_fit=promo)
    total = max(0, min(100, sum(parts.values()) - 20 * neg))
    return total, parts, moods
