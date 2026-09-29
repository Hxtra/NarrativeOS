"""Run every analyzer on a reference video and assemble its Style DNA."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from . import ANALYZER_VERSION, audio, shots, speech, visual
from .media import probe, sha256

# Band thresholds. Measured values are always kept alongside the band, so a
# threshold can be retuned later without re-analysing.
PACING = [(1.5, "very_fast"), (3.0, "fast"), (6.0, "moderate"), (10.0, "slow")]  # median shot seconds
CONTRAST = [(0.15, "low"), (0.25, "medium")]  # luma std, 0-1
SATURATION = [(0.18, "muted"), (0.40, "natural")]  # mean HSV saturation, 0-1
# Immerkaer noise sigma (0-255) on a native-resolution crop, as it survives in the delivered file.
# Calibrated on three references (2026-09-28): a clean screen-recorded vertical video 0.24, a
# compressed documentary 0.001, a Remotion render with a heavy grain overlay 1.05. Revisit with more.
GRAIN = [(0.35, "clean"), (0.9, "light")]


def band(value: float | None, table: list[tuple[float, str]], top: str) -> str | None:
    if value is None:
        return None
    for limit, name in table:
        if value < limit:
            return name
    return top


def analyze(video: Path, out_dir: Path, with_speech: bool = True, threshold: float = 10.0) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = probe(video)
    duration = meta["duration_sec"]

    frames, raw_cuts = shots.frame_track(video, threshold)
    hard = shots.merge_cuts(raw_cuts, duration)
    gradual = [g for g in shots.gradual_transitions(video, meta["fps"] or 30.0, hard) if shots.MIN_SHOT_SEC < g < duration - shots.MIN_SHOT_SEC]
    cuts = sorted(hard + gradual)
    shot_list = shots.shots_from_cuts(cuts, duration)
    flashes, dips = shots.flashes_and_dips(frames)
    kinds = shots.classify_gradual(frames, gradual)
    editing = {
        **shots.summarize(shot_list, duration),
        "hard_cuts": len(hard),
        "gradual_transitions": len(gradual),
        "gradual_fraction": round(len(gradual) / len(cuts), 3) if cuts else 0.0,
        "gradual_kinds": {k: kinds.count(k) for k in ("light", "dark", "dissolve")},
        "flash_frames_per_minute": round(len(flashes) / duration * 60, 2),
        "dips_to_black": len(dips),
        "transition_vocabulary": shots.transition_vocabulary(hard, gradual, kinds, flashes, dips),
    }
    editing["pacing"] = band(editing["shot_duration_sec"]["median"], PACING, "very_slow")

    look, per_shot, thumbs = visual.analyze(video, shot_list)
    mono, tinted = look["monochrome_shot_fraction"], look["tinted_monochrome_shot_fraction"]
    if mono + tinted >= 0.7:
        colour_band = "monochrome" if mono >= tinted else "tinted_monochrome"  # toned B&W / duotone
    else:
        colour_band = band(look["saturation"], SATURATION, "vivid")
    tone = "warm" if look["warmth"] > 0.03 else "cool" if look["warmth"] < -0.03 else "neutral"
    look["bands"] = {
        "colour": colour_band,
        "tone": tone,
        "contrast": band(look["contrast"], CONTRAST, "high"),
        "grain": band(look["grain"], GRAIN, "heavy"),
        "letterboxed": look["letterbox_fraction"] > 0.08,
    }

    sound = audio.analyze(video, cuts, duration) if meta["has_audio"] else {"status": "no_audio_stream"}
    if sound.get("status") == "measured":
        editing["beat_sync"] = sound["cut_sync_to_beats"]
    spoken = speech.analyze(video, duration) if (with_speech and meta["has_audio"]) else {"status": "not_measured", "reason": "speech analysis skipped" if meta["has_audio"] else "no audio stream"}

    dna = {
        "schema_version": 1,
        "analyzer_version": ANALYZER_VERSION,
        "source": {"file": video.name, "sha256": sha256(video), **meta, "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "editing": editing,
        "visual": look,
        "audio": sound,
        "speech": spoken,
        "typography": {"status": "not_measured", "reason": "no OCR engine installed yet; caption style, placement and animation are unknown"},
        "judgement": {"status": "not_run", "reason": "hook strength, tone and narrative pacing need a model pass over these measurements; add it later and label it as judgement"},
        "limitations": [
            "Gradual transitions are found by comparing colour histograms 0.5 s either side of each moment; very slow dissolves (> ~1.5 s) or transitions between similar-looking shots can be missed, and a fast whip within one scene can read as a transition.",
            f"Look and camera motion are sampled from up to {visual.MAX_SHOTS_SAMPLED} shots, one frame (look) or one frame pair (motion) per shot.",
            "Camera motion is a zoom+pan fit to matched feature points (ORB + RANSAC) over the middle of each shot; featureless shots (solid colour, heavy blur) are left unmeasured.",
        ],
    }
    (out_dir / "style_dna.json").write_text(json.dumps(dna, indent=2) + "\n", encoding="utf-8")
    (out_dir / "shots.json").write_text(json.dumps({"cuts_sec": cuts, "hard_cuts_sec": hard, "gradual_sec": gradual, "gradual_kinds": kinds, "flashes_sec": flashes, "dips_sec": dips, "shots": shot_list, "sampled": per_shot}, indent=2) + "\n", encoding="utf-8")
    write_contact_sheet(thumbs, out_dir / "shots_contact_sheet.jpg")
    return dna


def write_contact_sheet(thumbs: list[np.ndarray], dest: Path, cols: int = 6, width: int = 240) -> None:
    if not thumbs:
        return
    tiles = [cv2.resize(t, (width, int(t.shape[0] * width / t.shape[1]))) for t in thumbs]
    h = max(t.shape[0] for t in tiles)
    tiles = [np.pad(t, ((0, h - t.shape[0]), (0, 0), (0, 0))) for t in tiles]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i : i + cols]) for i in range(0, len(tiles), cols)]
    cv2.imwrite(str(dest), cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
