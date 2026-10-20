"""Check downloaded sound effects before they go into a film: measure each file and let a sound-recognition model (PANNs Cnn14,
AudioSet labels; style_intel/sound_tags.py) say what it hears, because the machine cannot listen and library titles can be wrong.

  python scripts/sfx_check.py DIR [--out report.json]

Per file: length, where the peak is (to line the peak up with the picture), brightness (spectral centroid), share of energy under
120 Hz (a "boom" should have it), and the model's top labels (strongest anywhere in the file, and on average).
MEASURED Oct 19 on 18 Pixabay effects: 2 were not what their titles said ("Writing with Pencil" -> panting/dog; a "Wood Creak" ->
computer typing). Wind recordings often get weak labels ("white noise"): a person checks those by ear.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repo root, for style_intel


def check(path: str) -> dict:
    import librosa
    from style_intel import sound_tags
    y, sr = librosa.load(path, sr=32000, mono=True)
    S = np.abs(np.fft.rfft(y)); f = np.fft.rfftfreq(len(y), 1 / sr)
    rep = {"file": os.path.basename(path), "seconds": round(len(y) / sr, 2), "peak_at": round(float(np.argmax(np.abs(y)) / sr), 2),
           "centroid_hz": round(float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))),
           "sub_120hz_share": round(float(S[f < 120].sum() / max(S.sum(), 1e-12)), 2)}
    if len(y) < sr:                                         # the model needs about 1 s: pad very short sounds (a 0.1 s tick crashed it)
        tmp = Path(tempfile.gettempdir()) / (Path(path).stem + ".padded.wav")
        import soundfile as sf
        sf.write(tmp, np.pad(y, (0, sr - len(y))), sr); src = tmp
    else:
        src = Path(path)
    try:
        p, labels, _ = sound_tags.tag(src)
        mx, mean = p.max(0), p.mean(0)
        rep["top_anywhere"] = [[labels[i], round(float(mx[i]), 2)] for i in np.argsort(-mx)[:3]]
        rep["top_average"] = [[labels[i], round(float(mean[i]), 2)] for i in np.argsort(-mean)[:3]]
    finally:
        if src != Path(path):
            src.unlink(missing_ok=True)
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir"); ap.add_argument("--out")
    a = ap.parse_args()
    reps = []
    for f in sorted(glob.glob(os.path.join(a.dir, "*.mp3")) + glob.glob(os.path.join(a.dir, "*.wav"))):
        r = check(f); reps.append(r)
        print(f"{r['file'][:50]:50s} {r['seconds']:6.1f}s peak@{r['peak_at']:5.2f} sub {r['sub_120hz_share']:.2f} | " +
              ", ".join(f"{l} {v}" for l, v in r.get("top_anywhere", [])))
    if a.out:
        Path(a.out).write_text(json.dumps(reps, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
