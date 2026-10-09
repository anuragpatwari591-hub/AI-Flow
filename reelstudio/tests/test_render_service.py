import pytest

from tests.test_audio import click_track
from reelstudio.audio.library import register_audio
from reelstudio.db import AuditLog
from reelstudio.render.service import AudioRightsError, render_reel
from reelstudio.writing.engine import run_cycle

FAST = {"canvas": {"fps": 20, "preset": "ultrafast"}}


def test_end_to_end_render_with_licensed_audio(session, tmp_path):
    c = run_cycle(session, categories=["situationship"], per_category=1)[0]
    wav = tmp_path / "own.wav"; click_track(wav, 100, 20)
    a = register_audio(session, title="own beat", artist="ANURAG", rights_status="original", local_file=str(wav),
                       allow_offplatform_render=True, allow_automated_publish=True, notes="own master")
    assert a.bpm and abs(a.bpm - 100) < 4
    reel = render_reel(session, c.id, audio_id=a.id, overrides=FAST, out_root=tmp_path / "r")
    assert reel.render_status == "rendered", reel.render_error
    assert reel.qa["video"]["passed"] and reel.qa["preview"]["passed"]
    assert reel.render_spec["beats_used"] > 5 and reel.render_spec["font"]["license"]
    assert reel.video_sha256 and reel.cover_path and "#" in reel.caption


def test_unverified_audio_blocks_render_and_is_audited(session, tmp_path):
    c = run_cycle(session, categories=["situationship"], per_category=1)[0]
    wav = tmp_path / "x.wav"; click_track(wav)
    a = register_audio(session, title="hit", rights_status="unverified", local_file=str(wav))
    with pytest.raises(AudioRightsError):
        render_reel(session, c.id, audio_id=a.id, overrides=FAST, out_root=tmp_path)
    assert session.query(AuditLog).filter_by(action="render.audio_blocked").count() == 1


def test_native_audio_renders_silent_and_flags_manual_step(session, tmp_path):
    c = run_cycle(session, categories=["cold_attitude"], per_category=1)[0]
    a = register_audio(session, title="trend", rights_status="instagram_native")
    reel = render_reel(session, c.id, audio_id=a.id, overrides=FAST, out_root=tmp_path)
    assert reel.render_status == "rendered" and reel.needs_native_audio and reel.audio_id is None


def test_branding_only_where_configured(session, tmp_path):
    c = run_cycle(session, categories=["situationship"], per_category=1)[0]
    r = render_reel(session, c.id, music_branding=True, overrides=FAST, preview_only=True, out_root=tmp_path)
    assert r.render_spec["spec"]["branding"]["enabled"] is False  # category not in apply_to_categories


def test_unreadable_style_fails_render(session, tmp_path):
    c = run_cycle(session, categories=["situationship"], per_category=1)[0]
    r = render_reel(session, c.id, overrides={**FAST, "text": {"color": "#202020"}}, out_root=tmp_path)
    assert r.render_status == "failed" and "readability" in r.render_error
