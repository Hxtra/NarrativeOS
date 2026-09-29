#!/usr/bin/env python3
"""Derive transparent editorial strategy artifacts from a brief and channel profile."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from copy import deepcopy


def plan_edit(timeline: dict, perception: dict, style: dict, director: dict | None = None) -> dict:
    """Conservative, local Director role. Events are proposals, never approvals."""
    if director and (director.get("mode", "deterministic") != "deterministic" or director.get("model")):
        raise ValueError("Only deterministic Director execution is implemented; no model is invoked")
    perception = deepcopy(perception)
    for kind in ("music", "speech"):
        if perception.get(kind, {}).get("status") in {"blocked", "pending", "not_measured", "silent"}:
            perception[kind]["events"] = []
    policy = style.get("editing", {})
    graph = {"schema_version": "1.1", "status": "review_required", "base_timeline": deepcopy(timeline),
             "director": director or {"mode": "deterministic", "model": None}, "style": deepcopy(style), "events": []}
    shots = deepcopy(timeline.get("shots", []))
    music = perception.get("music", {}).get("events", [])
    pauses = [e for e in perception.get("speech", {}).get("events", []) if e["type"] == "SPEECH_PAUSE" and e.get("preserve")]
    if policy.get("rhythm_mode", "free") == "free":
        # No snapping cuts to music, but accents and J/L-cuts are separate style choices.
        _accents(graph, shots, music, pauses, policy)
        _audio_overlaps(graph, shots, policy)
        return graph
    for left, right in zip(shots, shots[1:]):
        boundary = float(right["start"])
        window = policy.get("snap_window_sec", 0.2)
        protected = [e for e in pauses if e["start"] < boundary + window and e["end"] > boundary - window]
        if protected or left.get("editorial_intent") == "hold":
            graph["events"].append({"event_id": f"ED{len(graph['events']) + 1:04d}", "type": "HOLD", "status": "proposed",
                                    "purpose": "Preserve existing timing: explicit hold or protected speech pause.",
                                    "timing": {"start": left["start"], "duration": left["end"] - left["start"]},
                                    "affected_objects": [left["shot_id"]], "evidence_refs": [e["event_id"] for e in protected]})
            continue
        nearby = [e for e in music if e["type"] in {"IMPACT_CANDIDATE", "PHRASE_CANDIDATE", "ONSET", "BEAT"}
                  and e.get("confidence", 0) >= 0.2 and abs(e["start"] - boundary) <= policy.get("snap_window_sec", 0.2)]
        if not nearby:
            continue
        # A reveal wants the hit; an ordinary cut wants the phrase. Onsets and beats are fallbacks.
        order = (["IMPACT_CANDIDATE", "PHRASE_CANDIDATE"] if right.get("editorial_intent") == "reveal" else ["PHRASE_CANDIDATE", "IMPACT_CANDIDATE"]) + ["ONSET", "BEAT"]
        chosen = min(nearby, key=lambda e: (order.index(e["type"]), abs(e["start"] - boundary), -e["confidence"]))
        at = float(chosen["start"])
        if min(at - left["start"], right["end"] - at) < policy.get("min_shot_sec", 1):
            continue
        def fits(shot, duration):
            if shot.get("media_type") == "image":
                return True
            interval = shot.get("usable_interval")
            source = float(shot.get("source_start", 0))
            return bool(interval and interval[0] <= source and source + duration <= interval[1])
        if not fits(left, at - left["start"]) or not fits(right, right["end"] - at):
            continue
        left["end"] = right["start"] = at
        kind = "REVEAL" if right.get("editorial_intent") == "reveal" else "CUT"
        event = {"event_id": f"ED{len(graph['events']) + 1:04d}", "type": kind, "status": "proposed",
                 "purpose": "Align existing narrative boundary to nearby measured musical evidence; listening review required.",
                 "timing": {"start": at, "duration": right["end"] - at},
                 "affected_objects": [left["shot_id"], right["shot_id"]], "evidence_refs": [chosen["event_id"]],
                 "boundary": {"left_shot_id": left["shot_id"], "right_shot_id": right["shot_id"], "from": boundary, "to": at}}
        graph["events"].append(event)
        anticipation = min(policy.get("anticipation_sec", 0), at - left["start"])
        if kind == "REVEAL" and anticipation > 0:
            graph["events"].append({"event_id": f"ED{len(graph['events']) + 1:04d}", "type": "ANTICIPATE", "status": "proposed",
                                    "purpose": "Prepare reveal; timing marker only, no invented camera movement.",
                                    "timing": {"start": at - anticipation, "duration": anticipation},
                                    "affected_objects": [left["shot_id"]], "evidence_refs": [chosen["event_id"]]})
    _accents(graph, shots, music, pauses, policy)
    _audio_overlaps(graph, shots, policy)
    return graph


def _next_id(graph: dict) -> str:
    return f"ED{len(graph['events']) + 1:04d}"


def _accents(graph: dict, shots: list[dict], music: list[dict], pauses: list[dict], policy: dict) -> None:
    """A beat does not always mean CUT: an impact inside a held shot can be emphasized instead."""
    if policy.get("accent_action") != "emphasize":
        return
    edge = policy.get("min_shot_sec", 1) / 2
    for hit in (e for e in music if e["type"] == "IMPACT_CANDIDATE" and e.get("confidence", 0) >= 0.2):
        t = float(hit["start"])
        shot = next((s for s in shots if float(s["start"]) + edge <= t <= float(s["end"]) - edge), None)
        if shot is None or any(p["start"] <= t <= p["end"] for p in pauses):
            continue
        graph["events"].append({"event_id": _next_id(graph), "type": "EMPHASIZE", "status": "proposed",
                                "purpose": "Musical impact inside a held shot: emphasize (punch-in, flash or text) instead of cutting; listening review required.",
                                "timing": {"start": t, "duration": min(0.5, float(shot["end"]) - t)},
                                "affected_objects": [shot["shot_id"]], "evidence_refs": [hit["event_id"]]})


def _audio_overlaps(graph: dict, shots: list[dict], policy: dict) -> None:
    """J/L-cuts only where the style asks for them and both shots provably have sound to overlap."""
    overlap = policy.get("audio_overlap") or {}
    mode, offset = overlap.get("mode"), float(overlap.get("offset_sec", 0))
    if mode not in {"j_cut", "l_cut"} or offset <= 0:
        return
    for left, right in zip(shots, shots[1:]):
        if not (left.get("has_native_audio") and right.get("has_native_audio")):
            continue
        boundary = float(right["start"])
        if mode == "j_cut":
            # Incoming sound starts early: B's source needs audio before its in-point, and A must outlast the overlap.
            interval, needed = right.get("usable_interval"), float(right.get("source_start", 0)) - offset
            ok = bool(interval) and needed >= interval[0] and offset < float(left["end"]) - float(left["start"])
        else:
            # Outgoing sound runs past the cut: A's source needs audio beyond its out-point, and B must outlast the overlap.
            interval = left.get("usable_interval")
            needed = float(left.get("source_start", 0)) + (float(left["end"]) - float(left["start"])) + offset
            ok = bool(interval) and needed <= interval[1] and offset < float(right["end"]) - float(right["start"])
        if not ok:
            continue
        kind = "J_CUT" if mode == "j_cut" else "L_CUT"
        at = boundary - offset if kind == "J_CUT" else boundary
        graph["events"].append({"event_id": _next_id(graph), "type": kind, "status": "proposed",
                                "purpose": "Incoming sound leads the picture." if kind == "J_CUT" else "Outgoing sound carries over the next picture.",
                                "timing": {"start": at, "duration": offset},
                                "affected_objects": [left["shot_id"], right["shot_id"]],
                                "audio_overlap": {"left_shot_id": left["shot_id"], "right_shot_id": right["shot_id"], "offset_sec": offset}})

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    brief=(p/'brief.md').read_text(encoding='utf-8') if (p/'brief.md').exists() else ''
    low=brief.lower()
    genre='documentary' if any(x in low for x in ('documentary','history','investigation','disappearance')) else 'explainer'
    tone='dark/investigative' if any(x in low for x in ('dark','disappearance','murder','mystery','investigative')) else 'clear/engaging'
    strategy={'schema_version':1,'status':'passed','source':'brief-heuristics','intent':{'genre':genre,'tone':tone,'pacing':'slow-to-escalating' if 'dark' in tone else 'moderate','visual_priority':'real archival footage' if genre=='documentary' else 'literal explanatory visuals','music':'minimal tense' if 'dark' in tone else 'atmospheric','graphics':'investigative' if genre=='documentary' else 'supportive','narration':'serious' if genre=='documentary' else 'conversational','evidence_requirement':'high' if genre=='documentary' else 'medium'},'director_policy':{'ask_for_each_beat':['audience_feeling','audience_understanding','visual_information_needed'],'allow_silence':True,'avoid_effect_stacking':True,'minimum_visual_information':True}}
    beats=json.loads((p/'beat_map.json').read_text()).get('beats',[]) if (p/'beat_map.json').exists() else []
    arc=[]
    for i,b in enumerate(beats):
        t=i/max(1,len(beats)-1); intensity=round(3+6*(1-abs(2*t-1)),2); arc.append({'beat_id':b.get('beat_id',f'B{i+1:03d}'),'intensity':intensity,'function':'hook' if i==0 else ('reveal' if i==len(beats)//2 else 'build'),'silence_after_seconds':0.8 if i and i%4==3 else 0.0})
    retention=[{'time_seconds':round(float(b.get('start',0)),2),'event':'hook' if i==0 else ('new_question' if i%3==0 else 'information')} for i,b in enumerate(beats)]
    for name,data in [('director_strategy.json',strategy),('emotional_arc.json',{'schema_version':1,'status':'passed','points':arc}),('retention_plan.json',{'schema_version':1,'status':'review_required','events':retention,'notes':['Heuristic plan; validate with editorial review.']})]: (p/name).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({'status':'passed','beats':len(beats),'artifacts':['director_strategy.json','emotional_arc.json','retention_plan.json']},indent=2))
if __name__=='__main__': main()
