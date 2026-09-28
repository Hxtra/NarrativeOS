"""Tempo, beats, onsets, loudness, and whether cuts land on the beat more often than chance."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
from scipy.stats import binomtest

from .media import extract_audio

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
