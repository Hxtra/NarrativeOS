#!/usr/bin/env python3
"""Compile NarrativeOS Event Graph v0 events into a renderer-neutral timeline."""
from __future__ import annotations
import argparse, json
from pathlib import Path
ALLOWED={"REVEAL","EMPHASIZE","CUT"}

def validate(graph:dict)->list[dict]:
    errors=[]; seen=set()
    for e in graph.get("events",[]):
        eid=e.get("event_id")
        if not eid or eid in seen: errors.append({"event_id":eid,"error":"missing or duplicate event_id"})
        seen.add(eid)
        if e.get("type") not in ALLOWED: errors.append({"event_id":eid,"error":"unsupported event type"})
        if not e.get("purpose"): errors.append({"event_id":eid,"error":"missing purpose"})
        t=e.get("timing",{}); start=float(t.get("start",-1)); duration=float(t.get("duration",-1))
        if start < 0 or duration <= 0: errors.append({"event_id":eid,"error":"invalid timing"})
        if not e.get("affected_objects"): errors.append({"event_id":eid,"error":"missing affected_objects"})
    return errors

def compile_graph(graph:dict)->dict:
    events=sorted(graph.get("events",[]), key=lambda e:(float(e["timing"]["start"]),e["event_id"]))
    shots=[]; audio=[]; graphics=[]
    for e in events:
        t=e["timing"]; start=float(t["start"]); end=start+float(t["duration"])
        for obj in e["affected_objects"]:
            if obj.startswith("SHOT_"):
                visual=(e.get("visual") or [{}])[0]
                asset_id=visual.get("asset_id") or e.get("asset_id") or obj
                shots.append({"shot_id":obj,"asset_id":asset_id,"start":start,"end":end,"status":"simulation_approved","event_id":e["event_id"],"purpose":e["purpose"]})
        for a in e.get("audio",[]): audio.append({**a,"event_id":e["event_id"],"start":start,"end":end})
        for v in e.get("visual",[]):
            if v.get("operation") in {"text_overlay","lower_third","graphic"}: graphics.append({**v,"event_id":e["event_id"],"start":start,"end":end})
    return {"ir_version":"1.1","shots":shots,"tracks":{"video":"v_main","narration":"a_narration","native_audio":"a_native","music":"a_music","sfx":"a_sfx","graphics":"v_graphics"},"audio_events":audio,"graphics_events":graphics,"source_event_graph":graph}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--input",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); args=ap.parse_args()
    graph=json.loads(args.input.read_text()); errors=validate(graph)
    if errors: print(json.dumps({"status":"blocked","errors":errors},indent=2)); return 1
    out=compile_graph(graph); out["validation"]={"status":"passed","errors":[]}; args.output.write_text(json.dumps(out,indent=2)+"\n"); print(json.dumps(out["validation"],indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
