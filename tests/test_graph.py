import math
from types import SimpleNamespace

from walkthru.config import Config
from walkthru.graph import Pose, build_graph, build_nodes, classify, detect_junctions, detect_spins, shortest_path

CFG = Config()


def line(n=100, speed=0.1, yaw=0.0, x0=0.0, z0=0.0, t0=0.0):
    return [Pose(t=t0 + i * 0.2, x=x0 + math.sin(yaw) * i * speed, z=z0 + math.cos(yaw) * i * speed, yaw=yaw) for i in range(n)]


def test_node_spacing():
    nodes = build_nodes(line(100, 0.1), 0.75)       # 9.9 m of travel
    gaps = [math.dist((a.x, a.z), (b.x, b.z)) for a, b in zip(nodes, nodes[1:])]
    assert 12 <= len(nodes) <= 15
    assert all(0.7 <= g <= 1.2 for g in gaps)
    assert nodes[0].t == 0 and nodes[-1].t == line(100)[-1].t


def test_standing_still_gives_two_nodes_at_most():
    still = [Pose(t=i * 0.2, x=0, z=0, yaw=0) for i in range(30)]
    assert len(build_nodes(still, 0.75)) <= 2


def test_sequential_edges_and_directions():
    g, _ = build_graph(line(50, 0.1), CFG)
    fwd = [e for e in g.edges if e.kind == "forward"]
    back = [e for e in g.edges if e.kind == "back"]
    assert len(fwd) == len(back) == len(g.nodes) - 1
    assert all(classify(e.angle) == "forward" for e in fwd)
    assert all(e.reverse for e in back) and not any(e.reverse for e in fwd)
    assert all(e.t1 > e.t0 for e in fwd)


def test_junction_on_loop():
    # Walk a 4x4 m square loop and continue a bit: start and end pass the same spot.
    pts, t = [], 0.0
    for side in range(4):
        yaw = side * math.pi / 2
        for i in range(40):
            last = pts[-1] if pts else Pose(0, 0, 0, 0)
            pts.append(Pose(t=t, x=last.x + math.sin(yaw) * 0.1, z=last.z + math.cos(yaw) * 0.1, yaw=yaw))
            t += 0.2
    nodes = build_nodes(pts, 0.75)
    j = detect_junctions(nodes, 0.6, 4)
    assert len(j) == 1
    i, k = j[0]
    assert k - i >= 4


def test_junction_needs_visual_match_when_matcher_given():
    nodes = build_nodes(line(30, 0.1) + line(30, 0.1, yaw=math.pi, z0=2.9, t0=6), 0.75)
    assert detect_junctions(nodes, 0.6, 4, match_score=lambda i, j: 0) == []
    assert detect_junctions(nodes, 0.6, 4, match_score=lambda i, j: 100)


def test_junction_edges_get_turn_arrows():
    # Corridor along z, then a pass that crosses it heading +x (a T-junction crossing).
    a = line(60, 0.1)                                              # 0..5.9 m along z
    b = line(60, 0.1, yaw=math.pi / 2, x0=-3, z0=3.0, t0=20)       # crosses x=0 at z=3
    g, _ = build_graph(a + b, SimpleNamespace(**{**CFG.__dict__, "junction_min_gap": 4}))
    jn = [e for e in g.edges if e.kind == "junction"]
    assert jn, "crossing should create a junction"
    assert {e.action for e in jn} & {"left", "right"}
    # one edge per arrow per node
    keys = [(e.src, e.action) for e in g.edges]
    assert len(keys) == len(set(keys))


def test_spin_detection_and_look_edges():
    walk = line(20, 0.1)
    spin = [Pose(t=4 + i * 0.2, x=walk[-1].x, z=walk[-1].z, yaw=i * 2 * math.pi / 20) for i in range(21)]
    spins = detect_spins(walk + spin, 150, 0.8)
    assert len(spins) == 1 and spins[0].direction == 1
    g, _ = build_graph(walk + spin + line(20, 0.1, z0=walk[-1].z, t0=9), CFG)
    look = [e for e in g.edges if e.kind == "look"]
    assert {e.action for e in look} == {"left", "right"}


def test_shortest_path():
    g, _ = build_graph(line(50, 0.1), CFG)
    p = shortest_path(g, 0, len(g.nodes) - 1)
    assert len(p) == len(g.nodes) - 1
