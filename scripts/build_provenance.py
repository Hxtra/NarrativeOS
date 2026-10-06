#!/usr/bin/env python3
"""Collect hashes and lineage for project artifacts into a release manifest.

Besides the hash of every file, the manifest answers "what was this video made from, and by what?":
the pinned channel profile version, the script, the narration and every generation job (provider, model,
request hash), the analysis artifacts (music map, perception, breakdowns), the timeline, the renderer,
QA results and human approvals. Anything that cannot be read from a real artifact is recorded as
{"status": "unknown", "reason": ...}, never filled in.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

ANALYSIS = ["music_map.json", "beat_map.json", "perception/speech_map.json", "perception/visual_map.json", "director_proposals.json",
            "editorial_analysis.json", "breakdown/breakdown.json", "repetition_report.json"]


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (json.JSONDecodeError, OSError):
        return None


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _unknown(reason: str) -> dict:
    return {"status": "unknown", "reason": reason}


def lineage(p: Path) -> dict:
    out = {}
    prof = _load(p / "channel_profile.json")
    out["channel_profile"] = ({"channel_id": prof["pin"]["channel_id"], "profile_version": prof["pin"]["profile_version"],
                               "profile_sha256": prof["pin"]["profile_sha256"]} if prof and prof.get("pin") else
                              _unknown("channel_profile.json is not pinned to a channel version (channel.py apply)"))
    out["script"] = {"path": "script.json", "sha256": _sha(p / "script.json")} if (p / "script.json").is_file() else _unknown("no script.json")
    tts = _load(p / "tts_manifest.json")
    out["narration"] = ({"provider": tts.get("provider"), "model": tts.get("model") or tts.get("voice"), "sha256": _sha(p / "narration.mp3")}
                        if tts else _unknown("no tts_manifest.json"))
    jobs = []
    for f in sorted((p / "generation" / "jobs").glob("*.json")) if (p / "generation" / "jobs").is_dir() else []:
        j = _load(f) or {}
        jobs.append({"request_id": j.get("request_id"), "kind": j.get("kind"), "state": j.get("state"), "provider": j.get("provider"),
                     "model": j.get("model"), "request_hash": j.get("request_hash"), "output_sha256": (j.get("output") or {}).get("sha256")})
    out["generation_jobs"] = jobs
    out["analysis"] = [{"path": a, "sha256": _sha(p / a)} for a in ANALYSIS if (p / a).is_file()]
    tl = p / "timeline_ir.json"
    out["timeline"] = {"path": "timeline_ir.json", "sha256": _sha(tl), "ir_version": (_load(tl) or {}).get("ir_version")} if tl.is_file() else _unknown("no timeline_ir.json")
    rm = _load(p / "renders" / "render_manifest.json")
    if rm:
        enc = ((rm.get("ffprobe") or {}).get("format") or {}).get("tags", {}).get("encoder")
        out["render"] = {"output_path": rm.get("output_path"), "renderer": rm.get("renderer", "render_ffmpeg.py"), "encoder": enc,
                         "output_sha256": _sha(p / rm["output_path"]) if rm.get("output_path") else None}
    else:
        out["render"] = _unknown("no renders/render_manifest.json")
    qa = {}
    for name in ("technical_qa", "editorial_qa", "delivery_review"):
        d = _load(p / "qa" / f"{name}.json")
        qa[name] = d.get("status") if d else "missing"
    out["qa"] = qa
    approvals = {}
    q = _load(p / "quote_manifest.json")
    approvals["quote"] = (q or {}).get("approval") or "none"
    ev = _load(p / "evidence_review.json")
    approvals["evidence"] = (ev or {}).get("review") or "none"
    pkg = _load(p / "publish_package.json")
    approvals["publish_package"] = (pkg or {}).get("approval") or "none"
    out["approvals"] = approvals
    out["disclosure"] = (pkg or {}).get("disclosure") or _unknown("no publish package yet")
    return out


def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project; rows=[]
 for f in sorted(p.rglob('*')):
  if f.is_file() and '.git' not in f.parts and f.name not in {'provenance_manifest.json'}:
   h=hashlib.sha256(f.read_bytes()).hexdigest(); rows.append({'path':str(f.relative_to(p)),'sha256':h,'size_bytes':f.stat().st_size})
 lin=lineage(p)
 unknown=[k for k,v in lin.items() if isinstance(v,dict) and v.get('status')=='unknown']
 out={'schema_version':2,'status':'review_required','artifact_count':len(rows),'artifacts':rows,'lineage':lin,'lineage_unknown':unknown,
      'release_requirements':['rights evidence','human approvals','tool/model versions','QA reports']}
 (p/'provenance_manifest.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'status':'passed','artifacts':len(rows),'lineage_unknown':unknown},indent=2))
if __name__=='__main__': main()
