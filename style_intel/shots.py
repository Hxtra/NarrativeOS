"""Cuts, gradual transitions, shot lengths, flash frames and dips to black.

Hard cuts: ffmpeg's `scdet` compares each frame with the previous one.
Gradual transitions (dissolves, light-leak burns, wipes): no single frame
differs much from the last, so instead compare the colour histogram half a
second BEFORE each moment with half a second AFTER it. A peak there that is
not near a hard cut is a gradual transition. A burn shows up as two peaks
about a second apart (into the white, out of it), but the signal stays high
between them because the shots either side still differ, so each continuous
stretch above the threshold is one transition.
"""
from __future__ import annotations

import re
import statistics
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .media import run

MIN_SHOT_SEC = 0.25  # cuts closer than this are one event (a flash frame triggers scdet twice)
GRADUAL_WINDOW_SEC = 0.5  # compare frames this far before and after each moment
GRADUAL_MIN_DISTANCE = 0.6  # histogram L1 distance (0-2) that counts as a change of shot
NEAR_CUT_SEC = 1.5  # a gradual peak this close to a hard cut belongs to that cut (e.g. a burn laid over it)


def frame_track(path: Path, threshold: float = 10.0) -> tuple[list[dict], list[float]]:
    """Per-frame stats and raw cut times (seconds)."""
    out = run([
        "ffmpeg", "-v", "error", "-i", str(path), "-an",
        "-vf", f"scale=256:-2,signalstats,scdet=threshold={threshold},metadata=mode=print:file=-",
        "-f", "null", "-",
    ])
    frames: list[dict] = []
    cuts: list[float] = []
    for line in out.splitlines():
        if line.startswith("frame:"):
            m = re.search(r"pts_time:([\d.]+)", line)
            frames.append({"t": float(m.group(1)) if m else 0.0})
        elif frames and line.startswith("lavfi."):
            key, _, value = line.partition("=")
            try:
                v = float(value)
            except ValueError:
                continue
            short = key.rsplit(".", 1)[-1]
            frames[-1][short] = v
            if key == "lavfi.scd.time":
                cuts.append(v)
    return [f for f in frames if "YAVG" in f], cuts


def merge_cuts(cuts: list[float], duration: float) -> list[float]:
    merged: list[float] = []
    for c in sorted(cuts):
        if c < MIN_SHOT_SEC or c > duration - MIN_SHOT_SEC:
            continue
        if not merged or c - merged[-1] >= MIN_SHOT_SEC:
            merged.append(c)
    return merged


def shots_from_cuts(cuts: list[float], duration: float) -> list[dict]:
    edges = [0.0, *cuts, duration]
    return [{"index": i, "start": round(a, 3), "end": round(b, 3), "duration": round(b - a, 3)} for i, (a, b) in enumerate(zip(edges, edges[1:]))]


def flashes_and_dips(frames: list[dict]) -> tuple[list[float], list[float]]:
    """Flash = luma jumps >= 60 above the recent level and falls back within 4 frames. Dip = >= 2 frames near black."""
    y = [f["YAVG"] for f in frames]
    flashes, dips = [], []
    i = 3
    while i < len(y):
        base = statistics.median(y[i - 3 : i])
        if y[i] - base >= 60 and any(y[j] - base < 30 for j in range(i + 1, min(len(y), i + 5))):
            flashes.append(frames[i]["t"])
            i += 4
            continue
        i += 1
    run_start = None
    for i, v in enumerate(y):
        if v < 22:
            run_start = i if run_start is None else run_start
        else:
            if run_start is not None and i - run_start >= 2 and run_start > 0:
                dips.append(frames[run_start]["t"])
            run_start = None
    return flashes, dips


def summarize(shots: list[dict], duration: float) -> dict:
    d = sorted(s["duration"] for s in shots)
    q = lambda p: d[min(len(d) - 1, int(p * len(d)))]  # noqa: E731
    return {
        "shot_count": len(shots),
        "cuts_per_minute": round((len(shots) - 1) / duration * 60, 2),
        "shot_duration_sec": {
            "mean": round(statistics.mean(d), 3),
            "median": round(statistics.median(d), 3),
            "p10": round(q(0.10), 3),
            "p90": round(q(0.90), 3),
        },
    }


