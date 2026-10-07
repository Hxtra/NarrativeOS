/* NarrativeOS Studio — the cutting room.
   A live window onto a NarrativeOS project. You point at something (a clip, or a stretch of the ruler), say what
   should change, and watch the Director do it: every step it shows is a step the server actually performed, with
   what it found. Nothing changes until you apply; applying re-renders the preview and you can follow the encoder.
   Plain JS on purpose: no build step, served by timeline_api_server.py. */
"use strict";

const $ = (id) => document.getElementById(id);
const S = {
  projects: [], pid: null, data: null, etag: "", sel: null, zoom: 40, fit: true, video: null,
  chats: {}, busy: false, ghost: null, flipFrom: null, changed: new Set(), seen: new Set(), firstFeed: true,
  ltab: "pipeline", waves: new Map(), lastJobKey: "", pollTimer: 0,
};
const GROUPS = [
  ["Research", ["INTAKE", "STYLE_LOCK", "DIRECTOR_STRATEGY", "QUOTE", "RESEARCH_WORKSPACE", "SOURCE_INGEST", "RESEARCH", "CLAIM_BUILD", "EVIDENCE_REVIEW", "CONTRADICTION_REVIEW"]],
  ["Script", ["OUTLINE", "SCRIPT", "NARRATION_ALIGNMENT", "BEAT_MAP"]],
  ["Director", ["SHOT_PLAN", "ASSET_ACQUISITION", "ASSET_ANALYSIS", "VISUAL_BENCHMARK", "ASSET_APPROVAL", "CONTINUITY_BIBLE", "EVIDENCE_LINKING"]],
  ["Edit", ["GRAPHICS", "TTS", "ALIGNMENT", "CAPTIONS", "TIMELINE", "TIMELINE_IR", "AUDIO_MIX"]],
  ["QA", ["EDITORIAL_ANALYSIS", "EDITORIAL_REPAIR", "COST_REVIEW", "VARIANT_BUILD", "THUMBNAIL", "PREVIEW_RENDER", "TECHNICAL_QA", "EDITORIAL_QA", "TARGETED_REVISION"]],
  ["Publish", ["FINAL_RENDER", "DELIVERY_REVIEW", "PUBLISH", "COMPLETE"]],
];
const LANE_H = { video: 66, overlay: 34, caption: 34, audio: 48 };   // comfortable heights
const LANE_MIN = { video: 44, overlay: 26, caption: 26, audio: 34 };  // still readable when space is short
const ICONS = {
  check: '<svg viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  warn: '<svg viewBox="0 0 16 16"><path d="M8 3.5v5.5M8 12v.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  x: '<svg viewBox="0 0 16 16"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  q: '<svg viewBox="0 0 16 16"><path d="M5.8 6a2.2 2.2 0 1 1 3 2C8.2 8.3 8 8.7 8 9.4M8 12v.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  dot: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="2.5" fill="currentColor"/></svg>',
  play: '<svg viewBox="0 0 16 16"><path d="M5 3l8 5-8 5z" fill="currentColor"/></svg>',
  pause: '<svg viewBox="0 0 16 16"><path d="M4.5 3h2.5v10H4.5zM9 3h2.5v10H9z" fill="currentColor"/></svg>',
  cursor: '<svg viewBox="0 0 16 16"><path d="M3.5 2.5l9 5-4 1.2-1.8 3.8z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  range: '<svg viewBox="0 0 16 16"><path d="M2.5 3v10M13.5 3v10M5 8h6M5 8l2-2M5 8l2 2M11 8l-2-2M11 8l-2 2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  text: '<svg viewBox="0 0 16 16"><path d="M3 4h10M8 4v9" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  wave: '<svg viewBox="0 0 16 16"><path d="M2 8h1.5M5 5v6M8 3v10M11 6v4M14 8h-.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  spark: '<svg viewBox="0 0 16 16"><path d="M8 1.8l1.5 3.9 3.9 1.5-3.9 1.5L8 12.6 6.5 8.7 2.6 7.2l3.9-1.5z" fill="currentColor"/></svg>',
  render: '<svg viewBox="0 0 16 16"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  undo: '<svg viewBox="0 0 16 16"><path d="M5.5 3.5L2.5 6.5l3 3M3 6.5h6.5a4 4 0 0 1 0 8H7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  fit: '<svg viewBox="0 0 16 16"><path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  jump: '<svg viewBox="0 0 16 16"><path d="M3 8h9M9 4.5L12.5 8 9 11.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  xfade: '<svg viewBox="0 0 16 16"><path d="M2 4l12 8M2 12l12-8" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  close: '<svg viewBox="0 0 16 16"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
};

// ───────────────────────────────────────────────────────────── helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.setAttribute("style", v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}
const put = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false).map((k) => (k instanceof Node ? k : document.createTextNode(String(k)))));
function icon(name) { const t = document.createElement("template"); t.innerHTML = ICONS[name].trim(); return t.content.firstChild; }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (t) => { t = Math.max(0, +t || 0); const m = Math.floor(t / 60); return `${String(m).padStart(2, "0")}:${(t - m * 60).toFixed(1).padStart(4, "0")}`; };
const secs = (t) => `${(+t).toFixed(2)} s`;
const dur = (it) => +it.timeline_out - +it.timeline_in;
const uid = () => Math.random().toString(36).slice(2, 10);
const enc = encodeURIComponent;
function ago(iso) {
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (!isFinite(s)) return "";
  if (s < 10) return "just now";
  if (s < 60) return `${Math.floor(s)} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : (d && (d.message + (d.errors ? ": " + d.errors.join("; ") : ""))) || r.statusText);
  }
  return body;
}
function toast(text, kind = "") {
  const t = h("div", { class: `toast ${kind}` }, h("i"), text);
  $("toasts").append(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 400); }, 3400);
}
const tracks = () => (S.data && S.data.timeline && S.data.timeline.tracks) || [];
const mainTrack = () => tracks().find((x) => x.kind === "video");
const mainItems = () => { const t = mainTrack(); return t ? [...t.items].sort((a, b) => a.timeline_in - b.timeline_in) : []; };
function findItem(id) { for (const t of tracks()) for (const it of t.items) if (it.id === id) return [t, it]; return [null, null]; }
// Thumbnails are cached by the browser; the key changes only when that item's picture or trim changes.
function thumbUrl(id, t) {
  const [, it] = findItem(id);
  const key = it ? hash(`${it.asset_id}|${it.source_in || 0}|${dur(it).toFixed(3)}`) : "x";
  return `/api/studio/${enc(S.pid)}/thumb/${enc(id)}?${t != null ? `t=${(+t).toFixed(2)}&` : ""}k=${key}`;
}
function hash(str) { let x = 2166136261; for (let i = 0; i < str.length; i++) { x ^= str.charCodeAt(i); x = Math.imul(x, 16777619); } return (x >>> 0).toString(36); }
const kindOf = (t) => (t.kind === "audio" ? t.role || "music" : t.kind);
function trackName(t) {
  if (t.kind === "video") return "Picture";
  if (t.kind === "overlay") return "Overlay · FX";
  if (t.kind === "caption") return "Text";
  return { narration: "Voiceover", music: "Music", sfx: "Sound FX", ambience: "Ambience", dialogue: "Dialogue" }[t.role] || t.id;
}
function itemName(t, it) {
  if (it.text != null) return it.text;
  const a = (S.data.assets || {})[it.asset_id] || {};
  return a.file || it.asset_id || it.id;
}
function positions() { const out = {}; for (const t of tracks()) for (const it of t.items) out[it.id] = [+it.timeline_in, +it.timeline_out]; return out; }
const total = () => (S.data && S.data.validation && S.data.validation.duration) || 0;

// ───────────────────────────────────────────────────────────── loading + live updates
async function loadProjects() {
  const r = await api("/api/studio/");
  S.projects = r.projects;
  const sel = $("projectSel");
  put(sel, r.projects.map((p) => h("option", { value: p.project_id }, p.project_id)));
  const want = new URLSearchParams(location.search).get("p");
  S.pid = want && r.projects.some((p) => p.project_id === want) ? want : (r.projects[0] || {}).project_id;
  if (S.pid) sel.value = S.pid;
  sel.onchange = () => {
    S.pid = sel.value; S.sel = null; S.etag = ""; S.fit = true; S.ghost = null; S.seen.clear(); S.firstFeed = true; S.waves.clear();
    history.replaceState(null, "", `?p=${enc(S.pid)}`); load();
  };
  if (!S.pid) {
    $("pname").textContent = "No projects";
    put($("screen"), h("div", { class: "empty-screen" }, h("div", { class: "big" }, "No projects ", h("em", {}, "yet")), h("p", {}, `Point run_studio.py at a folder of NarrativeOS projects. Looking in: ${r.root}`)));
  }
}

async function load() {
  if (!S.pid) return;
  try {
    const d = await api(`/api/studio/${enc(S.pid)}`);
    if (S.data && Math.abs(((S.data.validation || {}).duration || 0) - ((d.validation || {}).duration || 0)) > 1e-3) S.fit = true;  // the edit changed length: refit
    S.data = d; S.etag = d.etag;
    setLive(true);
    if (S.fit) fitZoom();
    restoreGhost();
    renderAll();
  } catch (e) { console.error("Studio load failed", e); setLive(false, e.message); toast(`Couldn't load the project: ${e.message}`, "bad"); }
}
function jobActive(j) { return j && (j.state === "queued" || j.state === "rendering"); }
async function poll() {
  clearTimeout(S.pollTimer);
  if (S.pid) {
    try {
      const r = await api(`/api/studio/${enc(S.pid)}/poll?etag=${S.etag}`);
      setLive(true);
      if (S.data) { S.data.job = r.job; onJob(r.job); }
      if (r.changed) await load();
    } catch (e) { setLive(false, e.message); }
  }
  const fast = S.data && (jobActive(S.data.job) || S.busy);
  S.pollTimer = setTimeout(poll, fast ? 350 : 1500);
}
function setLive(ok, why) {
  const el = $("live");
  el.classList.toggle("off", !ok);
  $("liveText").textContent = ok ? "Live" : "Offline";
  el.title = ok ? "Watching the project: updates appear as they happen" : `Can't reach the Studio server: ${why || ""}`;
  if (ok) { el.classList.remove("blip"); void el.offsetWidth; el.classList.add("blip"); }
}
function renderAll() {
  renderTop(); renderLeft(); renderFeed(); renderPlayer(); renderHud(); renderShots(); renderScrubCuts();
  renderFocus(); renderChips(); renderChat(); renderTimeline(); renderDirectorStatus();
}

