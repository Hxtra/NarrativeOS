"""One explicit editorial intent for every modality; measured DNA is not mood."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def resolve_style(profile: dict, dna: dict | None = None) -> dict:
    intent = profile.get("editorial_intent", {})
    common = {"tone": intent.get("tone", "neutral"), "avoid": deepcopy(intent.get("avoid", []))}
    dna = dna or {}
    measured = dna.get("editing", {}).get("shot_duration_sec", {}).get("median")
    style = {"schema_version": 1, "profile_version": profile.get("profile_version"),
             "measurement_source": dna.get("source", {}).get("sha256"),
             "editing": {"target_shot_sec": measured, "min_shot_sec": 1.0, "snap_window_sec": 0.2, "rhythm_mode": "free", "anticipation_sec": 0,
                         "accent_action": "none", "audio_overlap": {"mode": "none", "offset_sec": 0}},
             "narration": {"pace": 1.0}, "captions": {"font_size": 42, "animation": "none"},
             "image": {}, "music": {}, "sfx": {}}
    for kind in ("editing", "narration", "captions", "image", "music", "sfx"):
        style[kind].update(common)
        style[kind].update(deepcopy(intent.get(kind, {})))
    style["style_id"] = fingerprint(style)
    return style


def production_directions(narration: dict, captions: dict, style: dict) -> dict:
    plan = deepcopy(narration)
    for segment in plan.get("segments", []):
        if segment.get("type") == "NARRATION":
            segment["voice_direction"] = {**style["narration"], **segment.get("voice_direction", {})}
            segment["style_id"] = style["style_id"]
    return {"schema_version": 1, "status": "review_required", "style_id": style["style_id"],
            "narration_plan": plan,
            "caption_request": {**deepcopy(captions), "style": deepcopy(style["captions"]), "style_id": style["style_id"]},
            "image_direction": deepcopy(style["image"]), "music_direction": deepcopy(style["music"]),
            "sfx_direction": deepcopy(style["sfx"])}
