import json

import pytest

from reelstudio.ads import service as ads
from reelstudio.audio.library import register_audio
from reelstudio.publishing import queue as q
from reelstudio.render.service import AudioRightsError
from tests.test_audio import click_track
from tests.test_render_service import FAST
from reelstudio.writing.engine import run_cycle


def campaign(s):
    return ads.create_campaign(s, name="launch", objective="video_views", destination_url="https://example.com/track",
                               audience_notes="18-24 IN, music", budget={"amount": 5, "currency": "USD", "period": "daily"},
                               ad_account="act_123")


def test_full_ad_workflow_and_export(session, env, tmp_path):
    concept = run_cycle(session, categories=["cold_attitude"], per_category=1)[0]
    c = campaign(session)
    vs = ads.add_variants(session, c, concept.id, hooks=["i stopped explaining", "nobody asked me to stay"],
                          ctas=["listen now"], out_root=tmp_path / "r", overrides={**FAST, "duration_override": 5})
    assert [v.label for v in vs] == ["A", "B"] and vs[0].test_dimension == "hook"
    ads.submit_for_review(session, c)
    for item in ads.APPROVAL_ITEMS[:-1]:
        ads.approve_item(session, c, item, "yash")
    assert c.status == "ready_for_review"  # one approval missing -> cannot be approved_to_launch
    d = ads.export_bundle(session, c, tmp_path / "export")
    man = json.loads((d / "manifest.json").read_text())
    assert man["missing_approvals"] == ["budget"] and man["launch_performed"] is False
    assert "DO NOT LAUNCH" in (d / "LAUNCH_STEPS.txt").read_text()
    ads.approve_item(session, c, "budget", "yash")
    assert c.status == "approved_to_launch"
    ads.export_bundle(session, c, tmp_path / "export2")
    assert c.status == "exported" and (tmp_path / "export2" / "variant_A" / "ad.mp4").exists()


def test_changing_budget_voids_budget_approval(session, env, tmp_path):
    concept = run_cycle(session, categories=["cold_attitude"], per_category=1)[0]
    c = campaign(session)
    ads.add_variants(session, c, concept.id, hooks=["h1"], out_root=tmp_path, overrides={**FAST, "duration_override": 5})
    ads.submit_for_review(session, c)
    for item in ads.APPROVAL_ITEMS:
        ads.approve_item(session, c, item, "yash")
    assert c.status == "approved_to_launch"
    ads.update_campaign(session, c, budget={"amount": 500, "currency": "USD", "period": "daily"})
    assert "budget" not in c.approvals and c.status == "ready_for_review"


def test_validation_rules(session):
    c = ads.create_campaign(session, name="x", objective="o")
    with pytest.raises(ads.AdsError):
        ads.approve_item(session, c, "budget", "yash")
    with pytest.raises(ads.AdsError):
        ads.approve_item(session, c, "creative", "system")
    c2 = campaign(session)
    ads.update_campaign(session, c2, destination_url="http://insecure.test")
    with pytest.raises(ads.AdsError, match="https"):
        ads.approve_item(session, c2, "destination", "yash")


def test_ad_audio_needs_commercial_clearance_and_ads_never_enter_organic_queue(stack, tmp_path):
    s = stack.s
    wav = tmp_path / "a.wav"; click_track(wav)
    a = register_audio(s, title="own", rights_status="original", local_file=str(wav), allow_offplatform_render=True,
                       allow_automated_publish=True, notes="own")
    c = campaign(s)
    with pytest.raises(AudioRightsError, match="ads"):
        ads.add_variants(s, c, stack.concept.id, hooks=["h"], audio_id=a.id, out_root=tmp_path, overrides=FAST)
    ad_reel = ads.add_variants(s, c, stack.concept.id, hooks=["h"], out_root=tmp_path / "ok", overrides={**FAST, "duration_override": 5})[0]
    with pytest.raises(q.QueueError, match="never enter"):
        q.submit_for_approval(s, ad_reel.reel_id, stack.acct.id)
