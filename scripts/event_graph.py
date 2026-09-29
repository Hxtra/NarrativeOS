#!/usr/bin/env python3
"""Compile NarrativeOS Event Graph v0 events into a renderer-neutral timeline."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from copy import deepcopy
ALLOWED={"REVEAL","EMPHASIZE","CUT","HOLD","ANTICIPATE","J_CUT","L_CUT"}

def validate(graph:dict)->list[dict]:
    import math
    errors=[]; seen=set()
    try:
        shots = deepcopy(graph.get("base_timeline", {}).get("shots", []))
        ids = [s["shot_id"] for s in shots]
        if "base_timeline" in graph:
            if not shots or len(set(ids)) != len(ids):
                raise ValueError("missing or duplicate base shots")
            previous = 0
            for s in shots:
                a, b = float(s["start"]), float(s["end"])
                if not math.isfinite(a) or not math.isfinite(b) or a < previous or b <= a:
                    raise ValueError("invalid base timing")
                previous = b
        changed = set()
        for e in graph.get("events",[]):
            eid=e.get("event_id")
            if not eid or eid in seen: errors.append({"event_id":eid,"error":"missing or duplicate event_id"})
            seen.add(eid)
            if e.get("type") not in ALLOWED: errors.append({"event_id":eid,"error":"unsupported event type"})
            if not e.get("purpose"): errors.append({"event_id":eid,"error":"missing purpose"})
            t=e.get("timing",{}); start=float(t.get("start",-1)); duration=float(t.get("duration",-1))
            if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
                errors.append({"event_id":eid,"error":"invalid timing"})
            if not e.get("affected_objects"): errors.append({"event_id":eid,"error":"missing affected_objects"})
            if "base_timeline" in graph:
                if any(obj not in ids for obj in e["affected_objects"]):
                    raise ValueError("unknown affected shot")
                if "boundary" in e:
                    b = e["boundary"]
                    i, j = ids.index(b["left_shot_id"]), ids.index(b["right_shot_id"])
                    at, before = float(b["to"]), float(b["from"])
                    if j != i + 1 or (i, j) in changed or e["type"] not in {"CUT", "REVEAL"}:
                        raise ValueError("nonadjacent or duplicate boundary")
                    left, right = shots[i], shots[j]
                    if (not math.isfinite(at) or not math.isfinite(before)
                            or before != left["end"] or before != right["start"]
                            or not left["start"] < at < right["end"] or at != start
                            or set(e["affected_objects"]) != {ids[i], ids[j]}):
                        raise ValueError("invalid boundary range or lineage")
                    left["end"] = right["start"] = at
                    changed.add((i, j))
                if e["type"] in {"J_CUT", "L_CUT"}:
                    o = e.get("audio_overlap") or {}
                    i, j = ids.index(o["left_shot_id"]), ids.index(o["right_shot_id"])
                    offset = float(o["offset_sec"])
                    left, right = shots[i], shots[j]
                    host = left if e["type"] == "J_CUT" else right  # the shot whose picture carries the other shot's sound
                    if (j != i + 1 or not math.isfinite(offset) or not 0 < offset <= 2.0
                            or offset >= host["end"] - host["start"] or duration != offset
                            or set(e["affected_objects"]) != {ids[i], ids[j]}
                            or not (left.get("has_native_audio") and right.get("has_native_audio"))):
                        raise ValueError("invalid J/L-cut overlap")
            elif "boundary" in e or e.get("type") in {"J_CUT", "L_CUT"}:
                raise ValueError("boundary and J/L-cut events require a base timeline")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append({"error": str(exc)})
    return errors

def compile_graph(graph:dict)->dict:
    errors = validate(graph)
    if errors:
        raise ValueError(f"Invalid event graph: {errors}")
    if "base_timeline" in graph:
        out = deepcopy(graph["base_timeline"])
        by_id = {s["shot_id"]: s for s in out["shots"]}
        markers = out.setdefault("markers", [])
        for e in graph["events"]:
            if "boundary" in e:
                b = e["boundary"]
                by_id[b["left_shot_id"]]["end"] = b["to"]
                by_id[b["right_shot_id"]]["start"] = b["to"]
            elif e["type"] in {"J_CUT", "L_CUT"}:
                o = e["audio_overlap"]
                left, right = by_id[o["left_shot_id"]], by_id[o["right_shot_id"]]
                split = left["end"] - o["offset_sec"] if e["type"] == "J_CUT" else left["end"] + o["offset_sec"]
                # Native audio is split off the picture cut. The FFmpeg renderer does not play native audio yet.
                left["native_audio_end"] = right["native_audio_start"] = round(split, 4)
                for shot in (left, right):
                    shot["native_audio_execution"] = "ir_only_renderer_pending"
            else:
                markers.append({"event_id": e["event_id"], "type": e["type"], "start": e["timing"]["start"],
                                "end": e["timing"]["start"] + e["timing"]["duration"], "purpose": e["purpose"], "execution": "review_marker_only"})
        for shot in out["shots"]:
            shot["status"] = "simulation_approved"
            shot["approved"] = False
            shot.pop("review", None)
        out.update(ir_version="1.1", status="review_required", approved=False, delivery_ready=False, source_event_graph=deepcopy(graph),
                   review={"required": True, "approved": False, "reason": "Perception edits require timeline, asset and listening review."})
        return out
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
