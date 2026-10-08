"""NarrativeOS Studio: a live window onto a project, with a typed-patch assistant ("change this part").

Mounted by timeline_api_server.py. It is a layer on top of the pipeline, never a replacement:

- read-only views: the production graph (controller.graph_data), the multi-track timeline, assets, evidence,
  render manifest and the event log, polled cheaply so the screen never looks dead;
- one write path, typed edit patches (scripts/edit_patch.py). The assistant PROPOSES a patch and shows its diff
  and validation; nothing changes until the user applies it. Applying writes a new version of the working edit
  timeline (timeline_v3.json; every version kept under timeline_versions/, so undo works), logs an event,
  records the correction in the channel's creative memory when the project is pinned to a channel, and
  re-renders a preview in the background with live progress.

Approved timelines (timeline.json with approvals, timeline_ir.json) are never written here: the controller's
gates still decide what ships.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

REPO_ROOT = Path(os.environ.get("NARRATIVEOS_REPO_ROOT") or Path(__file__).resolve().parents[2]).resolve()
sys.path[:0] = [str(REPO_ROOT / "scripts")]
import compile_timeline as ct  # noqa: E402
import edit_patch as ep  # noqa: E402

router = APIRouter(prefix="/api/studio")
TIMELINE = "timeline_v3.json"
VERSIONS = "timeline_versions"
_jobs: dict[str, dict] = {}
_pending: dict[str, dict] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (json.JSONDecodeError, OSError):
        return default


def _root() -> Path:
    from timeline_api_server import get_project_root
    return get_project_root()


def _project(pid: str) -> Path:
    from timeline_api_server import resolve_project_path
    p = resolve_project_path(_root(), pid)
    if not p.is_dir():
        raise HTTPException(404, f"project {pid!r} not found")
    return p


def _append_event(p: Path, event: dict) -> None:
    with (p / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": _now(), "verified_real": True, **event}, ensure_ascii=False) + "\n")


def _write_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def working_timeline(p: Path) -> tuple[Optional[dict], str]:
    """The multi-track edit timeline: timeline_v3.json, else converted (in memory) from timeline.json."""
    ir = _load(p / TIMELINE)
    if ir:
        return ir, TIMELINE
    shot = _load(p / "timeline.json")
    if shot and shot.get("shots"):
        caps = _load(p / "captions.json")
        narration = next((n for n in ("narration.mp3", "narration.wav", "audio/narration.wav") if (p / n).is_file()), None)
        try:
            return ct.from_shot_timeline(shot, p, narration=narration, captions=caps), "timeline.json (converted)"
        except ct.CompileError:
            return ct.from_shot_timeline(shot, p, captions=caps), "timeline.json (converted)"
    return None, "none"


def _versions(p: Path) -> list[str]:
    """Live versions, oldest first. Undone versions (vNNN.undone.json) are kept on disk but are not in the chain."""
    d = p / VERSIONS
    return sorted(x.name for x in d.glob("v*.json") if not x.name.endswith(".undone.json")) if d.is_dir() else []


def _next_version(p: Path) -> int:
    """Never reuse a number, including undone ones, so history files are never overwritten."""
    nums = [int(x.name[1:4]) for x in (p / VERSIONS).glob("v[0-9][0-9][0-9]*.json")]
    return max(nums, default=0) + 1


def _etag(p: Path) -> str:
    parts = []
    for name in ("state.json", "events.jsonl", TIMELINE, "timeline.json", "renders/render_manifest.json", "renders/preview.mp4"):
        f = p / name
        parts.append(f"{name}:{f.stat().st_mtime_ns if f.exists() else 0}")
    job = _jobs.get(str(p)) or {}
    parts.append(f"job:{job.get('state')}:{round(job.get('progress', 0), 2)}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _events(p: Path, n: int = 60) -> list[dict]:
    f = p / "events.jsonl"
    if not f.is_file():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _pipeline(p: Path) -> dict:
    if not (p / "state.json").is_file():
        return {"present": False}
    import controller
    g = controller.graph_data(p)
    return {"present": True, "current_stage": g["current_stage"], "paused": g["paused"], "counts": g["counts"],
            "nodes": [{"stage": n["stage"], "status": n["status"], "passed_at": n["passed_at"],
                       "blocking": n["blocking"][:2], "stale": n["stale"]} for n in g["nodes"]]}


def _assets(p: Path, ir: Optional[dict]) -> dict:
    reg = ct.asset_registry(p, ir or {})
    out = {}
    for aid, a in reg.items():
        out[aid] = {"status": a.get("status"), "rights_status": a.get("rights_status") or a.get("rights"),
                    "media_type": a.get("media_type") or a.get("kind"), "file": Path(str(a.get("local_path", ""))).name,
                    "source_url": a.get("source_url"), "generated": bool(a.get("generated") or str(a.get("media_class", "")).startswith("GENERATED"))}
    return out


def _evidence(p: Path) -> dict:
    links = _load(p / "claim_visual_links.json", {}) or {}
    by_shot: dict[str, list] = {}
    for link in links.get("links", []) if isinstance(links, dict) else []:
        sid = link.get("shot_id")
        if sid:
            by_shot.setdefault(sid, []).append({k: link.get(k) for k in ("claim_id", "status", "relationship", "source_ids") if k in link})
    return by_shot


@router.get("/{pid}")
def studio(pid: str):
    p = _project(pid)
    ir, source = working_timeline(p)
    rm = _load(p / "renders" / "render_manifest.json")
    research = _load(p / "research" / "sources.json", {}) or {}
    profile = _load(p / "channel_profile.json", {}) or {}
    proj = {}
    if (p / "project.yaml").is_file():
        for line in (p / "project.yaml").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(":")
            if v.strip():
                proj[k.strip()] = v.strip()
    check = ct.validate(ir, p) if ir else {"errors": ["no timeline yet"], "warnings": [], "duration": 0}
    ev = _evidence(p)
    return {
        "project_id": pid, "name": proj.get("title") or proj.get("project_id") or pid,
        "channel": (profile.get("pin") or {}) | {"name": (profile.get("identity") or {}).get("name")} if profile.get("pin") else None,
        # Shown as the compiler will render it: caption words placed from their source, spans fitted to the picture.
        "pipeline": _pipeline(p), "timeline": ct.resolve_dynamic(ir) if ir else None, "timeline_source": source, "versions": _versions(p),
        "timeline_sha256": ep.timeline_sha(ir) if ir else None,
        "validation": {"errors": check["errors"], "warnings": check["warnings"], "duration": check["duration"]},
        "assets": _assets(p, ir), "evidence": ev,
        "render": {k: rm.get(k) for k in ("status", "output_path", "duration", "rendered_at", "mode", "unrendered", "warnings", "timeline_sha256")} if rm else None,
        "preview_url": f"/api/studio/{pid}/preview" if (p / "renders" / "preview.mp4").is_file() else None,
        "job": _public_job(_jobs.get(str(p))), "events": _events(p),
        "assistant": {"rules": True, "provider": (lambda c: f"{c.get('name', 'provider')}/{c.get('model', '?')}" if c else None)(_provider(p))},
        "vfx_recipes": _vfx_recipes(),
        "stats": {"duration": check["duration"], "clips": len(next((t["items"] for t in (ir or {}).get("tracks", []) if t["kind"] == "video"), [])),
                  "sources": len(research.get("sources", [])) if isinstance(research, dict) else 0,
                  "evidence_links": sum(len(v) for v in ev.values())},
        "etag": _etag(p), "loaded_at": _now(),
    }


@router.get("/{pid}/poll")
def poll(pid: str, etag: str = ""):
    p = _project(pid)
    now = _etag(p)
    return {"changed": now != etag, "etag": now, "job": _public_job(_jobs.get(str(p))), "events": _events(p, 8)}


@router.get("/{pid}/thumb/{item_id}")
def thumb(pid: str, item_id: str, t: Optional[float] = None):
    p = _project(pid)
    ir, _ = working_timeline(p)
    if not ir:
        raise HTTPException(404, "no timeline")
    try:
        _, it = ep.find(ir, item_id)
    except ep.PatchError:
        raise HTTPException(404, "no such item")
    asset = ct.asset_registry(p, ir).get(it.get("asset_id", ""))
    if not asset:
        raise HTTPException(404, "item has no picture")
    try:
        src = ct.resolve_path(p, asset)
    except ct.CompileError:
        raise HTTPException(403, "asset outside allowed roots")
    at = float(it.get("source_in", 0)) + (t if t is not None else (float(it["timeline_out"]) - float(it["timeline_in"])) / 2)
    key = hashlib.sha1(f"{src}|{src.stat().st_mtime_ns if src.exists() else 0}|{at:.2f}".encode()).hexdigest()[:16]
    out = p / "renders" / "thumbs" / f"{key}.jpg"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        image = src.suffix.lower() in ct.IMAGE_EXT
        cmd = ["ffmpeg", "-v", "error", "-y", *([] if image else ["-ss", f"{at:.3f}"]), "-i", str(src), "-frames:v", "1", "-vf", "scale=240:-2", str(out)]
        if subprocess.run(cmd, capture_output=True).returncode or not out.is_file():
            raise HTTPException(500, "thumbnail failed")
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@router.get("/{pid}/preview")
def preview(pid: str):
    p = _project(pid)
    f = p / "renders" / "preview.mp4"
    if not f.is_file():
        raise HTTPException(404, "no preview rendered yet")
    return FileResponse(f, media_type="video/mp4", headers={"Cache-Control": "no-cache"})


# ----------------------------------------------------------------------------------------------- render jobs
def _render(p: Path, ir: dict) -> None:
    """Compile the preview, publishing what the compiler is really doing: its phases (with what each found) and
    FFmpeg's own frame/fps/speed counters. ETA is an extrapolation from the measured rate and says so."""
    key = str(p)
    job = _jobs[key]
    t_encode = [0.0]
    try:
        def on_phase(name: str, detail: dict) -> None:
            now = time.perf_counter()
            if job["phases"] and job["phases"][-1]["name"] == name:  # progress of the same phase (graphics): update it
                job["phases"][-1]["detail"] = detail
                if name == "graphics":
                    job["progress_graphics"] = detail.get("progress", 0)
                return
            if job["phases"]:
                job["phases"][-1]["ms"] = round((now - job["phases"][-1]["_t"]) * 1000)
            if name == "encode":
                t_encode[0] = now
                job["stats"] = {"frame": 0, "frames": detail["frames"], "fps": None, "speed": None, "eta_s": None}
            job["phases"].append({"name": name, "detail": detail, "at": _now(), "_t": now})
            job["phase"] = name

        def prog(f: float, stats: dict) -> None:
            job["progress"] = round(f, 3)
            elapsed = time.perf_counter() - t_encode[0]
            eta = round(elapsed * (1 - f) / f, 1) if f > 0.02 else None
            job["stats"] = {**job.get("stats", {}), **{k: v for k, v in stats.items() if v is not None}, "eta_s": eta}
            job["rendered_until"] = round(f * float(job.get("duration") or 0), 3)

        job.update(state="rendering", started_at=_now(), phases=[], duration=ct.validate(ir, p)["duration"])
        m = ct.compile_timeline(p, ir, Path("renders/preview.mp4"), preview=True, progress=prog, phase=on_phase)
        if job["phases"]:
            job["phases"][-1]["ms"] = round((time.perf_counter() - job["phases"][-1]["_t"]) * 1000)
        ver = m.get("verification") or {}
        job.update(state="done", progress=1.0, finished_at=_now(), rendered_until=m["duration"],
                   manifest={k: m[k] for k in ("status", "duration", "unrendered", "warnings", "timeline_sha256", "size_bytes")},
                   verification={"passed": ver.get("passed"), "av_delta_ms": ver.get("av_delta_ms"), "duration": ver.get("duration")})
        _append_event(p, {"action": "preview_rendered", "duration": m["duration"], "timeline_sha256": m["timeline_sha256"], "for": job.get("for")})
    except Exception as e:  # noqa: BLE001 - surfaced to the UI as the job's error
        job.update(state="failed", error=str(e)[-1500:], finished_at=_now())
        _append_event(p, {"action": "preview_failed", "error": str(e)[-300:]})
    finally:
        for ph in job.get("phases", []):
            ph.pop("_t", None)
        nxt = job.pop("next", None)
        if nxt is not None:
            _start_render(p, *nxt)


