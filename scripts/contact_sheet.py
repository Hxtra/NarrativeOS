"""Contact sheet: tile rendered stills (t_<seconds>.jpg) or frames of a video into one labelled image, so a whole film can be
looked at in one go. A template or a film is not done until its frames have been looked at (CLAUDE.md, evidence over assertion).

  python scripts/contact_sheet.py stills DIR OUT.jpg [--cols 5] [--width 480]
  python scripts/contact_sheet.py video FILM.mp4 OUT.jpg [--every 3] [--cols 8] [--width 384]

Render stills at the page's full size: rendering a 1920x1080 page at a smaller --size CROPS it to the top-left corner instead of
scaling it (MEASURED Oct 19: the first contact sheet showed a quarter of every frame).
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess

from PIL import Image, ImageDraw


def stills(d: str, out: str, cols: int, w: int) -> None:
    fs = sorted(glob.glob(os.path.join(d, "t_*.jpg")), key=lambda f: float(re.search(r"t_([\d.]+?)\.jpg$", f).group(1)))
    if not fs:
        raise SystemExit(f"no t_<seconds>.jpg stills in {d}")
    h = w * 9 // 16; rows = (len(fs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 18)), "black"); dr = ImageDraw.Draw(sheet)
    for i, f in enumerate(fs):
        x, y = (i % cols) * w, (i // cols) * (h + 18)
        sheet.paste(Image.open(f).convert("RGB").resize((w, h)), (x, y)); dr.text((x + 6, y + h + 3), os.path.basename(f), fill="white")
    sheet.save(out, quality=88); print(out, sheet.size, len(fs), "frames")


def video(f: str, out: str, every: float, cols: int, w: int) -> None:
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True).stdout)
    n = int(dur // every) + 1; rows = (n + cols - 1) // cols
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-vf", f"fps=1/{every},scale={w}:-2,tile={cols}x{rows}", "-frames:v", "1", out], check=True)
    print(out, n, "frames, one every", every, "s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("stills"); p.add_argument("dir"); p.add_argument("out"); p.add_argument("--cols", type=int, default=5); p.add_argument("--width", type=int, default=480)
    p = s.add_parser("video"); p.add_argument("film"); p.add_argument("out"); p.add_argument("--every", type=float, default=3); p.add_argument("--cols", type=int, default=8); p.add_argument("--width", type=int, default=384)
    a = ap.parse_args()
    stills(a.dir, a.out, a.cols, a.width) if a.cmd == "stills" else video(a.film, a.out, a.every, a.cols, a.width)


if __name__ == "__main__":
    main()
