"""Audio-visual sync: how tightly does the picture follow the sound, and through what?

Everything is MEASURED at the video's frame rate:
- audio, per frame: onset strength (hits), low band 20-150 Hz (kick and bass), high band 4-12 kHz (hats, sizzle), beats and tempo;
- picture, per frame: brightness, brightness rise (flashes), and frame change (motion energy).

Then:
- **lag**: the cross-correlation between each audio and picture curve inside the sync window (-2..+3 frames; wider offsets are
  noticed by viewers, ITU-R BT.1359). A positive lag means the picture comes
  AFTER the sound. Significance is tested against circularly shifted copies (a null that keeps both curves' rhythm), so a
  steady beat cannot fake a match.
- **hits**: for the strongest audio onsets, the share that have a picture event (a peak in brightness rise or frame change)
  within +-2 frames, compared with the same count at random times (chance).
- **coupling**: whether brightness rides the bass continuously (picture energy driven by the audio level, as audio-reactive
  visuals do), measured as the correlation of the two smoothed curves.

  python -m style_intel avsync VIDEO --out DIR [--crop x,y,w,h | --auto-crop]

--auto-crop keeps the rows that move: social posts often put a video inside a band with static text above and below.
Limits: this measures WHETHER and HOW the picture follows the sound, not how it was made (shared note list or audio analysis
look the same from outside); sub-frame precision is impossible at the video's frame rate.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

SR = 22050


def _video_frames(video: Path, crop: tuple | None, scale_w: int = 180):
    import cv2
    cap = cv2.VideoCapture(str(video)); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        frames.append(g)
    cap.release()
    if not frames:
        raise SystemExit(f"no frames in {video}")
    F = np.stack(frames)
    if crop == "auto":
        act = np.abs(np.diff(F, axis=0)).mean(axis=(0, 2))              # motion per row
        rows = np.where(act > max(act.max() * 0.08, 0.5))[0]
        y0, y1 = (int(rows.min()), int(rows.max()) + 1) if len(rows) else (0, F.shape[1])
        crop = (0, y0, F.shape[2], y1 - y0)
    if crop:
        x, y, w, h = crop; F = F[:, y:y + h, x:x + w]
    import cv2
    k = scale_w / F.shape[2]
    F = np.stack([cv2.resize(f, (scale_w, max(1, int(f.shape[0] * k))), interpolation=cv2.INTER_AREA) for f in F])
    return F, float(fps), crop


def _audio(video: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def _band_env(y: np.ndarray, lo: float, hi: float, hop: int, n: int) -> np.ndarray:
    import librosa
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop)); f = librosa.fft_frequencies(sr=SR, n_fft=2048)
    e = S[(f >= lo) & (f < hi)].sum(0)
    return np.pad(e, (0, max(0, n - len(e))))[:n]


def _z(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, float); s = x.std()
    return (x - x.mean()) / s if s > 0 else x * 0


SYNC_WINDOW = (-2, 3)   # frames: the picture from 2 frames before to 3 after the sound (about -67..+100 ms at 30 fps). Offsets
                        # beyond about 45-125 ms are noticed by viewers (ITU-R BT.1359), so a match at a larger lag is not sync.


def _xcorr(a: np.ndarray, b: np.ndarray, maxlag: int = 10, minlag: int | None = None) -> tuple[int, float, dict]:
    """Best lag (b relative to a; positive = b later) and its correlation, plus the curve, over minlag..maxlag."""
    a, b = _z(a), _z(b); n = len(a); curve = {}
    for L in range(-maxlag if minlag is None else minlag, maxlag + 1):
        if L >= 0:
            c = float(np.mean(a[:n - L] * b[L:])) if n - L > 2 else 0.0
        else:
            c = float(np.mean(a[-L:] * b[:n + L])) if n + L > 2 else 0.0
        curve[L] = c
    best = max(curve, key=lambda k: curve[k])
    return best, curve[best], curve


def _null(a: np.ndarray, b: np.ndarray, maxlag: int, rng, n_shift: int = 200, minlag: int | None = None) -> np.ndarray:
    """Best correlations after circularly shifting b by at least 1 s: what an unsynced picture with the same rhythm scores."""
    n = len(b); out = []
    for _ in range(n_shift):
        s = int(rng.integers(max(30, maxlag * 3), max(31, n - max(30, maxlag * 3))))
        out.append(_xcorr(a, np.roll(b, s), maxlag, minlag)[1])
    return np.array(out)


def _peaks(x: np.ndarray, k: float = 1.0) -> np.ndarray:
    z = _z(x); return np.array([i for i in range(1, len(z) - 1) if z[i] > k and z[i] >= z[i - 1] and z[i] >= z[i + 1]])


def analyze(video: Path, out: Path, crop=None) -> dict:
    import librosa
    out.mkdir(parents=True, exist_ok=True)
    F, fps, crop = _video_frames(video, crop)
    n = len(F)
    bright = F.mean(axis=(1, 2))
    rise = np.maximum(np.diff(bright, prepend=bright[0]), 0)                # flashes: brightness going UP
    change = np.concatenate([[0], np.abs(np.diff(F, axis=0)).mean(axis=(1, 2))])
    y = _audio(video); hop = int(round(SR / fps))
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop); onset = np.pad(onset, (0, max(0, n - len(onset))))[:n]
    low = _band_env(y, 20, 150, hop, n); high = _band_env(y, 4000, 12000, hop, n)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=SR, hop_length=hop)
    rng = np.random.default_rng(0)
    pairs = {"onset->flash": (onset, rise), "onset->change": (onset, change), "bass->flash": (low, rise),
             "bass->brightness": (low, bright), "highs->change": (high, change)}
    lags = {}
    lo, hi = SYNC_WINDOW
    for name, (a, b) in pairs.items():
        L, c, _ = _xcorr(a, b, hi, lo)                                     # inside the sync window only
        null = _null(a, b, hi, rng, minlag=lo)
        Lw, cw, _ = _xcorr(a, b, 10)                                       # the best match at any lag, for the record
        lags[name] = {"lag_frames": L, "lag_ms": round(1000 * L / fps), "corr": round(c, 3),
                      "chance_95": round(float(np.percentile(null, 95)), 3), "p": round(float((null >= c).mean()), 3),
                      "best_any_lag_frames": Lw, "best_any_corr": round(cw, 3)}
    # hits: strong onsets with a picture event within +-2 frames, against random times
    on_pk = _peaks(onset, 1.5); vis = np.union1d(_peaks(rise, 1.0), _peaks(change, 1.0))
    def share(ts):
        return float(np.mean([np.any(np.abs(vis - t) <= 2) for t in ts])) if len(ts) and len(vis) else 0.0
    rand = [share(rng.integers(2, n - 2, len(on_pk))) for _ in range(200)] if len(on_pk) else [0.0]
    hits = {"strong_onsets": int(len(on_pk)), "with_picture_event_pm2f": round(share(on_pk), 3),
            "chance_mean": round(float(np.mean(rand)), 3), "chance_95": round(float(np.percentile(rand, 95)), 3)}
    sm = lambda x, w=int(fps // 2) or 1: np.convolve(x, np.ones(w) / w, mode="same")
    coupling = {"bass_vs_brightness_r": round(float(np.corrcoef(sm(low), sm(bright))[0, 1]), 3),
                "onset_vs_change_r": round(float(np.corrcoef(sm(onset), sm(change))[0, 1]), 3)}
    where = regions(F, {"onset": onset, "bass": low, "highs": high}, fps)
    result = {"source": video.name, "fps": fps, "frames": n, "crop": crop, "tempo_bpm": round(float(np.atleast_1d(tempo)[0]), 1),
              "beats": int(len(beats)), "lags": lags, "hits": hits, "coupling": coupling, "regions_synced": where[:12],
              "regions_total": 6 * 4, "verdict": verdict(lags, hits, coupling)}
    if where:
        cells = sorted({tuple(r["cell"]) for r in where})
        result["verdict"].append(f"{len(cells)} of 24 picture regions follow the sound (best: cell {where[0]['cell']} row,col with {where[0]['audio']}, "
                                 f"r={where[0]['corr']}, {where[0]['lag_ms']} ms after)")
    np.savez_compressed(out / "av_curves.npz", bright=bright, rise=rise, change=change, onset=onset, low=low, high=high, beats=beats)
    (out / "av_sync.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def regions(F: np.ndarray, curves: dict, fps: float, grid=(6, 4), seed: int = 1) -> list[dict]:
    """Which part of the picture follows the sound: per grid cell, the brightness-rise curve against each audio curve, with the
    same shifted-copy null. A whole-frame average misses a small element (a ring, a flash) inside a busy picture."""
    rng = np.random.default_rng(seed); gy, gx = grid; H, Wd = F.shape[1], F.shape[2]; out = []
    for i in range(gy):
        for j in range(gx):
            cell = F[:, i * H // gy:(i + 1) * H // gy, j * Wd // gx:(j + 1) * Wd // gx].mean(axis=(1, 2))
            rise = np.maximum(np.diff(cell, prepend=cell[0]), 0)
            for name, a in curves.items():
                L, c, _ = _xcorr(a, rise, SYNC_WINDOW[1], SYNC_WINDOW[0])
                null = _null(a, rise, SYNC_WINDOW[1], rng, 100, SYNC_WINDOW[0])
                out.append({"cell": [i, j], "audio": name, "lag_frames": L, "lag_ms": round(1000 * L / fps), "corr": round(c, 3),
                            "chance_95": round(float(np.percentile(null, 95)), 3), "p": round(float((null >= c).mean()), 3)})
    return sorted([r for r in out if r["p"] <= 0.01 and r["corr"] > r["chance_95"]], key=lambda r: -r["corr"])


def verdict(lags: dict, hits: dict, coupling: dict) -> list[str]:
    v = []
    sig = {k: x for k, x in lags.items() if x["p"] <= 0.01 and x["corr"] > x["chance_95"]}
    for k, x in sig.items():
        when = "on the same frame" if x["lag_frames"] == 0 else (f"{x['lag_ms']} ms after" if x["lag_frames"] > 0 else f"{-x['lag_ms']} ms before")
        v.append(f"{k}: synced (r={x['corr']}, chance 95% {x['chance_95']}), picture {when} the sound")
    if not sig:
        v.append("no picture curve follows the sound better than chance")
    if hits["strong_onsets"] and hits["with_picture_event_pm2f"] > hits["chance_95"]:
        v.append(f"{round(100 * hits['with_picture_event_pm2f'])}% of strong hits have a picture event within 2 frames (chance {round(100 * hits['chance_mean'])}%)")
    return v


def summary(r: dict) -> str:
    lines = [f"{r['source']}: {r['frames']} frames at {r['fps']} fps, tempo {r['tempo_bpm']} BPM, {r['beats']} beats"]
    for k, x in r["lags"].items():
        lines.append(f"  {k:18s} lag {x['lag_frames']:+d} f ({x['lag_ms']:+d} ms)  r={x['corr']:.3f}  chance95={x['chance_95']:.3f}  p={x['p']}")
    h = r["hits"]; lines.append(f"  hits: {h['with_picture_event_pm2f']:.0%} of {h['strong_onsets']} strong onsets (chance {h['chance_mean']:.0%}, 95% {h['chance_95']:.0%})")
    lines.append(f"  coupling: bass~brightness r={r['coupling']['bass_vs_brightness_r']}, onset~change r={r['coupling']['onset_vs_change_r']}")
    return "\n".join(lines + ["  verdict: " + s for s in r["verdict"]])
