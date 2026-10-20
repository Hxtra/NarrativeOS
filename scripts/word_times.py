"""Word timings of a finished voiceover, so every picture event can land on a spoken word (the film's shots and effects are
keyed to words, not to guessed seconds).

  python scripts/word_times.py VO.wav OUT.json [--prompt "Eratosthenes, Syene, Alexandria"] [--model base]

Writes [{"w": word, "t0": start, "t1": end}, ...] in seconds of the voice file. faster-whisper is fed 16 kHz audio: other rates make
every timestamp late (MEASURED Oct 18: 24 kHz audio gave times 1.5x too late). --prompt lists rare names so they are spelled right.
Accuracy is about +-0.2 s with the base model; check the words that matter on a still.
"""
from __future__ import annotations

import argparse
import json


def word_times(path: str, prompt: str | None = None, model: str = "base") -> list[dict]:
    import numpy as np
    import soundfile as sf
    import soxr
    from faster_whisper import WhisperModel
    y, sr = sf.read(path); y = y.mean(1) if y.ndim > 1 else y
    y = soxr.resample(y, sr, 16000).astype(np.float32)
    m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(y, language="en", word_timestamps=True, vad_filter=False, initial_prompt=prompt)
    return [{"w": w.word.strip(), "t0": round(w.start, 3), "t1": round(w.end, 3)} for s in segs for w in s.words]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voice"); ap.add_argument("out"); ap.add_argument("--prompt"); ap.add_argument("--model", default="base")
    a = ap.parse_args()
    words = word_times(a.voice, a.prompt, a.model)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=0)
    print(len(words), "words ->", a.out)


if __name__ == "__main__":
    main()
