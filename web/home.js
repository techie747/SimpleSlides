const CHUNK = 8 * 1024 * 1024;
const STAGE_LABEL = { uploading: "Uploading", checking: "Checking video", frames: "Extracting frames",
  mapping: "Mapping the space", paths: "Building walk paths", encoding: "Preparing smooth playback", ready: "Ready ✨" };
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} }, del(k) { try { localStorage.removeItem(k); } catch {} } };
const local = {}; // tid -> local upload progress

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok && r.status !== 409) throw new Error(body.detail || "Request failed");
  return { status: r.status, ...body };
}

// ---------- upload ----------
const drop = $("#drop"), input = $("#file");
drop.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && input.click());
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => [...e.dataTransfer.files].forEach(upload));
input.addEventListener("change", () => { [...input.files].forEach(upload); input.value = ""; });

async function upload(file) {
  const key = `wt-upload:${file.name}:${file.size}:${file.lastModified}`;
  let tid = store.get(key), received = 0;
  try {
    if (tid) {
      const s = await api(`/api/uploads/${tid}`).catch(() => null);
      if (s && s.size === file.size) received = s.received; else tid = null;
    }
    if (!tid) {
      tid = (await api("/api/uploads", { method: "POST", body: JSON.stringify({ name: file.name, size: file.size }) })).id;
      store.set(key, tid);
    }
    refresh();
    while (received < file.size) {
      const part = file.slice(received, received + CHUNK);
      let tries = 0, r;
      for (;;) {
        try {
          r = await fetch(`/api/uploads/${tid}?offset=${received}`, { method: "PUT", body: part });
          if (r.ok || r.status === 409) break;
          throw new Error();
        } catch { if (++tries > 5) throw new Error("Network dropped — drop the same file again to resume."); await new Promise((ok) => setTimeout(ok, 1000 * 2 ** tries)); }
      }
      received = (await r.json()).received;
      local[tid] = (100 * received) / file.size;
      paintProgress(tid);
    }
    await api(`/api/uploads/${tid}/complete`, { method: "POST" });
    store.del(key);
    delete local[tid];
    refresh();
  } catch (err) {
    toast(err.message);
  }
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "card"; t.style.cssText = "position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:20;padding:12px 18px";
  t.textContent = msg; document.body.append(t); setTimeout(() => t.remove(), 5000);
}

// ---------- tour list ----------
let tours = [];
async function refresh() {
  tours = await api("/api/tours").then((r) => Object.values(r).filter((x) => typeof x === "object")).catch(() => tours);
  render();
  if (tours.some((t) => t.status === "processing" || t.status === "uploading")) setTimeout(refresh, 1000);
}

function steps(t) {
  const names = Object.keys(STAGE_LABEL);
  const idx = t.stage_index || 0;
  const pct = t.status === "uploading" ? (local[t.id] ?? t.progress) : t.progress;
  return `<div class="steps">${names.slice(0, -1).map((_, i) =>
    `<i class="${t.status === "ready" || i < idx ? "done" : i === idx ? "now" : ""}">${i === idx && t.status !== "ready" ? `<b style="width:${pct || 0}%"></b>` : ""}</i>`).join("")}</div>`;
}

function render() {
  const el = $("#tours");
  if (!tours.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<h2>Your tours</h2>` + tours.map((t) => {
    const link = `${location.origin}/t/${t.id}`;
    let status;
    if (t.status === "ready") status = `<span class="ok">Ready</span> · ${t.views} visitor${t.views === 1 ? "" : "s"}`;
    else if (t.status === "failed") status = `<span class="bad">${esc(t.error)}</span><br><span class="muted">💡 ${esc(t.tip)}</span>`;
    else status = `<span data-stage="${t.id}">${STAGE_LABEL[t.stage] || "Working"}…</span>${steps(t)}`;
    return `<article class="card tour" id="t-${t.id}">
      <div class="thumb" style="${t.status === "ready" ? `background-image:url(/media/${t.id}/stills/${t.start_node_id || 0}.jpg)` : ""}"></div>
      <div><h3>${esc(t.title)}</h3><div class="muted">${status}</div></div>
      <div class="actions">${t.status === "ready" ? `
        <a class="btn primary" href="/t/${t.id}" target="_blank">Open tour</a>
        <button data-copy="${link}">Copy link</button>
        <button data-edit="${t.id}">Edit</button>` : ""}
        <button data-del="${t.id}" aria-label="Delete tour" title="Delete">🗑</button></div></article>`;
  }).join("");
}

function paintProgress(tid) {
  const b = document.querySelector(`#t-${tid} .steps i.now b`);
  if (b) b.style.width = `${local[tid]}%`;
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.copy) { await navigator.clipboard?.writeText(b.dataset.copy); b.textContent = "Copied ✓"; setTimeout(() => (b.textContent = "Copy link"), 1500); }
  if (b.dataset.del && confirm("Delete this tour for good?")) { await api(`/api/tours/${b.dataset.del}`, { method: "DELETE" }); refresh(); }
  if (b.dataset.edit) openEditor(b.dataset.edit);
});

