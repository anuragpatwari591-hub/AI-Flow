"""Heuristic concept quality scoring + repetition guard.

The score is a *writing-quality heuristic*, not a prediction of performance. Confidence is deliberately
capped when there is no evidence from this account's own history.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

STOP = set("a an the and or but of to in on at is are was were i you me my it we he she they that this for with".split())
TENSION = re.compile(r"(:|'|\"|\bbut\b|\bnot\b|n't\b|\bjust\b|\bnever\b|\bonly\b|\bstill\b|\d)", re.I)


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())


def ngrams(text: str, n: int = 3) -> set[tuple[str, ...]]:
    w = normalize(text).split()
    return {tuple(w[i:i + n]) for i in range(max(len(w) - n + 1, 0))}


def max_similarity(candidate_lines: list[str], previous: list[str]) -> tuple[float, str]:
    best, which = 0.0, ""
    for c in candidate_lines:
        nc = normalize(c)
        for p in previous:
            np_ = normalize(p)
            if not nc or not np_:
                continue
            r = SequenceMatcher(None, nc, np_).ratio()
            if r > best:
                best, which = r, p
    return best, which


def find_banned(lines: list[str], banned: list[str]) -> list[str]:
    blob = normalize(" ".join(lines))
    return [b for b in banned if normalize(b) and normalize(b) in blob]


def score_concept(c: dict[str, Any], voice: dict[str, Any], previous_lines: list[str],
                  trend_score: float | None = None, own_history_n: int = 0) -> dict[str, Any]:
    v = voice["voice"]
    lines = [l["text"] for l in c["lines"]]
    hook = c["hook"]
    bd: dict[str, float] = {}
    hw = len(hook.split())
    bd["hook_brevity"] = 1.0 if hw <= 6 else 0.7 if hw <= 9 else 0.3
    bd["hook_tension"] = 1.0 if TENSION.search(hook) else 0.5 if len(lines) > 1 and TENSION.search(" ".join(lines)) else 0.2
    content = [w for l in lines for w in normalize(l).split() if w not in STOP]
    bd["specificity"] = min(len(set(content)) / max(len(content), 1) * 1.2, 1.0)
    over = [l for l in lines if len(l.split()) > v["max_words_per_line"]]
    bd["line_economy"] = 0.0 if over or len(lines) > v["max_lines"] else 1.0
    last, first = lines[-1], lines[0]
    bd["payoff_landing"] = 1.0 if len(last.split()) <= 7 and normalize(last) != normalize(first) else 0.5
    bd["lowercase_voice"] = 1.0 if all(l == l.lower() for l in lines) else 0.6
    banned = find_banned(lines + [c.get("caption", "")], voice.get("banned_phrases", []))
    bd["cliche_free"] = 0.0 if banned else 1.0
    sim, matched = max_similarity(lines, previous_lines)
    bd["originality_vs_history"] = 1.0 if sim < 0.6 else 0.4 if sim < 0.8 else 0.0
    weights = {"hook_brevity": 1, "hook_tension": 1.5, "specificity": 1, "line_economy": 1.5,
               "payoff_landing": 1.5, "lowercase_voice": 0.5, "cliche_free": 2, "originality_vs_history": 2}
    score = sum(bd[k] * w for k, w in weights.items()) / sum(weights.values())
    if trend_score is not None:
        score = 0.85 * score + 0.15 * trend_score
    # confidence: heuristic ceiling; rises only with the account's own measured history
    conf = min(0.35 + 0.05 * min(own_history_n, 8), 0.75) * (0.5 + 0.5 * score)
    flags = []
    if banned:
        flags.append(f"banned phrases: {banned}")
    if sim >= 0.8:
        flags.append(f"too similar to previously used line: '{matched}' ({sim:.2f})")
    if over:
        flags.append("line exceeds max words")
    return {"score": round(score, 3), "confidence": round(conf, 3), "breakdown": {k: round(x, 2) for k, x in bd.items()},
            "flags": flags, "blocked": bool(banned) or sim >= 0.8,
            "basis": f"heuristic text-quality checks + {own_history_n} own-account observations; not a performance forecast"}
