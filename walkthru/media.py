"""ffmpeg/ffprobe helpers: probing, frame sampling, clip encoding."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


class MediaError(Exception):
    """Friendly, user-facing failure."""


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise MediaError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "ffmpeg failed")
    return p.stdout


def probe(path: Path) -> dict:
    try:
        out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    except MediaError:
        raise MediaError("We couldn't read this file as a video. Try exporting it again as MP4 or MOV.")
    info = json.loads(out)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        raise MediaError("This file has no video track.")
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = int(v.get("tags", {}).get("rotate", rot))
    if abs(rot) % 180 == 90:
        w, h = h, w
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    dur = float(info.get("format", {}).get("duration") or v.get("duration") or 0)
    tags = json.dumps(info).lower()
    is_360 = (w > 0 and abs(w / h - 2.0) < 0.02) or "spherical" in tags or "equirectangular" in tags
    return {"width": w, "height": h, "fps": fps or 30.0, "duration": dur, "codec": v.get("codec_name"), "is_360": is_360}


def normalize(src: Path, dst: Path, max_h: int, gop: int) -> None:
    """Re-encode any input (MOV, MKV, AVI, 3GP...) to H.264 MP4, upright, constant frame rate."""
    vf = f"scale=-2:'min({max_h},ih)',fps=30,format=yuv420p"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "21", "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0", "-movflags", "+faststart", str(dst)])


def sample_frames(src: Path, fps: float, width: int, is_360: bool, gray: bool = True):
    """Yield (t, frame) at `fps` (grayscale unless gray=False). For 360 video use the front-facing quarter (pinhole-like)."""
    cap = cv2.VideoCapture(str(src))
    vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(vfps / fps))
    i = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            if is_360:
                h, w = frame.shape[:2]
                frame = frame[h // 4: 3 * h // 4, 3 * w // 8: 5 * w // 8]
            scale = width / frame.shape[1]
            frame = cv2.resize(frame, (width, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
            yield i / vfps, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if gray else frame
        i += 1
    cap.release()


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def thumbnail(src: Path, t: float, dst: Path, width: int = 480) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "4", str(dst)])


def still(src: Path, t: float, dst: Path) -> None:
    """Full-quality still for a node (shown instantly while clips load)."""
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-q:v", "3", str(dst)])


def clip(src: Path, t0: float, t1: float, dst: Path, reverse: bool, gop: int) -> None:
    """Cut [t0, t1] with keyframes at both ends; optionally pre-reversed (mobile can't play backwards)."""
    vf = "reverse" if reverse else "null"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(src), "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-g", str(gop), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(dst)])


def keep_only(src: Path, dst: Path, ranges: list, gop: int) -> None:
    """Re-encode `src` keeping only the given (start, end) ranges, joined back to back."""
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in ranges)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"select='{expr}',setpts=N/FRAME_RATE/TB", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-g", str(gop), "-keyint_min", str(gop),
         "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)])
