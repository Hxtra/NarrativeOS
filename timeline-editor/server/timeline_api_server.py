#!/usr/bin/env python3
"""
NarrativeOS Timeline API Server

Read-only state adapter for NarrativeOS production artifacts, plus a narrow,
validated write path for EDITORIAL_QA timeline revisions.

This server does not invent data. Every field it returns is read directly
from a JSON artifact on disk. If an artifact is missing, the API says so
explicitly (missing: true) rather than fabricating a default value that
could be mistaken for real production state.

Verified against actual output of:
    scripts/simulate_documentary.py
    scripts/controller.py --init

Two project shapes exist in NarrativeOS today and this server supports both:

1. Simulation projects (scripts/simulate_documentary.py)
   - Flat layout: qa_plan.json, no qa/ subfolder, no assets.json
   - approved_assets.json has: shot_id, asset_id, status, rights_status,
     evidence_frame_paths, usable_interval (NOT sha256, NOT narration)
   - No events.jsonl (simulation calls scripts directly, not controller.run)

2. Controller-driven projects (scripts/controller.py --init, then staged)
   - assets.json exists (starts as {"assets": []} stub)
   - qa/technical_qa.json, qa/editorial_qa.json, qa/delivery_review.json
   - events.jsonl is append-only, written by controller.py on every stage

This server does NOT assume either shape is present. It probes for what
exists and reports missing artifacts as missing, not as errors that crash
the whole response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("timeline_api")

def get_repo_root() -> Path:
    """Locate NarrativeOS explicitly, with a checkout-relative fallback."""
    import os
    configured = os.environ.get("NARRATIVEOS_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


REPO_ROOT = get_repo_root()
CONTROLLER_SCRIPT = REPO_ROOT / "scripts" / "controller.py"
TIMELINE_IR_SCRIPT = REPO_ROOT / "scripts" / "timeline_ir.py"

app = FastAPI(title="NarrativeOS Timeline API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Artifact loading — explicit about what's missing, never silently defaults
# ---------------------------------------------------------------------------

class ArtifactResult:
    """Wraps a loaded artifact plus whether it was actually present on disk."""

    __slots__ = ("data", "present", "error")

    def __init__(self, data: Any, present: bool, error: Optional[str] = None):
        self.data = data
        self.present = present
        self.error = error

    def to_response(self) -> dict:
        out: dict = {"present": self.present, "data": self.data}
        if self.error:
            out["error"] = self.error
        return out


def load_artifact(project_path: Path, relative_path: str) -> ArtifactResult:
    """Load a single JSON artifact. Never raises. Reports absence explicitly."""
    full_path = project_path / relative_path
    if not full_path.is_file():
        return ArtifactResult(data=None, present=False)
    try:
        text = full_path.read_text(encoding="utf-8")
        return ArtifactResult(data=json.loads(text), present=True)
    except json.JSONDecodeError as e:
        logger.warning("Corrupt JSON in %s: %s", full_path, e)
        return ArtifactResult(data=None, present=True, error=f"invalid_json: {e}")
    except OSError as e:
        logger.warning("Cannot read %s: %s", full_path, e)
        return ArtifactResult(data=None, present=False, error=f"read_error: {e}")


def load_events_jsonl(project_path: Path, since: int = 0, limit: int = 500) -> tuple[list[dict], bool]:
    """
    Load events.jsonl if present. Not all projects have one:
    scripts/simulate_documentary.py does not write it (it calls stage
    scripts directly, bypassing scripts/controller.py's run() which is
    the only thing that appends to events.jsonl).
    """
    events_path = project_path / "events.jsonl"
    if not events_path.is_file():
        return [], False

    events: list[dict] = []
    try:
        with events_path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < since:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed line %d in events.jsonl", i)
                if len(events) >= limit:
                    break
    except OSError as e:
        logger.warning("Cannot read events.jsonl: %s", e)
        return [], False

    return events, True


def resolve_project_path(project_root: Path, project_id: str) -> Path:
    """
    Resolve a project_id to a path under project_root, rejecting anything
    that would escape project_root via '..' or an absolute path. project_id
    arrives from the URL path, i.e. untrusted input.
    """
    if not project_id or "/" in project_id or "\\" in project_id or project_id in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid project_id")

    candidate = (project_root / project_id).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    return candidate


def get_project_root() -> Path:
    import os
    root = os.environ.get("NARRATIVEOS_PROJECT_ROOT", "/tmp/narrativeos-projects")
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


ALLOWED_MEDIA_ROOTS = {"footage", "frames", "previews", "assets", "audio"}


def resolve_media_path(project_path: Path, media_path: str) -> Path:
    """Resolve a media URL without allowing traversal or arbitrary file reads."""
    if not media_path or media_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid media path")
    parts = Path(media_path).parts
    if not parts or parts[0] not in ALLOWED_MEDIA_ROOTS or any(p in ("", ".", "..") for p in parts):
        raise HTTPException(status_code=400, detail="Media must be under an allowed project media directory")
    candidate = (project_path / Path(*parts)).resolve()
    try:
        candidate.relative_to(project_path.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return candidate


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Evidence validation — mirrors the real fields present in approved_assets.json
# ---------------------------------------------------------------------------

REQUIRED_EVIDENCE_FRAMES = 3


def evidence_status_for_shot(shot_id: str, approved_assets: Optional[dict]) -> dict:
    """
    Determine display status for a shot based on approved_assets.json.

    Real field set observed from scripts/simulate_documentary.py and
    scripts/build_timeline.py output:
        shot_id, asset_id, status, rights_status, evidence_frame_paths,
        usable_interval

    NOTE: sha256 and source_url are NOT present in approved_assets.json in
    either the simulation or controller-driven path as currently written
    in scripts/acquire_assets.py / scripts/simulate_documentary.py. Those
    fields live on assets.json / asset_candidates.json entries instead, and
    only in the manual acquisition path. This function does not require
    them, and the UI does not claim to show a hash it never received.
    """
    if not approved_assets or "assets" not in approved_assets:
        return {
            "level": "red",
            "reasons": ["no_approved_assets_artifact"],
        }

    entry = next(
        (a for a in approved_assets.get("assets", []) if a.get("shot_id") == shot_id),
        None,
    )
    if entry is None:
        return {"level": "red", "reasons": ["shot_not_in_approved_assets"]}

    reasons = []
    frame_count = len(entry.get("evidence_frame_paths") or [])
    if frame_count < REQUIRED_EVIDENCE_FRAMES:
        reasons.append(f"insufficient_evidence_frames ({frame_count}/{REQUIRED_EVIDENCE_FRAMES})")

    rights = entry.get("rights_status")
    if rights not in ("verified", "public-domain-simulation"):
        reasons.append(f"rights_not_verified (status={rights!r})")

    status = entry.get("status")
    if status not in ("approved", "simulation_approved"):
        reasons.append(f"asset_not_approved (status={status!r})")

    if not reasons:
        level = "yellow" if status == "simulation_approved" else "green"
    else:
        level = "red"

    return {
        "level": level,
        "reasons": reasons,
        "asset_id": entry.get("asset_id"),
        "rights_status": rights,
        "evidence_frame_count": frame_count,
        "usable_interval": entry.get("usable_interval"),
        "is_simulation": status == "simulation_approved",
    }


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RevisionRequest(BaseModel):
    """
    A proposed edit to a shot's timing during EDITORIAL_QA.

    This does NOT modify timeline.json directly. It is validated, then
    (if valid) applied and re-validated via scripts/timeline_ir.py before
    being persisted. If timeline_ir.py reports errors, the revision is
    rejected and timeline.json is left untouched.
    """
    shot_id: str = Field(..., min_length=1, max_length=128)
    new_start: Optional[float] = None
    new_end: Optional[float] = None
    reason: str = Field(..., min_length=1, max_length=1000)

    @field_validator("new_start", "new_end")
    @classmethod
    def non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("timing values must be non-negative")
        return v


# ---------------------------------------------------------------------------
# WebSocket connection registry
# ---------------------------------------------------------------------------

_connections: dict[str, set[WebSocket]] = {}
_connections_lock = asyncio.Lock()


async def register_connection(project_id: str, ws: WebSocket) -> None:
    async with _connections_lock:
        _connections.setdefault(project_id, set()).add(ws)


async def unregister_connection(project_id: str, ws: WebSocket) -> None:
    async with _connections_lock:
        conns = _connections.get(project_id)
        if conns:
            conns.discard(ws)
            if not conns:
                _connections.pop(project_id, None)


async def broadcast(project_id: str, message: dict) -> None:
    async with _connections_lock:
        conns = list(_connections.get(project_id, ()))
    dead: list[WebSocket] = []
    for ws in conns:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    if dead:
        async with _connections_lock:
            for ws in dead:
                _connections.get(project_id, set()).discard(ws)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    ffmpeg_present = _which("ffmpeg") is not None
    ffprobe_present = _which("ffprobe") is not None
    return {
        "status": "ok",
        "service": "narrativeos-timeline-api",
        "ffmpeg_available": ffmpeg_present,
        "ffprobe_available": ffprobe_present,
        "controller_script_found": CONTROLLER_SCRIPT.is_file(),
    }


def _which(binary: str) -> Optional[str]:
    import shutil
    return shutil.which(binary)


@app.get("/api/project/{project_id}")
async def get_project(project_id: str):
    """
    Load everything the timeline UI needs in one call.

    Every key in the response is either:
      - {"present": true, "data": ...}  the artifact exists and parsed, or
      - {"present": false, "data": None}  the artifact does not exist

    The UI must check `present` before rendering — a missing artifact is
    not the same as an empty one, and conflating the two hides real
    production gaps (e.g. "no approved assets yet" vs "assets.json was
    never created because this is a simulation project").
    """
    project_root = get_project_root()
    project_path = resolve_project_path(project_root, project_id)

    if not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    artifacts = {
        "timeline": load_artifact(project_path, "timeline.json"),
        "timeline_ir": load_artifact(project_path, "timeline_ir.json"),
        "approved_assets": load_artifact(project_path, "approved_assets.json"),
        "assets": load_artifact(project_path, "assets.json"),
        "shot_specs": load_artifact(project_path, "shot_specs.json"),
        "beat_map": load_artifact(project_path, "beat_map.json"),
        "script": load_artifact(project_path, "script.json"),
        "claim_ledger": load_artifact(project_path, "claim_ledger.json"),
        "claim_visual_links": load_artifact(project_path, "claim_visual_links.json"),
        "entity_bible": load_artifact(project_path, "entity_bible.json"),
        "audio_events": load_artifact(project_path, "audio_events.json"),
        "editorial_analysis": load_artifact(project_path, "editorial_analysis.json"),
        "qa_plan": load_artifact(project_path, "qa_plan.json"),
        "qa_technical": load_artifact(project_path, "qa/technical_qa.json"),
        "qa_editorial": load_artifact(project_path, "qa/editorial_qa.json"),
        "state": load_artifact(project_path, "state.json"),
        "integration_report": load_artifact(project_path, "integration_report.json"),
    }

    # Evidence status per shot, computed from whichever asset artifact is
    # actually present (approved_assets.json in both known project shapes).
    evidence_by_shot: dict[str, dict] = {}
    timeline_data = artifacts["timeline"].data
    if artifacts["timeline"].present and timeline_data:
        approved = artifacts["approved_assets"].data if artifacts["approved_assets"].present else None
        for shot in timeline_data.get("shots", []):
            shot_id = shot.get("shot_id")
            if shot_id:
                evidence_by_shot[shot_id] = evidence_status_for_shot(shot_id, approved)

    events, events_present = load_events_jsonl(project_path)

    return {
        "project_id": project_id,
        "artifacts": {k: v.to_response() for k, v in artifacts.items()},
        "evidence_by_shot": evidence_by_shot,
        "events": {"present": events_present, "items": events},
        "loaded_at": now_iso(),
    }


@app.get("/api/project/{project_id}/evidence/{shot_id}")
async def get_shot_evidence(project_id: str, shot_id: str):
    """Full context for one shot, assembled only from artifacts that exist."""
    project_root = get_project_root()
    project_path = resolve_project_path(project_root, project_id)

    if not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    timeline = load_artifact(project_path, "timeline.json")
    if not timeline.present:
        raise HTTPException(status_code=404, detail="timeline.json not present in this project")

    shot = next((s for s in timeline.data.get("shots", []) if s.get("shot_id") == shot_id), None)
    if shot is None:
        raise HTTPException(status_code=404, detail=f"Shot '{shot_id}' not found in timeline.json")

    approved_assets = load_artifact(project_path, "approved_assets.json")
    shot_specs = load_artifact(project_path, "shot_specs.json")
    claim_links = load_artifact(project_path, "claim_visual_links.json")
    claim_ledger = load_artifact(project_path, "claim_ledger.json")
    audio_events = load_artifact(project_path, "audio_events.json")
    editorial = load_artifact(project_path, "editorial_analysis.json")

    spec = None
    if shot_specs.present:
        spec = next((s for s in shot_specs.data.get("shots", []) if s.get("shot_id") == shot_id), None)

    links = []
    if claim_links.present:
        links = [l for l in claim_links.data.get("links", []) if l.get("shot_id") == shot_id]

    linked_claim_ids = {l.get("claim_id") for l in links if l.get("claim_id")}
    claims = []
    if claim_ledger.present and linked_claim_ids:
        claims = [c for c in claim_ledger.data.get("claims", []) if c.get("claim_id") in linked_claim_ids]

    overlapping_audio = []
    if audio_events.present:
        s_start, s_end = float(shot.get("start", 0)), float(shot.get("end", 0))
        for ev in audio_events.data.get("events", []):
            ev_start = float(ev.get("start", 0))
            ev_end = ev_start + float(ev.get("duration", 0)) if "duration" in ev else float(ev.get("end", ev_start))
            if ev_start < s_end and ev_end > s_start:
                overlapping_audio.append(ev)

    editorial_decision = None
    if editorial.present:
        for d in editorial.data.get("silence_candidates", []):
            if d.get("shot_id") == shot_id:
                editorial_decision = d
                break

    evidence = evidence_status_for_shot(shot_id, approved_assets.data if approved_assets.present else None)

    return {
        "shot_id": shot_id,
        "shot": shot,
        "shot_spec": {"present": spec is not None, "data": spec},
        "evidence": evidence,
        "claim_links": links,
        "claims": claims,
        "overlapping_audio_events": overlapping_audio,
        "editorial_note": editorial_decision,
    }


@app.get("/api/project/{project_id}/events")
async def get_events(project_id: str, since: int = 0, limit: int = 500):
    project_root = get_project_root()
    project_path = resolve_project_path(project_root, project_id)

    if not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    events, present = load_events_jsonl(project_path, since=since, limit=limit)
    return {"present": present, "items": events, "count": len(events)}


@app.get("/api/project/{project_id}/media/{media_path:path}")
async def get_media(project_id: str, media_path: str):
    """Stream a verified local footage/frame/preview file to the editor."""
    project_root = get_project_root()
    project_path = resolve_project_path(project_root, project_id)
    if not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    media_file = resolve_media_path(project_path, media_path)
    return FileResponse(media_file)


@app.post("/api/project/{project_id}/revision")
async def submit_revision(project_id: str, revision: RevisionRequest):
    """
    Apply a shot timing revision, but only after re-running
    scripts/timeline_ir.py to validate the result. If validation fails,
    the change is rejected and timeline.json is restored from backup.

    The server enforces the EDITORIAL_QA gate as defense in depth. The caller
    may hide editing controls, but a direct API caller cannot bypass the
    project's persisted stage state.
    """
    project_root = get_project_root()
    project_path = resolve_project_path(project_root, project_id)

    if not project_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    state = load_artifact(project_path, "state.json")
    if not state.present or not isinstance(state.data, dict):
        raise HTTPException(status_code=409, detail="Revision requires state.json with current_stage=EDITORIAL_QA")
    if state.data.get("current_stage") != "EDITORIAL_QA":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Revisions are only allowed during EDITORIAL_QA",
                "current_stage": state.data.get("current_stage"),
            },
        )

    timeline_path = project_path / "timeline.json"
    timeline = load_artifact(project_path, "timeline.json")
    if not timeline.present:
        raise HTTPException(status_code=404, detail="timeline.json not present")

    shots = timeline.data.get("shots", [])
    shot_index = next((i for i, s in enumerate(shots) if s.get("shot_id") == revision.shot_id), None)
    if shot_index is None:
        raise HTTPException(status_code=404, detail=f"Shot '{revision.shot_id}' not found")

    before = dict(shots[shot_index])
    backup_text = timeline_path.read_text(encoding="utf-8")

    if revision.new_start is not None:
        shots[shot_index]["start"] = revision.new_start
    if revision.new_end is not None:
        shots[shot_index]["end"] = revision.new_end

    if shots[shot_index]["end"] <= shots[shot_index]["start"]:
        raise HTTPException(status_code=422, detail="Resulting shot would have end <= start")

    timeline_path.write_text(json.dumps(timeline.data, indent=2) + "\n", encoding="utf-8")

    validation_ok, validation_detail = _run_timeline_ir_validation(project_path)

    if not validation_ok:
        timeline_path.write_text(backup_text, encoding="utf-8")
        raise HTTPException(
            status_code=422,
            detail={"message": "Revision failed timeline_ir validation; reverted.", "validation": validation_detail},
        )

    _append_revision_event(project_path, revision, before, shots[shot_index])

    await broadcast(project_id, {
        "type": "revision_applied",
        "shot_id": revision.shot_id,
        "before": before,
        "after": shots[shot_index],
        "reason": revision.reason,
        "timestamp": now_iso(),
    })

    return {
        "status": "applied",
        "shot_id": revision.shot_id,
        "before": before,
        "after": shots[shot_index],
        "validation": validation_detail,
    }


def _run_timeline_ir_validation(project_path: Path) -> tuple[bool, dict]:
    if not TIMELINE_IR_SCRIPT.is_file():
        return False, {"error": "timeline_ir.py script not found in this checkout"}
    try:
        result = subprocess.run(
            [sys.executable, str(TIMELINE_IR_SCRIPT), "--project", str(project_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, {"error": "timeline_ir.py timed out"}

    try:
        parsed = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        parsed = {"raw_stdout": result.stdout[-2000:]}

    return result.returncode == 0, parsed


def _append_revision_event(project_path: Path, revision: RevisionRequest, before: dict, after: dict) -> None:
    events_path = project_path / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": now_iso(),
        "action": "revision_applied",
        "source": "timeline_editor",
        "shot_id": revision.shot_id,
        "before": before,
        "after": after,
        "reason": revision.reason,
        "verified_real": True,
    }
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.get("/api/projects")
async def list_projects():
    project_root = get_project_root()
    projects = []
    for entry in sorted(project_root.iterdir()):
        if not entry.is_dir():
            continue
        state = load_artifact(entry, "state.json")
        integration_report = load_artifact(entry, "integration_report.json")
        has_timeline = (entry / "timeline.json").is_file()
        projects.append({
            "project_id": entry.name,
            "has_timeline": has_timeline,
            "state": state.data if state.present else None,
            "is_simulation": integration_report.present,
        })
    return {"projects": projects, "count": len(projects)}


# ---------------------------------------------------------------------------
# WebSocket — server pushes events, does not accept arbitrary agent commands
# ---------------------------------------------------------------------------

@app.websocket("/ws/timeline/{project_id}")
async def timeline_websocket(websocket: WebSocket, project_id: str):
    """
    One-directional-in-spirit channel: the server broadcasts state changes
    (from POST /revision, or from an external poller watching events.jsonl).
    It accepts a small, fixed set of inbound message types — it does not
    execute arbitrary instructions received over the socket.
    """
    project_root = get_project_root()
    try:
        resolve_project_path(project_root, project_id)
    except HTTPException:
        await websocket.close(code=4004, reason="invalid project_id")
        return

    await websocket.accept()
    await register_connection(project_id, websocket)
    logger.info("WebSocket connected: project=%s", project_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "invalid_json"})
                continue

            msg_type = message.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": now_iso()})
            else:
                # Explicitly reject unknown message types rather than
                # silently ignoring them — a caller relying on an
                # unsupported message type should find out immediately.
                await websocket.send_json({
                    "type": "error",
                    "detail": f"unsupported_message_type: {msg_type!r}",
                })
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: project=%s", project_id)
    finally:
        await unregister_connection(project_id, websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="info")