// ───────────────────────────────────────────────────────────── top bar
function stageStatus(name) {
  const p = S.data.pipeline;
  if (!p.present) return "pending";
  const n = p.nodes.find((x) => x.stage === name);
  return n ? n.status : "pending";
}
function groupState(stages) {
  const st = stages.map(stageStatus);
  if (st.includes("blocked")) return "bad";
  if (st.includes("current")) return "cur";
  if (st.includes("stale")) return "stale";
  if (st.every((s) => s === "passed")) return "done";
  return "";
}
function renderTop() {
  const d = S.data;
  $("pname").textContent = d.name;
  document.title = `${d.name} · NarrativeOS Studio`;
  const c = d.timeline && d.timeline.canvas;
  $("pmeta").textContent = [fmt(d.stats.duration), `${d.stats.clips} shots`, c ? `${c.width}×${c.height}` : null, c ? `${c.fps} fps` : null].filter(Boolean).join(" · ");
  put($("rail"), GROUPS.map(([g, stages]) => {
    const passed = stages.map(stageStatus).filter((s) => s === "passed").length;
    const st = d.pipeline.present ? groupState(stages) : "";
    return h("div", { class: `seg-i ${st}`, title: d.pipeline.present ? `${g}: ${passed} of ${stages.length} stages passed` : "This project isn't driven by the controller, so there is no stage progress" },
      h("span", {}, g, h("em", {}, `${passed}/${stages.length}`)), h("div", { class: "bar" }, h("i", { style: `width:${(100 * passed) / stages.length}%` })));
  }));
}

// ───────────────────────────────────────────────────────────── left: pipeline / media / history
function renderLeft() {
  document.querySelectorAll("[data-ltab]").forEach((b) => b.classList.toggle("on", b.dataset.ltab === S.ltab));
  const box = $("leftBody");
  if (S.ltab === "media") return put(box, mediaList());
  if (S.ltab === "history") return put(box, historyList());
  put(box, pipelineMap());
}
function ring(frac) {
  const r = 9, c = 2 * Math.PI * r;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 22 22"); svg.setAttribute("class", "ring");
  for (const [cls, off] of [["bg", 0], ["fg", c * (1 - frac)]]) {
    const ci = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    ci.setAttribute("cx", "11"); ci.setAttribute("cy", "11"); ci.setAttribute("r", String(r)); ci.setAttribute("class", cls);
    if (cls === "fg") { ci.setAttribute("stroke-dasharray", String(c)); ci.setAttribute("stroke-dashoffset", String(off)); }
    svg.append(ci);
  }
  return svg;
}
function pipelineMap() {
  const p = S.data.pipeline;
  if (!p.present) {
    return h("div", { class: "pipe-empty" }, h("div", { class: "big" }, "Edit-only project"),
      "There's no controller state here, so no stage progress to follow. The timeline is still fully editable — point at something and tell the Director.");
  }
  const open = new Set(JSON.parse(sessionGet("nos_open") || "[]"));
  return [
    p.paused ? h("div", { class: "chip warn", style: "margin:0 0 8px 6px" }, `Paused: ${p.paused.reason || ""}`) : null,
    GROUPS.map(([g, stages]) => {
      const st = stages.map(stageStatus);
      const passed = st.filter((s) => s === "passed").length;
      const state = groupState(stages);
      const isOpen = open.has(g) || (state === "cur" && !open.has(`-${g}`));
      const el = h("div", { class: `grp ${state}${isOpen ? " open" : ""}` },
        h("div", { class: "grp-h", onclick: () => {
          const now = !el.classList.contains("open");
          el.classList.toggle("open", now);
          open.delete(g); open.delete(`-${g}`); open.add(now ? g : `-${g}`);
          sessionSet("nos_open", JSON.stringify([...open]));
        } }, ring(passed / stages.length), h("span", { class: "gname" }, g), h("span", { class: "gcount" }, `${passed}/${stages.length}`)),
        h("div", { class: "stages" }, stages.map((s, i) => {
          const node = p.nodes.find((n) => n.stage === s) || {};
          const why = node.blocking && node.blocking[0] ? (typeof node.blocking[0] === "string" ? node.blocking[0] : JSON.stringify(node.blocking[0])).slice(0, 140) : node.stale ? "an upstream input changed since it passed" : "";
          return h("div", { class: `stg ${st[i]}`, title: why }, s.toLowerCase().replaceAll("_", " "), st[i] === "blocked" || node.stale ? h("span", { class: "why" }, why) : null);
        })));
      return el;
    }),
  ];
}
function mediaList() {
  const a = S.data.assets || {};
  const users = {};
  for (const t of tracks()) for (const it of t.items) if (it.asset_id) (users[it.asset_id] = users[it.asset_id] || []).push([t, it]);
  const ids = Object.keys(a);
  if (!ids.length) return h("div", { class: "pipe-empty" }, h("div", { class: "big" }, "No media yet"), "Assets appear here once the pipeline registers them.");
  return ids.map((id) => {
    const x = a[id], u = users[id] || [];
    const pic = u.find(([t]) => t.kind === "video" || t.kind === "overlay");
    return h("div", { class: "media-i", title: x.source_url || "" },
      h("div", { class: "th", style: pic ? `background-image:url('${thumbUrl(pic[1].id)}')` : "" }, pic ? null : (u[0] && u[0][0].kind === "audio" ? icon("wave") : "—")),
      h("div", { style: "min-width:0" }, h("div", { class: "nm" }, x.file || id),
        h("div", { class: "sub" },
          h("span", { class: `chip ${x.status === "approved" ? "ok" : "warn"}` }, x.status || "no status"),
          x.rights_status ? h("span", { class: "chip" }, x.rights_status) : null,
          x.generated ? h("span", { class: "chip warn" }, "generated") : null,
          h("span", { class: "chip" }, `used ×${u.length}`))));
  });
}
function historyList() {
  const ev = (S.data.events || []).filter((e) => e.action === "patch_applied");
  const live = new Set((S.data.versions || []).map((v) => v.replace(".json", "")));
  const current = [...live].sort().pop();
  const rows = [...ev].reverse().map((e) => h("div", { class: `hv${e.version === current ? " cur" : ""}${live.has(e.version) ? "" : " undone"}` },
    h("div", { class: "vh" }, h("b", {}, e.version), h("span", {}, ago(e.timestamp))),
    h("div", { class: "q" }, `“${e.request}”`),
    h("div", { class: "s" }, `${live.has(e.version) ? "" : "undone · "}${e.summary || ""}`)));
  return [
    h("div", { style: "display:flex;justify-content:space-between;align-items:center;padding:0 4px 10px" },
      h("span", { class: "dim", style: "font-size:12px" }, `${live.size ? live.size - 1 : 0} edit(s) on the working timeline`),
      h("button", { class: "btn ghost sm", disabled: live.size < 2, onclick: undo }, icon("undo"), "Undo last")),
    h("div", { class: "hist" }, rows, h("div", { class: `hv${!current || current === "v001" ? " cur" : ""}` },
      h("div", { class: "vh" }, h("b", {}, "v001"), h("span", {}, "")), h("div", { class: "q" }, "Starting point"),
      h("div", { class: "s" }, "The timeline as the pipeline built it")))];
}
function sessionGet(k) { try { return sessionStorage.getItem(k); } catch (_) { return null; } }
function sessionSet(k, v) { try { sessionStorage.setItem(k, v); } catch (_) { /* storage unavailable */ } }

function eventView(e) {
  const a = (e.action || "").replaceAll("_", " ");
  if (e.action === "patch_applied") return ["ember", `Applied ${e.version}: “${e.request}”`];
  if (e.action === "patch_undone") return ["ice", `Undo: restored ${e.restored}`];
  if (e.action === "preview_rendered") return ["ok", `Preview rendered · ${fmt(e.duration)}`];
  if (e.action === "preview_failed") return ["bad", `Preview failed: ${e.error}`];
  if (e.stage) return [/block|fail/.test(e.action || "") ? "bad" : /pass|approve/.test(e.action || "") ? "ok" : "", `${e.stage.toLowerCase().replaceAll("_", " ")} · ${a}${e.reason ? ` (${e.reason})` : ""}`];
  return ["", a || JSON.stringify(e).slice(0, 80)];
}
function renderFeed() {
  const ev = [...(S.data.events || [])].reverse().slice(0, 30);
  $("actCount").textContent = ev.length ? String((S.data.events || []).length) : "";
  put($("feed"), ev.length ? ev.map((e) => {
    const key = (e.timestamp || "") + (e.action || "") + (e.version || "");
    const isNew = !S.firstFeed && !S.seen.has(key);
    S.seen.add(key);
    const [cls, text] = eventView(e);
    return h("div", { class: `ev${isNew ? " new" : ""}` }, h("span", { class: `ic ${cls}` }), h("span", {}, text), h("time", { "data-t": e.timestamp }, ago(e.timestamp)));
  }) : h("div", { class: "none" }, "Quiet so far. Pipeline stages, edits and renders show up here as they happen."));
  S.firstFeed = false;
}

