"""Where in a song each moment of an edit's music comes from: song offset, speed, and how sure (MEASURED).

The edit's music stem (voice removed by Demucs) and a candidate song are reduced to onset-strength envelopes
(rhythm, independent of pitch, so a sped-up and pitched-up song still matches). Each window of the stem is
correlated with the song resampled at a range of speeds (normalised cross-correlation by FFT); the best (speed,
offset) and its correlation are kept. Consecutive windows that agree on speed and line up in song time are one
continuous use of the song; a jump means the editor cut inside the music. A fingerprint hit (Shazam) only says the
song is there; this says exactly which part, at what speed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 22050
HOP = 256


def envelope(path: Path) -> np.ndarray:
    import librosa
    y, _ = librosa.load(str(path), sr=SR, mono=True)
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    return (env - env.mean()) / (env.std() + 1e-9)


def _ncc(window: np.ndarray, series: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of window against every offset of series."""
    n = len(window)
    if len(series) < n:
        return np.zeros(1)
    w = (window - window.mean()) / (window.std() * n + 1e-9)
    L = 1 << int(np.ceil(np.log2(len(series) + n)))
    corr = np.fft.irfft(np.fft.rfft(series, L) * np.conj(np.fft.rfft(w, L)), L)[: len(series) - n + 1]
    c1 = np.cumsum(np.concatenate([[0], series]))
    c2 = np.cumsum(np.concatenate([[0], series ** 2]))
    s, s2 = c1[n:] - c1[:-n], c2[n:] - c2[:-n]
    std = np.sqrt(np.maximum(s2 / n - (s / n) ** 2, 1e-12))
    return corr / std


def align(stem: np.ndarray, song: np.ndarray, win_sec: float = 6.0, step_sec: float = 2.0,
          speeds: np.ndarray = np.round(np.arange(0.85, 1.301, 0.01), 3)) -> list[dict]:
    fps = SR / HOP
    win, step = int(win_sec * fps), int(step_sec * fps)
    # song resampled for each speed: playing the song at speed s, edit time t shows song time s*t
    resampled = {}
    for s in speeds:
        idx = np.arange(0, len(song) - 1, s)
        resampled[float(s)] = np.interp(idx, np.arange(len(song)), song)
    out = []
    for a in range(0, len(stem) - win + 1, step):
        w = stem[a:a + win]
        best = (-1.0, None, None)
        for s, ser in resampled.items():
            c = _ncc(w, ser)
            k = int(np.argmax(c))
            if c[k] > best[0]:
                best = (float(c[k]), s, k)
        corr, s, k = best
        out.append({"edit_t": round(a / fps, 2), "speed": s, "song_t": round(k * s / fps, 2), "corr": round(corr, 3)})
    return out


BPO = 36  # CQT bins per octave: a third of a semitone, so a 0.96x tape speed (-0.7 semitone) is visible


def cqt(path: Path) -> np.ndarray:
    import librosa
    y, _ = librosa.load(str(path), sr=SR, mono=True)
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=HOP, fmin=librosa.note_to_hz("C2"), n_bins=BPO * 6, bins_per_octave=BPO))
    L = np.log1p(C * 10)
    return L / (np.linalg.norm(L, axis=0, keepdims=True) + 1e-9)


def harmonic_score(edit: np.ndarray, song: np.ndarray, a: int, n: int, speed: float, song_frame: int, pitch_follows: bool) -> float:
    """Mean cosine similarity of edit frames a..a+n with the song frames they would come from at this speed,
    the song's spectrum shifted by the speed's pitch change when the speed was a tape-style change."""
    idx = np.round(song_frame + np.arange(n) * speed).astype(int)
    if idx[-1] >= song.shape[1] or idx[0] < 0:
        return -1.0
    S = song[:, idx]
    shift = int(round(BPO * np.log2(speed))) if pitch_follows else 0
    if shift:
        S = np.roll(S, shift, axis=0)
        if shift > 0:
            S[:shift] = 0
        else:
            S[shift:] = 0
    E = edit[:, a:a + n]
    return float((E * S).sum(axis=0).mean())


def align_harmonic(stem_env: np.ndarray, song_env: np.ndarray, stem_cqt: np.ndarray, song_cqt: np.ndarray, win_sec: float = 6.0,
                   step_sec: float = 2.0, speeds: np.ndarray = np.round(np.arange(0.85, 1.301, 0.01), 3), top: int = 12) -> list[dict]:
    """Rhythm proposes, harmony decides: the top rhythm candidates per window are scored on the spectrum."""
    fps = SR / HOP
    win, step = int(win_sec * fps), int(step_sec * fps)
    resampled = {float(s): np.interp(np.arange(0, len(song_env) - 1, s), np.arange(len(song_env)), song_env) for s in speeds}
    out = []
    for a in range(0, min(len(stem_env), stem_cqt.shape[1]) - win + 1, step):
        w = stem_env[a:a + win]
        cands = []
        for s, ser in resampled.items():
            c = _ncc(w, ser)
            for k in np.argsort(c)[-3:]:
                cands.append((float(c[k]), s, int(round(k * s))))
        cands.sort(reverse=True)
        best = None
        for rc, s, sf in cands[:top]:
            for follows in (True, False):
                h = harmonic_score(stem_cqt, song_cqt, a, win, s, sf, follows)
                if best is None or h > best["harmonic"]:
                    best = {"edit_t": round(a / fps, 2), "speed": s, "song_t": round(sf / fps, 2), "rhythm": round(rc, 3), "harmonic": round(h, 3),
                            "pitch": "shifted with speed" if follows else "kept"}
        out.append(best)
    return out
