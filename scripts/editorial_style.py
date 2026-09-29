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
    from editing_config import DIRECTOR_DEFAULTS
    dna = dna or {}
    measured = dna.get("editing", {}).get("shot_duration_sec", {}).get("median")
    editing = {"target_shot_sec": measured, **deepcopy(DIRECTOR_DEFAULTS)}
    if dna.get("editing") and dna.get("visual"):
        # Transitions come from what the reference measurably used, never from guesses (style_intel.profile).
        from style_intel.profile import choose_transitions
        editing["allowed_transitions"] = choose_transitions(dna)
        editing["allowed_transitions_source"] = "style_dna"
        editing["transition_vocabulary"] = deepcopy(dna["editing"].get("transition_vocabulary"))
    else:
        editing["allowed_transitions_source"] = "default: no full Style DNA, hard cuts only"
    style = {"schema_version": 1, "profile_version": profile.get("profile_version"),
             "measurement_source": dna.get("source", {}).get("sha256"),
             "editing": editing,
             "narration": {"pace": 1.0}, "captions": {"font_size": 42, "animation": "none"},
             "image": {}, "music": {}, "sfx": {}}
    for kind in ("editing", "narration", "captions", "image", "music", "sfx"):
        style[kind].update(common)
        style[kind].update(deepcopy(intent.get(kind, {})))
    if "allowed_transitions" in intent.get("editing", {}):
        style["editing"]["allowed_transitions_source"] = "profile"
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
