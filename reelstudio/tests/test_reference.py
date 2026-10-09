import subprocess

import pytest

from reelstudio.reference.library import UninspectedObservation, add_observation, add_reference, principles_summary


def make_video(path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=270x480:d=2:r=24",
                    "-f", "lavfi", "-i", "color=c=white:s=270x480:d=1:r=24",
                    "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(path)], check=True)


def test_measure_and_observation_rules(session, tmp_path):
    v = tmp_path / "ref.mp4"
    make_video(v)
    item = add_reference(session, account="salzr", source_url="https://www.instagram.com/salzr/", local_file=str(v))
    assert item.measurements["duration_s"] == pytest.approx(3, abs=0.2)
    assert item.measurements["dark_frame_ratio"] > 0.5
    assert item.measurements["scene_cuts_detected"] >= 1
    with pytest.raises(UninspectedObservation):
        add_observation(session, item.id, "uses serif fonts", inspected=False, evidence="")
    add_observation(session, item.id, "mostly black frame", inspected=True, evidence="viewed supplied ref.mp4")
    assert len(principles_summary(session)["observations"]) == 1


def test_observation_without_any_material_rejected(session):
    item = add_reference(session, account="salzr", source_url="https://www.instagram.com/salzr/")
    with pytest.raises(UninspectedObservation):
        add_observation(session, item.id, "claims", inspected=True, evidence="memory")
