# Progress

## Done
- **Phase 1 – Skeleton & upload:** FastAPI app, resumable chunked upload (≤4 GB, all 9 extensions), SQLite `tours`/`jobs`/`views`, in-process worker with live stage progress, friendly failure messages + fix tips.
- **Phase 2 – Path Graph MVP:** frame sampling + blur filter, ORB visual odometry, node spacing, forward + pre-reversed clips, viewer with preloading and no-black-frame transitions.
- **Phase 3 (partial):** junction detection (position + ORB verification, NMS), spin/look-around detection, 360° sphere viewer (Three.js) with drag-to-look, floor chevrons, minimap with heading cone.
- **Phase 4 (partial):** editor (title, start point, room labels, brand name/colour), share link, iframe embed, visitor counts, room auto-walk (BFS), guided walk.
- Tests: 8 graph unit tests on synthetic camera paths; end-to-end test renders a synthetic corridor video, uploads it in chunks and checks the finished tour.

## Next
1. pycolmap sequential SfM as primary pose source (VO stays as per-segment fallback).
2. Supabase (Postgres + Auth + Storage/TUS + Realtime) and Next.js front end; Vercel + container worker. Needs your accounts.
3. Hotspots (info/link/image), scale from one known measurement, trim ends.
4. HLS segments for long tours; analytics dashboard.
5. Phase 5 Gaussian-splat mode (GPU worker) and Phase 6 plan limits / Stripe stub — will ask before adding paid services.

## Known limitations
- Monocular VO has no true scale (assumes 0.8 m/s walking) and drifts on long videos; junctions rely on visual matching to compensate.
- Walking backwards while filming may be read as forward motion.
- No authentication yet: anyone with the server URL can upload; media folder is public.
- Flat-video Left/Right only exist where you spun in place or crossed a path (by design: no dead-end arrows).
