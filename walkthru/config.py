"""Tunable algorithm settings. Every value can be overridden with an env var WALKTHRU_<NAME>."""
import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Config:
    # Where uploads, clips and the database live.
    data_dir: Path = Path(os.environ.get("WALKTHRU_DATA_DIR", "data"))
    # Accepted containers. ffmpeg decodes all of them; we always re-encode to H.264 MP4 for playback.
    allowed_ext: tuple = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpeg", ".mpg", ".3gp")
    max_upload_bytes: int = 4 * 1024**3          # 4 GB
    max_duration_s: float = 20 * 60              # 20 minutes
    # Analysis: frames per second sampled for pose estimation. 5 fps keeps enough overlap
    # between frames for feature matching at walking speed while staying fast on CPU.
    sample_fps: float = 5.0
    analysis_width: int = 640                    # pose estimation resolution
    # Frames whose sharpness (variance of Laplacian) is below this fraction of the median are dropped.
    blur_rel_threshold: float = 0.35
    # One node per this many metres of travelled distance (after scale normalisation).
    node_spacing_m: float = 0.75
    # Without a known measurement we assume the walker moves at this speed while translating.
    assumed_walk_speed_mps: float = 0.8
    # Two nodes closer than this (and visually matching) become a junction.
    junction_dist_m: float = 0.6
    # Junction nodes must be at least this many nodes apart along the path (else they're just neighbours).
    junction_min_gap: int = 4
    # ORB "good matches" needed to accept a visual loop closure without position support.
    junction_strong_matches: int = 60
    # ...and with position support.
    junction_weak_matches: int = 25
    # A spin-in-place segment: yaw changes at least this much while moving less than spin_max_move_m.
    spin_min_yaw_deg: float = 150.0
    spin_max_move_m: float = 0.8
    # Playback clips: max height and keyframe interval (frames) so seeks/starts are instant.
    playback_max_height: int = 1080
    playback_gop: int = 12
    # Selfie removal: cut parts where the camera faces the person filming (flat video only; a 360
    # camera always sees the person holding it). A frame counts as "selfie" when its largest face is
    # at least this fraction of the frame height: arm's-length selfies are ~0.25-0.5, people walking
    # past a few metres away are ~0.05-0.12.
    selfie_remove: bool = True
    selfie_face_min_height: float = 0.18
    selfie_score: float = 0.8              # face detector confidence
    selfie_sample_fps: float = 3.0         # frames checked per second
    selfie_min_duration_s: float = 1.0     # shorter face runs are passers-by, not selfies
    selfie_merge_gap_s: float = 1.5        # bridge brief misses (head turned, motion blur)
    selfie_pad_s: float = 0.5              # also cut the phone-flipping moment around each selfie


def load() -> Config:
    cfg = Config()
    for f in fields(Config):
        env = os.environ.get(f"WALKTHRU_{f.name.upper()}")
        if env is not None and f.name not in ("data_dir", "allowed_ext"):
            cur = getattr(cfg, f.name)
            setattr(cfg, f.name, env.strip().lower() in ("1", "true", "yes", "on") if isinstance(cur, bool) else type(cur)(env))
    cfg.data_dir = Path(cfg.data_dir)
    return cfg


CONFIG = load()
