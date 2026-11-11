"""Find "selfie" stretches: parts of a video where the camera points back at the person filming.

A selfie looks very different from walk-through footage: one face fills a big part of the frame
and stays there for a while. People passing by in a walk-through are smaller and gone quickly.
So we flag frames whose largest face is at least `selfie_face_min_height` of the frame height,
group nearby flagged frames into runs, ignore runs that are too short, and pad each run a little
so the turn-the-phone-around moment is cut too.

Face detection uses YuNet (MIT licence, ~230 KB, bundled in walkthru/models), via OpenCV.
"""
from __future__ import annotations

from pathlib import Path

import cv2

from . import media

MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"


class FaceSizer:
    """Largest face height as a fraction of frame height (0.0 when there is no face)."""

    def __init__(self, score: float):
        self.det = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), score)
        self.size = None

    def __call__(self, bgr) -> float:
        h, w = bgr.shape[:2]
        if self.size != (w, h):
            self.det.setInputSize((w, h))
            self.size = (w, h)
        _, faces = self.det.detect(bgr)
        if faces is None or len(faces) == 0:
            return 0.0
        return float(max(f[3] for f in faces)) / h


def find_segments(times, fractions, duration, cfg) -> list[tuple[float, float]]:
    """Turn per-frame face sizes into padded, merged (start, end) ranges to remove. Pure logic."""
    step = 1.0 / cfg.selfie_sample_fps
    runs: list[list[float]] = []
    for t, f in zip(times, fractions):
        if f < cfg.selfie_face_min_height:
            continue
        if runs and t - runs[-1][1] <= cfg.selfie_merge_gap_s:
            runs[-1][1] = t
        else:
            runs.append([t, t])
    out: list[tuple[float, float]] = []
    for a, b in runs:
        if b - a + step < cfg.selfie_min_duration_s:
            continue                              # a face flashing past, not a selfie
        a, b = max(0.0, a - cfg.selfie_pad_s), min(duration, b + step + cfg.selfie_pad_s)
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def keep_ranges(remove, duration, min_len=0.4) -> list[tuple[float, float]]:
    """The parts of [0, duration] not covered by `remove`, dropping slivers shorter than min_len."""
    keep, cur = [], 0.0
    for a, b in remove:
        if a - cur >= min_len:
            keep.append((cur, a))
        cur = max(cur, b)
    if duration - cur >= min_len:
        keep.append((cur, duration))
    return keep


def detect(video: Path, duration: float, cfg, sizer=None) -> list[tuple[float, float]]:
    """Scan `video` and return the selfie ranges to remove (empty list if none)."""
    sizer = sizer or FaceSizer(cfg.selfie_score)
    times, fracs = [], []
    for t, frame in media.sample_frames(video, cfg.selfie_sample_fps, cfg.analysis_width, False, gray=False):
        times.append(t)
        fracs.append(sizer(frame))
    return find_segments(times, fracs, duration, cfg)


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"
