"""Processing pipeline. Each stage reports progress to the jobs table."""
from __future__ import annotations

import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from . import db, media
from .config import CONFIG
from .graph import build_graph
from .poses import VisualMatcher, estimate_path

STAGES = ["uploading", "checking", "frames", "mapping", "paths", "encoding", "ready"]


class Friendly(Exception):
    def __init__(self, msg, tip=""):
        super().__init__(msg)
        self.tip = tip


def stage(tid, name, progress=0.0):
    db.update_job(tid, stage=name, stage_index=STAGES.index(name), progress=progress)


def process(tid: str, cfg=CONFIG):
    t_start = time.time()
    tour = db.q("SELECT * FROM tours WHERE id=?", (tid,), one=True)
    d = db.tour_dir(tid)
    src = d / f"original{tour['ext']}"
    try:
        # 2. Checking
        stage(tid, "checking", 5)
        info = media.probe(src)
        db.append_log(tid, f"probe: {json.dumps(info)}")
        if info["duration"] <= 1.5:
            raise Friendly("This video is too short to walk through.", "Record at least a few seconds of walking.")
        if info["duration"] > cfg.max_duration_s:
            raise Friendly("This video is longer than 20 minutes.", "Trim it or split the space into two tours.")
        db.update_tour(tid, input_type="360" if info["is_360"] else "flat")
        work = d / "work.mp4"
        media.normalize(src, work, cfg.playback_max_height if not info["is_360"] else 2160, cfg.playback_gop)
        stage(tid, "checking", 100)

        # 3. Frames
        stage(tid, "frames", 0)
        frames, sharp = [], []
        est = max(1, int(info["duration"] * cfg.sample_fps))
        for k, (t, g) in enumerate(media.sample_frames(work, cfg.sample_fps, cfg.analysis_width, info["is_360"])):
            frames.append((t, g))
            sharp.append(media.sharpness(g))
            if k % 10 == 0:
                stage(tid, "frames", min(99, 100 * k / est))
        if len(frames) < 4:
            raise Friendly("We couldn't pull enough frames from this video.", "Try a longer, steadier recording.")
        # Compare each frame with its neighbours (+-2 s): content changes (a blank wall) aren't blur.
        sharp = np.array(sharp)
        win = max(2, int(2 * cfg.sample_fps))
        local = np.array([np.median(sharp[max(0, i - win): i + win + 1]) for i in range(len(sharp))])
        keep = [f for f, s, m in zip(frames, sharp, local) if s >= cfg.blur_rel_threshold * m]
        db.append_log(tid, f"frames: {len(frames)} sampled, {len(keep)} sharp")
        if len(keep) < 0.4 * len(frames):
            raise Friendly("Most of this video is blurry.", "Walk slower and keep lights on so each frame is crisp.")
        if np.mean([g.mean() for _, g in keep]) < 25:
            raise Friendly("This video is too dark to map.", "Turn the lights on and record again.")
        stage(tid, "frames", 100)

        # 4. Mapping
        stage(tid, "mapping", 10)
        pr = estimate_path(keep, cfg.assumed_walk_speed_mps)
        db.append_log(tid, f"mapping: method={pr.method} tracked={pr.tracked_ratio:.0%} lost={len(pr.lost_segments)}")
        if pr.tracked_ratio < 0.5:
            raise Friendly("We couldn't follow the camera through most of this video.",
                           "Walk slower, avoid pointing at blank walls, and keep the camera at chest height.")
        warnings = []
        for a, b in pr.lost_segments:
            if b - a > 1.0:
                warnings.append(f"Tracking was lost between {a:.1f}s and {b:.1f}s (fast motion or blank view); the map is approximate there.")
        stage(tid, "mapping", 100)

        # 5. Paths
        stage(tid, "paths", 10)
        by_t = {round(t, 3): g for t, g in keep}
        graph0, _ = build_graph(pr.poses, cfg)   # node positions only, to get node frames
        node_imgs = [by_t.get(round(n.t, 3)) for n in graph0.nodes]
        node_imgs = [g if g is not None else keep[0][1] for g in node_imgs]
        matcher = VisualMatcher(node_imgs)
        graph, spins = build_graph(pr.poses, cfg, match_score=matcher)
        n_j = sum(e.kind == "junction" for e in graph.edges) // 2
        db.append_log(tid, f"graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges, {n_j} junctions, {len(spins)} look-arounds")
        if len(graph.nodes) < 2:
            raise Friendly("We didn't detect any walking in this video.",
                           "Walk through the space; standing still only works with a 360° camera.")
        stage(tid, "paths", 100)

        # 6. Encoding
        stage(tid, "encoding", 0)
        (d / "clips").mkdir(exist_ok=True)
        (d / "stills").mkdir(exist_ok=True)
        jobs = []
        for n in graph.nodes:
            jobs.append(("still", n))
        for e in graph.edges:
            if e.kind == "junction":
                continue                         # same spot: instant crossfade to the target still
            e.clip = f"clips/{e.kind}_{min(e.src, e.dst)}_{max(e.src, e.dst)}_{'r' if e.reverse else 'f'}.mp4" \
                if e.kind != "look" else f"clips/look_{e.src}_{e.t0:.2f}_{'r' if e.reverse else 'f'}.mp4"
            jobs.append(("clip", e))
        done, uniq = 0, {}
        for kind, obj in jobs:
            key = f"stills/{obj.id}.jpg" if kind == "still" else obj.clip
            uniq.setdefault(key, (kind, obj))

        def do(item):
            key, (kind, obj) = item
            out = d / key
            if kind == "still":
                media.still(work, obj.t, out)
            else:
                media.clip(work, obj.t0, obj.t1, out, obj.reverse, cfg.playback_gop)

        with ThreadPoolExecutor(max_workers=4) as ex:
            for _ in ex.map(do, uniq.items()):
                done += 1
                if done % 3 == 0:
                    stage(tid, "encoding", 100 * done / len(uniq))

        tour_json = {
            "id": tid, "input_type": "360" if info["is_360"] else "flat",
            "width": info["width"], "height": info["height"], "duration": info["duration"],
            "method": pr.method, "warnings": warnings, "start_node": 0,
            **graph.to_dict(),
            "path": [[p.t, p.x, p.z] for p in pr.poses],
        }
        (d / "tour.json").write_text(json.dumps(tour_json))
        db.update_tour(tid, status="ready", start_node_id=0)
        db.append_log(tid, f"done in {time.time() - t_start:.1f}s")
        stage(tid, "ready", 100)
    except Friendly as e:
        fail(tid, str(e), e.tip)
    except media.MediaError as e:
        fail(tid, str(e), "Try exporting the video again as MP4 or MOV.")
    except Exception as e:  # noqa: BLE001
        db.append_log(tid, traceback.format_exc())
        fail(tid, "Something went wrong while processing this video.", f"Details: {e}")


def fail(tid, msg, tip):
    db.update_job(tid, error=msg, tip=tip)
    db.update_tour(tid, status="failed")
