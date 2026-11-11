(() => {
  const $ = (s) => document.querySelector(s);
  const tid = location.pathname.split("/").filter(Boolean).pop();
  const embed = location.pathname.startsWith("/embed/");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const session = Math.random().toString(36).slice(2);
  const HFOV = 65 * Math.PI / 180;
  let g, cur, out = {}, moving = false, is360 = false, viewYaw = 0, three = null, guided = false;
  const cache = new Map();
  const deg = (r) => r * 180 / Math.PI;
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

  fetch(`/api/tours/${tid}/graph`).then((r) => {
    if (!r.ok) throw new Error("This tour isn't ready yet — check back in a minute.");
    return r.json();
  }).then(init).catch((e) => ($("#loading").textContent = e.message));

  function track(event, node) {
    fetch(`/api/tours/${tid}/views`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: session, node_id: node ?? null, event }) }).catch(() => {});
  }

  function init(data) {
    g = data;
    document.title = g.title;
    is360 = g.input_type === "360";
    // Rooms carry forward: a labelled spot names everything after it until the next label.
    let room = null;
    g.nodes.forEach((n) => { room = n.room || room; n.roomName = room; });
    const b = g.branding || {};
    if (b.color) document.documentElement.style.setProperty("--accent", b.color);
    $("#brand").textContent = b.name ? `${b.name} · WalkThru` : "Made with WalkThru";
    if (embed) $("#share").hidden = true;
    if (is360) setup360();
    goTo(g.start_node, true);
    track("open", g.start_node);
    drawRooms();
    bindInput();
  }

  // ---------- media ----------
  const url = (p) => g.media + p;
  function video(clip) {
    if (cache.has(clip)) return cache.get(clip);
    const v = document.createElement("video");
    Object.assign(v, { muted: true, playsInline: true, preload: "auto", src: url(clip) });
    v.setAttribute("playsinline", ""); v.setAttribute("aria-hidden", "true"); v.crossOrigin = "anonymous";
    $("#videos").append(v);
    cache.set(clip, v);
    if (cache.size > 16) { const [k, old] = cache.entries().next().value; if (!old.classList.contains("on")) { old.remove(); cache.delete(k); } }
    return v;
  }
  const preloadImg = (id) => { const i = new Image(); i.src = url(`stills/${id}.jpg`); };

  function setStill(id, fade) {
    const src = url(`stills/${id}.jpg`);
    if (is360) { three.setImage(src); return; }
    if (!fade) { $("#still").src = src; return; }
    const s2 = $("#still2"); s2.src = src; s2.style.opacity = 1;
    setTimeout(() => { $("#still").src = src; s2.style.opacity = 0; }, 320);
  }

  // ---------- navigation ----------
  function goTo(id, first) {
    cur = g.nodes[id];
    out = {};
    for (const e of g.edges) if (e.src === id) out[e.action] = e;
    if (first) setStill(id);
    for (const e of Object.values(out)) { if (e.clip) video(e.clip); preloadImg(e.dst); }
    const r = cur.roomName; $("#room").hidden = !r; $("#room").textContent = r || "";
    $("#loading").hidden = true;
    updateControls(); drawMap();
  }

  function edgeFor(action) {
    if (!is360) return out[action];
    // 360: left/right always rotate; forward/back pick the edge closest to where you're looking.
    if (action === "left" || action === "right") return { kind: "rotate", action };
    const want = action === "forward" ? viewYaw : wrap(viewYaw + Math.PI);
    let best = null, bd = Math.PI / 3;
    for (const e of g.edges) {
      if (e.src !== cur.id || e.kind === "look") continue;
      const d = Math.abs(wrap(e.angle - want));
      if (d < bd) { bd = d; best = e; }
    }
    return best;
  }

  function updateControls() {
    document.querySelectorAll(".bar [data-act]").forEach((b) => (b.disabled = !edgeFor(b.dataset.act)));
    const ch = $("#chevrons"); ch.innerHTML = "";
    const arrows = is360 ? g.edges.filter((e) => e.src === cur.id && e.kind !== "look") : Object.values(out).filter((e) => e.kind !== "look");
    for (const e of arrows) {
      const rel = wrap(e.angle - (is360 ? viewYaw : 0));
      if (Math.abs(rel) > HFOV / 2 + 0.2) continue;               // only arrows you can actually see
      const btn = document.createElement("button");
      btn.className = "chev"; btn.textContent = "↑";
      btn.setAttribute("aria-label", `Go ${e.action}`);
      btn.style.left = `${50 + (rel / HFOV) * 100}%`;
      btn.style.rotate = `${deg(rel) * 0.6}deg`;
      btn.onclick = (ev) => { ev.stopPropagation(); run(e); };
      ch.append(btn);
    }
  }

  function act(action) {
    const e = edgeFor(action);
    if (e) run(e);
  }

  function run(e) {
    if (moving) return;
    if (e.kind === "rotate") { rotate(e.action === "left" ? -Math.PI / 4 : Math.PI / 4); return; }
    moving = true; document.body.classList.add("moving");
    const finish = () => {
      moving = false; document.body.classList.remove("moving");
      if (is360 && e.kind === "junction") viewYaw = wrap(viewYaw - e.angle);
      goTo(e.dst); track("move", e.dst);
      if (pending.length) setTimeout(() => run(pending.shift()), 30);
      else if (guided) setTimeout(guideStep, 600);
    };
    if (!e.clip || reduced) { setStill(e.dst, true); setTimeout(finish, 340); return; }
    const v = video(e.clip);
    v.currentTime = 0;
    const show = () => {
      if (is360) three.setVideo(v);
      else { document.querySelectorAll("#videos video.on").forEach((x) => x !== v && x.classList.remove("on")); v.classList.add("on"); }
    };
    v.onplaying = show;
    v.onended = () => {
      v.onended = null;
      setStill(e.dst);                          // still is identical to the clip's last frame: no flash
      setTimeout(() => { if (!is360) v.classList.remove("on"); }, 60);
      finish();
    };
    v.play().catch(() => { setStill(e.dst, true); setTimeout(finish, 340); });
  }

  // ---------- auto-walk / guided ----------
  let pending = [];
  function walkTo(target) {
    const prev = new Map([[cur.id, null]]), q = [cur.id];
    while (q.length) {
      const u = q.shift(); if (u === target) break;
      for (const e of g.edges) if (e.src === u && e.kind !== "look" && !prev.has(e.dst)) { prev.set(e.dst, e); q.push(e.dst); }
    }
    if (!prev.has(target)) return;
    const path = []; for (let u = target; prev.get(u); u = prev.get(u).src) path.unshift(prev.get(u));
    pending = path; if (pending.length) run(pending.shift());
  }
  function guideStep() {
    if (!guided) return;
    const e = out.forward || out.right || out.left;
    if (e && e.kind !== "look") run(e); else { guided = false; $("#guided").textContent = "▶"; }
  }

  // ---------- 360 ----------
  function rotate(by) {
    if (!is360) return;
    const from = viewYaw, to = viewYaw + by, t0 = performance.now();
    const step = (t) => { const k = Math.min(1, (t - t0) / 350); viewYaw = wrap(from + (to - from) * (1 - (1 - k) ** 3)); three.look(); if (k < 1) requestAnimationFrame(step); else updateControls(); };
    requestAnimationFrame(step);
  }
  function setup360() {
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
    s.onload = () => {
      const T = window.THREE, el = $("#three");
      const renderer = new T.WebGLRenderer({ antialias: true }); renderer.setPixelRatio(Math.min(2, devicePixelRatio));
      el.append(renderer.domElement);
      const scene = new T.Scene(), cam = new T.PerspectiveCamera(75, 1, 0.1, 100);
      const geo = new T.SphereGeometry(10, 64, 32); geo.scale(-1, 1, 1);
      const mat = new T.MeshBasicMaterial(); scene.add(new T.Mesh(geo, mat));
      let pitch = 0, imgTex = null;
      const loader = new T.TextureLoader(); loader.crossOrigin = "anonymous";
      const size = () => { renderer.setSize(innerWidth, innerHeight); cam.aspect = innerWidth / innerHeight; cam.updateProjectionMatrix(); };
      addEventListener("resize", size); size();
      three = {
        look() { cam.rotation.order = "YXZ"; cam.rotation.y = -viewYaw - Math.PI / 2; cam.rotation.x = pitch; },
        setImage(src) { loader.load(src, (t) => { imgTex?.dispose(); imgTex = t; mat.map = t; mat.needsUpdate = true; }); },
        setVideo(v) { mat.map = new T.VideoTexture(v); mat.needsUpdate = true; },
        pitchBy(d) { pitch = Math.max(-1.2, Math.min(1.2, pitch + d)); },
      };
      $("#still").hidden = true;
      three.setImage(url(`stills/${cur.id}.jpg`)); three.look();
      renderer.setAnimationLoop(() => renderer.render(scene, cam));
    };
    document.head.append(s);
    three = { look() {}, setImage() {}, setVideo() {}, pitchBy() {} };
  }

  // ---------- map ----------
  function drawMap() {
    const c = $("#mapc"), x = c.getContext("2d"), P = g.path;
    const xs = P.map((p) => p[1]), zs = P.map((p) => p[2]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minZ = Math.min(...zs), maxZ = Math.max(...zs);
    const s = Math.min((c.width - 30) / (maxX - minX || 1), (c.height - 30) / (maxZ - minZ || 1));
    const tx = (px) => 15 + (px - minX) * s + ((c.width - 30) - (maxX - minX) * s) / 2;
    const tz = (pz) => c.height - 15 - (pz - minZ) * s - ((c.height - 30) - (maxZ - minZ) * s) / 2;
    x.clearRect(0, 0, c.width, c.height);
    x.strokeStyle = "rgba(154,160,166,.6)"; x.lineWidth = 2; x.beginPath();
    P.forEach((p, i) => (i ? x.lineTo(tx(p[1]), tz(p[2])) : x.moveTo(tx(p[1]), tz(p[2])))); x.stroke();
    x.fillStyle = "#5c6370"; g.nodes.forEach((n) => { x.beginPath(); x.arc(tx(n.x), tz(n.z), 2, 0, 7); x.fill(); });
    const yaw = cur.yaw + (is360 ? viewYaw : 0), cx = tx(cur.x), cz = tz(cur.z);
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    x.fillStyle = accent + "55"; x.beginPath(); x.moveTo(cx, cz);
    x.arc(cx, cz, 26, -Math.PI / 2 + yaw - 0.5, -Math.PI / 2 + yaw + 0.5); x.closePath(); x.fill();
    x.fillStyle = accent; x.beginPath(); x.arc(cx, cz, 6, 0, 7); x.fill(); x.strokeStyle = "#fff"; x.stroke();
  }
  function drawRooms() {
    const first = new Map(); g.nodes.forEach((n) => n.room && !first.has(n.room) && first.set(n.room, n.id));
    $("#roomlist").innerHTML = "";
    for (const [name, id] of first) {
      const b = document.createElement("button"); b.textContent = name; b.onclick = () => walkTo(id); $("#roomlist").append(b);
    }
  }

  // ---------- input ----------
  function bindInput() {
    document.querySelectorAll(".bar [data-act]").forEach((b) => (b.onclick = () => act(b.dataset.act)));
    const keys = { ArrowUp: "forward", w: "forward", ArrowDown: "back", s: "back", ArrowLeft: "left", a: "left", ArrowRight: "right", d: "right" };
    addEventListener("keydown", (e) => { const a = keys[e.key] || keys[e.key.toLowerCase?.()]; if (a) { e.preventDefault(); act(a); } });
    $("#mapbtn").onclick = () => $("#map").classList.toggle("hide");
    $("#fs").onclick = () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.());
    $("#share").onclick = async () => {
      const link = `${location.origin}/t/${tid}`;
      if (navigator.share) navigator.share({ title: g.title, url: link }).catch(() => {});
      else { await navigator.clipboard?.writeText(link); $("#share").textContent = "✓"; setTimeout(() => ($("#share").textContent = "⤴"), 1500); }
    };
    $("#guided").onclick = () => { guided = !guided; $("#guided").textContent = guided ? "⏸" : "▶"; if (guided) guideStep(); };
    // Swipe: horizontal turns, vertical walks. In 360 a drag looks around.
    let sx, sy, lx, ly, dragging = false;
    const st = $("#stage");
    st.addEventListener("pointerdown", (e) => { sx = lx = e.clientX; sy = ly = e.clientY; dragging = true; });
    st.addEventListener("pointermove", (e) => {
      if (!dragging || !is360) return;
      viewYaw = wrap(viewYaw - (e.clientX - lx) * 0.005); three.pitchBy((e.clientY - ly) * 0.004); three.look();
      lx = e.clientX; ly = e.clientY;
    });
    st.addEventListener("pointerup", (e) => {
      dragging = false;
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (is360) { updateControls(); drawMap(); if (Math.hypot(dx, dy) > 12) return; }
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 40) return;
      if (Math.abs(dx) > Math.abs(dy)) act(dx < 0 ? "right" : "left"); else act(dy < 0 ? "forward" : "back");
    });
  }
})();
