#!/usr/bin/env python3
"""Derive transparent editorial strategy artifacts from a brief and channel profile."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from copy import deepcopy


# What a musical event may turn into. A beat is never automatically a CUT.
EVENT_ACTIONS = {"CUT", "HOLD", "ANTICIPATE", "REVEAL", "EMPHASIZE", "MOTION", "TRANSITION", "J_CUT", "L_CUT", "NO_OP"}

# Energy change at a cut -> transition families, most preferred first. Only recipes the style allows are used,
# and with a Style DNA those are the transitions the reference measurably used (style_intel.profile.choose_transitions).
TRANSITION_FAMILIES = {
    "IMPACT_CANDIDATE": ["flash_cut", "exposure_bump"],
    "BREAKDOWN_CANDIDATE": ["dip_to_black", "crossfade_soft", "blur_dissolve"],
    "SECTION_DOWN": ["dip_to_black", "crossfade_soft", "blur_dissolve"],
    "SECTION_UP": ["light_leak_warm", "light_leak_cool", "leak_crossfade", "film_burn_passage", "crossfade_soft"],
}


def plan_edit(timeline: dict, perception: dict, style: dict, director: dict | None = None) -> dict:
    """Rule-based, music-aware Director. Every event is a proposal; nothing here approves or overwrites a timeline.

    director: None / {"mode": "deterministic"} (default), or
              {"mode": "model_assisted", "provider": <model_provider config>} to add validated model proposals.
    """
    from editing_config import director_config
    director = director or {"mode": "deterministic", "model": None}
    mode = director.get("mode", "deterministic")
    if mode not in {"deterministic", "model_assisted"} or (mode == "deterministic" and director.get("model")):
        raise ValueError("Director mode must be 'deterministic' or 'model_assisted' (with a provider config)")
    if mode == "model_assisted" and not director.get("provider"):
        raise ValueError("model_assisted Director needs a reasoning provider config")
    cfg = director_config(style.get("editing", {}))
    perception = deepcopy(perception)
    for kind in ("music", "speech"):
        if perception.get(kind, {}).get("status") in {"blocked", "pending", "not_measured", "silent"}:
            perception[kind]["events"] = []
    graph = {"schema_version": "1.2", "status": "review_required", "base_timeline": deepcopy(timeline),
             "director": {"mode": mode, "model": None}, "style": deepcopy(style), "director_config": cfg, "events": []}
    shots = deepcopy(timeline.get("shots", []))
    music = [e for e in perception.get("music", {}).get("events", []) if e.get("confidence", 0) >= cfg["min_event_confidence"]]
    pauses = [e for e in perception.get("speech", {}).get("events", []) if e["type"] == "SPEECH_PAUSE" and e.get("preserve")]
    if cfg["rhythm_mode"] == "phrase_aware":
        _snap_boundaries(graph, shots, music, pauses, cfg)
    _transitions(graph, shots, music, cfg)
    _motions(graph, shots, music, cfg)
    _accents(graph, shots, music, pauses, cfg)
    _audio_overlaps(graph, shots, cfg)
    _no_ops(graph, shots, music, pauses, cfg)
    if mode == "model_assisted":
        _model_proposals(graph, director["provider"], perception)
    return graph


def _next_id(graph: dict) -> str:
    return f"ED{len(graph['events']) + 1:04d}"


def _snap_boundaries(graph: dict, shots: list[dict], music: list[dict], pauses: list[dict], cfg: dict) -> None:
    """Move existing cuts onto nearby musical events, unless a hold or a meaningful pause protects them."""
    window = cfg["snap_window_sec"]
    for left, right in zip(shots, shots[1:]):
        boundary = float(right["start"])
        protected = [e for e in pauses if e["start"] < boundary + window and e["end"] > boundary - window]
        if protected or left.get("editorial_intent") == "hold":
            graph["events"].append({"event_id": _next_id(graph), "type": "HOLD", "status": "proposed",
                                    "purpose": "Preserve existing timing: explicit hold or protected speech pause.",
                                    "timing": {"start": left["start"], "duration": left["end"] - left["start"]},
                                    "affected_objects": [left["shot_id"]], "evidence_refs": [e["event_id"] for e in protected]})
            continue
        nearby = [e for e in music if e["type"] in {"IMPACT_CANDIDATE", "PHRASE_CANDIDATE", "ONSET", "BEAT"}
                  and abs(e["start"] - boundary) <= window]
        if not nearby:
            continue
        # A reveal wants the hit; an ordinary cut wants the phrase. Onsets and beats are fallbacks.
        order = (["IMPACT_CANDIDATE", "PHRASE_CANDIDATE"] if right.get("editorial_intent") == "reveal" else ["PHRASE_CANDIDATE", "IMPACT_CANDIDATE"]) + ["ONSET", "BEAT"]
        chosen = min(nearby, key=lambda e: (order.index(e["type"]), abs(e["start"] - boundary), -e["confidence"]))
        at = float(chosen["start"])
        if min(at - left["start"], right["end"] - at) < cfg["min_shot_sec"]:
            continue
        if not _fits(left, at - left["start"]) or not _fits(right, right["end"] - at):
            continue
        left["end"] = right["start"] = at
        kind = "REVEAL" if right.get("editorial_intent") == "reveal" else "CUT"
        graph["events"].append({"event_id": _next_id(graph), "type": kind, "status": "proposed",
                                "purpose": "Align existing narrative boundary to nearby measured musical evidence; listening review required.",
                                "timing": {"start": at, "duration": right["end"] - at},
                                "affected_objects": [left["shot_id"], right["shot_id"]], "evidence_refs": [chosen["event_id"]],
                                "boundary": {"left_shot_id": left["shot_id"], "right_shot_id": right["shot_id"], "from": boundary, "to": at}})
        anticipation = min(cfg["anticipation_sec"], at - left["start"])
        if kind == "REVEAL" and anticipation > 0:
            graph["events"].append({"event_id": _next_id(graph), "type": "ANTICIPATE", "status": "proposed",
                                    "purpose": "Prepare reveal; timing marker only, no invented camera movement.",
                                    "timing": {"start": at - anticipation, "duration": anticipation},
                                    "affected_objects": [left["shot_id"]], "evidence_refs": [chosen["event_id"]]})


def _fits(shot: dict, duration: float) -> bool:
    if shot.get("media_type") == "image":
        return True
    interval = shot.get("usable_interval")
    source = float(shot.get("source_start", 0))
    return bool(interval and interval[0] <= source and source + duration <= interval[1])


def _transitions(graph: dict, shots: list[dict], music: list[dict], cfg: dict) -> None:
    """An energy change at a cut earns a transition, chosen only from the style's allowed (measured) recipes."""
    if cfg["transition_policy"] != "energy":
        return
    allowed = set(cfg["allowed_transitions"]) - {"hard_cut"}
    if not allowed:
        return
    for left, right in zip(shots, shots[1:]):
        boundary = float(right["start"])
        near = [e for e in music if abs(e["start"] - boundary) <= cfg["transition_window_sec"]
                and e["type"] in {"IMPACT_CANDIDATE", "BREAKDOWN_CANDIDATE", "SECTION_CANDIDATE"}]
        for hit in sorted(near, key=lambda e: -e["confidence"]):
            family = hit["type"]
            if family == "SECTION_CANDIDATE":
                family = "SECTION_UP" if hit["evidence"].get("delta_db", 0) > 0 else "SECTION_DOWN"
            recipe = next((r for r in TRANSITION_FAMILIES[family] if r in allowed), None)
            if recipe is None:
                continue
            graph["events"].append({"event_id": _next_id(graph), "type": "TRANSITION", "status": "proposed",
                                    "purpose": f"Energy change ({family.lower()}) at the cut; transition from the style's measured vocabulary.",
                                    "timing": {"start": boundary, "duration": cfg["transition_marker_sec"]},
                                    "affected_objects": [left["shot_id"], right["shot_id"]], "evidence_refs": [hit["event_id"]],
                                    "transition": {"left_shot_id": left["shot_id"], "right_shot_id": right["shot_id"], "recipe": recipe}})
            break


