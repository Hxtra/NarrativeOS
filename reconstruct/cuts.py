"""Frame-exact cuts and flashes, from every frame (MEASURED).

Every frame is decoded small (128x72). For each frame boundary: the mean colour difference and the histogram
distance to the previous frame. A cut is a boundary whose difference stands out from its neighbours (a local
peak, well above the median of the surrounding second). A flash is a short run of frames much brighter than the
frames on both sides of it, which then returns; it is reported as a flash, not as two cuts. Picture-in-picture
pop-ins change only part of the frame: each boundary also records how much of the frame changed, so the watcher
can tell a cut from an inset appearing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

W, H = 128, 72
CUT_CORR = 0.6   # layout correlation below this is a new picture (all labelled non-cuts were >= 0.6)


def probe(video: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                        "-show_entries", "format=duration", "-of", "json", str(video)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    return {"width": s["width"], "height": s["height"], "fps": num / den, "fps_rational": s["r_frame_rate"], "duration": float(d["format"]["duration"])}


def frames(video: Path, cache: Path | None = None) -> np.ndarray:
    if cache and cache.is_file():
        return np.load(cache)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    if cache:
        np.save(cache, f)
    return f


def boundary_metrics(f: np.ndarray) -> dict:
    x = f.astype(np.float32)
    diff = np.abs(x[1:] - x[:-1]).mean(axis=(1, 2, 3))                       # mean colour change, 0-255
    changed = (np.abs(x[1:] - x[:-1]).max(axis=3) > 40).mean(axis=(1, 2))     # share of pixels that changed a lot
    hist = []
    for a in range(len(f)):
        h = np.concatenate([np.histogram(f[a, ..., c], 16, (0, 256))[0] for c in range(3)]).astype(np.float32)
        hist.append(h / h.sum())
    hist = np.array(hist)
    hd = 0.5 * np.abs(hist[1:] - hist[:-1]).sum(axis=1)                       # total variation, 0-1
    g = x @ np.array([0.299, 0.587, 0.114], np.float32)
    luma = g.mean(axis=(1, 2))
    # Layout correlation on a 32x18 grey grid, each frame normalised: a flash or a grade change keeps the layout
    # (high), a new picture does not (low). Calibrated on hand-labelled frames of the first real reference.
    small = g.reshape(len(f), H // 4, 4, W // 4, 4).mean(axis=(2, 4))
    z = (small - small.mean(axis=(1, 2), keepdims=True)) / (small.std(axis=(1, 2), keepdims=True) + 1e-3)
    corr = (z[1:] * z[:-1]).mean(axis=(1, 2))
    return {"diff": diff, "changed": changed, "hist": hd, "luma": luma, "corr": corr}


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    sa = a.reshape(H // 4, 4, W // 4, 4).mean(axis=(1, 3))
    sb = b.reshape(H // 4, 4, W // 4, 4).mean(axis=(1, 3))
    za, zb = (sa - sa.mean()) / (sa.std() + 1e-3), (sb - sb.mean()) / (sb.std() + 1e-3)
    return float((za * zb).mean())


def detect(f: np.ndarray, fps: float, min_score: float = 3.0) -> dict:
    """Cuts (index of the first frame of the new shot) and flashes (first and last frame)."""
    m = boundary_metrics(f)
    d, hd, luma = m["diff"], m["hist"], m["luma"]
    g = f.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    n = len(d)
    win = int(round(fps))
    score = np.zeros(n)
    for i in range(n):
        lo, hi = max(0, i - win), min(n, i + win + 1)
        around = np.delete(d[lo:hi], i - lo)
        base = np.median(around) + 1.0
        score[i] = d[i] / base
    # Flashes: frames much brighter than both neighbours that come back within 4 frames.
    flashes, in_flash = [], set()
    for i in range(1, len(luma) - 1):
        if i in in_flash:
            continue
        for L in range(1, 5):
            j = i + L
            if j >= len(luma):
                break
            before, after = luma[i - 1], luma[j]
            run = luma[i:j]
            washed = all(g[k].std() < 25 for k in range(i, j))                  # near-white, no picture
            same_picture = max(_corr(g[k], g[i - 1]) for k in range(i, j)) >= CUT_CORR or max(_corr(g[k], g[j]) for k in range(i, j)) >= CUT_CORR
            if run.min() - max(before, after) > 40 and abs(before - after) < 60 and (washed or same_picture):
                flashes.append({"first": i, "last": j - 1, "frames": L, "peak_luma": round(float(run.max()), 1)})
                in_flash.update(range(i, j + 1))
                break
    cuts = []
    corr = m["corr"]
    for i in range(n):
        frame = i + 1  # boundary i is between frames i and i+1
        if frame in in_flash:
            continue
        if (corr[i] < CUT_CORR and d[i] >= 10) or (corr[i] < 0.8 and d[i] >= 20 and hd[i] >= 0.15):
            cuts.append({"frame": frame, "t": round(frame / fps, 4), "diff": round(float(d[i]), 1), "score": round(float(score[i]), 1),
                         "hist": round(float(hd[i]), 3), "changed": round(float(m["changed"][i]), 3), "corr": round(float(corr[i]), 3),
                         "kind": "full_frame" if m["changed"][i] > 0.15 else "partial (inset or text change?)"})
    return {"cuts": cuts, "flashes": flashes, "frames": len(f)}


def shots_from(cuts: list[dict], flashes: list[dict], frames_total: int, fps: float) -> list[dict]:
    """Shots between cuts; a flash inside a shot stays in it as an event."""
    edges = [0] + [c["frame"] for c in cuts if c["kind"] == "full_frame"] + [frames_total]
    out = []
    for k, (a, b) in enumerate(zip(edges, edges[1:]), 1):
        if b <= a:
            continue
        out.append({"id": f"S{k:03d}", "first": a, "last": b - 1, "frames": b - a, "start": round(a / fps, 4), "end": round(b / fps, 4),
                    "partial_changes": [c["frame"] for c in cuts if c["kind"] != "full_frame" and a < c["frame"] < b],
                    "flashes": [fl for fl in flashes if a <= fl["first"] < b]})
    return out
