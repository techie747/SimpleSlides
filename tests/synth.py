"""Render a synthetic walk-through video: textured corridor, walk forward, spin in place, walk on."""
import math
from pathlib import Path

import cv2
import numpy as np


def make_video(path: Path, seconds_walk=4.0, fps=30, w=640, h=360, ext_codec="mp4v"):
    rng = np.random.default_rng(0)
    # Points on the walls/floor/ceiling of a 4 m wide, 30 m long corridor + a room at the end.
    n = 6000
    pts = np.stack([rng.uniform(-6, 6, n), rng.uniform(-1.5, 1.5, n), rng.uniform(-6, 20, n)], 1)
    side = rng.integers(0, 3, n)
    pts[side == 0, 0] = np.sign(rng.uniform(-1, 1, (side == 0).sum())) * 2.0
    pts[side == 1, 1] = np.sign(rng.uniform(-1, 1, (side == 1).sum())) * 1.5
    pts[side == 2, 2] = np.where(rng.uniform(size=(side == 2).sum()) > .5, 20.0, -6.0)
    cols = rng.integers(40, 255, (n, 3))
    f = 0.9 * w
    path_ = []
    T = int(seconds_walk * fps)
    for i in range(T):
        path_.append((0.0, 0.8 * i / fps, 0.0))                  # walk forward 0.8 m/s
    z0 = 0.8 * T / fps
    for i in range(int(8 * fps)):
        path_.append((0.0, z0, 2 * math.pi * i / (8 * fps)))     # spin 360 in 8 s
    for i in range(T):
        path_.append((0.0, z0 + 0.8 * i / fps, 0.0))             # walk on
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*ext_codec), fps, (w, h))
    for x, z, yaw in path_:
        c, s = math.cos(yaw), math.sin(yaw)
        rel = pts - np.array([x, 0, z])
        cx = c * rel[:, 0] - s * rel[:, 2]
        cz = s * rel[:, 0] + c * rel[:, 2]
        cy = rel[:, 1]
        m = cz > 0.2
        u = (f * cx[m] / cz[m] + w / 2).astype(int)
        v = (f * cy[m] / cz[m] + h / 2).astype(int)
        r = np.clip((6 / cz[m]).astype(int), 1, 12)
        img = np.full((h, w, 3), 90, np.uint8)
        order = np.argsort(-cz[m])
        for k in order:
            if 0 <= u[k] < w and 0 <= v[k] < h:
                cv2.circle(img, (u[k], v[k]), int(r[k]), tuple(int(q) for q in cols[m][k]), -1)
        vw.write(img)
    vw.release()
    return path