def _motions(graph: dict, shots: list[dict], music: list[dict], cfg: dict) -> None:
    """A musical build inside a shot can drive camera motion (a push-in) instead of a cut."""
    if cfg["build_motion"] != "push_in":
        return
    for build in (e for e in music if e["type"] == "BUILD_CANDIDATE"):
        b0, b1 = float(build["start"]), float(build["evidence"].get("end_sec", build["start"]))
        for shot in shots:
            start, end = max(b0, float(shot["start"])), min(b1, float(shot["end"]))
            if end - start >= cfg["motion_min_sec"]:
                graph["events"].append({"event_id": _next_id(graph), "type": "MOTION", "status": "proposed",
                                        "purpose": "Musical build inside the shot: slow push-in rising with it, instead of cutting.",
                                        "timing": {"start": start, "duration": end - start},
                                        "affected_objects": [shot["shot_id"]], "evidence_refs": [build["event_id"]],
                                        "motion": {"kind": "push_in", "scale_from": 1.0, "scale_to": cfg["push_in_scale"]}})


def _accents(graph: dict, shots: list[dict], music: list[dict], pauses: list[dict], cfg: dict) -> None:
    """A beat does not always mean CUT: an impact inside a held shot can be emphasized instead."""
    if cfg["accent_action"] != "emphasize":
        return
    edge = cfg["min_shot_sec"] / 2
    for hit in (e for e in music if e["type"] == "IMPACT_CANDIDATE"):
        t = float(hit["start"])
        shot = next((s for s in shots if float(s["start"]) + edge <= t <= float(s["end"]) - edge), None)
        if shot is None or any(p["start"] <= t <= p["end"] for p in pauses):
            continue
        graph["events"].append({"event_id": _next_id(graph), "type": "EMPHASIZE", "status": "proposed",
                                "purpose": "Musical impact inside a held shot: emphasize (punch-in, flash or text) instead of cutting; listening review required.",
                                "timing": {"start": t, "duration": min(cfg["emphasize_sec"], float(shot["end"]) - t)},
                                "affected_objects": [shot["shot_id"]], "evidence_refs": [hit["event_id"]]})