// ───────────────────────────────────────────────────────────── player
function renderPlayer() {
  const d = S.data, screen = $("screen");
  if (!d.preview_url) {
    if (S.video) { S.video.pause(); S.video = null; }
    put(screen, h("div", { class: "empty-screen" },
      h("div", { class: "big" }, d.timeline ? h("span", {}, "Nothing rendered ", h("em", {}, "yet")) : "No timeline yet"),
      h("p", {}, d.timeline ? "Render a preview to watch the cut. Every edit you apply re-renders it for you, and you can watch the encoder work." : "The pipeline hasn't built a timeline for this project yet. Its progress is on the left."),
      d.timeline ? h("button", { class: "btn primary", onclick: requestRender }, icon("render"), "Render preview") : null));
    $("ambient").classList.remove("on");
    return;
  }
  const src = `${d.preview_url}?v=${enc((d.render && d.render.rendered_at) || "")}`;
  if (S.video && S.video.dataset.src === src) return;
  const old = S.video, t = old ? old.currentTime : 0, wasPlaying = old && !old.paused;
  const v = h("video", { preload: "auto", playsinline: true, class: old ? "incoming" : "" });
  v.dataset.src = src; v.src = src;
  v.addEventListener("loadeddata", () => {
    v.currentTime = Math.min(t, v.duration || t);
    if (old) {
      requestAnimationFrame(() => v.classList.remove("incoming"));
      setTimeout(() => old.remove(), 700);
      flashHud();
      if (wasPlaying) v.play().catch(() => {});
    }
    sampleAmbient();
  });
  v.addEventListener("timeupdate", onTime);
  v.addEventListener("seeked", () => { onTime(); sampleAmbient(); });
  v.addEventListener("play", () => { put($("playBtn"), icon("pause")); ambientLoop(); });
  v.addEventListener("pause", () => put($("playBtn"), icon("play")));
  v.addEventListener("ended", () => put($("playBtn"), icon("play")));
  v.addEventListener("click", togglePlay);
  if (old) old.pause();
  S.video = v;
  if (old && old.isConnected) screen.append(v); else put(screen, v);
}
function togglePlay() { if (S.video) (S.video.paused ? S.video.play() : S.video.pause()); }
function seek(t) {
  t = Math.max(0, Math.min(t, total() || t));
  if (S.video) S.video.currentTime = t; else { S.playTime = t; drawPlayhead(t); }
}
function nowTime() { return S.video ? S.video.currentTime : S.playTime || 0; }
function onTime() {
  const t = nowTime(), tot = (S.video && S.video.duration) || total();
  $("tcNow").textContent = fmt(t); $("tcTotal").textContent = fmt(tot);
  const pct = tot ? (100 * t) / tot : 0;
  $("scrubFill").style.width = `${pct}%`; $("scrubKnob").style.left = `${pct}%`;
  drawPlayhead(t);
  const items = mainItems();
  let cur = null;
  for (const it of items) if (t >= it.timeline_in - 1e-3 && t < it.timeline_out) cur = it;
  document.querySelectorAll(".shot").forEach((el) => {
    const it = items.find((x) => x.id === el.dataset.id);
    const bar = el.querySelector(".now");
    if (bar) bar.style.width = it && cur && it.id === cur.id ? `${(100 * (t - it.timeline_in)) / dur(it)}%` : "0";
  });
  if (cur && S.hudShot !== cur.id) { S.hudShot = cur.id; renderHud(); }
}
// Ambient light: the real frame, averaged down to 48×27 and blurred behind everything (like a bias light).
function sampleAmbient() {
  const v = S.video, c = $("ambient");
  if (!v || v.readyState < 2) return;
  try { c.getContext("2d").drawImage(v, 0, 0, c.width, c.height); c.classList.add("on"); } catch (_) { /* not decodable yet */ }
}
function ambientLoop() {
  if (!S.video || S.video.paused) return;
  sampleAmbient();
  setTimeout(() => requestAnimationFrame(ambientLoop), 220);
}
function renderHud() {
  const d = S.data;
  const items = mainItems(), t = nowTime();
  const cur = items.find((it) => t >= it.timeline_in - 1e-3 && t < it.timeline_out) || items[0];
  put($("hudShot"), cur ? h("span", { class: "tag" }, h("b", {}, cur.id), itemName(mainTrack(), cur)) : null);
  const j = d.job;
  let tag;
  if (jobActive(j)) tag = h("span", { class: "tag work" }, h("span", { class: "d" }), j.state === "queued" ? "Queued" : `Rendering ${Math.round((j.progress || 0) * 100)}%`);
  else if (j && j.state === "failed") tag = h("span", { class: "tag bad", title: j.error }, h("span", { class: "d" }), "Last render failed");
  else if (d.render) {
    const fresh = d.timeline_sha256 && d.render.timeline_sha256 === d.timeline_sha256;
    tag = h("span", { class: `tag ${fresh ? "" : "warn"}`, id: "freshTag" }, h("span", { class: "d" }), fresh ? `Preview matches the edit` : "Preview is behind the edit");
  }
  put($("hudState"), tag);
  renderRenderOverlay();
}
function flashHud() { const t = $("freshTag"); if (t) { t.classList.remove("flash"); void t.offsetWidth; t.classList.add("flash"); } }
const PHASES = [["validate", "Validate"], ["graph", "Filtergraph"], ["encode", "Encode"], ["verify", "Verify"]];
function renderRenderOverlay() {
  const j = S.data.job, ovl = $("renderOvl");
  if (!jobActive(j) || !S.data.preview_url) { ovl.hidden = true; S.ovlPrev = null; return; }
  const wasHidden = ovl.hidden;
  ovl.hidden = false;
  const names = (j.phases || []).map((p) => p.name);
  const cur = names[names.length - 1];
  const st = j.stats || {};
  put(ovl,
    h("div", { class: "r1" }, h("span", { class: "ttl" }, j.state === "queued" ? "Queued" : `Rendering ${j.for && j.for.startsWith("v") ? j.for : "preview"}`),
      h("span", { class: "pct" }, `${Math.round((j.progress || 0) * 100)}%`), h("span", { class: "grow" }),
      h("span", { class: "st" }, statsLine(st))),
    h("div", { class: "phs" }, PHASES.map(([n, l]) => h("span", { class: names.includes(n) ? (n === cur ? "on" : "done") : "" }, l))),
    h("div", { class: "prog", "data-sid": "ovl" }, h("i", { style: `width:${(j.progress || 0) * 100}%` })));
  if (!wasHidden && S.ovlPrev != null) {
    const i = ovl.querySelector(".prog i"), target = i.style.width;
    i.style.width = S.ovlPrev;
    requestAnimationFrame(() => requestAnimationFrame(() => (i.style.width = target)));
  }
  S.ovlPrev = `${(j.progress || 0) * 100}%`;
}
function statsLine(st) {
  return [st.frame != null && st.frames ? `frame ${st.frame}/${st.frames}` : null, st.fps ? `${Math.round(st.fps)} fps` : null,
    st.speed ? `${st.speed.toFixed(1)}× realtime` : null, st.eta_s != null ? `~${Math.max(0, Math.round(st.eta_s))} s left` : null].filter(Boolean).join(" · ");
}
function requestRender() {
  api(`/api/studio/${enc(S.pid)}/render`, { method: "POST", body: "{}" })
    .then((job) => {
      chat().push({ id: uid(), role: "ai", kind: "run", request: null, title: "Rendering a fresh preview", steps: [], state: "applied", renderFor: "requested", render: followable(job, "requested"), t0: Date.now() });
      saveChats(); renderChat(); onJob(job); poll();
    })
    .catch((e) => toast(e.message, "bad"));
}

// ───────────────────────────────────────────────────────────── transport + shots
function renderScrubCuts() {
  const tot = total();
  put($("scrubCuts"), tot ? mainItems().slice(1).map((it) => h("span", { style: `left:${(100 * it.timeline_in) / tot}%` })) : []);
}
function renderShots() {
  const items = mainItems();
  const out = [];
  items.forEach((it, i) => {
    if (i) {
      const tr = it.transition_in;
      out.push(h("div", { class: "joint", title: tr ? `${tr.type.replace("_", " ")}${tr.duration ? ` · ${tr.duration} s` : ""}` : "cut" },
        !tr || tr.type === "cut" ? h("i", { class: "cut" }) : tr.type === "crossfade" ? icon("xfade") : h("i", { class: `dip${tr.type === "dip_white" ? " w" : ""}` })));
    }
    out.push(h("div", { class: `shot${S.sel && S.sel.item_id === it.id ? " sel" : ""}${S.changed.has(it.id) ? " changed" : ""}`, "data-id": it.id, onclick: () => select({ item_id: it.id }, true) },
      h("div", { class: "th", style: `background-image:url('${thumbUrl(it.id)}')` }, h("span", { class: "num" }, String(i + 1).padStart(2, "0")), h("span", { class: "len" }, `${dur(it).toFixed(1)}s`), h("i", { class: "now" })),
      h("div", { class: "nm" }, `${it.id} · ${itemName(mainTrack(), it)}`)));
  });
  put($("shots"), out.length ? out : h("div", { class: "dim", style: "padding:20px" }, "No shots yet."));
  const selEl = document.querySelector(".shot.sel");
  if (selEl) selEl.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
}

