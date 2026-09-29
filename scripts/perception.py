"""Adapt measured inputs to time-local evidence; never infer human emotion."""
from __future__ import annotations
import math
from pathlib import Path


def visual_map(path: Path, asset_id: str, timeline_start: float = 0) -> dict:
    """Full-source cut times, sampled ORB motion. This is not semantic approval."""
    from style_intel import shots, visual
    from style_intel.media import probe, sha256
    meta = probe(path)
    frames, raw = shots.frame_track(path)
    hard = shots.merge_cuts(raw, meta["duration_sec"])
    gradual = shots.gradual_transitions(path, meta["fps"] or 30.0, hard)
    kinds = shots.classify_gradual(frames, gradual)
    flashes, dips = shots.flashes_and_dips(frames)
    cuts = sorted(hard + gradual)
    intervals = shots.shots_from_cuts(cuts, meta["duration_sec"])
    measured = []
    for shot in visual.sample_shots(intervals):
        motion = visual.camera_motion(path, shot)
        mid = shot["start"] + shot["duration"] / 2
        dt = min(3.0, shot["duration"] * 0.6)
        measured.append({**shot, "asset_id": asset_id,
                         "start": shot["start"] + timeline_start, "end": shot["end"] + timeline_start,
                         "motion": motion, "motion_class": visual.classify_motion(motion),
                         "confidence": round(motion["inlier_share"], 3) if motion else None,
                         "evidence": {"method": "style_intel.ORB_RANSAC", "source_interval": [shot["start"], shot["end"]],
                                      "sample_times_sec": [mid - dt / 2, mid + dt / 2] if motion else [], "cut_method": "ffmpeg.scdet + histogram_window"}})
    return {"status": "measured", "asset_id": asset_id, "source": {"file": path.name, "sha256": sha256(path)},
            "duration_sec": meta["duration_sec"], "timeline_start": timeline_start,
            "cuts_sec": [t + timeline_start for t in cuts], "gradual_transitions_sec": [t + timeline_start for t in gradual],
            "transition_vocabulary": shots.transition_vocabulary(hard, gradual, kinds, flashes, dips), "shots": measured,
            "not_measured": ["gaze", "faces", "action_identity", "emotion", "shot_scale", "directional_continuity"],
            "limitations": ["Hard cuts plus histogram-detected gradual transitions; at most 60 motion samples. Featureless frames remain unmeasured.", "Motion evidence does not establish rights, identity or narrative relevance."]}


def speech_map(alignment: dict, narration: dict, duration: float, config: dict | None = None) -> dict:
    from editing_config import speech_config
    cfg = speech_config(config)
    if alignment.get("status") != "passed" or not alignment.get("captions"):
        return {"status": "not_measured", "events": [], "reason": "No passed, nonempty alignment supplied."}
    events = []
    previous_caption_end = 0.0
    for index, caption in enumerate(alignment.get("captions", [])):
        start, end = float(caption["start"]), float(caption["end"])
        if not all(math.isfinite(t) for t in (start, end, duration)) or start < previous_caption_end or not start < end <= duration:
            return {"status": "blocked", "events": [], "reason": "Invalid or overlapping alignment interval."}
        previous_caption_end = end
        previous_word_end = start
        for word in caption.get("words", []) or [caption]:
            a, b = float(word["start"]), float(word["end"])
            if not all(math.isfinite(t) for t in (a, b)) or a < previous_word_end or not a < b <= end:
                return {"status": "blocked", "events": [], "reason": "Invalid word timing."}
            previous_word_end = b
            events.append({"event_id": f"S{len(events) + 1:05d}",
                           "type": "WORD" if caption.get("words") else "SPEECH_SEGMENT",
                           "start": float(word["start"]), "end": float(word["end"]),
                           "text": word.get("word", word.get("text", "")),
                           "confidence": word.get("probability"),
                           "evidence": {"method": "supplied_alignment", "model": alignment.get("alignment_model"), "caption_index": index}})
    previous = 0.0
    for word in list(events) + [{"start": duration, "end": duration}]:
        if word["start"] - previous >= cfg["min_pause_sec"]:
            pause = {"event_id": f"S{len(events) + 1:05d}", "type": "SPEECH_PAUSE", "start": previous, "end": word["start"],
                     "preserve": True, "meaning_source": None, "reason": "Unclassified timing gap; preserve pending editorial review.",
                     "confidence": None, "evidence": {"method": "alignment_gap", "acoustic_silence_verified": False}}
            for segment in narration.get("segments", []):
                t = segment.get("timing", {})
                if segment.get("type") == "SILENCE" and segment.get("reason") and float(t["target_start"]) < pause["end"] and float(t["target_end"]) > pause["start"]:
                    pause.update(meaning_source=f"narration_plan:{segment['segment_id']}", reason=segment["reason"])
            events.append(pause)
        previous = word["end"]
    trim_candidates(events, cfg["repeat_max_gap_sec"])
    return {"status": "measured", "events": sorted(events, key=lambda e: (e["start"], e["event_id"])),
            "not_measured": ["emotion", "breaths", "false_starts", "emphasis", "acoustic_silence", "discourse_fillers (like / you know)"]}


