"""Tempo, beats, onsets, loudness, and whether cuts land on the beat more often than chance."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
from scipy.stats import binomtest

from .media import extract_audio, sha256


# Every music-map threshold lives here; callers override any subset via temporal_map(config=...).
MUSIC_MAP_DEFAULTS = {
    "sample_rate": 22050,
    "hop_length": 256,
    "silence_dbfs": -60.0,          # whole file quieter than this: status "silent", no events at all
    "energy_window_sec": 0.5,       # RMS energy curve resolution
    "section_context_windows": 4,   # windows averaged either side of a candidate section boundary
    "section_contrast_db": 6.0,     # energy contrast that makes a section candidate
    "section_min_gap_sec": 2.0,     # section candidates closer than this collapse to the strongest
    "phrase_onset_window_sec": 0.3, # an onset this close to a section boundary is its phrase candidate
    "build_min_windows": 8,         # a build lasts at least this many energy windows (8 x 0.5 s = 4 s)
    "build_min_rise_db": 6.0,
    "build_max_dip_db": 1.5,        # a build may dip this much per window and still count as rising
    "flat_step_db": 0.3,            # steps smaller than this are flat (trimmed from build ends)
    "impact_jump_db": 9.0,          # one-window rise that counts as an impact
    "breakdown_drop_db": 9.0,       # one-window fall that counts as a breakdown ...
    "breakdown_hold_windows": 4,    # ... if it stays down this many windows
    "support_scale_db": 24.0,       # dB change that maps to full heuristic support
    "max_inferred_support": 0.75,   # inferred events never claim more support than this
}

# What this map can and cannot tell an editor. MEASURED = read directly from the signal;
# INFERRED = a heuristic built on measured signals; NOT_MEASURED = no detector, never guessed.
MEASUREMENTS = {
    "onsets": {"status": "MEASURED", "method": "librosa spectral-flux onset detection"},
    "energy": {"status": "MEASURED", "method": "RMS level per window"},
    "beats": {"status": "INFERRED", "method": "librosa beat tracker fits a periodic grid to onset strength; phase and half/double time are ambiguous"},
    "tempo": {"status": "INFERRED", "method": "period of the tracked beat grid"},
    "section_boundaries": {"status": "INFERRED", "method": "sustained energy contrast"},
    "phrase_boundaries": {"status": "INFERRED", "method": "onset nearest a section candidate"},
    "build_impact_breakdown": {"status": "INFERRED", "method": "shapes of the energy curve (rise, jump, fall)"},
    "kick": {"status": "NOT_MEASURED", "reason": "an onset is any sharp spectral change, not a kick drum; needs source separation or a drum classifier"},
    "snare": {"status": "NOT_MEASURED", "reason": "same as kick"},
    "hihat": {"status": "NOT_MEASURED", "reason": "same as kick"},
    "downbeat": {"status": "NOT_MEASURED", "reason": "the beat tracker has no bar position; needs a downbeat model"},
    "meter": {"status": "NOT_MEASURED", "reason": "no bar grid is estimated"},
    "chorus": {"status": "NOT_MEASURED", "reason": "energy contrast is not song-form recognition"},
    "vocal_entry": {"status": "NOT_MEASURED", "reason": "needs vocal/instrument separation"},
    "instrument_identity": {"status": "NOT_MEASURED", "reason": "no instrument classifier"},
    "tempo_changes": {"status": "NOT_MEASURED", "reason": "one global tempo is estimated"},
    "emotion": {"status": "NOT_MEASURED", "reason": "not inferable from these signals"},
}


def temporal_map(path: Path, config: dict | None = None) -> dict:
    """Time-local signal evidence an editor can cut against. Not instrument, emotion or song-form recognition.

    Every event is labelled MEASURED or INFERRED; `measurements` lists what is NOT_MEASURED and why.
    Confidence is heuristic detector support, NOT a calibrated probability.
    """
    cfg = {**MUSIC_MAP_DEFAULTS, **(config or {})}
    with tempfile.TemporaryDirectory() as td:
        wav = extract_audio(path, Path(td) / "audio.wav", sr=cfg["sample_rate"])
        y, sr = librosa.load(str(wav), sr=cfg["sample_rate"], mono=True)
    duration = len(y) / sr
    rms_db = float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12))
    base = {"schema_version": 2, "source": {"file": path.name, "sha256": sha256(path)}, "duration_sec": duration,
            "rms_dbfs": round(rms_db, 2), "config": cfg, "measurements": MEASUREMENTS,
            "not_measured": [k for k, v in MEASUREMENTS.items() if v["status"] == "NOT_MEASURED"],
            "confidence_kind": "heuristic_support_not_probability",
            "limitations": ["Beat phase and half/double-time are ambiguous.",
                            "Section, phrase, build, impact and breakdown candidates are loudness shapes that need listening review; they are not recognised song sections or bass drops.",
                            "An onset is any sharp spectral change: it is not a kick, snare or downbeat."]}
    if rms_db < cfg["silence_dbfs"]:
        return {**base, "status": "silent", "tempo": None, "tempo_bpm": None, "tempo_confidence": 0.0, "energy": [], "events": []}

    hop = cfg["hop_length"]
    strength = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    onset_frames = librosa.onset.onset_detect(onset_envelope=strength, sr=sr, hop_length=hop)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=strength, sr=sr, hop_length=hop)
    onsets = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    regularity = float(np.clip(1 - np.std(np.diff(beats)) / max(np.mean(np.diff(beats)), 1e-6), 0, 1)) if len(beats) >= 4 else 0.0
    events: list[dict] = []

    def event(kind, basis, t, confidence, evidence):
        events.append({"event_id": f"M{len(events) + 1:05d}", "type": kind, "basis": basis,
                       "start": round(float(t), 4), "end": round(float(t), 4),
                       "confidence": round(float(confidence), 3), "evidence": evidence})

    for t, f in zip(onsets, onset_frames):
        support = float(strength[f] / max(float(strength.max()), 1e-6))
        event("ONSET", "MEASURED", t, support, {"method": "librosa.spectral_flux", "strength": float(strength[f]), "hop_sec": hop / sr})
    for t in beats:
        event("BEAT", "INFERRED", t, regularity * 0.8, {"method": "librosa.beat_track", "interval_regularity": regularity, "metrical_level_ambiguous": True})

    win = cfg["energy_window_sec"]
    energy = []
    for start in np.arange(0, duration, win):
        chunk = y[round(start * sr):min(len(y), round((start + win) * sr))]
        db = float(20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-12))
        energy.append({"start": round(float(start), 4), "end": round(min(float(start) + win, duration), 4), "rms_dbfs": round(db, 2)})

    n = cfg["section_context_windows"]
    changes = []
    for i in range(n, len(energy) - n + 1):
        before = float(np.mean([w["rms_dbfs"] for w in energy[i - n:i]]))
        after = float(np.mean([w["rms_dbfs"] for w in energy[i:i + n]]))
        if abs(after - before) >= cfg["section_contrast_db"]:
            changes.append((abs(after - before), i, after - before))
    selected: list[float] = []
    for magnitude, i, delta in sorted(changes, reverse=True):
        t = energy[i]["start"]
        if any(abs(t - prior) < cfg["section_min_gap_sec"] for prior in selected):
            continue
        selected.append(t)
        evidence = {"method": "adjacent_rms_contrast", "delta_db": round(delta, 2), "context_sec": n * win, "threshold_db": cfg["section_contrast_db"]}
        support = min(cfg["max_inferred_support"], magnitude / cfg["support_scale_db"])
        event("SECTION_CANDIDATE", "INFERRED", t, support, evidence)
        if len(onsets):
            nearest = float(onsets[np.argmin(abs(onsets - t))])
            if abs(nearest - t) <= cfg["phrase_onset_window_sec"]:
                event("PHRASE_CANDIDATE", "INFERRED", nearest, support * 0.8,
                      {**evidence, "method": "energy_boundary_near_onset", "boundary_sec": t, "meter_known": False})
    energy_events(energy, event, cfg)
    tempo_bpm = round(float(np.atleast_1d(tempo)[0]), 2) if len(beats) >= 4 else None
    return {**base, "status": "measured",
            "tempo": {"bpm": tempo_bpm, "basis": "INFERRED", "support": round(regularity * 0.8, 3)} if tempo_bpm else None,
            "tempo_bpm": tempo_bpm, "tempo_confidence": round(regularity * 0.8, 3), "energy": energy,
            "events": sorted(events, key=lambda e: (e["start"], e["type"]))}


def energy_events(energy: list[dict], event, cfg: dict) -> None:
    """Loudness shapes an editor listens for, from the RMS energy curve (all INFERRED).

    BUILD_CANDIDATE: loudness climbs >= build_min_rise_db over >= build_min_windows, dipping no more than build_max_dip_db per window.
    IMPACT_CANDIDATE: a rise of >= impact_jump_db within one window (a hit).
    BREAKDOWN_CANDIDATE: a fall of >= breakdown_drop_db within one window that stays down for breakdown_hold_windows.
    """
    db = [w["rms_dbfs"] for w in energy]
    top = cfg["max_inferred_support"]
    scale = cfg["support_scale_db"]
    i = 0
    while i < len(db) - 1:
        j = i
        # Extend while loudness holds or climbs, but stop at an impact-sized jump: that is the payoff, not the build.
        while j + 1 < len(db) and -cfg["build_max_dip_db"] <= db[j + 1] - db[j] < cfg["impact_jump_db"]:
            j += 1
        a, b = i, j
        while a < b and db[a + 1] - db[a] < cfg["flat_step_db"]:  # flat lead-in is not part of the build
            a += 1
        while b > a and db[b] - db[b - 1] < cfg["flat_step_db"]:  # nor a flat plateau at the top
            b -= 1
        if b - a >= cfg["build_min_windows"] and db[b] - db[a] >= cfg["build_min_rise_db"]:
            event("BUILD_CANDIDATE", "INFERRED", energy[a]["start"], min(top, (db[b] - db[a]) / scale),
                  {"method": "sustained_rms_rise", "end_sec": energy[b]["end"], "rise_db": round(db[b] - db[a], 2)})
            j = b
        i = max(i + 1, j)
    hold = cfg["breakdown_hold_windows"]
    for k in range(1, len(db)):
        jump = db[k] - db[k - 1]
        if jump >= cfg["impact_jump_db"]:
            event("IMPACT_CANDIDATE", "INFERRED", energy[k]["start"], min(top, jump / scale), {"method": "rms_step", "jump_db": round(jump, 2)})
        elif jump <= -cfg["breakdown_drop_db"] and k + hold <= len(db) and max(db[k:k + hold]) <= db[k - 1] - cfg["breakdown_drop_db"]:
            event("BREAKDOWN_CANDIDATE", "INFERRED", energy[k]["start"], min(top, -jump / scale),
                  {"method": "rms_step_sustained", "drop_db": round(-jump, 2), "held_windows": hold})


SYNC_TOLERANCE_SEC = 0.07  # a cut within ~2 frames of a beat counts as on-beat


def loudness(path: Path) -> dict:
    err = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    lra = re.findall(r"LRA:\s+([\d.]+) LU", err)
    return {"integrated_lufs": float(i[-1]) if i else None, "loudness_range_lu": float(lra[-1]) if lra else None}


def cut_sync(cuts: list[float], events: np.ndarray, duration: float) -> dict:
    """Do cuts land on events (beats/onsets) more often than chance? One-sided binomial test, p < 0.01."""
    if len(cuts) < 4 or len(events) < 2:
        return {"cuts_tested": len(cuts), "on_event_fraction": None, "chance_fraction": None, "p_value": None, "synced": None}
    dist = np.array([np.min(np.abs(events - c)) for c in cuts])
    hits = int((dist <= SYNC_TOLERANCE_SEC).sum())
    observed = hits / len(cuts)
    chance = min(1.0, 2 * SYNC_TOLERANCE_SEC * len(events) / duration)
    # Dense beat grids make chance high, so ask whether this many hits is unlikely by luck.
    p_value = float(binomtest(hits, len(cuts), chance, alternative="greater").pvalue) if 0 < chance < 1 else 1.0
    return {
        "cuts_tested": len(cuts),
        "on_event_fraction": round(observed, 3),
        "chance_fraction": round(chance, 3),
        "p_value": round(p_value, 5),
        "synced": bool(observed >= 0.5 and p_value < 0.01),
    }


def analyze(path: Path, cuts: list[float], duration: float) -> dict:
    with tempfile.TemporaryDirectory() as td:
        wav = extract_audio(path, Path(td) / "audio.wav")
        y, sr = librosa.load(str(wav), sr=22050, mono=True)
    rms_db = float(20 * np.log10(np.sqrt(np.mean(y**2)) + 1e-12))
    if rms_db < -60:
        return {"status": "silent", "rms_dbfs": round(rms_db, 1)}
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beats = librosa.frames_to_time(beat_frames, sr=sr)
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    tempo_val = float(np.atleast_1d(tempo)[0])
    return {
        "status": "measured",
        "rms_dbfs": round(rms_db, 1),
        **loudness(path),
        "tempo_bpm": round(tempo_val, 1) if len(beats) >= 4 else None,
        "beat_count": int(len(beats)),
        "onsets_per_sec": round(len(onsets) / duration, 2),
        "cut_sync_to_beats": cut_sync(cuts, beats, duration),
        "cut_sync_to_onsets": cut_sync(cuts, onsets, duration),
    }