// ───────────────────────────────────────────────────────────── timeline
function niceStep(z) { for (const s of [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]) if (s * z >= 80) return s; return 1200; }
function fitZoom() {
  const tot = total(), w = $("lanes").clientWidth;
  if (!tot || !w) return;
  S.zoom = Math.max(4, Math.min(220, (w - 40) / tot));
  $("zoom").value = String(Math.round(S.zoom));
  S.fit = false;
}
function laneH(t) {
  const full = LANE_H[t.kind] || 40, min = LANE_MIN[t.kind] || 26;
  return Math.round(min + (full - min) * (S.laneK ?? 1));
}
// The timeline panel takes the height its tracks need (up to 45% of the window), unless the user dragged it;
// when that is not enough, lanes shrink toward their minimum so every track stays in view without scrolling.
function fitTimelineHeight() {
  const ts = tracks();
  const chrome = ($("timeline").querySelector(".tl-bar").offsetHeight || 45) + 30 + 14;  // bar + ruler + scrollbar/borders
  const full = ts.reduce((a, t) => a + (LANE_H[t.kind] || 40), 0), min = ts.reduce((a, t) => a + (LANE_MIN[t.kind] || 26), 0);
  let tlH;
  if (S.userTl) tlH = $("timeline").getBoundingClientRect().height;
  else {
    tlH = Math.max(170, Math.min(chrome + full, Math.round(window.innerHeight * 0.45)));
    document.documentElement.style.setProperty("--tl-h", `${tlH}px`);
  }
  const avail = tlH - chrome;
  S.laneK = full <= avail ? 1 : full > min ? Math.max(0, (avail - min) / (full - min)) : 1;
}
function renderTimeline() {
  const d = S.data, inner = $("inner"), heads = $("heads");
  const vs = (d.versions || []);
  $("tlSource").textContent = d.timeline ? `${d.timeline_source}${vs.length ? ` · ${vs[vs.length - 1].replace(".json", "")}` : ""}` : "no timeline";
  if (!d.timeline) { put(inner, h("div", { class: "tl-empty" }, "No timeline yet.")); put(heads); return; }
  fitTimelineHeight();
  const z = S.zoom, tot = Math.max(total(), 1);
  inner.style.width = `${tot * z + 30}px`;
  inner.classList.toggle("has-ghost", !!S.ghost);
  $("ghostLegend").hidden = !S.ghost;
  // ruler
  const step = niceStep(z), minor = step / 5;
  const ruler = h("div", { class: "ruler", id: "ruler" });
  for (let t = 0; t <= tot + 1e-6; t += minor) {
    const maj = Math.abs(t / step - Math.round(t / step)) < 1e-6;
    if (!maj && minor * z < 9) continue;
    ruler.append(h("div", { class: `tk${maj ? " maj" : ""}`, style: `left:${t * z}px` }, maj ? h("b", {}, fmt(t).replace(/\.0$/, "")) : null));
  }
  // lanes
  const cur = positions();
  const flip = S.flipFrom && S.flipFrom.sha !== d.timeline_sha256 ? S.flipFrom.pos : null;
  const lanes = tracks().map((t) => {
    const lane = h("div", { class: "lane", style: `height:${laneH(t)}px` });
    const items = [...t.items].sort((a, b) => a.timeline_in - b.timeline_in);
    items.forEach((it, i) => {
      const w = Math.max(3, dur(it) * z - 1), k = kindOf(t);
      const cls = `clip ${t.kind === "audio" ? "audio " + k : t.kind}${S.sel && S.sel.item_id === it.id ? " sel" : ""}${S.changed.has(it.id) ? " changed" : ""}`;
      const label = t.kind === "audio" ? `${it.id}${it.gain_db ? ` · ${it.gain_db} dB` : ""}` : t.kind === "caption" ? it.text : `${it.id} · ${itemName(t, it)}`;
      const c = h("div", { class: cls, "data-id": it.id, style: `left:${it.timeline_in * z}px;width:${w}px`, title: `${it.id} · ${fmt(it.timeline_in)} → ${fmt(it.timeline_out)} (${dur(it).toFixed(2)} s)`,
        onclick: (e) => { e.stopPropagation(); select({ item_id: it.id }, true); } });
      if (t.kind === "video") {
        const n = Math.max(1, Math.min(14, Math.round(w / 92)));
        c.append(h("div", { class: "strip" }, Array.from({ length: n }, (_, j) => h("span", { style: `background-image:url('${thumbUrl(it.id, ((j + 0.5) * dur(it)) / n)}')` }))));
      }
      if (t.kind === "audio") { const cv = h("canvas"); c.append(cv); drawWave(it, cv, w, laneH(t) - 10); }
      c.append(h("span", { class: "lbl" }, label));
      lane.append(c);
      if (flip && flip[it.id]) {
        const [a0, a1] = flip[it.id];
        const dx = (a0 - it.timeline_in) * z, sx = Math.max(0.05, ((a1 - a0) * z - 1) / w);
        if (Math.abs(dx) > 0.5 || Math.abs(sx - 1) > 0.01) {
          c.style.transformOrigin = "0 50%"; c.style.transform = `translateX(${dx}px) scaleX(${sx})`;
          requestAnimationFrame(() => requestAnimationFrame(() => { c.style.transition = "transform .75s cubic-bezier(.2,.8,.2,1), box-shadow .2s"; c.style.transform = ""; }));
        }
      }
      if (t.kind === "video" && i > 0 && it.transition_in) {
        const prev = items[i - 1], tr = it.transition_in;
        if (tr.type === "crossfade") lane.append(h("div", { class: "xfade", style: `left:${it.timeline_in * z}px;width:${Math.max(4, (prev.timeline_out - it.timeline_in) * z)}px`, title: `crossfade ${tr.duration} s` }));
        else if (tr.type.startsWith("dip")) lane.append(h("div", { class: `dipm${tr.type === "dip_white" ? " w" : ""}`, style: `left:${it.timeline_in * z}px`, title: tr.type.replace("_", " ") }));
      }
      // ghost of the proposed cut, drawn where this item would end up
      if (S.ghost) {
        const a = S.ghost.after[it.id];
        if (!a) lane.append(h("div", { class: "tghost rm", style: `left:${it.timeline_in * z}px;width:${w}px` }));
        else if (Math.abs(a[0] - cur[it.id][0]) > 1e-3 || Math.abs(a[1] - cur[it.id][1]) > 1e-3) {
          const edited = S.ghost.edited.has(it.id);
          const by = a[0] - cur[it.id][0];
          lane.append(h("div", { class: "tghost", style: `left:${a[0] * z}px;width:${Math.max(3, (a[1] - a[0]) * z - 1)}px` },
            (a[1] - a[0]) * z > 60 ? h("b", {}, edited ? secs(a[1] - a[0]) : `${by > 0 ? "+" : ""}${by.toFixed(2)} s`) : null));
        }
      }
    });
    return lane;
  });
  if (flip) S.flipFrom = null;
  const j = d.job;
  const sweep = jobActive(j) ? h("div", { class: "sweep", id: "sweep", style: `width:${(j.rendered_until || 0) * z}px` }) : null;
  const range = S.sel && S.sel.item_id == null ? h("div", { class: "range", style: `left:${S.sel.from * z}px;width:${(S.sel.to - S.sel.from) * z}px` }) : null;
  put(inner, ruler, lanes, sweep, range, h("div", { class: "hoverline", id: "hoverline" }), h("div", { class: "playhead", id: "playhead" }));
  put(heads, h("div", { class: "pad" }), tracks().map((t) => {
    const k = kindOf(t);
    const gains = [...new Set(t.items.map((x) => x.gain_db).filter((g) => g != null))];
    const sub = t.kind === "video" ? `${t.items.length}` : t.kind === "audio" && gains.length === 1 ? `${gains[0]} dB` : `${t.items.length}`;
    return h("div", { class: "thead", style: `height:${laneH(t)}px` }, h("span", { class: "sw", style: `background:var(--${{ dialogue: "ambience" }[k] || k})` }), h("span", { class: "tn" }, trackName(t)), h("span", { class: "ts" }, sub));
  }));
  drawPlayhead(nowTime());
  wireTimeline(ruler);
  S.changed.clear();
}
function drawPlayhead(t) { const ph = $("playhead"); if (ph) ph.style.left = `${t * S.zoom}px`; }
// Waveforms: the server measures peak |sample| per bucket; shown on a dB scale (−48 dB floor), mirrored.
function drawWave(it, cv, w, hgt) {
  const n = Math.max(16, Math.min(600, Math.round(w / 3)));
  const key = `${it.id}|${it.source_in || 0}|${dur(it).toFixed(3)}|${n}|${it.asset_id}`;
  const paint = (wv) => {
    if (!wv || !wv.peaks || !wv.peaks.length || !cv.isConnected && !cv.parentNode) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr); cv.height = Math.round(hgt * dpr);
    const ctx = cv.getContext("2d");
    const col = getComputedStyle(cv.parentNode).getPropertyValue("--c").trim() || "#8391ff";
    ctx.fillStyle = col; ctx.globalAlpha = 0.85;
    const mid = cv.height * 0.58, amp = cv.height * 0.36, bw = cv.width / wv.peaks.length;
    wv.peaks.forEach((p, i) => {
      const db = 20 * Math.log10(Math.max(p, 1e-5));
      const v = Math.max(0, Math.min(1, (db + 48) / 48));
      const hh = Math.max(1 * dpr, v * amp);
      ctx.fillRect(i * bw + bw * 0.15, mid - hh, Math.max(1, bw * 0.7), hh * 2);
    });
  };
  const hit = S.waves.get(key);
  if (hit && hit.peaks) { requestAnimationFrame(() => paint(hit)); return; }
  if (!hit) {
    const p = api(`/api/studio/${enc(S.pid)}/wave/${enc(it.id)}?n=${n}`).then((wv) => { S.waves.set(key, wv); return wv; }).catch(() => null);
    S.waves.set(key, p);
  }
  Promise.resolve(S.waves.get(key)).then((wv) => paint(wv));
}
function wireTimeline(ruler) {
  const lanes = $("lanes");
  let start = null;
  const at = (e) => Math.max(0, (e.clientX - $("inner").getBoundingClientRect().left) / S.zoom);
  ruler.onmousedown = (e) => { start = at(e); e.preventDefault(); };
  window.onmousemove = (e) => {
    if (start == null) return;
    const t = at(e);
    if (Math.abs(t - start) * S.zoom < 4) return;
    S.sel = { from: Math.min(start, t), to: Math.min(total(), Math.max(start, t)) };
    let r = $("inner").querySelector(".range");
    if (!r) { r = h("div", { class: "range" }); $("inner").append(r); }
    r.style.left = `${S.sel.from * S.zoom}px`; r.style.width = `${(S.sel.to - S.sel.from) * S.zoom}px`;
  };
  window.onmouseup = (e) => {
    if (start == null) return;
    const t = at(e), moved = Math.abs(t - start) * S.zoom >= 4;
    start = null;
    if (moved) select(S.sel, false); else seek(t);
  };
  lanes.onmousemove = (e) => {
    const t = at(e), hl = $("hoverline");
    if (hl) { hl.style.display = "block"; hl.style.left = `${t * S.zoom}px`; }
    $("hoverTc").textContent = t <= total() ? fmt(t) : "";
    const clip = e.target.closest && e.target.closest(".clip.video");
    const pop = $("scrubpop");
    if (!clip) { pop.hidden = true; return; }
    const [, it] = findItem(clip.dataset.id);
    if (!it) return;
    const rel = Math.max(0, Math.min(dur(it) - 0.05, t - it.timeline_in));
    const q = Math.round(rel * 4) / 4;
    pop.hidden = false;
    pop.style.left = `${e.clientX}px`; pop.style.top = `${clip.getBoundingClientRect().top}px`;
    if (pop.dataset.k !== `${it.id}@${q}`) {
      pop.dataset.k = `${it.id}@${q}`;
      clearTimeout(S.popT);
      S.popT = setTimeout(() => { pop.querySelector("img").src = thumbUrl(it.id, q); }, 60);
    }
    pop.querySelector("span").textContent = `${it.id} · ${fmt(t)}`;
  };
  lanes.onmouseleave = () => { const hl = $("hoverline"); if (hl) hl.style.display = "none"; $("hoverTc").textContent = ""; $("scrubpop").hidden = true; };
  lanes.onclick = (e) => { if (e.target === lanes || e.target.classList.contains("lane") || e.target.id === "inner") seek(at(e)); };
}
function select(sel, doSeek) {
  S.sel = sel;
  if (doSeek && sel && sel.item_id) { const [, it] = findItem(sel.item_id); if (it) seek(+it.timeline_in + 0.04); }
  renderShots(); renderFocus(); renderChips(); renderTimeline();
}

