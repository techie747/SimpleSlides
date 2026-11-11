# WalkThru

Turn an ordinary walk-through video into an interactive tour. Visitors press **Forward / Back / Turn Left / Turn Right** and move through real footage — no free-fly confusion, no teleporting between photos.

**One upload in, one shareable link out.** Accepts every common video format:

| Format | Extensions | Typical source |
|---|---|---|
| MP4 | .mp4 | Universal |
| MOV | .mov | iPhone, pro cameras, Apple workflows |
| WebM | .webm | Browser recordings |
| MKV | .mkv | High-quality / screen captures |
| AVI | .avi | Legacy video |
| M4V | .m4v | Apple video |
| MPEG | .mpeg, .mpg | Legacy video |
| 3GP | .3gp | Older phones |

Everything is re-encoded to H.264 MP4 for playback, so visitors never need a special player. 2:1 equirectangular (360°) video is detected automatically and gets free look-around.

## Run it

```bash
docker compose up            # → http://localhost:8000
```

or without Docker (needs Python 3.11+ and ffmpeg):

```bash
pip install -r requirements.txt
uvicorn walkthru.app:app --port 8000
pytest -q                    # graph unit tests + end-to-end processing test
```

| Env var | Default | Meaning |
|---|---|---|
| `WALKTHRU_DATA_DIR` | `data` | uploads, clips, SQLite DB |
| `WALKTHRU_<SETTING>` | see `walkthru/config.py` | any algorithm setting, e.g. `WALKTHRU_NODE_SPACING_M=0.5` |

## How it works

1. **Upload** — resumable 8 MB chunks; drop the same file again after a network drop and it continues.
2. **Checking** — ffprobe (duration, fps, rotation, 360 detection), normalise to H.264.
3. **Frames** — sample 5 fps, drop blurry frames (variance of Laplacian vs. neighbours).
4. **Mapping** — ORB visual odometry; rotation-only fallback during spins; gaps reported, never hidden.
5. **Walk paths** — a node every 0.75 m; forward/back edges; junctions where you passed the same spot twice (position + visual match); look-around where you spun in place.
6. **Smooth playback** — a forward and a pre-reversed clip per edge with keyframes at every node, plus a still per node so there's never a black frame.

Viewer: double-buffered video, floor chevrons only where movement is possible, arrow keys/WASD, swipe, minimap with heading, tap a room to auto-walk there, guided walk, share + iframe embed, reduced-motion crossfade.

See `PROGRESS.md` for what's done, what's next, and known limitations.
