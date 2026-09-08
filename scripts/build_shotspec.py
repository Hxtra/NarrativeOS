#!/usr/bin/env python3
"""Build portable ShotSpec records from a project timeline.

This creates planning requirements only. It never claims that an asset matches;
frame-level analysis and approval remain separate evidence-gated steps.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--project",type=Path,required=True); ap.add_argument("--out",default="shot_specs.json"); args=ap.parse_args()
    p=args.project; timeline=json.loads((p/"timeline.json").read_text(encoding="utf-8"))
    source=timeline.get("shots") or timeline.get("script") or []
    if not source:
        tracks=timeline.get("tracks",[])
        for track in tracks:
            if track.get("id") in {"v_main","video"}: source.extend(track.get("items",[]))
    specs=[]
    for i,item in enumerate(source):
        sid=item.get("shot_id") or item.get("beat_id") or f"B{i+1:03d}-S01"
        text=item.get("narration") or item.get("text") or item.get("rationale") or ""
        start=float(item.get("start", item.get("in_sec", item.get("timeline",{}).get("in_sec",0))))
        end=float(item.get("end", item.get("out_sec", item.get("timeline",{}).get("out_sec",start+5))))
        specs.append({
            "shot_id":sid,
            "beat_id":item.get("beat_id",sid),
            "narration":text,
            "visual_purpose":item.get("visual_purpose") or item.get("rationale") or "Support the narration without contradiction.",
            "visual_mode":item.get("visual_mode","literal"),
            "required_subjects":item.get("required_subjects",[]),
            "required_actions":item.get("required_actions",item.get("required_action",[])),
            "required_location":item.get("required_location",""),
            "required_time_period":item.get("required_time_period",""),
            "forbidden_meanings":item.get("forbidden_meanings",[]),
            "duration_seconds":max(0.0,end-start),
            "preferred_shot_type":item.get("preferred_shot_type",""),
            "fallbacks":item.get("fallbacks",["verified map","document treatment","labelled reconstruction"]),
            "status":"needs_asset_review"
        })
    out=p/args.out; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps({"schema_version":1,"status":"planning_only","shots":specs},indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"passed","planning_only":True,"shot_count":len(specs),"output":str(out)},indent=2))
if __name__=="__main__": main()