// ───────────────────────────────────────────────────────────── director: focus + chips
function selLabel(sel) {
  if (!sel) return "";
  if (sel.item_id) { const [, it] = findItem(sel.item_id); return it ? `${it.id} · ${fmt(it.timeline_in)}` : sel.item_id; }
  return `${fmt(sel.from)}–${fmt(sel.to)}`;
}
function renderFocus() {
  const box = $("focus"), sel = S.sel;
  const clear = h("button", { class: "ibtn", title: "Clear selection (Esc)", onclick: () => select(null) }, icon("close"));
  if (sel && sel.item_id) {
    const [t, it] = findItem(sel.item_id);
    if (!it) { S.sel = null; return renderFocus(); }
    const a = (S.data.assets || {})[it.asset_id] || null;
    const ev = (S.data.evidence || {})[it.id];
    const tr = it.transition_in, mo = it.motion;
    const pic = t.kind === "video" || t.kind === "overlay";
    put(box, h("div", { class: "f-card" },
      h("div", { class: "th", style: pic ? `background-image:url('${thumbUrl(it.id)}')` : "" }, pic ? null : icon(t.kind === "caption" ? "text" : "wave")),
      h("div", { style: "min-width:0" },
        h("div", { class: "t1" }, itemName(t, it)),
        h("div", { class: "t2" }, `${it.id} · ${trackName(t)} · ${fmt(it.timeline_in)} → ${fmt(it.timeline_out)} · ${dur(it).toFixed(2)} s`),
        h("div", { class: "t3" },
          t.kind === "video" ? h("span", { class: "chip" }, tr ? tr.type.replace("_", " ") : "cut in") : null,
          mo && mo.kind !== "none" ? h("span", { class: "chip" }, `${mo.kind.replace("_", " ")} ${mo.scale_from}→${mo.scale_to}`) : null,
          t.kind === "audio" ? h("span", { class: "chip" }, `${it.gain_db ?? 0} dB`) : null,
          t.kind === "overlay" ? h("span", { class: "chip" }, `${it.blend || "normal"} · ${Math.round((it.opacity ?? 1) * 100)}%`) : null,
          a ? h("span", { class: `chip ${a.status === "approved" ? "ok" : "warn"}` }, a.status || "no status") : null,
          a && a.rights_status ? h("span", { class: "chip" }, a.rights_status) : null,
          a && a.generated ? h("span", { class: "chip warn" }, "generated · never evidence") : null,
          t.kind === "video" ? h("span", { class: `chip ${ev ? "ok" : ""}` }, ev ? `${ev.length} evidence link(s)` : "no claim linked") : null)),
      clear));
    return;
  }
  if (sel) {
    const inside = mainItems().filter((x) => x.timeline_in >= sel.from - 1e-6 && x.timeline_in < sel.to);
    put(box, h("div", { class: "f-card" }, h("div", { class: "th" }, icon("range")),
      h("div", {}, h("div", { class: "t1" }, "A stretch of the edit"), h("div", { class: "t2" }, `${fmt(sel.from)} → ${fmt(sel.to)} · ${(sel.to - sel.from).toFixed(2)} s`),
        h("div", { class: "t3" }, inside.length ? inside.map((x) => h("span", { class: "chip" }, x.id)) : h("span", { class: "chip" }, "no shot starts here"))), clear));
    return;
  }
  put(box, h("div", { class: "f-empty" }, h("div", { class: "gl" }, icon("cursor")),
    h("div", {}, h("b", {}, "Point at something"), "Click a clip or a shot, or drag across the ruler to pick a stretch — then say what should change.")));
}
function suggestions() {
  const sel = S.sel;
  const music = tracks().find((t) => t.role === "music"), vo = tracks().find((t) => t.role === "narration");
  const global = [music ? "Music down 3 dB" : null, vo ? "Narration up 2 dB" : null].filter(Boolean);
  if (sel && sel.item_id) {
    const [t, it] = findItem(sel.item_id);
    if (!it) return global;
    if (t.kind === "video") {
      const first = mainItems()[0] && mainItems()[0].id === it.id;
      return ["Make this faster", "Let it breathe", first ? null : "Crossfade into this", first ? null : "Dip to black here", "Push in", "Make it 2.5 s", "Remove this shot"].filter(Boolean);
    }
    if (t.kind === "caption") return [`Change the caption to "${it.text}"`, "Remove this"];
    if (t.kind === "audio") { const n = t.role === "narration" ? "Narration" : trackName(t); return [`${n} down 3 dB`, `${n} up 3 dB`]; }
    return ["Remove this"];
  }
  if (sel) return ["Increase the pace in this part", "Let this part breathe", ...global];
  return global;
}
function renderChips() {
  put($("chips"), suggestions().map((c) => h("button", { onclick: () => { if (c.includes('"') && S.sel && S.sel.item_id) { $("prompt").value = c; $("prompt").focus(); autosize(); } else send(c); } }, c)));
  put($("selpill"), S.sel ? [selLabel(S.sel), h("button", { title: "Clear selection", onclick: () => select(null) }, "×")] : []);
}
function renderDirectorStatus(text) {
  const prov = S.data && S.data.assistant && S.data.assistant.provider;
  const j = S.data && S.data.job;
  const st = $("dStatus"), orb = $("orb");
  st.classList.remove("work"); orb.className = "orb";
  if (S.busy) { st.textContent = text || "Working…"; st.classList.add("work"); orb.classList.add("work"); return; }
  if (jobActive(j)) { st.textContent = `Rendering ${j.for && j.for.startsWith("v") ? j.for : "preview"} · ${Math.round((j.progress || 0) * 100)}%`; st.classList.add("work"); orb.classList.add("work"); return; }
  const last = chat()[chat().length - 1];
  if (last && last.kind === "run" && last.state === "question") orb.classList.add("ask");
  st.textContent = `Ready · editing rules${prov ? ` + ${prov}` : ""} · nothing changes until you apply`;
}