def gradual_transitions(path: Path, fps: float, hard_cuts: list[float]) -> list[float]:
    """Centres (seconds) of transitions that change the shot without a hard cut."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    thumbs = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64, 3)
    hists = []
    for f in thumbs:
        h = cv2.calcHist([cv2.cvtColor(f, cv2.COLOR_RGB2HSV)], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
        hists.append(h / max(h.sum(), 1))
    hists = np.array(hists)
    w = max(1, round(GRADUAL_WINDOW_SEC * fps))
    d = np.zeros(len(hists))
    d[w:-w] = np.abs(hists[2 * w :] - hists[: -2 * w]).sum(axis=1)
    # Relative to the quiet quarter of the video, not the median: in fast-cut edits (or short clips)
    # windows that span a cut are common enough to lift the median past every real transition.
    floor = max(GRADUAL_MIN_DISTANCE, 4 * float(np.percentile(d[w:-w], 25))) if len(d) > 2 * w else GRADUAL_MIN_DISTANCE
    above = np.flatnonzero(d >= floor)
    luma = thumbs.mean(axis=(1, 2, 3))
    regions: list[list[int]] = []
    for t in above:
        gap = range(regions[-1][-1] + 1, int(t)) if regions else range(0)
        # Mid-burn both windows sit on white (or black), so the signal dips inside one transition.
        # Bridge a gap that short or that blown-out; a gap showing a normal shot separates two transitions.
        inside_burn = len(gap) <= w and (len(gap) <= 2 or luma[list(gap)].mean() > 200 or luma[list(gap)].mean() < 20)
        if regions and inside_burn:
            regions[-1].append(int(t))
        else:
            regions.append([int(t)])
    duration = len(d) / fps
    # A real transition keeps the signal up for about a window's width; a lone frame is a histogram-bin flicker.
    regions = [r for r in regions if r[-1] - r[0] + 1 >= max(2, w // 2)]
    centres = [(r[0] + r[-1]) / 2 / fps for r in regions]
    # Fades from/to black at the very start or end are not shot changes.
    return [
        round(c, 3)
        for c in centres
        if not any(abs(c - h) < NEAR_CUT_SEC for h in hard_cuts) and NEAR_CUT_SEC <= c <= duration - NEAR_CUT_SEC
    ]


def classify_gradual(frames: list[dict], gradual: list[float]) -> list[str]:
    """light (burn / leak / flash-through), dark (dip through black) or dissolve, from the luma path."""
    t = np.array([f["t"] for f in frames])
    y = np.array([f["YAVG"] for f in frames])
    kinds = []
    for g in gradual:
        inside = y[(t >= g - 0.75) & (t <= g + 0.75)]
        around = y[((t >= g - 1.5) & (t < g - 0.75)) | ((t > g + 0.75) & (t <= g + 1.5))]
        if not len(inside) or not len(around):
            kinds.append("dissolve")
            continue
        base = float(np.median(around))
        if inside.max() - base > 35:
            kinds.append("light")
        elif base - inside.min() > 35 or inside.min() < 25:
            kinds.append("dark")
        else:
            kinds.append("dissolve")
    return kinds


def transition_vocabulary(hard_cuts: list[float], gradual: list[float], kinds: list[str], flashes: list[float], dips: list[float]) -> dict:
    """The transitions a video measurably uses, with times. Counts come straight from the detectors above;
    nothing is added that they did not see (no whip, glitch or wipe detector exists, so none are reported)."""
    by_kind = {"dissolve": [], "light": [], "dark": []}
    for t, k in zip(gradual, kinds):
        by_kind[k].append(t)
    return {
        "hard_cut": {"count": len(hard_cuts), "times_sec": list(hard_cuts)},
        "dissolve": {"count": len(by_kind["dissolve"]), "times_sec": by_kind["dissolve"]},
        "light_burn": {"count": len(by_kind["light"]), "times_sec": by_kind["light"]},
        "dip_through_black": {"count": len(by_kind["dark"]), "times_sec": by_kind["dark"]},
        "flash_frame": {"count": len(flashes), "times_sec": list(flashes)},
        "black_frames": {"count": len(dips), "times_sec": list(dips)},
        "not_detected": ["whip_pan", "glitch", "wipe", "zoom_transition", "match_cut"],
    }
