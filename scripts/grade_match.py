#!/usr/bin/env python3
"""Grade every shot toward a reference's measured colour, so a cut stops jumping between looks.

Promoted from the friends_future project script (match_grade.py v2, the grade of the draft the owner rated best).
The reference is sampled at 2 fps and its colour measured in Lab (lightness and the two colour axes): mean, spread
and chroma (MEASURED). Each shot's used range is measured the same way, through the crop it will be shown in, and a
33-point .cube LUT moves it toward the reference:
- lightness, per shot: toward the reference's lightness, bounded (MAX_L_SHIFT), so a night street stays night;
- colour, for the whole film: one shared tint shift (each shot keeps its colour relative to the others) and one
  shared chroma gain toward the reference's chroma.

    python scripts/grade_match.py target REFERENCE.mp4 [--from S] [--to S] [--aspect 1:1]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

STRENGTH = 0.7
MAX_L_SHIFT = 12.0          # Lab L is 0-100
L_RATIO = (0.8, 1.25)
CHROMA_GAIN = (1.0, 1.8)
N = 33
SAMPLE = 160                # analysis size (pixels, the crop's longer side)


def _crop(aspect: Optional[tuple[int, int]], cx: float = 0.5) -> str:
    """ffmpeg filter: the part of the frame a canvas of this aspect shows (cover fit, crop centre cx)."""
    if not aspect:
        return f"scale={SAMPLE}:-2"
    w, h = aspect
    r = w / h
    return (f"crop='if(gt(iw/ih,{r}),ih*{r},iw)':'if(gt(iw/ih,{r}),ih,iw/{r})':"
            f"'if(gt(iw/ih,{r}),max(0,min(iw-ih*{r},iw*{cx:.4f}-ih*{r}/2)),0)':'if(gt(iw/ih,{r}),0,(ih-iw/{r})/2)',scale={SAMPLE}:-2")


def frames(path: Path, t0: float, t1: float, fps: float = 2.0, aspect: Optional[tuple[int, int]] = None, cx: float = 0.5) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(path), "-vf",
                          f"fps={fps},{_crop(aspect, cx)}", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    import cv2
    imgs, k = [], 0
    while True:  # split the PNG stream (sizes are not predicted)
        j = out.find(b"IEND", k)
        if j < 0:
            break
        png = out[k:j + 8]
        k = j + 8
        imgs.append(cv2.cvtColor(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB))
    if not imgs:
        raise ValueError(f"no frames from {path.name} between {t0:.2f}s and {t1:.2f}s")
    return np.stack([i[: imgs[0].shape[0], : imgs[0].shape[1]] for i in imgs])


def lab_pixels(rgb: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(rgb.reshape(-1, 1, 3).astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB).reshape(-1, 3)


def measure(rgb: np.ndarray) -> dict:
    lab = lab_pixels(rgb)
    return {"mean": [round(float(x), 2) for x in lab.mean(0)], "std": [round(float(x), 2) for x in lab.std(0)],
            "chroma": round(float(np.sqrt(lab[:, 1] ** 2 + lab[:, 2] ** 2).mean()), 2)}


def measure_target(video: Path, t0: float = 0.0, t1: Optional[float] = None, aspect: Optional[tuple[int, int]] = None) -> dict:
    """The reference's colour (MEASURED), the target every shot is graded toward."""
    if t1 is None:
        t1 = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                                  capture_output=True, text=True, check=True).stdout)
    return {"status": "MEASURED", "space": "Lab", **measure(frames(video, t0, t1, 2.0, aspect)), "sampled": [round(t0, 2), round(t1, 2)], "fps": 2}


def lut(src: dict, ref: dict, gain: float, ab_offset: np.ndarray) -> tuple[np.ndarray, dict]:
    """Lightness per shot (Reinhard on L, bounded); a/b by the film-wide gain and offset: a' = gain * a + offset."""
    import cv2
    ms, ss = np.array(src["mean"]), np.array(src["std"])
    mt, st = np.array(ref["mean"]), np.array(ref["std"])
    ratio = np.array([float(np.clip(st[0] / max(ss[0], 1e-3), *L_RATIO)), 1.0, 1.0])
    shift = np.zeros(3)
    shift[0] = float(np.clip(mt[0] - ms[0], -MAX_L_SHIFT, MAX_L_SHIFT))
    g = np.linspace(0, 1, N, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # .cube order: red changes fastest
    rgb = np.stack([r, gg, b], -1).reshape(-1, 1, 3)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).reshape(-1, 3)
    moved = (lab - ms) * ratio + ms + shift
    moved[:, 1:] = lab[:, 1:] * gain + ab_offset
    out_lab = lab + STRENGTH * (moved - lab)
    out = cv2.cvtColor(out_lab.reshape(-1, 1, 3).astype(np.float32), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    return np.clip(out, 0, 1), {"lightness_shift": round(float(shift[0]) * STRENGTH, 2), "lightness_spread_ratio": round(float(ratio[0]), 3)}


def write_cube(path: Path, table: np.ndarray, title: str) -> None:
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {N}", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in table]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def shot_luts(shots: list[dict], target: dict, out_dir: Path, aspect: Optional[tuple[int, int]] = None) -> dict:
    """shots: [{"id", "path", "source_in", "length", "cx"}]. Writes out_dir/<id>.cube; returns the report."""
    if target.get("chroma") is None:
        raise ValueError("the grade target has no measured chroma (re-measure the reference)")
    out_dir.mkdir(parents=True, exist_ok=True)
    measured = {s["id"]: measure(frames(s["path"], s["source_in"], s["source_in"] + s["length"], 2.0, aspect, s.get("cx", 0.5))) for s in shots}
    film_ab = np.mean([m["mean"][1:] for m in measured.values()], 0)
    film_chroma = float(np.mean([m["chroma"] for m in measured.values()]))
    gain = float(np.clip(target["chroma"] / max(film_chroma, 1e-3), *CHROMA_GAIN))
    ab_offset = np.array(target["mean"][1:]) - gain * film_ab
    report = {"target": {k: target[k] for k in ("mean", "std", "chroma")}, "strength": STRENGTH, "max_lightness_shift": MAX_L_SHIFT,
              "film": {"chroma": round(film_chroma, 2), "chroma_gain": round(gain, 3), "ab_mean": [round(float(x), 2) for x in film_ab],
                       "ab_offset": [round(float(x), 2) for x in ab_offset]}, "shots": {}}
    for s in shots:
        table, how = lut(measured[s["id"]], target, gain, ab_offset)
        write_cube(out_dir / f"{s['id']}.cube", table, f"{s['id']} toward the reference's measured colour")
        report["shots"][s["id"]] = {**measured[s["id"]], **how}
    (out_dir / "grade_report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("target")
    t.add_argument("video", type=Path)
    t.add_argument("--from", dest="t0", type=float, default=0.0)
    t.add_argument("--to", dest="t1", type=float)
    t.add_argument("--aspect")
    a = ap.parse_args()
    aspect = tuple(int(x) for x in a.aspect.split(":")) if a.aspect else None
    print(json.dumps(measure_target(a.video, a.t0, a.t1, aspect), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
