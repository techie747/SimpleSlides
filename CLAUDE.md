# WalkThru — project context for Claude Code

Turns a walk-through video (.mp4 .mov .webm .mkv .avi .m4v .mpeg/.mpg .3gp) into an interactive tour
with Forward / Back / Turn Left / Turn Right navigation over real footage.

## Layout
- `walkthru/app.py` FastAPI app: resumable chunked upload API, tour API, static pages, in-process job worker
- `walkthru/pipeline.py` stages: checking → frames → mapping → paths → encoding → ready
- `walkthru/media.py` ffmpeg/ffprobe helpers · `walkthru/poses.py` ORB visual odometry
- `walkthru/graph.py` Path Graph (nodes, forward/back, junctions, look-around spins) — pure numpy, unit-tested
- `walkthru/config.py` every tunable value (override with `WALKTHRU_<NAME>` env vars)
- `web/` creator page (`index.html`, `home.js`), viewer (`viewer.html`, `viewer.js`), filming guide
- `tests/` graph unit tests + end-to-end test on a synthetic video (`tests/synth.py`)

## Commands
- Run: `uvicorn walkthru.app:app --reload --port 8000` → http://localhost:8000 (needs ffmpeg)
- Test: `pytest -q`
- Docker: `docker compose up`

## How to work
- Read `PROGRESS.md` first; update it after each change (done / next / known limitations).
- Algorithm choices go in `config.py` with an explained default.
- Never fake results: if mapping fails, surface it with a friendly message + fix tip.
- Ask before adding any paid third-party service.
- Design: dark UI (#0E0F12), accent #4F8CFF, Inter/Raleway, 12px radius, 44px tap targets, one primary action per screen.
