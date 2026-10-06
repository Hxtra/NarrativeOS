#!/usr/bin/env python3
"""Evidence-gated video workflow controller.

This controller is intentionally deterministic. It records state and refuses to
advance when a real stage artifact is absent or marked blocked/pending.

The production is a visible graph: every passed stage records the hashes of its artifacts, so a stage
whose artifacts were edited afterwards, or whose upstream stage passed again later, shows as STALE and
blocks what depends on it until it is re-run. A human can pause the run, resume it, or revise a stage
(which reopens it and everything downstream, with the reason logged).

    controller.py --project P --init | [--stage S] | --graph | --pause --reason R | --resume | --revise S --reason R
"""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

STAGES = [
    "INTAKE", "STYLE_LOCK", "DIRECTOR_STRATEGY", "QUOTE", "RESEARCH_WORKSPACE",
    "SOURCE_INGEST", "RESEARCH", "CLAIM_BUILD", "EVIDENCE_REVIEW", "CONTRADICTION_REVIEW", "OUTLINE",
    "SCRIPT", "NARRATION_ALIGNMENT", "BEAT_MAP", "SHOT_PLAN", "ASSET_ACQUISITION",
    "ASSET_ANALYSIS", "VISUAL_BENCHMARK", "ASSET_APPROVAL", "CONTINUITY_BIBLE", "EVIDENCE_LINKING",
    "GRAPHICS", "TTS", "ALIGNMENT", "CAPTIONS", "TIMELINE", "TIMELINE_IR", "AUDIO_MIX",
    "EDITORIAL_ANALYSIS", "EDITORIAL_REPAIR", "COST_REVIEW", "VARIANT_BUILD", "THUMBNAIL", "PREVIEW_RENDER", "TECHNICAL_QA", "EDITORIAL_QA",
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
    "SOURCE_INGEST": ["research/sources.json"],
    "RESEARCH": ["research.json", "claim_ledger.json"],
    "CLAIM_BUILD": ["research/claims/claims.json"],
    "EVIDENCE_REVIEW": ["evidence_review.json"],
    "CONTRADICTION_REVIEW": ["research/contradictions/contradictions.json"],
    "OUTLINE": ["outline.json"],
    "SCRIPT": ["script.json"],
    "NARRATION_ALIGNMENT": ["narration_alignment.json"],
    "BEAT_MAP": ["beat_map.json"],
    "SHOT_PLAN": ["shot_specs.json"],
    "ASSET_ACQUISITION": ["asset_candidates.json"],
    "ASSET_ANALYSIS": ["asset_analysis.json"],
    "VISUAL_BENCHMARK": ["visual_benchmark_report.json"],
    "ASSET_APPROVAL": ["approved_assets.json"],
    "CONTINUITY_BIBLE": ["entity_bible.json", "temporal_constraints.json", "geographic_plan.json"],
    "EVIDENCE_LINKING": ["claim_visual_links.json", "shot_explanations.json"],
    "GRAPHICS": ["graphics_manifest.json"],
    "TTS": ["narration.mp3", "tts_manifest.json"],
    "ALIGNMENT": ["alignment.json"],
    "CAPTIONS": ["captions.json", "captions.ass"],
    "TIMELINE": ["timeline.json"],
    "TIMELINE_IR": ["timeline_ir.json"],
    "AUDIO_MIX": ["audio_mix_manifest.json"],
    "EDITORIAL_ANALYSIS": ["editorial_analysis.json"],
    "EDITORIAL_REPAIR": ["revision_plan.json"],
    "COST_REVIEW": ["cost_decisions.json"],
    "VARIANT_BUILD": ["variant_comparison.json"],
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

CONTROLLER_OWNED = {"state.json"}  # rewritten by every run: never a stage's fingerprint


def sha_json(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def downstream(stage):
    """Every stage that depends on `stage`, directly or not."""
    return [s for s in STAGES if stage in DEPS.get(s, [])]


def stale_stages(project, state):
    """Passed stages whose recorded artifacts changed, or whose dependencies passed again after them."""
    records = state.get("stage_records", {})
    completed = state.get("completed_stages", [])
    stale = {}
    for stage in completed:
        rec = records.get(stage)
        if not rec:
            continue
        changed = [a for a, h in rec.get("artifacts", {}).items() if file_sha(project / a) != h]
        later = [d for d in DEPS.get(stage, []) if d in records and records[d]["passed_at"] > rec["passed_at"]]
        if changed or later:
            stale[stage] = {"artifacts_changed": changed, "upstream_passed_later": later}
    return stale


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
            data = load_json(project / artifact, {})
            if isinstance(data, dict) and data.get("review", {}).get("required") is True and data.get("review", {}).get("approved") is not True:
                blocked.append({"artifact": artifact, "status": "review_required"})
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
    if stage == "STYLE_LOCK":
        profile = load_json(project / "channel_profile.json", {})
        pin = profile.get("pin")
        if pin:
            body = {k: v for k, v in profile.items() if k not in ("created_at", "profile_sha256", "status", "pinned_at", "pin")}
            if sha_json(body) != pin.get("profile_sha256"):
                return False, {"pinned_profile_edited": "channel_profile.json no longer matches the profile version it pins; change the channel with channel.py update, then apply again"}
    if stage == "PUBLISH":
        state = load_json(project / "state.json", {})
        if state.get("publish_authorized") is not True: return False, {"publish_authorized": False}
    return True, {"checked_files": required}

def run(project, requested=None):
    state = load_json(project / "state.json", {})
    completed = set(state.get("completed_stages", []))
    stage = requested or state.get("current_stage", "INTAKE")
    if stage not in STAGES: raise SystemExit(f"Unknown stage: {stage}")
    if state.get("paused"):
        append_jsonl(project / "events.jsonl", {"timestamp": now(), "stage": stage, "action": "blocked", "reason": "paused", "verified_real": True})
        print(json.dumps({"status": "blocked", "reason": "paused", "paused": state["paused"]}))
        return 1
    stale = {d: v for d, v in stale_stages(project, state).items() if d in DEPS.get(stage, [])}
    if stale:
        state.update({"stage_status": "blocked", "project_status": "blocked", "delivery_ready": False})
        state["blocking_findings"] = [{"stage": stage, "stale_dependency": d, **v} for d, v in stale.items()]
        save_json(project / "state.json", state)
        append_jsonl(project / "events.jsonl", {"timestamp": now(), "stage": stage, "action": "blocked", "reason": "stale_dependency", "stale": stale, "verified_real": True})
        return 1
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
    state.setdefault("stage_records", {})[stage] = {"passed_at": now(), "artifacts": {a: file_sha(project / a) for a in REQUIRED.get(stage, []) if (project / a).is_file() and a not in CONTROLLER_OWNED}}
    state.update({"stage_status": "passed", "project_status": "in_progress", "last_successful_stage": stage, "completed_stages": sorted(completed, key=STAGES.index), "blocking_findings": []})
    idx = STAGES.index(stage)
    state["current_stage"] = STAGES[min(idx + 1, len(STAGES) - 1)]
    if stage == "DELIVERY_REVIEW": state.update({"project_status": "complete", "delivery_ready": True})
    save_json(project / "state.json", state)
    append_jsonl(project / "events.jsonl", {"timestamp": now(), "stage": stage, "action": "passed", "details": details, "verified_real": True})
    return 0

def pause(project, reason):
    state = load_json(project / "state.json", {})
    state["paused"] = {"at": now(), "reason": reason}
    save_json(project / "state.json", state)
    append_jsonl(project / "events.jsonl", {"timestamp": now(), "action": "paused", "reason": reason, "verified_real": True})
    return 0


def resume(project):
    state = load_json(project / "state.json", {})
    was = state.pop("paused", None)
    save_json(project / "state.json", state)
    append_jsonl(project / "events.jsonl", {"timestamp": now(), "action": "resumed", "was_paused": was, "verified_real": True})
    return 0


def revise(project, stage, reason):
    """Reopen a stage and everything downstream of it; the artifacts stay, the passes do not."""
    if stage not in STAGES: raise SystemExit(f"Unknown stage: {stage}")
    if not reason.strip(): raise SystemExit("--revise needs --reason")
    state = load_json(project / "state.json", {})
    reopened = [s for s in [stage, *downstream(stage)] if s in state.get("completed_stages", [])]
    state["completed_stages"] = [s for s in state.get("completed_stages", []) if s not in reopened]
    for s in reopened:
        state.get("stage_records", {}).pop(s, None)
    state.update({"current_stage": stage, "stage_status": "pending", "project_status": "in_progress", "delivery_ready": False,
                  "last_successful_stage": state["completed_stages"][-1] if state["completed_stages"] else None})
    state.setdefault("revisions", []).append({"at": now(), "stage": stage, "reason": reason, "reopened": reopened})
    save_json(project / "state.json", state)
    append_jsonl(project / "events.jsonl", {"timestamp": now(), "stage": stage, "action": "revised", "reason": reason, "reopened": reopened, "verified_real": True})
    print(json.dumps({"revised": stage, "reopened": reopened}))
    return 0


def graph(project):
    """Every stage as a node: status, artifacts with hashes, evidence, revisions, what it feeds."""
    state = load_json(project / "state.json", {})
    completed = state.get("completed_stages", [])
    records = state.get("stage_records", {})
    stale = stale_stages(project, state)
    findings = state.get("blocking_findings", [])
    nodes = []
    for i, stage in enumerate(STAGES):
        if stage in stale: status = "stale"
        elif stage in completed: status = "passed"
        elif any(f.get("stage") == stage for f in findings): status = "blocked"
        elif stage == state.get("current_stage"): status = "current"
        else: status = "pending"
        arts = []
        for a in REQUIRED.get(stage, []):
            f = project / a
            arts.append({"path": a, "exists": f.is_file(), "sha256": file_sha(f), "status": status_of(project, a) if a.endswith(".json") else None,
                         "sha256_at_pass": (records.get(stage) or {}).get("artifacts", {}).get(a)})
        direct_in = ["DELIVERY_REVIEW"] if stage in ("PUBLISH", "COMPLETE") else ([STAGES[i - 1]] if i else [])
        direct_out = [s for s in STAGES if direct_in_of(s) == [stage]]
        nodes.append({"stage": stage, "status": status, "artifacts": arts, "passed_at": (records.get(stage) or {}).get("passed_at"),
                      "stale": stale.get(stage), "blocking": [f for f in findings if f.get("stage") == stage],
                      "revisions": [r for r in state.get("revisions", []) if r["stage"] == stage],
                      "inputs_from": direct_in, "feeds": direct_out})
    out = {"schema_version": 1, "generated_at": now(), "paused": state.get("paused"), "current_stage": state.get("current_stage"),
           "counts": {k: sum(n["status"] == k for n in nodes) for k in ("passed", "stale", "blocked", "current", "pending")}, "nodes": nodes}
    save_json(project / "production_graph.json", out)
    print(json.dumps({"counts": out["counts"], "paused": out["paused"], "stale": sorted(stale)}, indent=2))
    return 0


def direct_in_of(stage):
    i = STAGES.index(stage)
    return ["DELIVERY_REVIEW"] if stage in ("PUBLISH", "COMPLETE") else ([STAGES[i - 1]] if i else [])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--stage")
    ap.add_argument("--graph", action="store_true", help="write production_graph.json")
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--revise", metavar="STAGE")
    ap.add_argument("--reason", default="")
    args = ap.parse_args()
    if args.init: init_project(args.project); return 0
    if not (args.project / "state.json").exists(): raise SystemExit("Missing state.json; run --init first")
    if args.graph: return graph(args.project)
    if args.pause:
        if not args.reason.strip(): raise SystemExit("--pause needs --reason")
        return pause(args.project, args.reason)
    if args.resume: return resume(args.project)
    if args.revise: return revise(args.project, args.revise, args.reason)
    return run(args.project, args.stage)
if __name__ == "__main__": raise SystemExit(main())
