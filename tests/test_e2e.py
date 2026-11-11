"""End-to-end: upload a synthetic walk video in chunks, process it, and check the tour."""
import os
import subprocess
import time

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["WALKTHRU_DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    import importlib
    import walkthru.config as c
    importlib.reload(c)
    import walkthru.db, walkthru.pipeline, walkthru.app
    for m in (walkthru.db, walkthru.pipeline, walkthru.app):
        importlib.reload(m)
    from fastapi.testclient import TestClient
    with TestClient(walkthru.app.app) as tc:
        yield tc


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    from tests.synth import make_video
    d = tmp_path_factory.mktemp("vid")
    raw = make_video(d / "raw.avi", ext_codec="MJPG")
    out = d / "hallway.mov"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-c:v", "libx264", str(out)], check=True)
    return out


def upload(client, path, chunk=256 * 1024):
    data = path.read_bytes()
    tid = client.post("/api/uploads", json={"name": path.name, "size": len(data)}).json()["id"]
    off = 0
    while off < len(data):
        off = client.put(f"/api/uploads/{tid}?offset={off}", content=data[off:off + chunk]).json()["received"]
    assert client.post(f"/api/uploads/{tid}/complete").json()["ok"]
    return tid


def wait(client, tid, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        t = client.get(f"/api/tours/{tid}").json()
        if t["status"] in ("ready", "failed"):
            return t
        time.sleep(0.5)
    raise TimeoutError


def test_rejects_unknown_format(client):
    r = client.post("/api/uploads", json={"name": "notes.txt", "size": 10})
    assert r.status_code == 400 and "supported" in r.json()["detail"]


@pytest.mark.parametrize("ext", [".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpeg", ".mpg", ".3gp"])
def test_all_formats_accepted(client, ext):
    assert client.post("/api/uploads", json={"name": f"a{ext}", "size": 10}).status_code == 200


def test_full_pipeline(client, video):
    tid = upload(client, video)
    t = wait(client, tid)
    assert t["status"] == "ready", t["job"]
    g = client.get(f"/api/tours/{tid}/graph").json()
    assert len(g["nodes"]) >= 4
    kinds = {e["kind"] for e in g["edges"]}
    assert {"forward", "back"} <= kinds
    assert "look" in kinds, t["job"]["log"]           # the synthetic spin should be detected
    for e in g["edges"]:
        if e["clip"]:
            assert client.get(f"/media/{tid}/{e['clip']}").status_code == 200
    assert client.get(f"/t/{tid}").status_code == 200
    assert client.patch(f"/api/tours/{tid}", json={"rooms": {"0": "Hallway"}, "start_node": 1}).json()["ok"]
    g = client.get(f"/api/tours/{tid}/graph").json()
    assert g["start_node"] == 1 and g["nodes"][0]["room"] == "Hallway"


def test_resume_upload(client, video):
    data = video.read_bytes()
    tid = client.post("/api/uploads", json={"name": "x.mp4", "size": len(data)}).json()["id"]
    client.put(f"/api/uploads/{tid}?offset=0", content=data[:1000])
    assert client.get(f"/api/uploads/{tid}").json()["received"] == 1000
    r = client.put(f"/api/uploads/{tid}?offset=0", content=data[:10])   # stale offset → told where to resume
    assert r.status_code == 409 and r.json()["received"] == 1000
