#!/usr/bin/env python3
"""
Generate synthetic overlay clips with KNOWN properties, for testing the
ingest tool and the Remotion OverlayLayer without any licensed footage.

    python make_test_overlays.py <out-dir>

Each clip is 640x360 @ 30fps, 3s (90 frames):
  synthetic_leak_warm.mp4  orange blob on black, brightness peaks at frame 45
  synthetic_leak_cool.mp4  blue blob on black, peaks at frame 20
  synthetic_flash.mp4      black, full white on frames 60-62
  synthetic_texture.mp4    light grey paper-like noise (multiply material)

These are engineering fixtures only; never register them as real assets.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

W, H, FPS, FRAMES = 640, 360, 30, 90


def blob(peak: int, cx: float, r: float, g: float, b: float) -> str:
    # Triangular brightness envelope around `peak`, Gaussian blob at (cx*W, 0.5*H).
    k = f"max(0,1-abs(N-{peak})/35)"
    shape = f"exp(-(pow(X-W*{cx},2)+pow(Y-H*0.5,2))/(2*pow(W*0.22,2)))"
    return (
        f"geq=r='{255 * r}*{k}*{shape}':g='{255 * g}*{k}*{shape}':b='{255 * b}*{k}*{shape}'"
    )


CLIPS = {
    "synthetic_leak_warm.mp4": blob(45, 0.3, 1.0, 0.55, 0.12),
    "synthetic_leak_cool.mp4": blob(20, 0.7, 0.15, 0.45, 1.0),
    "synthetic_flash.mp4": "geq=lum='if(between(N,60,62),255,0)':cb=128:cr=128",
    "synthetic_texture.mp4": "geq=lum='205+25*sin(X/7)*cos(Y/5)+15*sin((X+Y+N)/3)':cb=128:cr=128",
}


def make(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for name, vf in CLIPS.items():
        dest = out_dir / name
        src = "rgb24" if vf.startswith("geq=r") else "yuv444p"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=black:size={W}x{H}:rate={FPS}:duration={FRAMES / FPS}",
             "-vf", f"format={src},{vf},format=yuv420p",
             "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", str(dest)],
            check=True,
        )
        made.append(dest)
    return made


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(1)
    for p in make(Path(sys.argv[1])):
        print(p)
