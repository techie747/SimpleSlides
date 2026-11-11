"""Camera path estimation.

Current method: ORB monocular visual odometry (OpenCV). It gives relative motion between consecutive
sharp frames. Monocular video has no absolute scale, so each step is weighted by its *parallax*
(feature motion not explained by pure rotation): turning in place produces ~zero translation, walking
produces translation. The whole path is then scaled so translation happens at an assumed walking speed.
The creator can later fix scale with one known measurement.

Planned upgrade: pycolmap sequential SfM, falling back to this module per segment.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .graph import Pose


@dataclass
class PoseResult:
    poses: list[Pose]
    method: str
    tracked_ratio: float     # share of frame pairs where motion was estimated
    lost_segments: list[tuple[float, float]]


ORB = None


def orb():
    global ORB
    if ORB is None:
        ORB = cv2.ORB_create(nfeatures=1500, fastThreshold=12)
    return ORB


def features(gray):
    kp, des = orb().detectAndCompute(gray, None)
    return kp, des


def good_matches(des1, des2, ratio=0.75):
    if des1 is None or des2 is None or len(des1) < 8 or len(des2) < 8:
        return []
    m = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des1, des2, k=2)
    return [a for a, *rest in m if rest and a.distance < ratio * rest[0].distance]


def estimate_path(frames: list[tuple[float, np.ndarray]], walk_speed: float) -> PoseResult:
    """frames: list of (timestamp, gray image) — already filtered for blur."""
    if len(frames) < 2:
        raise ValueError("Not enough sharp frames to map the space.")
    h, w = frames[0][1].shape
    f = 0.9 * w                                   # typical phone horizontal FOV ~ 65-70 deg
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    Kinv = np.linalg.inv(K)

    R_w = np.eye(3)
    c_w = np.zeros(3)
    raw = [(frames[0][0], c_w.copy(), R_w.copy())]
    steps: list[float] = []
    lost: list[tuple[float, float]] = []
    tracked = 0
    prev_kp, prev_des = features(frames[0][1])
    last_dir = np.array([0.0, 0.0, 1.0])
    last_R, last_move = np.eye(3), np.zeros(3)

    for (t, img), (tp, _) in zip(frames[1:], frames[:-1]):
        kp, des = features(img)
        m = good_matches(prev_des, des)
        R = np.eye(3)
        tvec = np.zeros(3)
        parallax = 0.0
        ok = False
        if len(m) >= 20:
            p1 = np.float32([prev_kp[x.queryIdx].pt for x in m])
            p2 = np.float32([kp[x.trainIdx].pt for x in m])
            E, mask = cv2.findEssentialMat(p1, p2, K, method=cv2.RANSAC, prob=0.999, threshold=1.0)
            if E is not None and E.shape == (3, 3):
                n_in, R_, t_, mask2 = cv2.recoverPose(E, p1, p2, K, mask=mask)
                if n_in >= 15:
                    R, tvec = R_, t_.ravel()
                    inl = mask2.ravel().astype(bool)
                    # Parallax: residual after removing rotation-only motion (homography K R K^-1).
                    H = K @ R @ Kinv
                    p1h = cv2.perspectiveTransform(p1[inl].reshape(-1, 1, 2), H).reshape(-1, 2)
                    parallax = float(np.median(np.linalg.norm(p2[inl] - p1h, axis=1))) if inl.any() else 0.0
                    ok = True
        if not ok and len(m) >= 10:
            # Rotation-only fallback (typical during a spin, where E is degenerate): H ~ K R K^-1.
            p1 = np.float32([prev_kp[x.queryIdx].pt for x in m])
            p2 = np.float32([kp[x.trainIdx].pt for x in m])
            Hm, hmask = cv2.findHomography(p1, p2, cv2.RANSAC, 3.0)
            if Hm is not None and int(hmask.sum()) >= 8:
                U, _, Vt = np.linalg.svd(Kinv @ Hm @ K)
                R = U @ Vt
                if np.linalg.det(R) < 0:
                    R = -R
                tvec, parallax, ok = np.zeros(3), 0.0, True
        if ok and math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2)))) > 35:
            ok = False                            # >175 deg/s between samples: a bad estimate, not real motion
        if ok:
            tracked += 1
            last_R = R
            # Camera 2 in camera-1 coords: rotation R^T, centre -R^T t.
            d = -R.T @ tvec
            if np.linalg.norm(d) == 0:
                d = last_dir.copy()
            else:
                d = d / np.linalg.norm(d)
            # Walkers move forward-ish; recoverPose has sign ambiguity in degenerate cases.
            if d[2] < -0.3 and last_dir[2] > 0:
                d = -d
            last_dir = d
            step = max(0.0, parallax - 0.6) / w   # pixels of parallax, de-noised, resolution independent
            last_move = R_w @ d * step
            c_w = c_w + last_move
            R_w = R_w @ R.T
        else:
            if lost and abs(lost[-1][1] - tp) < 1e-6:
                lost[-1] = (lost[-1][0], t)
            else:
                lost.append((tp, t))
            # Constant-velocity guess through the gap (degraded but continuous); reported to the creator.
            c_w = c_w + last_move
            R_w = R_w @ last_R.T
        steps.append(np.linalg.norm(c_w - raw[-1][1]))
        raw.append((t, c_w.copy(), R_w.copy()))
        prev_kp, prev_des = kp, des

    # Scale: moving steps should correspond to walk_speed.
    ts = np.array([r[0] for r in raw])
    dt = np.diff(ts)
    st = np.array(steps)
    moving = st > (np.percentile(st, 40) if len(st) > 4 else 0)
    speed = np.median(st[moving] / np.maximum(dt[moving], 1e-3)) if moving.any() else 0
    scale = walk_speed / speed if speed > 0 else 1.0

    poses = []
    for t, c, Rw in raw:
        fwd = Rw @ np.array([0.0, 0.0, 1.0])
        poses.append(Pose(t=float(t), x=float(c[0] * scale), z=float(c[2] * scale), yaw=math.atan2(fwd[0], fwd[2])))
    return PoseResult(poses=poses, method="orb-visual-odometry", tracked_ratio=tracked / (len(frames) - 1),
                      lost_segments=lost)


class VisualMatcher:
    """ORB match counts between node images — used to verify junctions / loop closures."""

    def __init__(self, grays: list[np.ndarray]):
        self.feats = [features(g)[1] for g in grays]
        self.cache: dict[tuple[int, int], int] = {}

    def __call__(self, i: int, j: int) -> int:
        k = (i, j)
        if k not in self.cache:
            self.cache[k] = len(good_matches(self.feats[i], self.feats[j], ratio=0.7))
        return self.cache[k]
