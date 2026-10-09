import json

import httpx
import pytest

from reelstudio.config import load_yaml
from reelstudio.db import Concept, Trend
from reelstudio.writing.engine import normalise, record_published_lines, run_cycle
from reelstudio.writing.providers import AnthropicProvider, LocalSeedProvider
from reelstudio.writing.scoring import find_banned, score_concept
from reelstudio.writing.types import ConceptRequest

VOICE = load_yaml("voice_guide.yaml")


def mk(lines, cat="relatable_genz"):
    return normalise({"category": cat, "lines": [{"text": t} for t in lines]}, VOICE, cat)


def test_cycle_covers_all_categories_with_full_fields(session):
    cs = run_cycle(session, per_category=2)
    assert {c.category for c in cs} == set(VOICE["categories"])
    c = cs[0]
    assert c.hook and c.lines[0]["start"] < c.lines[0]["end"] <= c.lines[1]["start"] + 1e-6
    assert c.caption and c.hashtags and c.audio_mood and c.style["template"] and c.loop_strategy and c.payoff
    assert 0 <= c.confidence <= 0.4  # offline seeds are capped
    assert all(l["text"] == l["text"].lower() for l in c.lines)


def test_published_lines_block_repetition(session):
    first = run_cycle(session, categories=["situationship"], per_category=1)
    record_published_lines(session, first[0])
    again = run_cycle(session, categories=["situationship"], per_category=3)
    used = {l["text"] for l in first[0].lines}
    assert all(not ({l["text"] for l in c.lines} & used) for c in again)


def test_cliche_and_similarity_blocked():
    c = mk(["this is your sign", "to leave him", "no cap"])
    r = score_concept(c, VOICE, [])
    assert r["blocked"] and r["breakdown"]["cliche_free"] == 0
    c2 = mk(["i don't miss you every day", "just the days", "that have a sky"], "heartbreak_latenight")
    r2 = score_concept(c2, VOICE, ["i don't miss you every day"])
    assert r2["blocked"]


def test_overlong_timing_rejected():
    assert mk(["word " * 6] * 5) is None or mk(["word " * 6] * 5)["lines"][-1]["end"] <= VOICE["timing"]["max_duration_seconds"]


def test_trend_influences_seed_choice(session):
    session.add(Trend(kind="topic", title="left on read ignoring texts", source="t", dedupe_key="k1", score=0.8))
    session.flush()
    cs = run_cycle(session, categories=["situationship"], per_category=1)
    assert cs[0].hook == "mixed signals"


def test_anthropic_provider_contract():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["h"] = dict(req.headers); seen["body"] = json.loads(req.content)
        arr = [{"hook": "x", "lines": [{"text": "a"}, {"text": "b"}], "payoff": "p", "loop_strategy": "l"}]
        return httpx.Response(200, json={"content": [{"type": "text", "text": "```json\n" + json.dumps(arr) + "\n```"}]})

    p = AnthropicProvider("k", "claude-sonnet-5-5", httpx.Client(transport=httpx.MockTransport(handler)))
    out = p.generate_concepts(ConceptRequest("situationship", 1, [], VOICE, ["old line"]))
    assert out[0]["hook"] == "x" and seen["h"]["x-api-key"] == "k"
    assert "old line" in seen["body"]["messages"][0]["content"]
    with pytest.raises(RuntimeError):
        AnthropicProvider("", "m")


def test_provider_failure_does_not_kill_cycle(session):
    class Bad:
        name = "bad"
        def generate_concepts(self, req): raise RuntimeError("boom")
    assert run_cycle(session, Bad(), per_category=1) == []
