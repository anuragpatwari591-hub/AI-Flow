import wave
from pathlib import Path

import numpy as np
import pytest

from reelstudio.audio.beats import analyze_audio
from reelstudio.audio.library import match_audio, register_audio
from reelstudio.audio.rights import clearance
from reelstudio.db import AudioAsset, Concept


def click_track(path: Path, bpm=120, secs=12, sr=22050):
    y = np.zeros(int(sr * secs), dtype=np.float32)
    period = 60 / bpm
    for i in range(int(secs / period)):
        s = int((0.25 + i * period) * sr)
        t = np.arange(2000) / sr
        y[s:s + 2000] += (np.sin(2 * np.pi * 900 * t) * np.exp(-t * 60)).astype(np.float32)[: len(y[s:s + 2000])]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y * 30000).astype(np.int16).tobytes())


@pytest.mark.parametrize("bpm", [90, 120, 140])
def test_tempo_and_beat_positions(tmp_path, bpm):
    p = tmp_path / "c.wav"; click_track(p, bpm)
    r = analyze_audio(p)
    assert r["bpm"] == pytest.approx(bpm, rel=0.03)
    period = 60 / bpm
    errs = [min(abs((b - 0.25) % period, ), abs(period - (b - 0.25) % period)) for b in r["beats"][:16]]
    assert np.median(errs) < 0.06


def test_rights_gating(session, tmp_path):
    f = tmp_path / "a.wav"; click_track(f)
    unv = register_audio(session, title="Hit", rights_status="unverified", local_file=str(f))
    assert unv.bpm is None  # never analysed without cleared rights
    for purpose in ("render", "publish", "ads"):
        assert not clearance(unv, purpose)[0]
    with pytest.raises(ValueError):
        register_audio(session, title="x", rights_status="licensed")
    own = register_audio(session, title="Mine", artist="ANURAG", rights_status="original", local_file=str(f),
                         allow_offplatform_render=True, allow_automated_publish=True, notes="own master, AP STUDIOS")
    assert clearance(own, "render")[0] and clearance(own, "publish")[0]
    assert not clearance(own, "ads")[0]  # ads need explicit commercial flag
    native = register_audio(session, title="Trending", rights_status="instagram_native")
    assert not clearance(native, "render")[0] and "manual" in clearance(native, "render")[1][0]
    assert clearance(None, "publish")[0]


def test_matching_prefers_cleared_and_mood(session, tmp_path):
    f = tmp_path / "a.wav"; click_track(f, 80)
    register_audio(session, title="slow", rights_status="original", local_file=str(f), mood="slow ambient piano",
                   allow_offplatform_render=True, notes="own")
    register_audio(session, title="risky", rights_status="unverified", mood="slow ambient sparse piano")
    c = Concept(cycle_id="x", category="heartbreak_latenight", hook="h", lines=[], audio_mood="slow, ambient, sparse piano")
    session.add(c); session.flush()
    m = match_audio(session, c)
    assert m[0]["title"] == "slow" and m[0]["cleared"] and not m[1]["cleared"] and m[1]["score"] == 0
