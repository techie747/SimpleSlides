# Progress

## Done
- **Phase 1 – Skeleton & upload:** FastAPI app, resumable chunked upload (≤4 GB, all 9 extensions), SQLite `tours`/`jobs`/`views`, in-process worker with live stage progress, friendly failure messages + fix tips.
- **Phase 2 – Path Graph MVP:** frame sampling + blur filter, ORB visual odometry, node spacing, forward + pre-reversed clips, viewer with preloading and no-black-frame transitions.
- **Phase 3 (partial):** junction detection (position + ORB verification, NMS), spin/look-around detection, 360° sphere viewer (Three.js) with drag-to-look, floor chevrons, minimap with heading cone.
- **Phase 4 (partial):** editor (title, start point, room labels, brand name/colour), share link, iframe embed, visitor counts, room auto-walk (BFS), guided walk.
- Local setup verified on macOS (Python 3.12 venv in `.venv/`, Homebrew ffmpeg): 20/20 tests pass, app serves on :8000.
- **Selfie removal:** flat videos are scanned for stretches where the camera faces the person filming (YuNet face detector, bundled, MIT); those parts plus 0.5 s padding are cut before mapping, and the editor lists what was removed. Tunables `selfie_*` in `config.py`; turn off with `WALKTHRU_SELFIE_REMOVE=0`. 10 tests in `tests/test_selfie.py`.
- Tests: 8 graph unit tests on synthetic camera paths; end-to-end test renders a synthetic corridor video, uploads it in chunks and checks the finished tour.

## Next
1. pycolmap sequential SfM as primary pose source (VO stays as per-segment fallback).
2. Supabase (Postgres + Auth + Storage/TUS + Realtime) and Next.js front end; Vercel + container worker. Needs your accounts.
3. Hotspots (info/link/image), scale from one known measurement, trim ends.
4. HLS segments for long tours; analytics dashboard.
5. Phase 5 Gaussian-splat mode (GPU worker) and Phase 6 plan limits / Stripe stub — will ask before adding paid services.

## Known limitations
- Selfie removal: a cut joins two separate stretches of footage, so tracking may briefly break at the seam. A selfie with the face mostly out of frame (or filmed far away) may not be caught. A walk-through where someone stands close to the camera for over a second may be cut by mistake.
- Monocular VO has no true scale (assumes 0.8 m/s walking) and drifts on long videos; junctions rely on visual matching to compensate.
- Walking backwards while filming may be read as forward motion.
- No authentication yet: anyone with the server URL can upload; media folder is public.
- Flat-video Left/Right only exist where you spun in place or crossed a path (by design: no dead-end arrows).