def _start_render(p: Path, ir: dict, label: str = "preview") -> dict:
    key = str(p)
    with _lock:
        job = _jobs.get(key)
        if job and job.get("state") in ("queued", "rendering"):
            job["next"] = (ir, label)  # render the newest version once the current one finishes
            return job
        _jobs[key] = {"state": "queued", "progress": 0.0, "queued_at": _now(), "for": label, "phases": []}
    threading.Thread(target=_render, args=(p, ir), daemon=True).start()
    return _jobs[key]


def _public_job(job: Optional[dict]) -> Optional[dict]:
    if not job:
        return None
    snap = dict(job)  # the render thread keeps writing: work on a C-level copy, never iterate the live dict
    out = {k: v for k, v in snap.items() if k != "next"}
    out["phases"] = [{k: v for k, v in dict(ph).items() if k != "_t"} for ph in list(snap.get("phases", []))]
    out["queued_next"] = "next" in snap
    return out


class RenderRequest(BaseModel):
    reason: str = "requested from Studio"


@router.post("/{pid}/render")
def render(pid: str, req: RenderRequest = RenderRequest()):
    p = _project(pid)
    ir, _ = working_timeline(p)
    if not ir:
        raise HTTPException(400, "no timeline to render")
    check = ct.validate(ir, p)
    if check["errors"]:
        raise HTTPException(400, {"message": "the timeline does not validate", "errors": check["errors"]})
    return _public_job(_start_render(p, ir, "requested"))


