"""Path Graph: turn a camera path into navigable nodes and edges.

Pure numpy so it can be unit-tested with synthetic camera paths.

Coordinates: x = right, z = forward on the floor plane (y is up/down and ignored for navigation).
Yaw is measured in radians, 0 = facing +z, positive = turning right (towards +x).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import numpy as np


@dataclass
class Pose:
    t: float                 # video timestamp (s)
    x: float
    z: float
    yaw: float               # radians


@dataclass
class Node:
    id: int
    t: float
    x: float
    z: float
    yaw: float
    room: Optional[str] = None


@dataclass
class Edge:
    id: int
    src: int
    dst: int
    kind: str                # forward | back | junction | look
    action: str              # forward | back | left | right  (which arrow triggers it)
    t0: float                # clip start in source video
    t1: float                # clip end
    reverse: bool            # play reversed footage
    angle: float = 0.0       # signed direction relative to src heading (radians)
    clip: Optional[str] = None


@dataclass
class Graph:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)

    def to_dict(self):
        return {"nodes": [asdict(n) for n in self.nodes], "edges": [asdict(e) for e in self.edges]}


def wrap(a: float) -> float:
    """Wrap angle to (-pi, pi]."""
    return (a + math.pi) % (2 * math.pi) - math.pi


def classify(angle: float) -> str:
    """Map a relative direction to an arrow."""
    d = math.degrees(wrap(angle))
    if -45 <= d <= 45:
        return "forward"
    if 45 < d < 135:
        return "right"
    if -135 < d < -45:
        return "left"
    return "back"


def path_length(poses: list[Pose]) -> np.ndarray:
    """Cumulative travelled distance at each pose."""
    p = np.array([[q.x, q.z] for q in poses])
    if len(p) < 2:
        return np.zeros(len(p))
    step = np.linalg.norm(np.diff(p, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(step)])


def build_nodes(poses: list[Pose], spacing: float) -> list[Node]:
    """One node every `spacing` metres of travel; first and last pose always become nodes."""
    if not poses:
        return []
    cum = path_length(poses)
    picks = [0]
    nxt = spacing
    for i in range(1, len(poses)):
        if cum[i] >= nxt:
            picks.append(i)
            nxt = cum[i] + spacing
    if picks[-1] != len(poses) - 1:
        # Merge a tiny tail into the last node instead of creating a near-duplicate.
        if cum[-1] - cum[picks[-1]] < spacing * 0.4 and len(picks) > 1:
            picks[-1] = len(poses) - 1
        else:
            picks.append(len(poses) - 1)
    return [Node(id=k, t=poses[i].t, x=poses[i].x, z=poses[i].z, yaw=poses[i].yaw) for k, i in enumerate(picks)]


@dataclass
class Spin:
    t0: float
    t1: float
    direction: int           # +1 turned right, -1 turned left
    node: int = -1


def detect_spins(poses: list[Pose], min_yaw_deg: float, max_move: float) -> list[Spin]:
    """Find look-around segments: lots of yaw change with little translation."""
    spins: list[Spin] = []
    n = len(poses)
    if n < 3:
        return spins
    yaw = np.unwrap(np.array([p.yaw for p in poses]))
    pos = np.array([[p.x, p.z] for p in poses])
    min_yaw = math.radians(min_yaw_deg)
    i = 0
    while i < n - 1:
        best = None
        for j in range(i + 1, n):
            if np.linalg.norm(pos[j] - pos[i]) > max_move:
                break
            dy = yaw[j] - yaw[i]
            if abs(dy) >= min_yaw:
                best = j
                # keep extending while still turning the same way
                if j + 1 < n and abs(yaw[j + 1] - yaw[i]) <= abs(dy):
                    break
        if best is not None:
            spins.append(Spin(t0=poses[i].t, t1=poses[best].t, direction=1 if yaw[best] > yaw[i] else -1))
            i = best + 1
        else:
            i += 1
    return spins


def detect_junctions(
    nodes: list[Node],
    dist_thr: float,
    min_gap: int,
    match_score: Optional[Callable[[int, int], int]] = None,
    strong: int = 60,
    weak: int = 25,
) -> list[tuple[int, int]]:
    """Pairs of nodes where the walker passed the same spot twice.

    A pair qualifies if positions are close and (when a visual matcher is given) images agree,
    or if images agree strongly regardless of position (handles odometry drift).
    Non-maximum suppression keeps one junction per crossing.
    """
    n = len(nodes)
    if n < min_gap + 1:
        return []
    pos = np.array([[q.x, q.z] for q in nodes])
    cands: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + min_gap, n):
            d = float(np.linalg.norm(pos[i] - pos[j]))
            close = d < dist_thr
            if match_score is None:
                if close:
                    cands[(i, j)] = dist_thr - d
                continue
            # Far apart by odometry: only a very strong visual match can override (handles drift).
            s = match_score(i, j)
            if (close and s >= weak) or s >= strong:
                cands[(i, j)] = s + (dist_thr - d if close else 0)
    keep = []
    for (i, j), s in cands.items():
        neighbourhood = [(i + a, j + b) for a in (-2, -1, 0, 1, 2) for b in (-2, -1, 0, 1, 2) if (a, b) != (0, 0)]
        if all(cands.get(k, -1e9) < s or (cands.get(k) == s and k > (i, j)) for k in neighbourhood):
            keep.append((i, j))
    return sorted(keep)


def build_graph(poses: list[Pose], cfg, match_score=None) -> tuple[Graph, list[Spin]]:
    nodes = build_nodes(poses, cfg.node_spacing_m)
    g = Graph(nodes=nodes)
    eid = 0

    def add(**kw):
        nonlocal eid
        g.edges.append(Edge(id=eid, **kw))
        eid += 1

    # Sequential edges: forward plays footage, back plays the pre-reversed version.
    for a, b in zip(nodes, nodes[1:]):
        heading = math.atan2(b.x - a.x, b.z - a.z)
        add(src=a.id, dst=b.id, kind="forward", action="forward", t0=a.t, t1=b.t, reverse=False,
            angle=wrap(heading - a.yaw))
        add(src=b.id, dst=a.id, kind="back", action="back", t0=a.t, t1=b.t, reverse=True,
            angle=wrap(heading + math.pi - b.yaw))

    # Junctions: jump to the other pass through the same spot. Arrow chosen from heading difference.
    for i, j in detect_junctions(nodes, cfg.junction_dist_m, cfg.junction_min_gap, match_score,
                                 cfg.junction_strong_matches, cfg.junction_weak_matches):
        for s, d in ((i, j), (j, i)):
            rel = wrap(nodes[d].yaw - nodes[s].yaw)
            add(src=s, dst=d, kind="junction", action=classify(rel), t0=nodes[d].t, t1=nodes[d].t,
                reverse=False, angle=rel)

    # Look-around: attach each spin to its nearest node; left/right plays the spin one way or the other.
    spins = detect_spins(poses, cfg.spin_min_yaw_deg, cfg.spin_max_move_m)
    for sp in spins:
        mid = (sp.t0 + sp.t1) / 2
        node = min(nodes, key=lambda q: abs(q.t - mid))
        sp.node = node.id
        add(src=node.id, dst=node.id, kind="look", action="right" if sp.direction > 0 else "left",
            t0=sp.t0, t1=sp.t1, reverse=False, angle=sp.direction * math.pi / 2)
        add(src=node.id, dst=node.id, kind="look", action="left" if sp.direction > 0 else "right",
            t0=sp.t0, t1=sp.t1, reverse=True, angle=-sp.direction * math.pi / 2)

    # Never offer two edges for the same arrow at one node: keep the best (sequential > junction > look).
    rank = {"forward": 0, "back": 0, "junction": 1, "look": 2}
    best: dict[tuple[int, str], Edge] = {}
    for e in g.edges:
        k = (e.src, e.action)
        if k not in best or rank[e.kind] < rank[best[k].kind]:
            best[k] = e
    g.edges = sorted(best.values(), key=lambda e: e.id)
    return g, spins


def shortest_path(g: Graph, src: int, dst: int) -> list[int]:
    """BFS over edge ids (used by auto-walk)."""
    from collections import deque
    out: dict[int, list[Edge]] = {}
    for e in g.edges:
        if e.kind != "look":
            out.setdefault(e.src, []).append(e)
    prev: dict[int, Edge] = {}
    q, seen = deque([src]), {src}
    while q:
        u = q.popleft()
        if u == dst:
            break
        for e in out.get(u, []):
            if e.dst not in seen:
                seen.add(e.dst)
                prev[e.dst] = e
                q.append(e.dst)
    if dst not in seen:
        return []
    path, u = [], dst
    while u != src:
        path.append(prev[u].id)
        u = prev[u].src
    return path[::-1]
