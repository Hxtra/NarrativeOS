"""On-screen captions read from every frame of the reference (MEASURED), not from the transcript or a watcher.

Measured on ref_6cbda51b: the transcript and the watcher both disagree with the screen. Of 247 spoken words, 43 had no
watched caption; 19 of those were on screen (watcher misses), some were misheard by speech recognition ("ship" on
screen is "chip", "parts" is "parks"), some are written differently ("A hundred million square feet" is
"100,000,000ft²"), and the rest are not captioned at all. So the frames are the only source of truth.

Every frame is read by RapidOCR (local). A line counts as caption text when it is bright, white and unsaturated (the
edit's caption look), so footage text (lower-thirds, signs, tickers) is kept apart and labelled.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

W, H = 1276, 718


def read_all(video: Path, out: Path, every: int = 1) -> list[dict]:
    from rapidocr import RapidOCR
    ocr = RapidOCR(params={"Global.log_level": "critical"})
    raw = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    rows, n = [], 0
    with out.open("w", encoding="utf-8") as fh:
        while True:
            buf = raw.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            if n % every == 0:
                img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
                r = ocr(img)
                lines = []
                for box, txt, score in zip(r.boxes if r.boxes is not None else [], r.txts or [], r.scores or []):
                    b = np.asarray(box)
                    x0, y0 = b.min(0)
                    x1, y1 = b.max(0)
                    crop = img[int(max(0, y0)):int(y1) + 1, int(max(0, x0)):int(x1) + 1].astype(np.float32)
                    bright = crop[crop.mean(axis=2) > 200] if crop.size else np.zeros((0, 3))
                    sat = float((bright.max(axis=1) - bright.min(axis=1)).mean()) if len(bright) else 255.0
                    lines.append({"text": txt, "score": round(float(score), 3), "box": [round(float(v), 1) for v in (x0, y0, x1, y1)],
                                  "white_px": int(len(bright)), "white_sat": round(sat, 1),
                                  "caption_look": bool(len(bright) >= 30 and sat < 40)})
                row = {"frame": n, "lines": lines}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                rows.append(row)
            n += 1
    raw.wait()
    return rows


if __name__ == "__main__":
    import sys
    read_all(Path(sys.argv[1]), Path(sys.argv[2]))
