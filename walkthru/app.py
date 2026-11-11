"""WalkThru web app: upload API, tour API, static UI, and an in-process job worker."""
from __future__ import annotations

import json
import queue
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, pipeline
from .config import CONFIG

WEB = Path(__file__).resolve().parent.parent / "web"
jobs: "queue.Queue[str]" = queue.Queue()


def worker():
    while True:
        tid = jobs.get()
        try:
            pipeline.process(tid)
        finally:
            jobs.task_done()


@asynccontextmanager
async def lifespan(_app):
    db.init()
    # Resume anything that was mid-processing when the server stopped.
    for t in db.q("SELECT id FROM tours WHERE status='processing'"):
        jobs.put(t["id"])
    threading.Thread(target=worker, daemon=True).start()
    yield


app = FastAPI(title="WalkThru", lifespan=lifespan)


# ---------- uploads (resumable, chunked) ----------
class NewUpload(BaseModel):
    name: str
    size: int
    title: str | None = None


@app.post("/api/uploads")
def new_upload(u: NewUpload):
    ext = Path(u.name).suffix.lower()
    if ext not in CONFIG.allowed_ext:
        raise HTTPException(400, f"{ext or 'This file type'} isn't supported. Use MP4, MOV, WebM, MKV, AVI, M4V, MPEG or 3GP.")
    if u.size > CONFIG.max_upload_bytes:
        raise HTTPException(400, "That file is over 4 GB. Trim it or export at a lower resolution.")
    title = (u.title or Path(u.name).stem.replace("_", " ").replace("-", " ")).strip()[:80] or "My tour"
    tid = db.create_tour(title, u.name, ext, u.size)
    return {"id": tid, "received": 0}


def _tour(tid):
    t = db.q("SELECT * FROM tours WHERE id=?", (tid,), one=True)
    if not t:
        raise HTTPException(404, "Tour not found")
    return t


@app.get("/api/uploads/{tid}")
def upload_status(tid: str):
    t = _tour(tid)
    return {"id": tid, "received": t["received"], "size": t["size"]}


@app.put("/api/uploads/{tid}")
async def upload_chunk(tid: str, request: Request, offset: int):
    t = _tour(tid)
    if t["status"] != "uploading":
        raise HTTPException(409, "Upload already finished")
    if offset != t["received"]:
        return JSONResponse({"received": t["received"]}, status_code=409)
    path = db.tour_dir(tid) / f"original{t['ext']}"
    n = 0
    with open(path, "r+b" if path.exists() else "wb") as f:
        f.seek(offset)
        f.truncate()
        async for chunk in request.stream():
            f.write(chunk)
            n += len(chunk)
    received = offset + n
    if received > t["size"]:
        raise HTTPException(400, "More data than expected")
    db.update_tour(tid, received=received)
    db.update_job(tid, progress=100 * received / max(1, t["size"]))
    return {"received": received}


@app.post("/api/uploads/{tid}/complete")
def upload_complete(tid: str):
    t = _tour(tid)
    if t["received"] != t["size"]:
        raise HTTPException(400, "Upload is incomplete")
    if t["status"] == "uploading":
        db.update_tour(tid, status="processing")
        db.update_job(tid, stage="checking", stage_index=1, progress=0)
        jobs.put(tid)
    return {"ok": True}


# ---------- tours ----------
def _edits(tid) -> dict:
    p = db.tour_dir(tid) / "edits.json"
    return json.loads(p.read_text()) if p.exists() else {}


@app.get("/api/tours")
def list_tours():
    rows = db.q("SELECT t.*, j.stage, j.stage_index, j.progress, j.error, j.tip FROM tours t "
                "LEFT JOIN jobs j ON j.tour_id=t.id ORDER BY t.created_at DESC")
    for r in rows:
        r["branding"] = json.loads(r["branding"] or "{}")
        r["views"] = db.q("SELECT COUNT(DISTINCT session_id) n FROM views WHERE tour_id=?", (r["id"],), one=True)["n"]
    return rows


@app.get("/api/tours/{tid}")
def get_tour(tid: str):
    t = _tour(tid)
    t["branding"] = json.loads(t["branding"] or "{}")
    t["job"] = db.q("SELECT stage, stage_index, progress, error, tip, log FROM jobs WHERE tour_id=?", (tid,), one=True)
    t["stages"] = pipeline.STAGES
    return t


@app.get("/api/tours/{tid}/graph")
def get_graph(tid: str):
    t = _tour(tid)
    p = db.tour_dir(tid) / "tour.json"
    if t["status"] != "ready" or not p.exists():
        raise HTTPException(404, "Tour is not ready yet")
    g = json.loads(p.read_text())
    e = _edits(tid)
    g["title"] = t["title"]
    g["branding"] = json.loads(t["branding"] or "{}")
    g["start_node"] = e.get("start_node", g["start_node"])
    rooms = e.get("rooms", {})
    for n in g["nodes"]:
        n["room"] = rooms.get(str(n["id"]))
    g["hotspots"] = e.get("hotspots", [])
    g["media"] = f"/media/{tid}/"
    return g


class Patch(BaseModel):
    title: str | None = None
    start_node: int | None = None
    rooms: dict[str, str] | None = None
    hotspots: list[dict] | None = None
    branding: dict | None = None


@app.patch("/api/tours/{tid}")
def patch_tour(tid: str, p: Patch):
    _tour(tid)
    if p.title is not None:
        db.update_tour(tid, title=p.title.strip()[:80] or "My tour")
    if p.branding is not None:
        db.update_tour(tid, branding=p.branding)
    e = _edits(tid)
    for k in ("start_node", "rooms", "hotspots"):
        v = getattr(p, k)
        if v is not None:
            e[k] = v
    (db.tour_dir(tid) / "edits.json").write_text(json.dumps(e))
    return {"ok": True}


@app.delete("/api/tours/{tid}")
def delete_tour(tid: str):
    _tour(tid)
    db.q("DELETE FROM tours WHERE id=?", (tid,))
    db.q("DELETE FROM jobs WHERE tour_id=?", (tid,))
    db.q("DELETE FROM views WHERE tour_id=?", (tid,))
    shutil.rmtree(db.tour_dir(tid), ignore_errors=True)
    return {"ok": True}


class View(BaseModel):
    session_id: str
    node_id: int | None = None
    event: str


@app.post("/api/tours/{tid}/views")
def add_view(tid: str, v: View):
    import time
    db.q("INSERT INTO views(tour_id,session_id,node_id,event,created_at) VALUES(?,?,?,?,?)",
         (tid, v.session_id[:64], v.node_id, v.event[:32], time.time()))
    return {"ok": True}


# ---------- pages & media ----------
CONFIG.data_dir.mkdir(parents=True, exist_ok=True)
(CONFIG.data_dir / "tours").mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=CONFIG.data_dir / "tours"), name="media")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def home():
    return FileResponse(WEB / "index.html")


@app.get("/help")
def help_page():
    return FileResponse(WEB / "help.html")


@app.get("/t/{tid}")
@app.get("/embed/{tid}")
def viewer(tid: str):
    return FileResponse(WEB / "viewer.html")