def _no_ops(graph: dict, shots: list[dict], music: list[dict], pauses: list[dict], cfg: dict) -> None:
    """A strong musical event that no rule acted on is recorded as NO_OP with the reasons, so restraint is
    visible and reviewable instead of silent. The reasons come from the actual settings, never invented."""
    if not cfg["explain_no_ops"] or not shots:
        return
    used = {ref for e in graph["events"] for ref in e.get("evidence_refs", [])}
    boundaries = [float(s["start"]) for s in shots[1:]]
    for ev in music:
        if ev["type"] not in cfg["no_op_event_types"] or ev["event_id"] in used or ev.get("confidence", 0) < cfg["no_op_min_confidence"]:
            continue
        t = float(ev["start"])
        shot = next((s for s in shots if float(s["start"]) <= t < float(s["end"])), shots[-1])
        near_cut = any(abs(t - b) <= cfg["snap_window_sec"] for b in boundaries)
        why = []
        if any(p["start"] <= t <= p["end"] for p in pauses):
            why.append("it falls in a protected speech pause")
        if near_cut and cfg["rhythm_mode"] == "free":
            why.append("rhythm_mode is free: existing cuts are not moved onto music")
        if near_cut and cfg["transition_policy"] == "none" and ev["type"] != "IMPACT_CANDIDATE":
            why.append("transition_policy is none: energy changes at cuts are not marked")
        if not near_cut:
            why.append(f"no cut within {cfg['snap_window_sec']} s, and a cut is not invented where the story has none")
            if ev["type"] == "IMPACT_CANDIDATE" and cfg["accent_action"] == "none":
                why.append("accent_action is none: impacts inside a shot are not emphasized")
            if ev["type"] != "IMPACT_CANDIDATE" and cfg["build_motion"] == "none":
                why.append("build_motion is none: energy changes inside a shot do not drive camera motion")
        if not why:
            why.append("no rule's conditions were met (see director_config)")
        graph["events"].append({"event_id": _next_id(graph), "type": "NO_OP", "status": "proposed",
                                "purpose": "Considered and deliberately not acted on: " + "; ".join(why) + ".",
                                "timing": {"start": t, "duration": 0.1}, "affected_objects": [shot["shot_id"]],
                                "evidence_refs": [ev["event_id"]], "considered": {"music_event": ev["type"], "reasons": why}})


def _audio_overlaps(graph: dict, shots: list[dict], cfg: dict) -> None:
    """J/L-cuts only where the style asks for them and both shots provably have sound to overlap."""
    mode, offset = cfg["audio_overlap"]["mode"], float(cfg["audio_overlap"]["offset_sec"])
    if mode not in {"j_cut", "l_cut"} or not 0 < offset <= cfg["max_audio_overlap_sec"]:
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


def _model_proposals(graph: dict, provider_config: dict, perception: dict) -> None:
    """Ask the configured reasoning model for extra proposals; keep only those that pass the same validator."""
    from event_graph import validate
    from model_provider import load_reasoning_provider
    identity, call = load_reasoning_provider(provider_config)
    graph["director"]["model"] = identity
    reply = call("propose_edit_events", {
        "allowed_event_types": sorted(EVENT_ACTIONS), "base_timeline": graph["base_timeline"],
        "music_events": perception.get("music", {}).get("events", []), "speech_events": perception.get("speech", {}).get("events", []),
        "style": graph["style"], "existing_events": graph["events"],
        "rules": "Every event needs type, purpose, timing {start, duration}, affected_objects; boundary/transition/audio_overlap payloads as in existing_events."})
    graph["rejected_model_events"] = []
    for proposed in reply.get("events", []):
        candidate = {**deepcopy(proposed), "event_id": _next_id(graph), "status": "proposed", "source": {"kind": "model", **identity}}
        errors = validate({**graph, "events": graph["events"] + [candidate]}) if isinstance(proposed, dict) else [{"error": "not an object"}]
        if errors:
            graph["rejected_model_events"].append({"event": proposed, "errors": errors})
        else:
            graph["events"].append(candidate)


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