// ---------- editor ----------
async function openEditor(tid) {
  const g = await api(`/api/tours/${tid}/graph`);
  const modal = $("#editor");
  const rooms = {}; g.nodes.forEach((n) => n.room && (rooms[n.id] = n.room));
  let start = g.start_node;
  const brand = g.branding || {};
  const link = `${location.origin}/t/${tid}`;
  const embed = `<iframe src="${location.origin}/embed/${tid}" width="100%" height="560" style="border:0;border-radius:12px" allow="fullscreen; xr-spatial-tracking" allowfullscreen></iframe>`;
  modal.innerHTML = `<div class="card" role="dialog" aria-modal="true" aria-label="Edit tour">
    <h2>Edit tour</h2>
    <div class="row"><label class="muted">Title</label><input id="e-title" value="${esc(g.title)}"></div>
    <div class="row"><label class="muted">Tap a spot to make it the start (green). Name spots to label rooms — visitors can tap a room to walk there.</label>
      <div class="rooms">${g.nodes.map((n) => `<div class="room ${n.id === start ? "start" : ""}" data-node="${n.id}">
        <img loading="lazy" src="${g.media}stills/${n.id}.jpg" alt="Spot ${n.id + 1}"><input placeholder="Room name" data-room="${n.id}" value="${esc(rooms[n.id] || "")}"></div>`).join("")}</div></div>
    <div class="row"><label class="muted">Brand name &amp; accent color</label>
      <div style="display:flex;gap:8px"><input id="e-brand" placeholder="Your company" value="${esc(brand.name || "")}"><input id="e-color" type="color" value="${brand.color || "#4F8CFF"}" style="width:64px;padding:4px"></div></div>
    <div class="row"><label class="muted">Share link</label><code class="box">${esc(link)}</code></div>
    <div class="row"><label class="muted">Embed on your site</label><code class="box">${esc(embed)}</code></div>
    ${g.notes?.length ? `<p class="muted">✂ ${g.notes.map(esc).join("<br>✂ ")}</p>` : ""}
    ${g.warnings?.length ? `<p class="muted">⚠ ${g.warnings.map(esc).join("<br>⚠ ")}</p>` : ""}
    <div class="actions" style="justify-content:flex-end"><button id="e-cancel">Cancel</button><button class="primary" id="e-save">Save</button></div></div>`;
  modal.hidden = false;
  modal.onclick = (e) => {
    const r = e.target.closest(".room");
    if (r && e.target.tagName !== "INPUT") { start = +r.dataset.node; modal.querySelectorAll(".room").forEach((x) => x.classList.toggle("start", +x.dataset.node === start)); }
    if (e.target === modal || e.target.id === "e-cancel") modal.hidden = true;
  };
  $("#e-save").onclick = async () => {
    // Labelling one spot labels everything after it until the next named spot.
    const named = {}; modal.querySelectorAll("[data-room]").forEach((i) => i.value.trim() && (named[i.dataset.room] = i.value.trim()));
    await api(`/api/tours/${tid}`, { method: "PATCH", body: JSON.stringify({
      title: $("#e-title").value, start_node: start, rooms: named,
      branding: { name: $("#e-brand").value.trim(), color: $("#e-color").value } }) });
    modal.hidden = true; refresh();
  };
}

refresh();