// ───────────────────────────────────────────────────────────── director: conversation
function chat() {
  if (!S.chats[S.pid]) S.chats[S.pid] = [];
  return S.chats[S.pid];
}
function saveChats() {
  try {
    for (const k of Object.keys(S.chats)) S.chats[k] = S.chats[k].slice(-60);
    localStorage.setItem("nos_studio_v2", JSON.stringify(S.chats));
  } catch (_) { /* storage may be unavailable */ }
}
function examples() {
  const items = mainItems(), out = [];
  if (items.length >= 3) out.push({ label: "Tighten the opening", hint: `${fmt(0)}–${fmt(items[1].timeline_out)}`, sel: { from: 0, to: +items[1].timeline_out }, text: "Increase the pace in this part" });
  const mid = items[Math.min(3, items.length - 1)];
  if (mid && items.length > 1) out.push({ label: `Dip to black into ${mid.id}`, hint: mid.id, sel: { item_id: mid.id }, text: "Dip to black here" });
  if (tracks().some((t) => t.role === "music")) out.push({ label: "Bring the music down", hint: "−3 dB", sel: null, text: "Music down 3 dB" });
  return out;
}
function renderChat() {
  const box = $("msgs");
  const msgs = chat();
  const intro = h("div", { class: "m-ai seen" },
    h("div", { class: "say intro" }, "What should change?"),
    h("div", { class: "say sub" }, "Point at a clip or drag across the ruler, then say it in plain words. I'll show every step I take and the exact cut I'd make — nothing changes until you apply it."),
    S.data && S.data.timeline ? h("div", { class: "examples" }, examples().map((x) => h("button", { onclick: () => { select(x.sel, !!(x.sel && x.sel.item_id)); send(x.text); } }, h("em", {}, x.label), h("span", {}, x.hint)))) : null);
  put(box, intro, msgs.map(msgEl));
  box.scrollTop = box.scrollHeight;
}
function msgEl(m) {
  if (m.role === "user") { const el = h("div", { class: "m-user", id: `m-${m.id}` }, m.ctx ? h("span", { class: "ctx" }, m.ctx) : null, m.text); if (m._shown) el.classList.add("seen"); m._shown = true; return el; }
  return runEl(m);
}
function stepEl(s, seen) {
  const ic = { done: "check", warn: "warn", failed: "x", question: "q", running: null }[s.status];
  const lines = Array.isArray(s.detail) ? s.detail : s.detail != null && s.detail !== "" ? [s.detail] : [];
  return h("div", { class: `step ${s.status}${seen ? " seen" : ""}`, "data-sid": s.id },
    h("div", { class: "ic" }, ic ? icon(ic) : null),
    h("div", { style: "min-width:0" },
      h("div", { class: "lb" }, s.label),
      lines.length || s.item_id ? h("div", { class: "dt" },
        s.item_id ? h("span", { class: "mini-th", style: `background-image:url('${thumbUrl(s.item_id)}')` }) : null,
        lines.map((l) => h("div", { class: String(l).startsWith("⚠") ? "w" : String(l).startsWith("✕") ? "x" : "" }, l))) : null,
      s.progress != null ? h("div", { class: "prog" }, h("i", { style: `width:${s.progress * 100}%` })) : null,
      s.stats ? h("div", { class: "stats" }, s.stats) : null,
      s.watch != null ? h("button", { class: "btn sm", style: "margin-top:8px", onclick: () => watchChange(s.watch) }, icon("play"), "Watch the change") : null),
    h("span", { class: "ms" }, s.ms != null ? (s.ms >= 1000 ? `${(s.ms / 1000).toFixed(1)} s` : `${Math.round(s.ms)} ms`) : ""));
}
function renderSteps(m) {
  const j = m.render;
  if (!j) return [];
  const ph = Object.fromEntries((j.phases || []).map((p) => [p.name, p]));
  const out = [];
  const failed = j.state === "failed";
  if (j.state === "queued") out.push({ id: "r-q", label: "Waiting for the render before it to finish", status: "running" });
  if (ph.validate) out.push({ id: "r-v", label: "Validated the timeline", detail: `${ph.validate.detail.tracks} tracks · ${ph.validate.detail.items} items · source ranges, handles, overlaps, paths`, status: ph.graph ? "done" : failed ? "failed" : "running", ms: ph.validate.ms });
  if (ph.graph) { const g = ph.graph.detail; out.push({ id: "r-g", label: "Built one FFmpeg filtergraph", detail: `${g.inputs} inputs · ${g.filters} filters · ${g.has_audio ? "audio mixed and loudness-normalised" : "no audio"}${g.warnings ? ` · ${g.warnings} warning(s)` : ""}`, status: ph.encode ? "done" : failed ? "failed" : "running", ms: ph.graph.ms }); }
  if (ph.encode) {
    const e = ph.encode.detail, st = j.stats || {}, enc_done = !!ph.verify || j.state === "done";
    out.push({ id: "r-e", label: enc_done ? `Encoded ${e.frames} frames` : `Encoding ${e.frames} frames`, detail: enc_done ? `${e.width}×${e.height} · ${e.fps} fps · ${e.duration.toFixed(2)} s` : null,
      status: enc_done ? "done" : failed ? "failed" : "running", ms: ph.encode.ms, progress: enc_done ? null : j.progress || 0, stats: enc_done ? null : statsLine(st) || "starting the encoder…" });
  }
  if (ph.verify) {
    const v = j.verification || {};
    out.push({ id: "r-f", label: "Checked the file with ffprobe", status: j.state === "done" ? (v.passed ? "done" : "failed") : failed ? "failed" : "running",
      detail: j.state === "done" ? `${(v.duration || 0).toFixed(2)} s · ${v.av_delta_ms != null ? `audio/video within ${v.av_delta_ms} ms` : "no audio to compare"} · matches the timeline` : null, ms: ph.verify.ms });
  }
  if (failed) out.push({ id: "r-x", label: "The render failed", detail: (j.error || "").split("\n").slice(-3), status: "failed" });
  if (j.state === "done") out.push({ id: "r-d", label: "Preview ready", status: "done", detail: m.version ? `${m.version} is on screen` : null, watch: m.changeAt != null ? m.changeAt : 0 });
  return out;
}
function runEl(m) {
  const working = m.state === "working" || m.state === "applying" || (m.render && jobActive(m.render));
  const el = h("div", { class: `m-ai${m._shown ? " seen" : ""}`, id: `m-${m.id}` });
  if (m._shown) el.style.animation = "none";
  m.seenSteps = m.seenSteps || [];
  const seen = new Set(m.seenSteps);
  const mk = (s) => { const e = stepEl(s, seen.has(s.id)); seen.add(s.id); return e; };
  const elapsed = m.state === "working" ? (Date.now() - m.t0) / 1000 : m.elapsed != null ? m.elapsed / 1000 : null;
  el.append(h("div", { class: "run" },
    h("div", { class: "run-h" }, h("span", { class: `lbl${working ? " work" : ""}` }, m.title ? m.title : working ? "Director · working" : "Director"),
      h("span", { class: "el", id: `el-${m.id}` }, elapsed != null ? `${elapsed.toFixed(1)} s` : "")),
    h("div", { class: "steps" }, (m.steps || []).map(mk))));
  if (m.reply) el.append(h("div", { class: "say" }, m.reply));
  if (m.proposal) el.append(propEl(m));
  const post = [...(m.after || []), ...renderSteps(m)];
  if (post.length) el.append(h("div", { class: "run", style: "margin-top:12px" }, h("div", { class: "steps" }, post.map(mk))));
  m.seenSteps = [...seen]; m._shown = true;
  return el;
}
function updateRun(m) {
  const old = document.getElementById(`m-${m.id}`);
  const box = $("msgs");
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 140;
  const el = runEl(m);
  carryProgress(old, el);
  if (old) old.replaceWith(el); else box.append(el);
  if (nearBottom) box.scrollTop = box.scrollHeight;
}
// Rebuilt nodes start their progress bars where the old ones were, then glide to the new value.
function carryProgress(old, el) {
  if (!old) return;
  const prev = {};
  old.querySelectorAll("[data-sid] .prog i").forEach((i) => (prev[i.closest("[data-sid]").dataset.sid] = i.style.width));
  el.querySelectorAll("[data-sid] .prog i").forEach((i) => {
    const w = prev[i.closest("[data-sid]").dataset.sid];
    if (w == null) return;
    const target = i.style.width;
    i.style.width = w;
    requestAnimationFrame(() => requestAnimationFrame(() => (i.style.width = target)));
  });
}
function propEl(m) {
  const p = m.proposal;
  const isStale = m.state === "pending" && S.data && p.parent && p.parent !== S.data.timeline_sha256;
  const state = isStale ? "stale" : m.state;
  const d = p.diff || { edited: [], shifted: [], removed: [], added: [] };
  const el = h("div", { class: `prop${state === "pending" ? " armed" : ""}`, style: m._propShown ? "animation:none" : "" });
  m._propShown = true;
  el.append(h("div", { class: "prop-h" }, h("span", { class: "ttl" }, "Proposed cut"), h("span", { class: "grow" }),
    h("span", { class: `chip ${p.basis === "rules" ? "" : "ember"}`, title: p.basis === "rules" ? "Parsed by NarrativeOS's own editing rules" : "Proposed by the configured reasoning provider and checked by the same validators" }, p.basis === "rules" ? "editing rules" : p.basis.replace("model:", "model · "))));
  el.append(h("div", { class: "prop-b" },
    h("ul", { class: "ex" }, (p.explain || []).map((x) => h("li", {}, x))),
    diffViz(p),
    h("div", { class: "meta" },
      h("span", {}, "length ", h("b", {}, `${secs(p.duration_before)} → ${secs(p.duration_after)}`)),
      h("span", {}, h("b", {}, d.edited.length), " edited"), d.shifted.length ? h("span", {}, h("b", {}, d.shifted.length), " slide") : null,
      d.removed.length ? h("span", {}, h("b", {}, d.removed.length), " removed") : null, h("span", {}, h("b", {}, d.untouched), " untouched")),
    (p.warnings || []).length || (p.errors || []).length ? h("div", { class: "notes" }, (p.warnings || []).map((w) => h("div", { class: "w" }, w)), (p.errors || []).map((e) => h("div", { class: "x" }, e))) : null));
  const foot = h("div", { class: "prop-f" });
  if (state === "pending") {
    foot.append(h("button", { class: "btn primary sm", disabled: !p.can_apply, onclick: () => applyRun(m) }, p.can_apply ? "Apply" : "Can't apply"),
      h("button", { class: "btn ghost sm", onclick: () => discard(m) }, "Discard"), h("span", { class: "grow" }),
      h("span", { class: "note" }, p.can_apply ? "Outlined on the timeline" : "Fails the compiler's checks"));
  } else if (state === "applying") foot.append(h("span", { class: "done" }, h("i"), "Applying…"));
  else if (state === "applied") foot.append(h("span", { class: "done" }, h("i"), `Applied as ${m.version}`));
  else if (state === "discarded") foot.append(h("span", { class: "done off" }, h("i"), "Discarded"));
  else if (state === "superseded") foot.append(h("span", { class: "done off" }, h("i"), "Replaced by a newer request"));
  else if (state === "stale") foot.append(h("span", { class: "done off" }, h("i"), "The edit changed since this was proposed — ask again"));
  else if (state === "failed") foot.append(h("span", { class: "done bad" }, h("i"), `Not applied: ${m.error || ""}`));
  el.append(foot);
  return el;
}
function diffViz(p) {
  const b = p.before || {}, a = p.after || {};
  const ids = Object.keys(b);
  if (!ids.length) return null;
  const span = Math.max(p.duration_before || 0, p.duration_after || 0, 0.001);
  const edited = new Set((p.diff.edited || []).map((e) => e.id)), shifted = new Set((p.diff.shifted || []).map((s) => s.id));
  const bar = (pos, cls) => h("i", { class: cls, style: `left:${(100 * pos[0]) / span}%;width:${Math.max(0.6, (100 * (pos[1] - pos[0])) / span - 0.4)}%` });
  return h("div", { class: "diffviz" },
    h("span", {}, "before"), h("div", { class: "row" }, ids.map((id) => bar(b[id], edited.has(id) ? "ch" : !a[id] ? "rm" : ""))),
    h("span", {}, "after"), h("div", { class: "row" }, ids.filter((id) => a[id]).map((id) => bar(a[id], edited.has(id) ? "ch" : shifted.has(id) ? "mv" : ""))));
}

