"""AI providers: an offline seed writer (always available) and Claude via the Messages API."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .types import AIProvider, ConceptRequest

# Original seed lines authored for this project. They are a fallback so the pipeline runs offline,
# not a substitute for a model: the engine marks their provider as "local_seed" and caps confidence.
SEEDS: dict[str, list[dict[str, Any]]] = {
    "relatable_genz": [
        {"lines": ["me: i'm sleeping early tonight", "me at 2:47am:", "learning how bridges are built"],
         "payoff": "the gap between the plan and the 2am rabbit hole", "loop": "last line cuts back to the first",
         "tags": ["late night", "3am", "overthinking"]},
        {"lines": ["my phone is at 4%", "my anxiety is at 100%", "only one of them has a charger"],
         "payoff": "deadpan reversal on who gets support", "loop": "fade to a 4% battery icon, restart",
         "tags": ["overthinking", "college"]},
        {"lines": ["i say 'we should hang out soon'", "like soon is a place", "i've never actually been to"],
         "payoff": "soft self-roast about cancelled plans", "loop": "text blinks like an unsent message",
         "tags": ["friends", "texting"]},
    ],
    "heartbreak_latenight": [
        {"lines": ["i don't miss you every day", "just the days", "that have a sky"],
         "payoff": "grief reframed as weather", "loop": "ending line fades into the first",
         "tags": ["heartbreak", "miss you", "late night"]},
        {"lines": ["it's quiet enough now", "to hear everything", "i said i was fine about"],
         "payoff": "silence exposes the unresolved", "loop": "slow fade to black then reappear",
         "tags": ["late night", "healing", "3am"]},
        {"lines": ["they said time heals", "time has been busy", "i'm still on the waiting list"],
         "payoff": "dry take on a stock phrase", "loop": "wait-list text counts up",
         "tags": ["healing", "moving on", "heartbreak"]},
    ],
    "situationship": [
        {"lines": ["we're not dating", "but you know my coffee order", "and which songs make me quiet"],
         "payoff": "intimacy without a label", "loop": "label 'not dating' reappears struck out",
         "tags": ["situationship", "texting"]},
        {"lines": ["'you're overthinking'", "said the person", "who made it confusing"],
         "payoff": "blame flipped back", "loop": "quote marks return at the end",
         "tags": ["situationship", "overthinking", "red flag"]},
        {"lines": ["mixed signals", "are just a no", "with good timing"],
         "payoff": "clarity from ambiguity", "loop": "hard cut, first line returns",
         "tags": ["situationship", "left on read", "ignoring"]},
    ],
    "cold_attitude": [
        {"lines": ["i used to chase answers", "now i just notice", "who stopped asking"],
         "payoff": "quiet power through observation", "loop": "last word held, cut to black",
         "tags": ["self respect", "moving on", "ignoring"]},
        {"lines": ["peace looks boring", "to people who mistake", "chaos for love"],
         "payoff": "standards reframed", "loop": "echo the first word as final frame",
         "tags": ["self respect", "red flag", "healing"]},
        {"lines": ["i'm not cold", "i just ran out", "of explanations"],
         "payoff": "boundaries as fatigue", "loop": "text dissolves, starting line returns",
         "tags": ["self respect", "ignoring"]},
    ],
    "funny_savage": [
        {"lines": ["my toxic trait:", "i reply 'haha' to everything", "and mean none of it"],
         "payoff": "self-aware deadpan", "loop": "'haha' repeats softly at the end",
         "tags": ["texting", "friends"]},
        {"lines": ["'let's keep it casual'", "you said, holding", "my spare charger"],
         "payoff": "actions contradict words", "loop": "charger icon blinks then restarts",
         "tags": ["situationship", "red flag"]},
        {"lines": ["he's 'just a friend'", "like the fire alarm", "is just a sound"],
         "payoff": "ironic comparison", "loop": "alarm-style flash on loop point",
         "tags": ["red flag", "situationship"]},
    ],
    "cinematic_nostalgic": [
        {"lines": ["every old street", "has a version of us", "still walking it"],
         "payoff": "places hold memory", "loop": "street names fade, repeat from first line",
         "tags": ["nostalgia", "miss you"]},
        {"lines": ["remember when summer", "felt endless", "and nobody had left yet"],
         "payoff": "time measured in people", "loop": "slow zoom out, then in",
         "tags": ["nostalgia", "friends", "college"]},
        {"lines": ["the city is loud", "but it still sounds", "like the last time we spoke"],
         "payoff": "memory overlaying the present", "loop": "ambience swells then restarts",
         "tags": ["nostalgia", "late night", "3am"]},
    ],
}


class LocalSeedProvider:
    name = "local_seed"

    def generate_concepts(self, req: ConceptRequest) -> list[dict[str, Any]]:
        seeds = SEEDS.get(req.category, [])
        trend_text = " ".join(f"{t.get('title','')} {t.get('description','')} {' '.join(t.get('tags', []))}"
                              for t in req.trends).lower()

        def affinity(seed: dict[str, Any]) -> tuple[int, int]:
            hit = sum(1 for k in seed["tags"] if k in trend_text)
            return (-hit, (seeds.index(seed) - req.cycle_seed) % max(len(seeds), 1))

        out = []
        for seed in sorted(seeds, key=affinity)[: req.count]:
            out.append({
                "category": req.category, "hook": seed["lines"][0],
                "lines": [{"text": t} for t in seed["lines"]],
                "payoff": seed["payoff"], "loop_strategy": seed["loop"],
                "rationale": "Seed concept; relevance to current trends judged only by tag overlap "
                             f"(matched: {[k for k in seed['tags'] if k in trend_text] or 'none'}).",
                "seed_tags": seed["tags"],
            })
        return out


class AnthropicProvider:
    """Claude via the official Messages API. Requires RS_ANTHROPIC_API_KEY. Not exercised in tests
    against the live API (no key in CI); the HTTP contract is tested with a mock transport."""
    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise RuntimeError("RS_ANTHROPIC_API_KEY is not set")
        self.api_key, self.model = api_key, model
        self.client = client or httpx.Client(timeout=90)

    def _prompt(self, req: ConceptRequest) -> str:
        v = req.voice
        return json.dumps({
            "task": f"Write {req.count} ORIGINAL on-screen-text reel concepts for category '{req.category}'.",
            "voice_guide": v.get("voice", {}),
            "banned_phrases": v.get("banned_phrases", []),
            "never_repeat_or_paraphrase": req.avoid_lines[:200],
            "trend_context (measured vs estimated is stated in each item; do not overstate)": req.trends[:6],
            "account_insights": req.account_insights,
            "rules": ["never copy another creator's lines", "no viral promises", "no factual claims about real people",
                      "max lines and words per line as in voice_guide", "lowercase"],
            "output": "JSON array only. Each item: {category, hook, lines:[{text}], payoff, loop_strategy, rationale}",
        })

    def generate_concepts(self, req: ConceptRequest) -> list[dict[str, Any]]:
        r = self.client.post(self.URL, headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                                "content-type": "application/json"},
                             json={"model": self.model, "max_tokens": 3000,
                                   "system": "You are a careful original copywriter for short-form text reels. Reply with JSON only.",
                                   "messages": [{"role": "user", "content": self._prompt(req)}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            raise ValueError("provider returned no JSON array")
        items = json.loads(m.group(0))
        for it in items:
            it.setdefault("category", req.category)
        return items


def get_provider(settings: Any) -> AIProvider:
    if settings.ai_provider == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    return LocalSeedProvider()
