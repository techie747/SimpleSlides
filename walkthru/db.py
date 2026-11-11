"""Tiny SQLite store (tours + jobs). Swappable for Supabase Postgres: same columns as the spec."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .config import CONFIG

_lock = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS tours(
  id TEXT PRIMARY KEY, title TEXT, slug TEXT UNIQUE, status TEXT, input_type TEXT,
  original_name TEXT, ext TEXT, size INTEGER, received INTEGER DEFAULT 0,
  start_node_id INTEGER, branding TEXT DEFAULT '{}', is_public INTEGER DEFAULT 1, created_at REAL);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, tour_id TEXT, stage TEXT, stage_index INTEGER DEFAULT 0, progress REAL DEFAULT 0,
  log TEXT DEFAULT '', error TEXT, tip TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS views(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tour_id TEXT, session_id TEXT, node_id INTEGER, event TEXT, created_at REAL);
"""


def conn() -> sqlite3.Connection:
    CONFIG.data_dir.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(CONFIG.data_dir / "walkthru.db", check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, conn() as c:
        c.executescript(SCHEMA)


def q(sql, args=(), one=False):
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def create_tour(title, name, ext, size):
    tid = uuid.uuid4().hex[:12]
    q("INSERT INTO tours(id,title,slug,status,original_name,ext,size,created_at) VALUES(?,?,?,?,?,?,?,?)",
      (tid, title, tid, "uploading", name, ext, size, time.time()))
    q("INSERT INTO jobs(id,tour_id,stage,created_at,updated_at) VALUES(?,?,?,?,?)",
      (tid, tid, "uploading", time.time(), time.time()))
    return tid


def tour_dir(tid: str) -> Path:
    d = CONFIG.data_dir / "tours" / tid
    d.mkdir(parents=True, exist_ok=True)
    return d


def update_job(tid, **kw):
    kw["updated_at"] = time.time()
    cols = ",".join(f"{k}=?" for k in kw)
    q(f"UPDATE jobs SET {cols} WHERE tour_id=?", (*kw.values(), tid))


def append_log(tid, line):
    q("UPDATE jobs SET log = log || ? WHERE tour_id=?", (line + "\n", tid))


def update_tour(tid, **kw):
    if "branding" in kw and not isinstance(kw["branding"], str):
        kw["branding"] = json.dumps(kw["branding"])
    cols = ",".join(f"{k}=?" for k in kw)
    q(f"UPDATE tours SET {cols} WHERE id=?", (*kw.values(), tid))