# Only unambiguous hesitation sounds. "like" and "you know" are often meaningful, so they are never flagged.
FILLERS = {"um", "uh", "uhm", "umm", "erm", "er", "ah", "hmm", "mm"}


def trim_candidates(events: list[dict], repeat_max_gap_sec: float) -> None:
    """Mark hesitation words and immediate word repeats as trim candidates. The editor decides; nothing is removed."""
    words = [e for e in events if e["type"] == "WORD"]
    norm = lambda w: "".join(c for c in w.get("text", "").lower() if c.isalnum() or c == "'")  # noqa: E731
    found = []
    for i, w in enumerate(words):
        token = norm(w)
        kind = None
        if token in FILLERS:
            kind, reason = "SPEECH_FILLER", f"Hesitation sound '{token}'."
        elif i and token and token == norm(words[i - 1]) and w["start"] - words[i - 1]["end"] < repeat_max_gap_sec:
            kind, reason = "SPEECH_REPEAT", f"'{token}' repeated immediately."
        if kind:
            found.append({"event_id": "", "type": kind, "start": w["start"], "end": w["end"], "action": "trim_candidate",
                          "reason": reason + " Review before trimming; some repeats carry emphasis.",
                          "confidence": None, "evidence": {"method": "alignment_text_match", "word_event": w["event_id"]}})
    for f in found:
        f["event_id"] = f"S{len(events) + 1:05d}"
        events.append(f)


def rhythm_review(timeline: dict, music: dict, visual: list[dict], config: dict | None = None) -> dict:
    """Editor's-eye warnings about monotony and mechanical cutting. Warnings for review, never automatic changes."""
    from editing_config import rhythm_review_config
    cfg = rhythm_review_config(config)
    shots = timeline.get("shots", [])
    warnings = []
    durations = [float(s["end"]) - float(s["start"]) for s in shots]
    n = int(cfg["mechanical_run"])
    for i in range(len(durations) - n + 1):
        run = durations[i:i + n]
        mean = sum(run) / n
        if mean > 0 and (sum((d - mean) ** 2 for d in run) / n) ** 0.5 / mean < cfg["mechanical_cv"]:
            warnings.append({"kind": "mechanical_shot_lengths", "shots": [s["shot_id"] for s in shots[i:i + n]],
                             "detail": f"{n} shots in a row last ~{mean:.2f} s each; vary holds so the rhythm breathes."})
            break
    beats = [float(e["start"]) for e in music.get("events", []) if e["type"] == "BEAT"]
    boundaries = [float(s["start"]) for s in shots[1:]]
    if beats and len(boundaries) >= cfg["min_boundaries"]:
        on_beat = sum(1 for b in boundaries if min(abs(b - t) for t in beats) <= cfg["on_beat_tolerance_sec"]) / len(boundaries)
        if on_beat >= cfg["on_beat_warn_fraction"]:
            warnings.append({"kind": "every_cut_on_the_beat", "on_beat_fraction": round(on_beat, 2),
                             "detail": "Nearly every cut lands on a beat; consider holding through some beats or cutting between them."})
    # Camera-motion monotony: map each timeline shot to the measured source shot it plays from.
    by_asset = {v["asset_id"]: v for v in visual}
    classes = []
    for s in shots:
        measured = by_asset.get(s.get("asset_id"))
        src = float(s.get("source_start", 0))
        hit = next((m for m in (measured or {}).get("shots", []) if m["evidence"]["source_interval"][0] <= src < m["evidence"]["source_interval"][1]), None)
        classes.append(hit["motion_class"] if hit and hit["motion_class"] not in {"unmeasured"} else None)
    run_start = 0
    for i in range(1, len(classes) + 1):
        if i == len(classes) or classes[i] != classes[run_start] or classes[run_start] is None:
            if classes[run_start] is not None and i - run_start >= cfg["motion_run"]:
                warnings.append({"kind": "repeated_camera_motion", "motion": classes[run_start],
                                 "shots": [s["shot_id"] for s in shots[run_start:i]],
                                 "detail": f"{i - run_start} shots in a row are '{classes[run_start]}'; a contrasting shot would add variety."})
            run_start = i
    return {"schema_version": 1, "status": "review_required", "config": cfg, "warnings": warnings,
            "not_measured": ["shot_scale (wide/medium/close)", "gaze and screen direction", "action matching"]}
