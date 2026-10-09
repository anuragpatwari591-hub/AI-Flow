import json
from datetime import date, datetime, timedelta, timezone

from reelstudio.config import load_yaml
from reelstudio.trends.models import TrendCandidate
from reelstudio.trends.scoring import score_trend
from reelstudio.trends.service import ranked_trends, run_research
from reelstudio.trends.sources import CredentialedApiSource, ManualFileSource, SeasonalCalendarSource

CFG = load_yaml("trends.yaml")


def test_unavailable_signals_are_marked_not_invented():
    c = TrendCandidate(kind="topic", title="left on read at 3am", source="t", observed_at=datetime.now(timezone.utc))
    r = score_trend(c, CFG)
    assert r["signals"]["momentum"]["kind"] == "unavailable" and r["signals"]["momentum"]["value"] is None
    assert "momentum" in r["missing"] and "engagement" in r["missing"]
    assert r["confidence"] < 0.6  # mostly estimates


def test_unverified_popular_audio_is_capped_below_relevant_original_topic(session, tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps([
        {"kind": "audio", "title": "Viral Hit Sound", "views": 9_000_000, "views_prev": 1_000_000, "likes": 900000,
         "observed_at": datetime.now(timezone.utc).isoformat(), "audio_rights": "unverified"},
        {"kind": "topic", "title": "situationship texting at 3am", "tags": "text_led;fade",
         "observed_at": datetime.now(timezone.utc).isoformat(), "views": 100000, "views_prev": 80000, "likes": 9000},
    ]))
    rep = run_research(session, [ManualFileSource(f)])
    assert rep["ingested"] == 2
    top = ranked_trends(session)[0]
    assert top.kind == "topic"
    audio = [t for t in ranked_trends(session) if t.kind == "audio"][0]
    assert audio.score <= 0.45
    assert audio.signals["momentum"]["kind"] == "measured"


def test_rerun_dedupes(session, tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps([{"kind": "topic", "title": "x ex"}]))
    run_research(session, [ManualFileSource(f)])
    rep = run_research(session, [ManualFileSource(f)])
    assert rep["updated"] == 1 and rep["ingested"] == 0


def test_missing_credentials_reported_unavailable(session):
    rep = run_research(session, [CredentialedApiSource("licensed_provider", "RS_PROVIDER_KEY")])
    assert rep["sources"]["licensed_provider"]["status"] == "unavailable"
    assert "RS_PROVIDER_KEY" in rep["sources"]["licensed_provider"]["reason"]


def test_seasonal_window():
    src = SeasonalCalendarSource([{"month": 2, "day": 14, "name": "V", "lead_days": 10}], today=date(2026, 2, 10))
    assert len(src.fetch()) == 1
    assert SeasonalCalendarSource([{"month": 2, "day": 14, "name": "V", "lead_days": 10}], today=date(2026, 5, 1)).fetch() == []


def test_avoid_keyword_veto():
    c = TrendCandidate(kind="topic", title="election drama", source="t", observed_at=datetime.now(timezone.utc))
    assert score_trend(c, CFG)["score"] <= 0.1
