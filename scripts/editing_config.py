"""Every editing tolerance in one place, validated. Styles override any subset; nothing else hard-codes these."""
from __future__ import annotations

import math
from copy import deepcopy

# The rule-based Director (director_brain.plan_edit).
DIRECTOR_DEFAULTS = {
    "rhythm_mode": "free",            # free: leave cut timing alone | phrase_aware: move cuts onto nearby musical events
    "snap_window_sec": 0.2,           # how far a cut may move to meet a musical event
    "min_shot_sec": 1.0,              # never create a shot shorter than this
    "min_event_confidence": 0.2,      # ignore music events with less heuristic support
    "anticipation_sec": 0.0,          # ANTICIPATE marker length before a reveal (0 = off)
    "accent_action": "none",          # none | emphasize: an impact inside a shot becomes EMPHASIZE, not a cut
    "emphasize_sec": 0.5,
    "build_motion": "none",           # none | push_in: a musical build inside a shot becomes a MOTION proposal
    "push_in_scale": 1.06,            # end scale of a proposed push-in
    "motion_min_sec": 2.0,            # a build must cover at least this much of a shot to earn a MOTION
    "transition_policy": "none",      # none | energy: an energy change at a cut becomes a TRANSITION proposal
    "transition_window_sec": 0.3,     # how close an energy event must be to a cut
    "transition_marker_sec": 0.5,
    "allowed_transitions": ["hard_cut"],  # recipe ids; from a Style DNA (measured) or the profile
    "audio_overlap": {"mode": "none", "offset_sec": 0.0},  # J/L-cuts: mode none | j_cut | l_cut
    "max_audio_overlap_sec": 2.0,
    # Restraint is a decision too: a strong musical event nothing acted on is recorded as NO_OP, with why.
    "explain_no_ops": True,
    "no_op_event_types": ["IMPACT_CANDIDATE", "SECTION_CANDIDATE", "BREAKDOWN_CANDIDATE"],
    "no_op_min_confidence": 0.4,
}

SPEECH_DEFAULTS = {
    "min_pause_sec": 0.3,             # gaps at least this long become SPEECH_PAUSE (preserved)
    "repeat_max_gap_sec": 0.5,        # an identical word this soon after the last is a repeat candidate
}

RHYTHM_REVIEW_DEFAULTS = {
    "on_beat_tolerance_sec": 0.07,    # a cut this close to a beat counts as on the beat
    "on_beat_warn_fraction": 0.9,     # warn when at least this share of cuts is on the beat ...
    "min_boundaries": 6,              # ... and there are at least this many cuts
    "mechanical_run": 5,              # this many shots in a row ...
    "mechanical_cv": 0.08,            # ... with lengths varying less than this (coefficient of variation)
    "motion_run": 4,                  # this many shots in a row with the same camera motion
}

_ENUMS = {
    "rhythm_mode": {"free", "phrase_aware"},
    "accent_action": {"none", "emphasize"},
    "build_motion": {"none", "push_in"},
    "transition_policy": {"none", "energy"},
}


def resolve(defaults: dict, overrides: dict | None, section: str) -> dict:
    """Defaults merged with the overrides the section knows about, type-checked. Unknown keys are ignored
    (a style carries keys for other components); a known key with a bad value raises."""
    out = deepcopy(defaults)
    for key, value in (overrides or {}).items():
        if key not in defaults:
            continue
        default = defaults[key]
        if key in _ENUMS:
            if value not in _ENUMS[key]:
                raise ValueError(f"{section}.{key} must be one of {sorted(_ENUMS[key])}, got {value!r}")
        elif isinstance(default, bool) or isinstance(default, str):
            if type(value) is not type(default):
                raise ValueError(f"{section}.{key} must be {type(default).__name__}")
        elif isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{section}.{key} must be a finite number >= 0, got {value!r}")
        elif isinstance(default, list):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{section}.{key} must be a list of strings")
        elif isinstance(default, dict):
            value = resolve(default, value, f"{section}.{key}") if isinstance(value, dict) else _bad(section, key)
        out[key] = deepcopy(value)
    if section == "editing":
        mode = out["audio_overlap"].get("mode")
        if mode not in {"none", "j_cut", "l_cut"}:
            raise ValueError("editing.audio_overlap.mode must be none, j_cut or l_cut")
    return out


def _bad(section: str, key: str):
    raise ValueError(f"{section}.{key} must be an object")


def director_config(policy: dict | None) -> dict:
    return resolve(DIRECTOR_DEFAULTS, policy, "editing")


def speech_config(overrides: dict | None = None) -> dict:
    return resolve(SPEECH_DEFAULTS, overrides, "speech")


def rhythm_review_config(overrides: dict | None = None) -> dict:
    return resolve(RHYTHM_REVIEW_DEFAULTS, overrides, "rhythm_review")
