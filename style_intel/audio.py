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


def temporal_map(path: Path) -> dict:
    """Time-local signal evidence, not instrument, emotion or song-form recognition.

    Confidence is heuristic detector support, NOT a calibrated probability.
    Section candidates require a sustained >=6 dB energy contrast. Phrase
    candidates are onsets near that contrast; no bar/meter grid is invented.
    """
    with tempfile.TemporaryDirectory() as td:
        wav = extract_audio(path, Path(td) / "audio.wav")
        y, sr = librosa.load(str(wav), sr=22050, mono=True)
    duration = len(y) / sr
    rms_db = float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12))
    hop = 256
    strength = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    onset_frames = librosa.onset.onset_detect(onset_envelope=strength, sr=sr, hop_length=hop)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=strength, sr=sr, hop_length=hop)
    onsets = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    regularity = float(np.clip(1 - np.std(np.diff(beats)) / max(np.mean(np.diff(beats)), 1e-6), 0, 1)) if len(beats) >= 4 else 0.0
    events = []

    def event(kind, t, confidence, evidence):
        events.append({"event_id": f"M{len(events) + 1:05d}", "type": kind,
                       "start": round(float(t), 4), "end": round(float(t), 4),
                       "confidence": round(float(confidence), 3), "evidence": evidence})

    for t, f in zip(onsets, onset_frames):
        support = float(strength[f] / max(float(strength.max()), 1e-6))
        event("ONSET", t, support, {"method": "librosa.spectral_flux", "strength": float(strength[f]), "hop_sec": hop / sr})
    for t in beats:
        event("BEAT", t, regularity * 0.8, {"method": "librosa.beat_track", "interval_regularity": regularity, "metrical_level_ambiguous": True})
    energy = []
    for start in np.arange(0, duration, 0.5):
        chunk = y[round(start * sr):min(len(y), round((start + 0.5) * sr))]
        db = float(20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-12))
        energy.append({"start": round(float(start), 4), "end": round(min(float(start) + 0.5, duration), 4), "rms_dbfs": round(db, 2)})
    changes = []
    for i in range(4, len(energy) - 3):
        before = float(np.mean([w["rms_dbfs"] for w in energy[i - 4:i]]))
        after = float(np.mean([w["rms_dbfs"] for w in energy[i:i + 4]]))
        delta = after - before
        if abs(delta) >= 6:
            changes.append((abs(delta), i, delta))
    selected = []
    for magnitude, i, delta in sorted(changes, reverse=True):
        t = energy[i]["start"]
        if any(abs(t - prior) < 2 for prior in selected):
            continue
        selected.append(t)
        evidence = {"method": "adjacent_2s_rms_contrast", "delta_db": round(delta, 2), "window_sec": 2, "threshold_db": 6}
        support = min(0.75, magnitude / 24)
        event("SECTION_CANDIDATE", t, support, evidence)
        if len(onsets):
            nearest = float(onsets[np.argmin(abs(onsets - t))])
            if abs(nearest - t) <= 0.3:
                event("PHRASE_CANDIDATE", nearest, support * 0.8, {**evidence, "method": "energy_boundary_near_onset", "boundary_sec": t, "meter_known": False})
    energy_events(energy, event)
    return {"schema_version": 1, "status": "silent" if rms_db < -60 else "measured", "source": {"file": path.name, "sha256": sha256(path)},
            "duration_sec": duration, "rms_dbfs": round(rms_db, 2),
            "tempo_bpm": round(float(np.atleast_1d(tempo)[0]), 2) if len(beats) >= 4 else None,
            "tempo_confidence": round(regularity * 0.8, 3), "energy": energy,
            "events": sorted(events, key=lambda e: (e["start"], e["type"])),
            "confidence_kind": "heuristic_support_not_probability",
            "not_measured": ["downbeat", "meter", "instrument_identity", "kick", "snare", "chorus", "emotion", "tempo_changes"],
            "limitations": ["Beat phase and half/double-time are ambiguous.", "Energy/phrase candidates need listening review; RMS does not identify musical form.",
                            "BUILD/IMPACT/BREAKDOWN are loudness shapes (sustained rise, sharp jump, sharp fall), not recognised song sections or bass drops."]}

def energy_events(energy: list[dict], event) -> None:
    """Loudness shapes an editor listens for, from the 0.5 s RMS curve.

    BUILD_CANDIDATE: loudness climbs >= 6 dB over >= 4 s without falling back more than 1.5 dB per step.
    IMPACT_CANDIDATE: a jump of >= 9 dB within one 0.5 s step (a hit / "drop" moment).
    BREAKDOWN_CANDIDATE: a fall of >= 9 dB within one step that stays down for >= 2 s.
    """
    db = [w["rms_dbfs"] for w in energy]
    i = 0
    while i < len(db) - 1:
        j = i
        # Extend while loudness holds or climbs, but stop at an impact-sized jump: that is the payoff, not the build.
        while j + 1 < len(db) and -1.5 <= db[j + 1] - db[j] < 9:
            j += 1
        a, b = i, j
        while a < b and db[a + 1] - db[a] < 0.3:  # flat lead-in is not part of the build
            a += 1
        while b > a and db[b] - db[b - 1] < 0.3:  # nor a flat plateau at the top
            b -= 1
        if b - a >= 8 and db[b] - db[a] >= 6:
            i, j = a, b
            event("BUILD_CANDIDATE", energy[i]["start"], min(0.75, (db[j] - db[i]) / 24),
                  {"method": "sustained_rms_rise", "end_sec": energy[j]["end"], "rise_db": round(db[j] - db[i], 2), "min_duration_sec": 4})
            i = j
        i += 1
    for k in range(1, len(db)):
        jump = db[k] - db[k - 1]
        if jump >= 9:
            event("IMPACT_CANDIDATE", energy[k]["start"], min(0.75, jump / 24), {"method": "rms_step", "jump_db": round(jump, 2), "window_sec": 0.5})
        elif jump <= -9 and k + 4 <= len(db) and max(db[k:k + 4]) <= db[k - 1] - 9:
            event("BREAKDOWN_CANDIDATE", energy[k]["start"], min(0.75, -jump / 24), {"method": "rms_step_sustained", "drop_db": round(-jump, 2), "held_sec": 2})


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
