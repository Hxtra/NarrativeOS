#!/usr/bin/env python3
"""Evidence-gated Hermes video workflow controller.

This controller is intentionally deterministic. It records state and refuses to
advance when a real stage artifact is absent or marked blocked/pending.
"""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

STAGES = [
    "INTAKE", "STYLE_LOCK", "DIRECTOR_STRATEGY", "QUOTE", "RESEARCH_WORKSPACE",
    "RESEARCH", "EVIDENCE_REVIEW", "CONTRADICTION_REVIEW", "OUTLINE",
    "SCRIPT", "NARRATION_ALIGNMENT", "BEAT_MAP", "SHOT_PLAN", "ASSET_ACQUISITION",
    "ASSET_ANALYSIS", "ASSET_APPROVAL", "CONTINUITY_BIBLE", "EVIDENCE_LINKING",
    "GRAPHICS", "TTS", "CAPTIONS", "TIMELINE", "TIMELINE_IR", "AUDIO_MIX",
    "EDITORIAL_ANALYSIS", "COST_REVIEW", "THUMBNAIL", "PREVIEW_RENDER", "TECHNICAL_QA", "EDITORIAL_QA",
    "TARGETED_REVISION", "FINAL_RENDER", "DELIVERY_REVIEW", "PUBLISH", "COMPLETE",
]
DEPS = {stage: STAGES[:i] for i, stage in enumerate(STAGES)}
# PUBLISH is optional, while COMPLETE follows delivery review by default.
DEPS["PUBLISH"] = ["DELIVERY_REVIEW"]
DEPS["COMPLETE"] = ["DELIVERY_REVIEW"]

REQUIRED = {
    "INTAKE": ["project.yaml", "brief.md", "state.json"],
    "STYLE_LOCK": ["channel_profile.json"],
    "DIRECTOR_STRATEGY": ["director_strategy.json", "emotional_arc.json", "retention_plan.json"],
    "QUOTE": ["quote_manifest.json"],
    "RESEARCH_WORKSPACE": ["research/research_manifest.json", "research/research_graph.json"],
    "RESEARCH": ["research.json", "claim_ledger.json"],
    "EVIDENCE_REVIEW": ["evidence_review.json"],
    "CONTRADICTION_REVIEW": ["research/contradictions/contradictions.json"],
    "OUTLINE": ["outline.json"],
    "SCRIPT": ["script.json"],
    "NARRATION_ALIGNMENT": ["narration_alignment.json"],
    "BEAT_MAP": ["beat_map.json"],
    "SHOT_PLAN": ["shot_specs.json"],
    "ASSET_ACQUISITION": ["asset_candidates.json"],
    "ASSET_ANALYSIS": ["asset_analysis.json"],
    "ASSET_APPROVAL": ["approved_assets.json"],
    "CONTINUITY_BIBLE": ["entity_bible.json", "temporal_constraints.json", "geographic_plan.json"],
    "EVIDENCE_LINKING": ["claim_visual_links.json", "shot_explanations.json"],
    "GRAPHICS": ["graphics_manifest.json"],
    "TTS": ["narration.mp3", "tts_manifest.json"],
    "CAPTIONS": ["captions.json", "captions.ass"],
    "TIMELINE": ["timeline.json"],
    "TIMELINE_IR": ["timeline_ir.json"],
    "AUDIO_MIX": ["audio_mix_manifest.json"],
    "EDITORIAL_ANALYSIS": ["editorial_analysis.json"],
    "COST_REVIEW": ["cost_decisions.json"],
    "THUMBNAIL": ["thumbnail_manifest.json"],
    "PREVIEW_RENDER": ["renders/preview.mp4", "renders/render_manifest.json"],
    "TECHNICAL_QA": ["qa/technical_qa.json"],
    "EDITORIAL_QA": ["qa/editorial_qa.json"],
    "TARGETED_REVISION": ["qa/revision_report.json"],
    "FINAL_RENDER": ["renders/final.mp4"],
    "DELIVERY_REVIEW": ["qa/delivery_review.json"],
    "PUBLISH": ["publish_manifest.json"],
}

def now(): return datetime.now(timezone.utc).isoformat()
def load_json(p, default):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception: return default
def save_json(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
def append_jsonl(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f: f.write(json.dumps(value, ensure_ascii=False) + "\n")
def status_of(project, artifact):
    data = load_json(project / artifact, {})
    return data.get("status") if isinstance(data, dict) else None

def init_project(project):
    project.mkdir(parents=True, exist_ok=True)
    for d in ("renders", "qa", "frames", "assets", "audio", "graphics"):
        (project / d).mkdir(exist_ok=True)
    state = {"schema_version": 2, "project_status": "pending", "stage_status": "pending",
             "current_stage": "INTAKE", "last_successful_stage": None,
             "completed_stages": [], "blocking_findings": [], "delivery_ready": False,
             "publish_authorized": False}
    save_json(project / "state.json", state)
    defaults = {
        "assets.json": {"assets": []}, "shot_specs.json": {"shots": []},
        "timeline.json": {"timeline_version": "v001", "shots": []},
        "channel_profile.json": {"channel_id": "unnamed", "profile_version": "v001", "language": "en"},
    }
    for name, value in defaults.items():
        if not (project / name).exists(): save_json(project / name, value)
    append_jsonl(project / "events.jsonl", {"timestamp": now(), "action": "project_initialized", "verified_real": True})

def validator(project, stage):
    required = REQUIRED.get(stage, [])
    missing = [x for x in required if not (project / x).is_file()]
    if missing: return False, {"missing_artifacts": missing}
    # Generic status gate: blocked/pending artifacts cannot pass merely because they exist.
    blocked = []
    for artifact in required:
        if artifact.endswith((".json", ".yaml")):
            status = status_of(project, artifact)
            if status in {"blocked", "pending", "review_required"}: blocked.append({"artifact": artifact, "status": status})
    if blocked: return False, {"blocked_artifacts": blocked}
    if stage == "ASSET_APPROVAL":
        data = load_json(project / "approved_assets.json", {})
        bad = [a.get("shot_id", "?") for a in data.get("assets", []) if a.get("status") != "approved" or len(a.get("evidence_frame_paths", [])) < 3 or not a.get("rights_status")]
        if bad: return False, {"invalid_approved_assets": bad}
    if stage == "TIMELINE":
        data = load_json(project / "timeline.json", {})
        bad = [s.get("shot_id", "?") for s in data.get("shots", []) if not s.get("asset_id") or s.get("status") != "approved"]
        if bad: return False, {"unapproved_or_unmapped_shots": bad}
    if stage == "DELIVERY_REVIEW":
        data = load_json(project / "qa/delivery_review.json", {})
        if data.get("delivery_ready") is not True: return False, {"delivery_ready": data.get("delivery_ready", False)}
    if stage == "PUBLISH":
        state = load_json(project / "state.json", {})
        if state.get("publish_authorized") is not True: return False, {"publish_authorized": False}
    return True, {"checked_files": required}

def run(project, requested=None):
    state = load_json(project / "state.json", {})
    completed = set(state.get("completed_stages", []))
    stage = requested or state.get("current_stage", "INTAKE")
    if stage not in STAGES: raise SystemExit(f"Unknown stage: {stage}")
    missing_deps = [d for d in DEPS.get(stage, []) if d not in completed and not (stage == "COMPLETE" and d == "PUBLISH")]
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
