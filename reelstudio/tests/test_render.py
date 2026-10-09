import pytest

from reelstudio.render.fonts import FontError, font_record, license_table
from reelstudio.render.layout import compute_layout, contrast_ratio
from reelstudio.render.pacing import snap_to_beats
from reelstudio.render.renderer import TextAnimator, plan_render, qa_video, render_cover, render_video
from reelstudio.render.spec import list_templates, load_template

LINES = [{"text": "me: i'm sleeping early tonight", "start": 0.6, "end": 3.0},
         {"text": "me at 2:47am:", "start": 3.0, "end": 4.6},
         {"text": "learning how bridges are built", "start": 4.6, "end": 8.0}]


def test_all_fonts_have_licenses():
    for row in license_table():
        assert row["license"] != "MISSING" and row["available"] == "True", row
    with pytest.raises(FontError):
        font_record("not_registered")


def test_templates_load_and_override():
    assert {"midnight_minimal", "editorial_bold", "soft_cinematic"} <= set(list_templates())
    s = load_template("midnight_minimal", {"text": {"size": 60}, "animation": {"zoom": 0.0}})
    assert s.text.size == 60 and s.animation.zoom == 0 and s.canvas.width == 1080


def test_text_fit_shrinks_long_text_and_flags_impossible():
    spec = load_template("editorial_bold")
    lay = compute_layout(spec, ["a surprisingly long sentence that must wrap onto several lines to fit"])
    assert lay.fits and lay.size <= spec.text.size
    assert lay.origin_y >= spec.safe.top and lay.origin_y + lay.height <= 1920 - spec.safe.bottom
    bad = compute_layout(spec.model_copy(update={"text": spec.text.model_copy(update={"min_size": 400, "size": 400})}),
                         ["extraordinarily"])
    assert not bad.fits and bad.problems


def test_contrast_and_readability_flags():
    spec = load_template("midnight_minimal")
    plan = plan_render(spec, LINES)
    assert plan.qa_text["contrast_ok"] and plan.qa_text["text_fits_safe_area"]
    low = load_template("midnight_minimal", {"text": {"color": "#222222"}})
    assert not plan_render(low, LINES).qa_text["contrast_ok"]
    assert contrast_ratio((255, 255, 255), (0, 0, 0)) == pytest.approx(21)


def test_beat_snapping_keeps_order():
    out = snap_to_beats(LINES, [0.5, 1.5, 3.2, 4.8, 6.0], 0.35)
    assert [l["start"] for l in out] == sorted(l["start"] for l in out)
    assert out[1]["start"] == 3.2 and out[2]["start"] == 4.8
    assert out[0]["end"] == out[1]["start"]


@pytest.mark.parametrize("tpl", ["midnight_minimal", "editorial_bold", "soft_cinematic"])
def test_preview_render_each_template(tmp_path, tpl):
    spec = load_template(tpl)
    plan = plan_render(spec, LINES, beats=[0.6, 3.0, 4.6], scale=0.25)
    out = render_video(plan, tmp_path / "p.mp4", preview=True)
    qa = qa_video(out, spec, 0.25, final=True)
    assert qa["passed"], qa
    assert qa["audio_codec_ok"] and abs(qa["duration_s"] - plan.duration) < 0.3


def test_full_res_render_and_cover(tmp_path):
    spec = load_template("midnight_minimal", {"canvas": {"fps": 24, "preset": "ultrafast"}, "duration_override": 4})
    lines = [{"text": "this is a test", "start": 0.4, "end": 1.6}, {"text": "of the renderer", "start": 1.6, "end": 3.4}]
    plan = plan_render(spec, lines)
    out = render_video(plan, tmp_path / "f.mp4")
    qa = qa_video(out, spec)
    assert qa["resolution"] == "1080x1920" and qa["passed"] and qa["video_codec_ok"] and qa["audio_codec_ok"]
    cover = render_cover(plan, tmp_path / "c.jpg")
    from PIL import Image
    im = Image.open(cover)
    assert im.size == (1080, 1920) and im.getextrema()[0][1] > 150  # text present


def test_text_actually_appears_in_frames():
    spec = load_template("midnight_minimal")
    plan = plan_render(spec, LINES, scale=0.25)
    an = TextAnimator(plan)
    import numpy as np
    blank = np.frombuffer(an.frame(0.1), dtype=np.uint8).reshape(480, 270, 4)[..., 3].max()
    shown = np.frombuffer(an.frame(7.0), dtype=np.uint8).reshape(480, 270, 4)[..., 3].max()
    gone = np.frombuffer(an.frame(plan.duration - 0.01), dtype=np.uint8).reshape(480, 270, 4)[..., 3].max()
    assert blank == 0 and shown > 200 and gone < 20


def test_render_is_deterministic_in_frames():
    spec = load_template("editorial_bold")
    plan = plan_render(spec, LINES, beats=[0.6, 3.0], scale=0.25)
    assert TextAnimator(plan).frame(3.3) == TextAnimator(plan).frame(3.3)


def test_font_lookup_survives_distro_path_differences(tmp_path, monkeypatch):
    """Same file name under a different directory (e.g. liberation2 vs liberation) must still resolve."""
    import shutil
    from reelstudio.render import fonts
    real = fonts.font_record("inter_medium")["path"]
    root = tmp_path / "fonts" / "other" / "dir"; root.mkdir(parents=True)
    shutil.copy(real, root / "Inter-Medium.otf")
    monkeypatch.setattr(fonts, "SEARCH_ROOTS", (str(tmp_path / "fonts"),))
    got = fonts._resolve("/nonexistent/place/Inter-Medium.otf")
    assert got and got.name == "Inter-Medium.otf"
    assert fonts._resolve("/nonexistent/place/Nope.otf") is None
