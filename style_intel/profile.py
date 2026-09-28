"""Turn Style DNA into a NarrativeOS StyleProfile the Remotion renderer can load.

Only measured traits drive settings. Traits the DNA could not measure
(typography, title layout) fall back to explicit defaults and are listed in
the profile's `unmeasured` field, so nobody mistakes a default for a finding.

Writes:
  <project>/src/styles/generated/<id>.ts   typed StyleProfile, loaded into STYLE_REGISTRY
  <project>/src/styles/generated/index.ts  regenerated list of all generated profiles
  <dna dir>/style_profile.json             the same profile as JSON
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / "templates" / "narrativeos-video-templates" / "project"
RECIPES = PROJECT / "src" / "vfx" / "recipes.ts"
GENERATED = PROJECT / "src" / "styles" / "generated"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def known_transitions() -> set[str]:
    return set(re.findall(r"\bid: '([a-z0-9_]+)'", RECIPES.read_text(encoding="utf-8")))


def grade(look: dict) -> dict:
    b = look["bands"]
    parts = []
    if b["colour"] in ("monochrome", "tinted_monochrome"):
        parts.append("grayscale(1)")
        if b["colour"] == "tinted_monochrome":
            # CSS duotone: sepia gives an orange tint (~35deg); rotate it to the measured dominant hue.
            parts.append(f"sepia(0.6) hue-rotate({(look['dominant_hue_deg'] - 35) % 360:.0f}deg)")
    else:
        parts.append(f"saturate({clamp(look['saturation'] / 0.30, 0.4, 1.6):.2f})")
    parts.append(f"contrast({clamp(look['contrast'] / 0.20, 0.8, 1.4):.2f})")
    parts.append(f"brightness({clamp(look['luma_mean'] / 0.42, 0.8, 1.15):.2f})")
    wash = {
        "warm": ("rgba(40,24,10,0.32)", "rgba(255,214,170,0.16)"),
        "cool": ("rgba(10,24,44,0.32)", "rgba(190,215,255,0.14)"),
        "neutral": ("rgba(0,0,0,0.22)", "rgba(255,255,255,0.06)"),
    }[b["tone"]]
    return {"filter": " ".join(parts), "shadow": wash[0], "highlight": wash[1]}


# Transitions are allowed only with evidence in the reference. Families the
# analyzer cannot detect yet (whip, glitch, RGB split, zoom punch, shake)
# are never switched on from a DNA; add them by hand if wanted.
def choose_transitions(dna: dict) -> list[str]:
    ed, look = dna["editing"], dna["visual"]
    kinds = ed.get("gradual_kinds", {})
    motion = look["camera_motion"]["fractions"]
    picks = ["hard_cut"]
    if ed["dips_to_black"] or kinds.get("dark"):
        picks.append("dip_to_black")
    if ed["flash_frames_per_minute"] >= 0.5:
        picks += ["flash_cut", "exposure_bump"]
    if kinds.get("light"):
        picks += ["light_leak_cool" if look["bands"]["tone"] == "cool" else "light_leak_warm", "film_burn_passage", "leak_crossfade"]
    if kinds.get("dissolve"):
        picks += ["crossfade_soft", "blur_dissolve"]
    if motion.get("push_in", 0) >= 0.2:
        picks.append("push_in_cut")
    if look["bands"]["colour"] in ("monochrome", "tinted_monochrome") and "film_burn_passage" in picks:
        picks.append("archive_flicker_cut")
    seen: list[str] = []
    for p in picks:
        if p not in seen:
            seen.append(p)
    missing = set(seen) - known_transitions()
    if missing:
        raise ValueError(f"profile picked transitions that are not registered in recipes.ts: {sorted(missing)}")
    return seen


def build(dna: dict, style_id: str, label: str | None = None) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", style_id):
        raise ValueError("style id must be lowercase letters, digits and underscores, starting with a letter")
    ed, look = dna["editing"], dna["visual"]
    cpm, flashes = ed["cuts_per_minute"], ed["flash_frames_per_minute"]
    density = "bold" if (cpm > 30 or flashes > 2) else "moderate" if cpm > 12 else "minimal"
    handheld = look["camera_motion"]["fractions"].get("handheld_or_action", 0)
    median_shot = ed["shot_duration_sec"]["median"]
    beat_sync = (ed.get("beat_sync") or {}).get("synced")
    return {
        "id": style_id,
        "label": label or f"From reference: {dna['source']['file']}",
        "status": "DOCUMENTED",
        "source": {"kind": "reference_video", "file": dna["source"]["file"], "sha256": dna["source"]["sha256"], "analyzerVersion": dna["analyzer_version"]},
        "unmeasured": ["typography", "title layout", "vignette"],
        "grade": grade(look),
        "typography": {
            # Not measured (no OCR yet): neutral defaults, listed in `unmeasured`.
            "serifFamily": "PlayfairLocal, Georgia, serif",
            "sansFamily": "InterLocal, Helvetica, Arial, sans-serif",
            "headlineWeight": 600,
            "kickerLetterSpacing": 5,
            "boneColor": "rgba(246,244,240,0.98)",
            "boneDimColor": "rgba(222,220,214,0.72)",
        },
        "motion": {
            "weaveAmount": round(clamp(handheld * 2, 0, 1.5), 2),
            "kenBurnsEase": [0.45, 0, 0.55, 1],
            "titleStaggerFrames": {"very_fast": 0.5, "fast": 0.7, "moderate": 1.0}.get(ed["pacing"], 1.5),
        },
        "transitionSet": ["none"],
        "vfx": {
            "density": density,
            "allowedTransitions": choose_transitions(dna),
            "overlayOpacityScale": {"minimal": 0.6, "moderate": 0.85, "bold": 1.0}[density],
            "tint": {"hueRotate": 0, "saturate": 0.3 if look["bands"]["colour"] in ("monochrome", "tinted_monochrome") else 1},
        },
        "pacing": {"targetShotSec": median_shot, "cutsPerMinute": cpm, "beatSync": bool(beat_sync)},
        "vignetteStrength": 0.8 if look["bands"]["colour"] in ("monochrome", "tinted_monochrome") else 0.5,
        "grainOpacity": {"clean": 0.05, "light": 0.15, "heavy": 0.32, None: 0.1}[look["bands"]["grain"]],
    }


def write_ts(profile: dict) -> Path:
    GENERATED.mkdir(parents=True, exist_ok=True)
    body = json.dumps(profile, indent="\t")
    ts = GENERATED / f"{profile['id']}.ts"
    ts.write_text(
        f"// Generated by style_intel from {profile['source']['file']} (sha256 {profile['source']['sha256'][:12]}).\n"
        "// Do not edit by hand: re-run `python -m style_intel profile <style_dna.json> --id <id>`.\n"
        "import type {StyleProfile} from '../StyleProfile';\n\n"
        f"export const style: StyleProfile = {body};\n",
        encoding="utf-8",
    )
    write_index()
    return ts


def write_index() -> Path:
    GENERATED.mkdir(parents=True, exist_ok=True)
    ids = sorted(p.stem for p in GENERATED.glob("*.ts") if p.stem != "index")
    lines = ["// Generated by style_intel: every profile in this folder. Do not edit by hand.", "import type {StyleProfile} from '../StyleProfile';"]
    lines += [f"import {{style as s{i}}} from './{sid}';" for i, sid in enumerate(ids)]
    lines += ["", f"export const GENERATED_STYLES: StyleProfile[] = [{', '.join(f's{i}' for i in range(len(ids)))}];", ""]
    index = GENERATED / "index.ts"
    index.write_text("\n".join(lines), encoding="utf-8")
    return index
