#!/usr/bin/env python3
"""Evidence-gated Hermes video workflow controller.

Executes one stage per invocation, persists state, and never marks a stage
complete without real artifacts and validation. No external Python packages.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

STAGES = [
    "INTAKE", "STYLE_LOCK", "SHOT_PLAN", "ASSET_ANALYSIS", "ASSET_APPROVAL",
    "TIMELINE", "PREVIEW_RENDER", "TECHNICAL_QA", "EDITORIAL_QA",
    "TARGETED_REVISION", "FINAL_RENDER", "DELIVERY_REVIEW", "COMPLETE",
]
DEPS = {
    "INTAKE": [], "STYLE_LOCK": ["INTAKE"], "SHOT_PLAN": ["STYLE_LOCK"],
    "ASSET_ANALYSIS": ["SHOT_PLAN"], "ASSET_APPROVAL": ["ASSET_ANALYSIS"],
    "TIMELINE": ["ASSET_APPROVAL"], "PREVIEW_RENDER": ["TIMELINE"],
    "TECHNICAL_QA": ["PREVIEW_RENDER"], "EDITORIAL_QA": ["PREVIEW_RENDER"],
    "TARGETED_REVISION": ["TECHNICAL_QA", "EDITORIAL_QA"],
    "FINAL_RENDER": ["TARGETED_REVISION", "TIMELINE"],
    "DELIVERY_REVIEW": ["FINAL_RENDER"], "COMPLETE": ["DELIVERY_REVIEW"],
}

def now(): return datetime.now(timezone.utc).isoformat()
def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): h.update(b)
    return h.hexdigest()
def load_json(p, default):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception: return default
def save_json(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
def append_jsonl(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f: f.write(json.dumps(value, ensure_ascii=False) + "\n")

def init_project(project):
    project.mkdir(parents=True, exist_ok=True)
    for d in ("renders", "qa", "frames"):
        (project / d).mkdir(exist_ok=True)
    state = {"schema_version": 1, "project_status": "pending", "stage_status": "pending",
             "current_stage": "INTAKE", "last_successful_stage": None,
             "completed_stages": [], "blocking_findings": [], "delivery_ready": False}
    save_json(project / "state.json", state)
    if not (project / "assets.json").exists(): save_json(project / "assets.json", {"assets": []})
    if not (project / "shot_specs.json").exists(): save_json(project / "shot_specs.json", {"shots": []})
    if not (project / "timeline.json").exists(): save_json(project / "timeline.json", {"timeline_version": "v001", "shots": []})
    if not (project / "channel_profile.json").exists(): save_json(project / "channel_profile.json", {"channel_id": "unnamed", "profile_version": "v001"})
    append_jsonl(project / "events.jsonl", {"timestamp": now(), "action": "project_initialized", "verified_real": True})

def validator(project, stage):
    required = {
        "INTAKE": ["project.yaml", "state.json"],
        "STYLE_LOCK": ["channel_profile.json"],
        "SHOT_PLAN": ["shot_specs.json"],
        "ASSET_ANALYSIS": ["asset_analysis.json"],
        "ASSET_APPROVAL": ["approved_assets.json"],
        "TIMELINE": ["timeline.json"],
        "PREVIEW_RENDER": ["renders/preview.mp4", "renders/render_manifest.json"],
        "TECHNICAL_QA": ["qa/technical_qa.json"],
        "EDITORIAL_QA": ["qa/editorial_qa.json"],
        "TARGETED_REVISION": ["qa/revision_report.json"],
        "FINAL_RENDER": ["renders/final.mp4"],
        "DELIVERY_REVIEW": ["qa/delivery_review.json"],
    }
    missing = [x for x in required.get(stage, []) if not (project / x).is_file()]
    if missing: return False, {"missing_artifacts": missing}
    if stage == "ASSET_APPROVAL":
        data = load_json(project / "approved_assets.json", {})
        bad = [a.get("shot_id", "?") for a in data.get("assets", []) if a.get("status") != "approved" or not a.get("evidence_frame_paths") or not a.get("rights_status")]
        if bad: return False, {"invalid_approved_assets": bad}
    if stage == "TIMELINE":
        data = load_json(project / "timeline.json", {})
        bad = [s.get("shot_id", "?") for s in data.get("shots", []) if not s.get("asset_id") or s.get("status") != "approved"]
        if bad: return False, {"unapproved_or_unmapped_shots": bad}
    if stage == "PREVIEW_RENDER":
        m = load_json(project / "renders/render_manifest.json", {})
        if m.get("status") != "passed": return False, {"render_manifest_status": m.get("status")}
    return True, {"checked_files": required.get(stage, [])}

def run(project, requested=None):
    state = load_json(project / "state.json", {})
    completed = set(state.get("completed_stages", []))
    stage = requested or state.get("current_stage", "INTAKE")
    if stage not in STAGES: raise SystemExit(f"Unknown stage: {stage}")
    missing_deps = [d for d in DEPS.get(stage, []) if d not in completed]
    if missing_deps:
        state.update({"stage_status": "blocked", "project_status": "blocked", "delivery_ready": False})
        state["blocking_findings"] = [{"stage": stage, "missing_dependency": d} for d in missing_deps]
        state["current_stage"] = missing_deps[0]
        save_json(project / "state.json", state)
        append_jsonl(project / "events.jsonl", {"timestamp": now(), "stage": stage, "action": "blocked", "reason": "missing_dependency", "missing_dependencies": missing_deps, "verified_real": True})
        return 1
    ok, details = validator(project, stage)
    if not ok:
        state.update({"stage_status": "blocked", "project_status": "blocked", "delivery_ready": False})
        state["blocking_findings"] = [{"stage": stage, **details}]
        save_json(project / "state.json", state)
        append_jsonl(project / "errors.jsonl", {"timestamp": now(), "stage": stage, "severity": "high", "message": "artifact_validation_failed", "details": details, "verified_real": True})
        append_jsonl(project / "events.jsonl", {"timestamp": now(), "stage": stage, "action": "blocked", "reason": "artifact_validation_failed", "details": details, "verified_real": True})
        return 1
    completed.add(stage)
    state.update({"stage_status": "passed", "project_status": "in_progress", "last_successful_stage": stage, "completed_stages": sorted(completed, key=STAGES.index), "blocking_findings": []})
    idx = STAGES.index(stage)
    state["current_stage"] = STAGES[min(idx + 1, len(STAGES) - 1)]
    if stage == "DELIVERY_REVIEW": state.update({"project_status": "complete", "delivery_ready": True})
    save_json(project / "state.json", state)
    append_jsonl(project / "events.jsonl", {"timestamp": now(), "stage": stage, "action": "passed", "details": details, "verified_real": True})
    return 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--stage")
    args = ap.parse_args()
    if args.init: init_project(args.project); return 0
    if not (args.project / "state.json").exists(): raise SystemExit("Missing state.json; run --init first")
    return run(args.project, args.stage)
if __name__ == "__main__": raise SystemExit(main())