# ----------------------------------------------------------------------------------------------- assistant and patches
class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    selection: dict = Field(default_factory=dict)


def _vfx_recipes() -> list[dict]:
    """The registered VFX transition recipes, when the Remotion project can run here (else none: never guessed)."""
    try:
        import remotion_bridge as rb
        if not rb.available()[0]:
            return []
        return [{k: r[k] for k in ("id", "label", "meaning", "intensity")} for r in rb.registry()["transitions"]]
    except Exception:  # noqa: BLE001 - recipes are optional; the assistant still handles native transitions
        return []


def _provider(p: Path) -> Optional[dict]:
    cfg = _load(p / "studio_provider.json") or (_load(Path(os.environ["NARRATIVEOS_REASONING_PROVIDER"])) if os.environ.get("NARRATIVEOS_REASONING_PROVIDER") else None)
    return cfg if isinstance(cfg, dict) and cfg.get("type") == "command" else None


def _tc(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def _track_label(t: dict) -> str:
    if t["kind"] == "audio":
        return {"narration": "voiceover", "music": "music", "sfx": "sfx", "ambience": "ambience"}.get(t.get("role"), t["id"])
    return {"video": "video", "overlay": "overlay", "caption": "caption"}.get(t["kind"], t["id"])


def _length(ir: dict) -> float:
    return max((float(i["timeline_out"]) for t in ir.get("tracks", []) for i in t.get("items", [])), default=0.0)


def assistant_run(p: Path, message: str, selection: dict):
    """The assistant's work as it happens. Every step is something the server actually did, with what it found
    and how long it took; the last event is the result. Nothing is written here: applying is a separate request."""
    clock = time.perf_counter()

    def step(sid: str, label: str, detail, status: str = "done", **extra) -> dict:
        nonlocal clock
        now = time.perf_counter()
        ev = {"type": "step", "id": sid, "label": label, "detail": detail, "status": status, "ms": round((now - clock) * 1000, 1), **extra}
        clock = now
        return ev

    def result(reply: str, **extra) -> dict:
        return {"type": "result", "reply": reply, "patch": None, **extra}

    ir, source = working_timeline(p)
    if not ir:
        yield step("read", "Read the edit", "There is no timeline yet: the pipeline has not built one.", "failed")
        yield result("There's no timeline to change yet. Its progress is in the pipeline on the left.")
        return
    main = ep.main_track(ir)
    shots = len(main["items"]) if main else 0
    yield step("read", "Read the edit", f"{source} · {shots} shots on {len(ir['tracks'])} tracks · {_length(ir):.1f} s · #{ep.timeline_sha(ir)[:7]}")

    # What the user is pointing at.
    sel = selection or {}
    if sel.get("item_id"):
        try:
            t, it = ep.find(ir, sel["item_id"])
            asset = ct.asset_registry(p, ir).get(it.get("asset_id", ""), {})
            name = Path(str(asset.get("local_path", ""))).name or it.get("text") or it.get("asset_id") or ""
            yield step("focus", "Found what you mean", f"{it['id']} · {_track_label(t)} · {name} · {_tc(it['timeline_in'])} → {_tc(it['timeline_out'])}",
                       item_id=it["id"])
        except ep.PatchError:
            yield step("focus", "Found what you mean", f"{sel['item_id']} is no longer on the timeline; reading the request on its own", "warn")
            sel = {}
    elif sel.get("from") is not None and sel.get("to") is not None:
        inside = [x["id"] for x in (main["items"] if main else []) if float(sel["from"]) - 1e-6 <= float(x["timeline_in"]) < float(sel["to"])]
        yield step("focus", "Found what you mean", f"{_tc(sel['from'])} → {_tc(sel['to'])} · shots starting here: {', '.join(inside) or 'none'}",
                   range=[sel["from"], sel["to"]])
    else:
        yield step("focus", "Found what you mean", "Nothing selected: reading the request on its own")

    # What the request means.
    assets = set(ct.asset_registry(p, ir))
    recipes = {r["id"] for r in _vfx_recipes()}
    r = ep.interpret(message, ir, sel, assets, recipes)
    basis = "rules"
    if r["understood"] and r["operations"]:
        yield step("understand", "Understood the request", [ep.explain(op, ir) for op in r["operations"]], basis="rules")
    elif not r["understood"] and _provider(p):
        prov = _provider(p)
        who = f"{prov.get('name', 'provider')}/{prov.get('model', '?')}"
        yield step("understand", "Understood the request", f"The editing rules don't cover this; asking the reasoning provider {who}", "running")
        try:
            r, basis = ep.ask_provider(ir, message, sel, assets, prov)
        except Exception as e:  # noqa: BLE001 - a provider failure is reported, never hidden
            yield step("understand", "Understood the request", f"{who} failed: {str(e)[:200]}", "failed")
            yield result(f"The reasoning provider couldn't help with that: {e}")
            return
        yield step("understand", "Understood the request", [ep.explain(op, ir) for op in r["operations"]] or "The provider proposed no change", basis=basis)
    else:
        yield step("understand", "Understood the request", "Needs one more detail before anything can change", "question")
        yield result(r["reply"])
        return
    patch = ep.make_patch(ir, message, sel, r["operations"], basis)
    if not patch:
        yield result(r["reply"])
        return

    # Try it on a copy.
    try:
        res = ep.apply(ir, patch, check=False)
    except ep.PatchError as e:
        yield step("simulate", "Tried it on a copy", str(e), "failed")
        yield result(f"{r['reply']} …but it can't be applied: {e}")
        return
    d = res["diff"]
    moves = sorted({s["by"] for s in d["shifted"]})
    detail = [ep.describe(res)]
    if moves:
        detail.append(f"{len(d['shifted'])} item(s) slide {', '.join(f'{m:+.2f} s' for m in moves)} to stay in sync")
    detail += [f"⚠ {w}" for w in res["warnings"]]
    yield step("simulate", "Tried it on a copy", detail, "warn" if res["warnings"] else "done")

    # Check it the way the renderer will.
    v = ct.validate(res["timeline"], p)
    before, after = _length(ir), _length(res["timeline"])
    vdetail = [f"source ranges, handles, overlaps, approvals, paths: {len(v['errors'])} error(s), {len(v['warnings'])} warning(s)",
               f"new length {after:.2f} s ({after - before:+.2f} s)"] + [f"✕ {e}" for e in v["errors"][:4]]
    yield step("validate", "Checked it with the compiler", vdetail, "failed" if v["errors"] else "done")

    _pending[patch["patch_id"]] = {"project": str(p), "patch": patch}
    positions = {i["id"]: [float(i["timeline_in"]), float(i["timeline_out"])] for t in res["timeline"]["tracks"] for i in t["items"]}
    yield result(r["reply"], patch=patch, diff=d, summary=ep.describe(res), warnings=res["warnings"], errors=v["errors"],
                 can_apply=not v["errors"], explain=[ep.explain(op, ir) for op in patch["operations"]], after=positions,
                 duration_before=before, duration_after=after)


@router.post("/{pid}/assistant")
def assistant(pid: str, req: AssistantRequest):
    p = _project(pid)
    last = None
    for ev in assistant_run(p, req.message, req.selection):
        last = ev
    return {k: v for k, v in last.items() if k != "type"}


@router.post("/{pid}/assistant/stream")
def assistant_stream(pid: str, req: AssistantRequest):
    """Same as /assistant, but one JSON line per step as it happens (application/x-ndjson)."""
    p = _project(pid)

    def lines():
        try:
            for ev in assistant_run(p, req.message, req.selection):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 - the stream must end with a result the UI can show
            yield json.dumps({"type": "result", "reply": f"Something went wrong: {e}", "patch": None}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{pid}/wave/{item_id}")
def wave(pid: str, item_id: str, n: int = 160):
    """Peak envelope of an item's sound (its own audio, or a video clip's native sound), MEASURED from the samples:
    peak |sample| / full scale per bucket, 0..1. Cached by source, range and bucket count."""
    p = _project(pid)
    ir, _ = working_timeline(p)
    if not ir:
        raise HTTPException(404, "no timeline")
    try:
        _, it = ep.find(ir, item_id)
    except ep.PatchError:
        raise HTTPException(404, "no such item")
    asset = ct.asset_registry(p, ir).get(it.get("asset_id", ""))
    if not asset:
        raise HTTPException(404, "item has no sound")
    try:
        src = ct.resolve_path(p, asset)
    except ct.CompileError:
        raise HTTPException(403, "asset outside allowed roots")
    n = max(8, min(1200, n))
    start, length = float(it.get("source_in", 0)), float(it["timeline_out"]) - float(it["timeline_in"])
    key = hashlib.sha1(f"{src}|{src.stat().st_mtime_ns if src.exists() else 0}|{start:.3f}|{length:.3f}|{n}".encode()).hexdigest()[:16]
    out = p / "renders" / "waves" / f"{key}.json"
    if out.is_file():
        return _load(out)
    import numpy as np
    sr = 8000
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr),
                        "-f", "s16le", "-"], capture_output=True)
    pcm = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0 if not r.returncode else np.zeros(0, np.float32)
    if pcm.size == 0:
        body = {"item_id": item_id, "peaks": [], "has_audio": False}
    else:
        edges = np.linspace(0, pcm.size, n + 1).astype(int)
        peaks = [float(np.abs(pcm[a:b]).max()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]
        body = {"item_id": item_id, "peaks": [round(x, 4) for x in peaks], "has_audio": True,
                "peak_dbfs": round(20 * float(np.log10(max(max(peaks), 1e-6))), 1), "sample_rate": sr}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body), encoding="utf-8")
    return body


