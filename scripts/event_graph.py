#!/usr/bin/env python3
"""Compile NarrativeOS Event Graph v0 events into a renderer-neutral timeline."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from copy import deepcopy
ALLOWED={"REVEAL","EMPHASIZE","CUT","HOLD","ANTICIPATE","J_CUT","L_CUT","MOTION","TRANSITION","NO_OP"}
MOTION_KINDS={"push_in","pull_out"}


def _known_recipes()->set:
    """Transition recipe ids registered in the Remotion VFX library (single source of truth)."""
    import sys
    root=str(Path(__file__).resolve().parents[1])
    if root not in sys.path: sys.path.insert(0,root)
    from style_intel.profile import known_transitions
    return known_transitions()

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
        from editing_config import DIRECTOR_DEFAULTS
        max_overlap = float(graph.get("director_config", {}).get("max_audio_overlap_sec", DIRECTOR_DEFAULTS["max_audio_overlap_sec"]))
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
                    if (j != i + 1 or not math.isfinite(offset) or not 0 < offset <= max_overlap
                            or offset >= host["end"] - host["start"] or duration != offset
                            or set(e["affected_objects"]) != {ids[i], ids[j]}
                            or not (left.get("has_native_audio") and right.get("has_native_audio"))):
                        raise ValueError("invalid J/L-cut overlap")
                if e["type"] == "MOTION":
                    m = e.get("motion") or {}
                    shot = shots[ids.index(e["affected_objects"][0])]
                    scales = [float(m.get("scale_from", 1)), float(m.get("scale_to", 1))]
                    if (len(e["affected_objects"]) != 1 or m.get("kind") not in MOTION_KINDS
                            or not all(math.isfinite(x) and 0.5 <= x <= 2.0 for x in scales)
                            or start < shot["start"] or start + duration > shot["end"] + 1e-6):
                        raise ValueError("invalid MOTION: one shot, known kind, sane scale, inside the shot")
                if e["type"] == "TRANSITION":
                    tr = e.get("transition") or {}
                    i, j = ids.index(tr["left_shot_id"]), ids.index(tr["right_shot_id"])
                    allowed = graph.get("director_config", {}).get("allowed_transitions")
                    if (j != i + 1 or start != shots[i]["end"] or set(e["affected_objects"]) != {ids[i], ids[j]}
                            or tr.get("recipe") not in _known_recipes()
                            or (allowed is not None and tr.get("recipe") not in allowed)):
                        raise ValueError("invalid TRANSITION: adjacent shots, at the cut, registered recipe allowed by the style")
            elif "boundary" in e or e.get("type") in {"J_CUT", "L_CUT", "MOTION", "TRANSITION"}:
                raise ValueError("boundary, J/L-cut, MOTION and TRANSITION events require a base timeline")
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
                marker = {"event_id": e["event_id"], "type": e["type"], "start": e["timing"]["start"],
                          "end": e["timing"]["start"] + e["timing"]["duration"], "purpose": e["purpose"],
                          "execution": "deliberate_no_op" if e["type"] == "NO_OP" else "review_marker_only"}
                for payload in ("motion", "transition", "source"):
                    if payload in e:
                        marker[payload] = deepcopy(e[payload])
                markers.append(marker)
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
