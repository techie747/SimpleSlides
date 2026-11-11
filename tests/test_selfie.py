"""Selfie removal: segment logic, the ffmpeg cut, and no false positives on walk-through footage."""

import pytest

from walkthru import media, selfie
from walkthru.config import Config

CFG = Config()


def frames(spec, fps=CFG.selfie_sample_fps):
    """spec: list of (seconds, face_fraction) blocks -> (times, fractions)."""
    times, fr, t = [], [], 0.0
    for secs, f in spec:
        for _ in range(int(round(secs * fps))):
            times.append(t)
            fr.append(f)
            t += 1 / fps
    return times, fr


def test_no_faces_nothing_removed():
    t, f = frames([(20, 0.0)])
    assert selfie.find_segments(t, f, 20, CFG) == []


def test_selfie_in_middle_removed_with_padding():
    t, f = frames([(5, 0.0), (4, 0.4), (6, 0.0)])
    (a, b), = selfie.find_segments(t, f, 15, CFG)
    assert a == pytest.approx(5 - CFG.selfie_pad_s, abs=0.01)
    assert b == pytest.approx(9 + CFG.selfie_pad_s, abs=0.01)


def test_passerby_ignored():
    # Small faces (someone walking by) and a big face for a split second are not selfies.
    t, f = frames([(5, 0.08), (0.34, 0.4), (5, 0.1)])
    assert selfie.find_segments(t, f, 10.3, CFG) == []


def test_flicker_bridged_into_one_segment():
    t, f = frames([(2, 0.0), (2, 0.35), (1, 0.0), (2, 0.35), (3, 0.0)])
    segs = selfie.find_segments(t, f, 10, CFG)
    assert len(segs) == 1 and segs[0][0] < 2 and segs[0][1] > 7


def test_selfie_at_start_and_end_clamped():
    t, f = frames([(3, 0.3), (6, 0.0), (3, 0.3)])
    segs = selfie.find_segments(t, f, 12, CFG)
    assert segs[0][0] == 0.0 and segs[-1][1] == 12


def test_keep_ranges():
    assert selfie.keep_ranges([(2, 4), (8, 9)], 10) == [(0, 2), (4, 8), (9, 10)]
    assert selfie.keep_ranges([(0, 3)], 10) == [(3, 10)]
    assert selfie.keep_ranges([(0, 10)], 10) == []
    assert selfie.keep_ranges([(0.2, 5)], 10) == [(5, 10)]      # 0.2 s sliver dropped


@pytest.fixture(scope="module")
def corridor(tmp_path_factory):
    from tests.synth import make_video
    d = tmp_path_factory.mktemp("selfie")
    raw = make_video(d / "raw.avi", seconds_walk=2.0, ext_codec="MJPG")
    out = d / "walk.mp4"
    media.normalize(raw, out, 720, CFG.playback_gop)
    return out


def test_keep_only_cuts_video(corridor):
    dur = media.probe(corridor)["duration"]
    out = corridor.parent / "cut.mp4"
    media.keep_only(corridor, out, [(0, 3), (6, dur)], CFG.playback_gop)
    assert media.probe(out)["duration"] == pytest.approx(dur - 3, abs=0.2)


def test_detect_finds_no_selfie_in_walkthrough(corridor):
    assert selfie.detect(corridor, media.probe(corridor)["duration"], CFG) == []


def test_detect_with_face_sizes(corridor):
    # Fake detector: pretend a big face is in view from 4 s to 8 s.
    calls = []

    def fake(_frame):
        t = len(calls) / CFG.selfie_sample_fps
        calls.append(t)
        return 0.4 if 4 <= t < 8 else 0.0

    (a, b), = selfie.detect(corridor, media.probe(corridor)["duration"], CFG, sizer=fake)
    assert 3 <= a <= 4 and 8 <= b <= 9


def test_model_file_present():
    assert selfie.MODEL.exists() and selfie.MODEL.stat().st_size > 100_000
