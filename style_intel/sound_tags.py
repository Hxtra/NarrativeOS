"""What each sound IS: AudioSet labels second by second with PANNs Cnn14 (Kong et al. 2020; code MIT, weights CC BY 4.0).

Run on the voice-free layer (music + effects + ambience) and the voice layer separately. The model and its label list live in
NARRATIVEOS_HOME/models/panns_data (the package reads them from <home>/panns_data, so home is pointed there for the import).
Labels are INFERRED by a model trained on YouTube clips: treat a label as a lead, check it against the frames and the ear.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

MODELS = Path(os.environ.get("NARRATIVEOS_HOME", r"C:\Users\openclaw\NarrativeOS-Data")) / "models"
SR = 32000
WIN, HOP = 2.0, 1.0
# AudioSet labels grouped the way a sound team thinks about a mix (the label names are AudioSet's own)
MUSIC = {"Music", "Musical instrument", "Orchestra", "Piano", "Strings", "Violin, fiddle", "Cello", "Synthesizer", "Ambient music",
         "Soundtrack music", "Background music", "Drum", "Percussion", "Choir", "Guitar", "Harp", "Bell", "Theme music",
         "Electronic music", "Classical music", "Sad music", "Tender music", "Exciting music", "Angry music", "Scary music",
         "Happy music", "Funny music"}
MOOD = {"Happy music", "Funny music", "Sad music", "Tender music", "Exciting music", "Angry music", "Scary music"}
IGNORE = {"Speech", "Male speech, man speaking", "Female speech, woman speaking", "Narration, monologue", "Conversation",
          "Silence", "Inside, small room", "Inside, large room or hall", "Outside, urban or manmade", "Outside, rural or natural"}


def _model():
    home = os.environ.get("USERPROFILE")
    os.environ["USERPROFILE"] = str(MODELS)
    try:
        from panns_inference import AudioTagging, labels
    finally:
        if home is not None:
            os.environ["USERPROFILE"] = home
    at = AudioTagging(checkpoint_path=str(MODELS / "panns_data" / "Cnn14_mAP=0.431.pth"), device="cpu")
    return at, labels


def tag(wav: Path, batch: int = 32) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Per-window probabilities (windows x 527) and window start times."""
    import librosa
    y, _ = librosa.load(str(wav), sr=SR, mono=True)
    at, labels = _model()
    w, h = int(WIN * SR), int(HOP * SR)
    starts = np.arange(0, max(len(y) - w, 0) + 1, h)
    probs = []
    for i in range(0, len(starts), batch):
        chunk = np.stack([y[s:s + w] for s in starts[i:i + batch]])
        clip, _ = at.inference(chunk)
        probs.append(clip)
    return np.concatenate(probs), list(labels), starts / SR


def segments(times: np.ndarray, p: np.ndarray, thr: float, min_len: float = 1.0, gap: float = 1.0) -> list[list[float]]:
    on = p >= thr
    segs, s = [], None
    for t, o in zip(times, on):
        if o and s is None:
            s = t
        elif not o and s is not None:
            segs.append([float(s), float(t + WIN - HOP)]); s = None
    if s is not None:
        segs.append([float(s), float(times[-1] + WIN)])
    merged = []
    for a, b in segs:
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [[round(a, 1), round(b, 1)] for a, b in merged if b - a >= min_len]


def analyze(no_vocals: Path, out: Path, sfx_thr: float = 0.25, music_thr: float = 0.3) -> dict:
    probs, labels, times = tag(no_vocals)
    np.save(out / "tags_no_vocals.npy", probs.astype(np.float16))
    L = {n: i for i, n in enumerate(labels)}
    music_p = probs[:, L["Music"]]
    music = segments(times, music_p, music_thr, min_len=3.0, gap=2.0)
    silent = segments(times, (music_p < 0.1).astype(float), 0.5, min_len=3.0, gap=0.0)
    mood = {m: round(float(probs[:, L[m]].mean()), 3) for m in MOOD}
    # every non-music, non-speech sound class that clearly occurs somewhere, with its times
    events = {}
    for name, i in L.items():
        if name in MUSIC or name in IGNORE:
            continue
        segs = segments(times, probs[:, i], sfx_thr, min_len=1.0, gap=1.0)
        if segs:
            events[name] = {"seconds": round(sum(b - a for a, b in segs), 1), "peak": round(float(probs[:, i].max()), 2), "times": segs}
    events = dict(sorted(events.items(), key=lambda kv: -kv[1]["seconds"]))
    result = {"window_sec": WIN, "hop_sec": HOP, "music_segments": music, "no_music_segments": silent,
              "music_share": round(float((music_p >= music_thr).mean()), 3), "music_mood_mean": mood, "sound_classes": events}
    (out / "sound_tags.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result