def _record_memory(p: Path, patch: dict, res: dict) -> Optional[str]:
    profile = _load(p / "channel_profile.json", {}) or {}
    pin = profile.get("pin")
    if not pin:
        return None
    try:
        import creative_memory
        targets = [e["id"] for e in res["diff"]["edited"]] + res["diff"]["removed"]
        rec = creative_memory.record(pin["channel_id"], p.name, "TIMELINE", ",".join(targets) or "timeline", "corrected", patch["request"],
                                     before=None, after={"operations": patch["operations"]}, tags=["studio"] + sorted({o["op"] for o in patch["operations"]}))
        return rec["id"]
    except Exception as e:  # noqa: BLE001 - memory is best-effort; the edit itself already succeeded
        return f"not recorded: {e}"


@router.post("/{pid}/patches/{patch_id}/apply")
def apply_patch(pid: str, patch_id: str):
    p = _project(pid)
    pend = _pending.get(patch_id)
    if not pend or pend["project"] != str(p):
        raise HTTPException(404, "unknown or expired patch; ask the assistant again")
    ir, source = working_timeline(p)
    try:
        res = ep.apply(ir, pend["patch"], p)
    except ep.PatchError as e:
        raise HTTPException(409, str(e))
    if res["validation"]["errors"]:
        raise HTTPException(400, {"message": "the edit does not validate", "errors": res["validation"]["errors"]})
    vdir = p / VERSIONS
    vdir.mkdir(exist_ok=True)
    if not _versions(p):
        _write_atomic(vdir / "v001.json", ir)  # the starting point, so the first edit can be undone
    n = _next_version(p)
    _write_atomic(vdir / f"v{n:03d}.json", res["timeline"])
    _write_atomic(p / TIMELINE, res["timeline"])
    mem = _record_memory(p, pend["patch"], res)
    _append_event(p, {"action": "patch_applied", "patch_id": patch_id, "request": pend["patch"]["request"], "basis": pend["patch"]["basis"],
                      "operations": pend["patch"]["operations"], "summary": ep.describe(res), "version": f"v{n:03d}", "creative_memory": mem})
    _pending.pop(patch_id, None)
    job = _start_render(p, res["timeline"], f"v{n:03d}")
    return {"version": f"v{n:03d}", "summary": ep.describe(res), "warnings": res["warnings"], "creative_memory": mem,
            "job": _public_job(job)}


@router.post("/{pid}/undo")
def undo(pid: str):
    p = _project(pid)
    vs = _versions(p)
    if len(vs) < 2:
        raise HTTPException(400, "nothing to undo")
    prev = _load(p / VERSIONS / vs[-2])
    (p / VERSIONS / vs[-1]).rename(p / VERSIONS / (vs[-1].replace(".json", ".undone.json")))
    _write_atomic(p / TIMELINE, prev)
    _append_event(p, {"action": "patch_undone", "restored": vs[-2]})
    job = _start_render(p, prev, f"undo to {vs[-2][:-5]}")
    return {"restored": vs[-2], "undone": vs[-1], "job": _public_job(job)}


@router.get("/")
def projects():
    root = _root()
    out = []
    for d in sorted(x for x in root.iterdir() if x.is_dir()) if root.is_dir() else []:
        if any((d / f).is_file() for f in ("state.json", TIMELINE, "timeline.json")):
            out.append({"project_id": d.name, "has_timeline": (d / TIMELINE).is_file() or (d / "timeline.json").is_file(),
                        "has_preview": (d / "renders" / "preview.mp4").is_file(), "modified": time.ctime(d.stat().st_mtime)})
    return {"root": str(root), "projects": out}
