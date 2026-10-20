"""Sound mix from a plan: voice, music cues, placed silences and sound effects, with the levels MEASURED in real documentary
mixes (Fern and Veritasium, Demucs stems, Oct 2026; skills/narrativeos-sound-design/SKILL.md):

- the voice sits about 24 dB above the music while it speaks (Fern 24.7, Veritasium 23.1 dB median);
- the music comes up about 3.5 dB in the gaps between lines (measured 2.9-3.5 dB);
- a placed silence drops the music, never the room: a mix with digital zero (-240 dB) inside the film fails the check.

  python scripts/sound_mix.py PLAN.json            writes the mix and a report with the measured levels

PLAN.json (times in film seconds; paths relative to the plan file):
{"duration": 112.2, "sr": 48000,
 "voice": {"file": "vo.wav", "start": 2.0},
 "music": [{"file": "a.mp3", "start": 0.4, "offset": 3.6, "gain": [[0, 0], [3, 1], [79, 1], [81, 0]]}],
 "voice_music_gap_db": 24.0, "gap_lift_db": 3.5,
 "sfx": [{"file": "boom.mp3", "t": 9.23, "peak": 0.63, "rel_db": 12, "clip": [0, 4], "fade": [0.02, 0.08], "lowpass": 1200}],
 "out": "out/mix.wav"}

- `gain` is a piecewise-linear envelope in film time (0..1), used for fades, cue changes and placed silences.
- Each music cue is levelled on its own so that while the voice speaks it sits `voice_music_gap_db` under it.
- An effect's `t` is where its `peak` (seconds into the file, after `clip`) lands; `rel_db` is how far its RMS sits under the
  voice's speaking level. Effect levels are a starting point for a person's ear, not a measurement.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

VOICE_MUSIC_GAP_DB = 24.0
GAP_LIFT_DB = 3.5


def load(path: Path, sr: int) -> np.ndarray:
    import librosa
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y.astype(np.float64)


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)) if len(x) else -240.0


def lowpass(x: np.ndarray, hz: float, sr: int) -> np.ndarray:
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / sr)
    return np.fft.irfft(X / np.sqrt(1 + (f / hz) ** 4), len(x))


def fade(x: np.ndarray, a: float, b: float, sr: int) -> np.ndarray:
    x = x.copy(); fa, fb = min(int(a * sr), len(x)), min(int(b * sr), len(x))
    if fa: x[:fa] *= np.linspace(0, 1, fa)
    if fb: x[-fb:] *= np.linspace(1, 0, fb)
    return x


def place(buf: np.ndarray, x: np.ndarray, t: float, sr: int, gain_db: float = 0.0) -> None:
    s = int(round(t * sr))
    if s < 0:
        x, s = x[-s:], 0
    e = min(len(buf), s + len(x))
    if e > s:
        buf[s:e] += x[:e - s] * 10 ** (gain_db / 20)


def envelope(keys: list, n: int, sr: int) -> np.ndarray:
    ts, gs = zip(*keys)
    return np.interp(np.arange(n) / sr, ts, gs)


def running_mean(x: np.ndarray, w: int) -> np.ndarray:
    """Centred moving average via a cumulative sum (a direct convolution of a whole film took minutes)."""
    c = np.cumsum(np.concatenate([np.zeros(w // 2 + 1), x, np.zeros(w)]))
    return (c[w:w + len(x)] - c[:len(x)]) / w


def levels(x: np.ndarray, hop: int) -> np.ndarray:
    return np.array([rms_db(x[i:i + hop]) for i in range(0, len(x), hop)])


def mix(plan: dict, base: Path) -> dict:
    sr = plan.get("sr", 48000); n = int(plan["duration"] * sr); hop = sr // 10
    gap_db = plan.get("voice_music_gap_db", VOICE_MUSIC_GAP_DB); lift = plan.get("gap_lift_db", GAP_LIFT_DB)
    V = np.zeros(n); place(V, load(base / plan["voice"]["file"], sr), plan["voice"].get("start", 0.0), sr)
    vlev = levels(V, hop); voiced = vlev > -80
    speaking = vlev > (np.percentile(vlev[voiced], 30) if voiced.any() else 0)
    voice_db = float(np.median(vlev[speaking])) if speaking.any() else -20.0
    sp = np.clip(running_mean(np.repeat(speaking.astype(float), hop)[:n], int(0.25 * sr)) * 1.6, 0, 1)

    M = np.zeros(n)
    for cue in plan.get("music", []):
        y = load(base / cue["file"], sr)[int(cue.get("offset", 0) * sr):]
        part = np.zeros(n); place(part, y, cue.get("start", 0.0), sr)
        if cue.get("gain"):
            part *= envelope(cue["gain"], n, sr)
        lv = levels(part, hop); m = speaking & (lv > -70)
        if m.any():
            part *= 10 ** ((voice_db - gap_db - float(np.median(lv[m]))) / 20)
        M += part
    M *= 10 ** ((lift * (1 - sp)) / 20)

    FX = np.zeros(n)
    for fx in plan.get("sfx", []):
        y = load(base / fx["file"], sr)
        if fx.get("lowpass"):
            y = lowpass(y, fx["lowpass"], sr)
        if fx.get("clip"):
            a, b = fx["clip"]; y = y[int(a * sr):int(b * sr)]
        a, b = fx.get("fade", [0.02, 0.08]); y = fade(y, a, b, sr)
        loud = y[np.abs(y) > 1e-4]
        place(FX, y, fx["t"] - fx.get("peak", 0.0), sr, voice_db - fx.get("rel_db", 18) - rms_db(loud) if len(loud) else 0.0)

    out = V + M + FX
    peak = float(np.max(np.abs(out))); out = out / peak * 0.89 if peak > 0.89 else out
    lv_all = levels(out, hop)
    inside = lv_all[int(0.5 * 10): max(int(0.5 * 10) + 1, len(lv_all) - 5)]          # ignore the first and last half second
    ml = levels(M, hop)
    report = {"voice_speech_db": round(voice_db, 1),
              "music_under_voice_db": round(float(np.median(ml[speaking & (ml > -80)])) - voice_db, 1) if (speaking & (ml > -80)).any() else None,
              "music_in_gaps_db": round(float(np.median(ml[~speaking & (ml > -80)])) - voice_db, 1) if (~speaking & (ml > -80)).any() else None,
              "dead_air_windows": int((inside < -90).sum()),
              "peak_scaled": peak > 0.89}
    report["ok"] = report["dead_air_windows"] == 0
    dst = base / plan.get("out", "out/mix.wav"); dst.parent.mkdir(parents=True, exist_ok=True)
    import soundfile as sf
    sf.write(dst, np.stack([out, out], 1).astype(np.float32), sr)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    a = ap.parse_args()
    p = Path(a.plan).resolve()
    rep = mix(json.loads(p.read_text(encoding="utf-8")), p.parent)
    (p.parent / (p.stem + "_report.json")).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep))
    if not rep["ok"]:
        raise SystemExit(f"dead air inside the film: {rep['dead_air_windows']} windows of 0.1 s below -90 dB")


if __name__ == "__main__":
    main()