// Pacing: steps arrive from the server faster than anyone can read; each is shown for a beat so you can follow along.
function pacer(apply) {
  const q = [];
  let busy = false, last = 0;
  async function pump() {
    if (busy) return;
    busy = true;
    while (q.length) {
      const ev = q.shift();
      const gap = ev.type === "result" ? 340 : ev.status === "running" ? 0 : 280;
      const wait = Math.max(0, gap - (performance.now() - last));
      if (wait) await sleep(wait);
      apply(ev);
      last = performance.now();
    }
    busy = false;
  }
  return { push(ev) { q.push(ev); pump(); }, async drain() { while (busy || q.length) await sleep(40); } };
}
async function streamAssistant(message, selection, onEvent) {
  const r = await fetch(`/api/studio/${enc(S.pid)}/assistant/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, selection }) });
  if (!r.ok || !r.body) { const b = await r.json().catch(() => ({})); throw new Error((b && b.detail) || r.statusText); }
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (line) onEvent(JSON.parse(line)); }
  }
  if (buf.trim()) onEvent(JSON.parse(buf));
}
async function send(text) {
  text = (text != null ? text : $("prompt").value).trim();
  if (!text || !S.pid) return;
  if (S.busy) { toast("Still working on the last request"); return; }
  if (!S.data || !S.data.timeline) { toast("There's no timeline to change yet", "bad"); return; }
  $("prompt").value = ""; autosize();
  for (const x of chat()) if (x.kind === "run" && x.state === "pending") x.state = "superseded";
  S.ghost = null;
  const sel = S.sel ? { ...S.sel } : null;
  chat().push({ id: uid(), role: "user", text, ctx: sel ? `about ${selLabel(sel)}` : null });
  const m = { id: uid(), role: "ai", kind: "run", request: text, steps: [], state: "working", t0: Date.now() };
  chat().push(m);
  S.busy = true;
  renderDirectorStatus(`Working on “${text.length > 40 ? text.slice(0, 40) + "…" : text}”`);
  renderChat(); renderTimeline();
  const tick = setInterval(() => { const e = $(`el-${m.id}`); if (e) e.textContent = `${((Date.now() - m.t0) / 1000).toFixed(1)} s`; }, 100);
  const before = positions(), sha = S.data.timeline_sha256;
  const pace = pacer((ev) => {
    if (ev.type === "step") {
      const i = m.steps.findIndex((s) => s.id === ev.id);
      if (i >= 0) m.steps[i] = ev; else m.steps.push(ev);
    } else finishRun(m, ev, before, sha);
    updateRun(m);
  });
  try {
    await streamAssistant(text, sel || {}, (ev) => pace.push(ev));
    await pace.drain();
    if (m.state === "working") { m.state = "answered"; }
  } catch (e) {
    await pace.drain();
    m.steps.push({ id: "net", label: "Couldn't reach the Studio server", detail: e.message, status: "failed" });
    m.state = "failed"; m.reply = "That request didn't go through. Check that run_studio.py is still running, then try again.";
  }
  clearInterval(tick);
  m.elapsed = Date.now() - m.t0;
  S.busy = false;
  saveChats(); updateRun(m); renderDirectorStatus(); renderTimeline();
}
function finishRun(m, ev, before, sha) {
  m.reply = ev.reply;
  if (ev.patch) {
    const main = new Set(mainItems().map((x) => x.id));
    const edited = (ev.diff.edited || []).map((e) => e.id), removed = ev.diff.removed || [];
    // Where each change is first visible: a moved start, else a moved end (a trim), else the item itself.
    const firstChange = (id) => {
      const b = before[id], a = ev.after[id];
      if (!b || !a) return (b || a || [null])[0];
      if (Math.abs(a[0] - b[0]) > 1e-3) return Math.min(a[0], b[0]);
      if (Math.abs(a[1] - b[1]) > 1e-3) return Math.min(a[1], b[1]);
      return a[0];
    };
    const ats = [...edited, ...removed].map(firstChange).filter((x) => x != null);
    m.proposal = {
      patch_id: ev.patch.patch_id, basis: ev.patch.basis, parent: sha, can_apply: ev.can_apply, explain: ev.explain, summary: ev.summary,
      warnings: ev.warnings, errors: ev.errors, diff: ev.diff, after: ev.after, duration_before: ev.duration_before, duration_after: ev.duration_after,
      before: Object.fromEntries(Object.entries(before).filter(([id]) => main.has(id))),
    };
    m.changeAt = ats.length ? Math.max(0, Math.min(...ats) - 1.0) : 0;
    m.state = "pending";
    S.ghost = { after: ev.after, edited: new Set(edited) };
  } else {
    const last = m.steps[m.steps.length - 1];
    m.state = last && last.status === "question" ? "question" : "answered";
  }
}
function restoreGhost() {
  const last = [...chat()].reverse().find((x) => x.kind === "run" && x.proposal);
  S.ghost = last && last.state === "pending" && last.proposal.parent === S.data.timeline_sha256
    ? { after: last.proposal.after, edited: new Set((last.proposal.diff.edited || []).map((e) => e.id)) } : null;
}
async function applyRun(m) {
  if (m.state !== "pending") return;
  m.state = "applying"; updateRun(m);
  const flip = positions();
  try {
    const r = await api(`/api/studio/${enc(S.pid)}/patches/${m.proposal.patch_id}/apply`, { method: "POST" });
    m.state = "applied"; m.version = r.version; m.renderFor = r.version; m.render = followable(r.job, r.version);
    m.after = [{ id: "saved", label: `Saved as ${r.version}`, status: r.warnings.length ? "warn" : "done",
      detail: [r.summary, ...(r.creative_memory && !String(r.creative_memory).startsWith("not") ? [`remembered for this channel (${r.creative_memory})`] : []), ...r.warnings.map((w) => `⚠ ${w}`)] }];
    (m.proposal.diff.edited || []).forEach((e) => S.changed.add(e.id));
    S.ghost = null; S.flipFrom = { pos: flip, sha: m.proposal.parent };
    toast(`Applied ${r.version} — rendering a fresh preview`);
    saveChats(); updateRun(m);
    await load(); poll();
  } catch (e) {
    m.state = "failed"; m.error = e.message; S.ghost = null;
    saveChats(); updateRun(m); renderTimeline();
  }
}
function discard(m) { m.state = "discarded"; S.ghost = null; saveChats(); updateRun(m); renderTimeline(); }
function watchChange(t) {
  if (!S.video) return;
  S.video.currentTime = Math.max(0, +t || 0);
  S.video.play().catch(() => {});
}
async function undo() {
  if (S.busy) return;
  const flip = positions(), sha = S.data.timeline_sha256;
  try {
    const r = await api(`/api/studio/${enc(S.pid)}/undo`, { method: "POST" });
    const m = { id: uid(), role: "ai", kind: "run", title: "Undo", steps: [{ id: "undo", label: `Restored ${r.restored.replace(".json", "")}`, status: "done", detail: `${r.undone.replace(".json", "")} is set aside (kept on disk as ${r.undone.replace(".json", ".undone.json")})` }],
      state: "applied", renderFor: `undo to ${r.restored.replace(".json", "")}`, render: followable(r.job, `undo to ${r.restored.replace(".json", "")}`), t0: Date.now(), elapsed: 0 };
    for (const x of chat()) if (x.kind === "run" && x.state === "pending") x.state = "superseded";
    chat().push(m);
    S.flipFrom = { pos: flip, sha }; S.ghost = null;
    toast(`Undone — back to ${r.restored.replace(".json", "")}`);
    saveChats(); await load(); poll();
  } catch (e) { toast(e.message, "bad"); }
}
// A render already running for something else means ours is queued behind it.
function followable(job, label) { return job && job.for === label ? job : { state: "queued", phases: [], for: label }; }
// Every run waiting on a render follows the job as it really progresses.
function onJob(j) {
  renderHud(); renderDirectorStatus();
  const sweep = $("sweep");
  if (sweep && j) sweep.style.width = `${(j.rendered_until || 0) * S.zoom}px`;
  else if (jobActive(j) && !sweep) renderTimeline();
  else if (!jobActive(j) && sweep) sweep.remove();
  if (!j) return;
  for (const m of chat()) {
    if (m.kind !== "run" || !m.renderFor || m.renderDone || m.renderFor !== j.for) continue;
    m.render = j;
    if (j.state === "done" || j.state === "failed") { m.renderDone = true; saveChats(); }
    updateRun(m);
  }
}

// ───────────────────────────────────────────────────────────── command palette
const PAL = { items: [], on: 0 };
function openPalette() {
  $("palette").hidden = false;
  $("palInput").value = "";
  put($("palSel"), S.sel ? selLabel(S.sel) : []);
  buildPalette(); $("palInput").focus();
}
function closePalette() { $("palette").hidden = true; }
function buildPalette() {
  const q = $("palInput").value.trim(), ql = q.toLowerCase();
  const items = [];
  if (q) items.push({ g: "Ask the Director", icon: "spark", label: `“${q}”`, k: "Enter", run: () => send(q) });
  suggestions().filter((s) => !ql || s.toLowerCase().includes(ql)).forEach((s) => items.push({ g: "Suggested for this selection", icon: "spark", label: s, run: () => send(s) }));
  const cmds = [
    { label: "Render a fresh preview", icon: "render", run: requestRender },
    { label: "Undo the last edit", icon: "undo", k: "Ctrl Z", run: undo },
    { label: "Fit the whole edit", icon: "fit", run: () => { S.fit = true; fitZoom(); renderTimeline(); } },
    ...mainItems().map((it, i) => ({ label: `Go to shot ${i + 1} · ${it.id} · ${itemName(mainTrack(), it)}`, icon: "jump", run: () => select({ item_id: it.id }, true) })),
  ];
  const hits = cmds.filter((c) => !ql || c.label.toLowerCase().includes(ql)).map((c) => ({ g: "Commands", ...c }));
  // A query that names a command ("shot 4", "render") means that command; anything else is a request for the Director.
  if (q && hits.length) items.unshift(...hits); else items.push(...hits);
  PAL.items = items; PAL.on = 0;
  let g = null;
  put($("palList"), items.map((it, i) => {
    const head = it.g !== g ? h("div", { class: "pal-g" }, (g = it.g)) : null;
    return [head, h("div", { class: `pal-i${i === 0 ? " on" : ""}`, "data-i": i, onmouseenter: () => palMove(i - PAL.on), onclick: () => palRun(i) }, icon(it.icon), it.label, it.k ? h("span", { class: "k" }, it.k) : null)];
  }));
}
function palMove(d) {
  if (!PAL.items.length) return;
  PAL.on = (PAL.on + d + PAL.items.length) % PAL.items.length;
  document.querySelectorAll(".pal-i").forEach((el) => el.classList.toggle("on", +el.dataset.i === PAL.on));
  const el = document.querySelector(".pal-i.on"); if (el) el.scrollIntoView({ block: "nearest" });
}
function palRun(i) { const it = PAL.items[i]; closePalette(); if (it) it.run(); }

// ───────────────────────────────────────────────────────────── wiring
function autosize() { const t = $("prompt"); t.style.height = "auto"; t.style.height = `${Math.min(140, t.scrollHeight)}px`; }
function typing() { const a = document.activeElement; return a && (a.tagName === "TEXTAREA" || a.tagName === "INPUT" || a.tagName === "SELECT"); }
function stepShot(d) {
  const items = mainItems();
  if (!items.length) return;
  const t = nowTime();
  let i = items.findIndex((it) => S.sel && S.sel.item_id === it.id);
  if (i < 0) i = Math.max(0, items.findIndex((it) => t >= it.timeline_in - 1e-3 && t < it.timeline_out));
  const nx = items[Math.max(0, Math.min(items.length - 1, i + d))];
  select({ item_id: nx.id }, true);
}
function wire() {
  $("playBtn").onclick = togglePlay;
  $("prevShot").onclick = () => stepShot(-1);
  $("nextShot").onclick = () => stepShot(1);
  $("scrub").onclick = (e) => { const r = $("scrub").getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * ((S.video && S.video.duration) || total())); };
  $("renderBtn").onclick = requestRender;
  $("undoBtn").onclick = undo;
  $("fitBtn").onclick = () => { S.fit = true; fitZoom(); renderTimeline(); };
  $("zoom").oninput = (e) => { S.zoom = +e.target.value; renderTimeline(); };
  $("lanes").onscroll = () => { $("heads").scrollTop = $("lanes").scrollTop; };
  $("send").onclick = () => send();
  $("prompt").oninput = autosize;
  $("prompt").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  $("clearChat").onclick = () => { S.chats[S.pid] = []; S.ghost = null; saveChats(); renderChat(); renderTimeline(); renderDirectorStatus(); };
  $("cmdkBtn").onclick = openPalette;
  $("palette").onclick = (e) => { if (e.target.id === "palette") closePalette(); };
  $("palInput").oninput = buildPalette;
  $("palInput").onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); palMove(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); palMove(-1); }
    else if (e.key === "Enter") { e.preventDefault(); palRun(PAL.on); }
    else if (e.key === "Escape") closePalette();
  };
  document.querySelectorAll("[data-ltab]").forEach((b) => (b.onclick = () => { S.ltab = b.dataset.ltab; renderLeft(); }));
  // timeline height
  const rz = $("resize");
  rz.onmousedown = (e) => {
    e.preventDefault();
    const y0 = e.clientY, h0 = $("timeline").getBoundingClientRect().height;
    const mv = (ev) => { const v = Math.max(170, Math.min(window.innerHeight * 0.66, h0 + (y0 - ev.clientY))); document.documentElement.style.setProperty("--tl-h", `${v}px`); };
    const up = () => {
      window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
      S.userTl = true; renderTimeline();
      try { localStorage.setItem("nos_tl_h", getComputedStyle(document.documentElement).getPropertyValue("--tl-h")); } catch (_) { /* unavailable */ }
    };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  };
  rz.ondblclick = () => { S.userTl = false; try { localStorage.removeItem("nos_tl_h"); } catch (_) { /* unavailable */ } renderTimeline(); };
  rz.title = "Drag to resize · double-click to fit the tracks";
  try { const v = localStorage.getItem("nos_tl_h"); if (v) { document.documentElement.style.setProperty("--tl-h", v); S.userTl = true; } } catch (_) { /* unavailable */ }
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); $("palette").hidden ? openPalette() : closePalette(); return; }
    if (!$("palette").hidden) return;
    if (e.key === "Escape") { if (typing()) document.activeElement.blur(); else if (S.sel) select(null); return; }
    if (typing()) return;
    if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); return; }
    if (e.key === "/") { e.preventDefault(); $("prompt").focus(); return; }
    if (e.code === "Space") { e.preventDefault(); if (document.activeElement && document.activeElement.tagName === "BUTTON") document.activeElement.blur(); togglePlay(); return; }
    const fps = (S.data && S.data.timeline && S.data.timeline.canvas.fps) || 30;
    if (e.key === "ArrowLeft") { e.preventDefault(); seek(nowTime() - (e.shiftKey ? 1 : 1 / fps)); }
    if (e.key === "ArrowRight") { e.preventDefault(); seek(nowTime() + (e.shiftKey ? 1 : 1 / fps)); }
    if (e.key === "ArrowUp") { e.preventDefault(); stepShot(-1); }
    if (e.key === "ArrowDown") { e.preventDefault(); stepShot(1); }
  });
  window.addEventListener("resize", () => { clearTimeout(S.rz); S.rz = setTimeout(() => { if (S.data) { S.fit = true; fitZoom(); renderTimeline(); } }, 150); });
  setInterval(() => document.querySelectorAll("time[data-t]").forEach((t) => (t.textContent = ago(t.dataset.t))), 15000);
  try { S.chats = JSON.parse(localStorage.getItem("nos_studio_v2") || "{}"); } catch (_) { S.chats = {}; }
  put($("playBtn"), icon("play"));
}

// Film grain: one 160×160 noise tile made once (a static image is cheap to composite; an SVG filter is not).
function makeGrain() {
  try {
    const c = document.createElement("canvas"); c.width = c.height = 160;
    const ctx = c.getContext("2d"), img = ctx.createImageData(160, 160);
    for (let i = 0; i < img.data.length; i += 4) { const v = Math.random() * 255; img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255; }
    ctx.putImageData(img, 0, 0);
    document.querySelector(".grain").style.backgroundImage = `url(${c.toDataURL("image/png")})`;
  } catch (_) { /* grain is decoration only */ }
}

makeGrain();
wire();
loadProjects().then(load).then(poll).catch((e) => { setLive(false, e.message); toast(`Couldn't reach the Studio server: ${e.message}`, "bad"); });
