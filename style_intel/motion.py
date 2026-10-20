"""Motion at full frame rate: how a film moves, not only what is on screen.

For every frame: the camera move (pan, zoom, rotation from a robust similarity fit of tracked points), how much the picture moves
on its own beyond that camera move (characters, animated elements), and whether the frame repeats the previous one (animation held
on twos or threes). From those:
- every shot boundary classified: hard cut, dissolve, dip to black, flash, wipe, cut on camera motion (whip or zoom-through),
  match cut on layout; with its length in frames;
- every shot's camera move with its easing (linear, ease in, ease out, ease in-out) from the speed curve;
- every shot's animation: held, camera-only, animated (and at what drawing rate).
All MEASURED from pixels; names of moves are INFERRED from stated thresholds. A reviewer looks at full-frame-rate strips before
trusting a label.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

WIDTH = 320          # analysis width; motion numbers are in pixels at this width
THUMB = 64           # transition thumbnails
CFG = {
    "cut_diff": 18.0, "cut_ratio": 3.0, "step_gap": 4,               # hard cut: thumb diff above this and above ratio x the neighbours
    "repeat_diff": 0.35,                              # a frame that repeats the previous one (animation held)
    "gradual_dist": 14.0, "gradual_resid": 0.35,      # blend test: A and B this different, C explained this well by a blend
    "gradual_spans": (3, 6, 10, 16),
    "dark_luma": 18.0, "light_luma": 225.0,
    "fast_camera": 6.0,                               # px/frame at WIDTH: a camera this fast into a cut = cut on motion
    "fast_zoom": 0.02,                                # scale change per frame
    "match_corr": 0.75,                               # layout correlation across a hard cut
    "move_pan": 6.0, "move_zoom": 0.03,               # total pan (px) or zoom (ratio) for a shot to count as a camera move
    "local_px": 0.8,                                  # residual motion (p90, px) above this = something moves in the frame
}


def _thumbs_and_motion(path: Path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    prev = None
    thumbs, luma, rows = [], [], []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        h = max(2, int(round(fr.shape[0] * WIDTH / fr.shape[1] / 2)) * 2)
        g = cv2.cvtColor(cv2.resize(fr, (WIDTH, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        t = cv2.resize(g, (THUMB, max(2, h * THUMB // WIDTH)), interpolation=cv2.INTER_AREA)
        thumbs.append(t)
        luma.append(float(g.mean()))
        row = {"dx": 0.0, "dy": 0.0, "zoom": 1.0, "rot": 0.0, "fit": 0.0, "local": 0.0, "moving": 0.0}
        if prev is not None:
            pts = cv2.goodFeaturesToTrack(prev, 300, 0.01, 6)
            if pts is not None and len(pts) >= 10:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, g, pts, None, winSize=(15, 15), maxLevel=3)
                good = st.ravel() == 1
                p0, p1 = pts[good].reshape(-1, 2), nxt[good].reshape(-1, 2)
                if len(p0) >= 10:
                    M, inl = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=1.0)
                    if M is not None:
                        a, b = M[0, 0], M[1, 0]
                        s = math.hypot(a, b)
                        # translation of the frame centre (so a zoom about the centre is not read as a pan)
                        c = np.array([WIDTH / 2, h / 2])
                        cc = M[:, :2] @ c + M[:, 2]
                        res = np.linalg.norm(p1 - (p0 @ M[:, :2].T + M[:, 2]), axis=1)
                        row = {"dx": float(cc[0] - c[0]), "dy": float(cc[1] - c[1]), "zoom": float(s), "rot": float(math.atan2(b, a)),
                               "fit": float(inl.mean()), "local": float(np.percentile(res, 90)), "moving": float((res > 1.5).mean())}
        rows.append(row)
        prev = g
    cap.release()
    return fps, np.array(thumbs, dtype=np.float32), np.array(luma), rows


def _diffs(th: np.ndarray) -> np.ndarray:
    d = np.zeros(len(th))
    d[1:] = np.abs(th[1:] - th[:-1]).mean(axis=(1, 2))
    return d


def hard_cuts(diff: np.ndarray, cfg: dict = CFG) -> list[int]:
    """Frame index i where frame i starts a new shot."""
    out = []
    for i in range(1, len(diff)):
        nb = np.r_[diff[max(1, i - 3):i], diff[i + 1:i + 4]]
        if diff[i] > cfg["cut_diff"] and diff[i] > cfg["cut_ratio"] * (np.median(nb) if len(nb) else 0) + 1e-6:
            out.append(i)
    return out


def settle_cuts(cuts: list[int], th: np.ndarray, cfg: dict = CFG) -> tuple[list[int], list[dict]]:
    """A real cut lands on a new picture that then holds. Picture jumps 4 frames or less apart are stepped animation
    (shapes jumping on threes or fours) inside one shot: keep the first jump as the cut, report the rest as one stepped run
    (MEASURED, Internet 20:40: four 'cuts' in 0.4 s were a cut-paper pattern animated in steps)."""
    keep, runs, i = [], [], 0
    while i < len(cuts):
        j = i
        while j + 1 < len(cuts) and cuts[j + 1] - cuts[j] <= cfg["step_gap"]:
            j += 1
        keep.append(cuts[i])
        if j > i:
            runs.append({"start": cuts[i], "end": cuts[j], "jumps": j - i})
        i = j + 1
    return keep, runs


def _blend_fit(A, B, C):
    d = A - B
    den = float((d * d).sum())
    if den <= 0:
        return 0.5, 1e9
    alpha = float(((C - B) * d).sum() / den)
    resid = float(np.abs(C - (alpha * A + (1 - alpha) * B)).mean())
    return alpha, resid


def gradual(th: np.ndarray, luma: np.ndarray, cuts: list[int], rows: list[dict], cfg: dict = CFG) -> list[dict]:
    """Transitions spread over several frames (dissolve, dip to black, flash, wipe), found by a blend test: the middle frame is
    explained by a mix of the frames before and after, which are themselves very different."""
    n, cand = len(th), []
    cutset = set(cuts)
    for span in cfg["gradual_spans"]:
        for k in range(span, n - span):
            if any(c in cutset for c in range(k - span + 1, k + span + 1)):
                continue
            A, B, C = th[k - span], th[k + span], th[k]
            dist = float(np.abs(A - B).mean())
            if dist < cfg["gradual_dist"]:
                continue
            # a camera move also makes the middle frame look "between": skip windows the camera explains
            win = rows[k - span + 1:k + span + 1]
            pan = math.hypot(sum(r["dx"] for r in win), sum(r["dy"] for r in win))
            zm = abs(sum(math.log(max(r["zoom"], 1e-6)) for r in win))
            if np.median([r["fit"] for r in win]) > 0.6 and (pan > 3 or zm > 0.03):
                continue
            lo, hi = luma[k - span:k + span + 1].min(), luma[k - span:k + span + 1].max()
            dark = lo < cfg["dark_luma"] and lo < min(luma[k - span], luma[k + span]) - 10
            light = hi > cfg["light_luma"] and hi > max(luma[k - span], luma[k + span]) + 10
            alpha, resid = _blend_fit(A, B, C)
            mask = np.abs(C - A) < np.abs(C - B)
            # a wipe: the frame is part A, part B, split by a clean edge (column or row majority flips once)
            colm, rowm = mask.mean(0), mask.mean(1)
            wipe = max(_one_flip(colm), _one_flip(rowm)) and 0.15 < mask.mean() < 0.85
            if dark or light or wipe or (0.15 < alpha < 0.85 and resid < cfg["gradual_resid"] * dist):
                kind = "dip_to_black" if dark else "flash" if light else "wipe" if wipe else "dissolve"
                cand.append((k, span, kind, dist, resid))
    # merge overlapping candidates into one transition, keep the widest span's frame range
    cand.sort()
    out: list[dict] = []
    for k, span, kind, dist, resid in cand:
        if out and k - span <= out[-1]["end"]:
            o = out[-1]
            o["start"], o["end"] = min(o["start"], k - span), max(o["end"], k + span)
            o["kinds"][kind] = o["kinds"].get(kind, 0) + 1
        else:
            out.append({"start": k - span, "end": k + span, "kinds": {kind: 1}})
    keep = []
    for o in out:
        o["kind"] = max(o["kinds"], key=lambda x: (o["kinds"][x], x != "dissolve"))
        if o["kind"] in ("dissolve", "wipe") and not _steady_blend(th, o["start"], o["end"], o["kind"]):
            continue   # animation inside a shot (drifting glyphs, unfolding paper), not a transition (MEASURED, Fern 0:12-1:01)
        keep.append(o)
    out = keep
    for o in out:
        # refine the length: frames inside where the picture is neither the first nor the last frame
        a, b = th[o["start"]], th[o["end"]]
        mids = [i for i in range(o["start"], o["end"] + 1)
                if np.abs(th[i] - a).mean() > 3 and np.abs(th[i] - b).mean() > 3]
        if mids:
            o["start"], o["end"] = mids[0], mids[-1]
        o["frames"] = o["end"] - o["start"] + 1
    return [o for o in out if o["frames"] >= 3]


def _steady_blend(th: np.ndarray, a: int, b: int, kind: str) -> bool:
    """A real dissolve moves steadily from picture A to picture B: the mix weight falls monotonically across the window and every
    frame is explained by the mix. A real wipe's edge travels one way. Animation inside a shot does neither."""
    A, B = th[max(a - 1, 0)], th[min(b + 1, len(th) - 1)]
    if b - a < 2:
        return False
    if kind == "dissolve":
        fits = [_blend_fit(A, B, th[i]) for i in range(a, b + 1)]
        alphas = np.array([f[0] for f in fits])
        dist = float(np.abs(A - B).mean()) or 1.0
        mono = np.corrcoef(np.arange(len(alphas)), alphas)[0, 1] if alphas.std() > 0 else 0.0
        return mono < -0.9 and alphas[0] > 0.6 and alphas[-1] < 0.4 and max(f[1] for f in fits) < 0.4 * dist
    edges = []
    for i in range(a, b + 1):
        m = np.abs(th[i] - A) < np.abs(th[i] - B)
        edges.append(m.mean())
    e = np.array(edges)
    return len(e) > 2 and abs(np.corrcoef(np.arange(len(e)), e)[0, 1]) > 0.9 and e.max() - e.min() > 0.5


def _one_flip(profile: np.ndarray) -> bool:
    p = profile > 0.5
    flips = int(np.abs(np.diff(p.astype(int))).sum())
    clean = np.mean(np.minimum(profile, 1 - profile)) < 0.2
    return flips == 1 and clean


def _corr(a, b) -> float:
    a, b = a - a.mean(), b - b.mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum())) or 1.0
    return float((a * b).sum() / den)


def classify_cut(i: int, th: np.ndarray, rows: list[dict], fps: float, cfg: dict = CFG) -> dict:
    """A hard cut, and what carries it: camera motion into/out of it (whip, zoom-through) or a matching layout (match cut)."""
    def speed(rng):
        rs = [rows[j] for j in rng if 0 <= j < len(rows) and rows[j]["fit"] > 0.4]
        if not rs:
            return 0.0, 0.0, (0.0, 0.0)
        pan = float(np.median([math.hypot(r["dx"], r["dy"]) for r in rs]))
        zoom = float(np.median([abs(math.log(max(r["zoom"], 1e-6))) for r in rs]))
        d = (float(np.median([r["dx"] for r in rs])), float(np.median([r["dy"] for r in rs])))
        return pan, zoom, d
    pin, zin, din = speed(range(i - 3, i))
    pout, zout, dout = speed(range(i + 1, i + 4))
    kind = "hard_cut"
    if max(pin, pout) > cfg["fast_camera"]:
        kind = "cut_on_pan"
    elif max(zin, zout) > cfg["fast_zoom"]:
        kind = "cut_on_zoom"
    elif _corr(th[i - 1], th[i]) > cfg["match_corr"]:
        kind = "match_cut"
    return {"frame": i, "t": round(i / fps, 3), "kind": kind, "frames": 1,
            "camera_in": {"pan_px": round(pin, 2), "zoom": round(zin, 4), "dir": [round(x, 2) for x in din]},
            "camera_out": {"pan_px": round(pout, 2), "zoom": round(zout, 4), "dir": [round(x, 2) for x in dout]}}


EASES = {"linear": lambda x: x, "ease_in_out": lambda x: x * x * (3 - 2 * x), "ease_out": lambda x: 1 - (1 - x) ** 3,
         "ease_in": lambda x: x ** 3, "ease_out_strong": lambda x: 1 - (1 - x) ** 5}


def camera_move(rows: list[dict], a: int, b: int, fps: float, cfg: dict = CFG) -> dict:
    """The shot's camera path (centre pan and zoom accumulated over frames) and the easing that fits it best."""
    seg = rows[a + 1:b]
    if len(seg) < 4:
        return {"kind": "too_short"}
    x = np.cumsum([r["dx"] if r["fit"] > 0.3 else 0 for r in seg])
    y = np.cumsum([r["dy"] if r["fit"] > 0.3 else 0 for r in seg])
    z = np.cumsum([math.log(r["zoom"]) if r["fit"] > 0.3 else 0 for r in seg])
    pan, zoom = float(math.hypot(x[-1], y[-1])), float(math.exp(z[-1]))
    if pan < cfg["move_pan"] and abs(zoom - 1) < cfg["move_zoom"]:
        return {"kind": "locked", "pan_px": round(pan, 1), "zoom": round(zoom, 3)}
    # progress 0..1 along the dominant axis of the move
    path = z / z[-1] if abs(zoom - 1) >= cfg["move_zoom"] and abs(z[-1]) * 200 > pan else (x * x[-1] + y * y[-1]) / (pan * pan)
    path = np.clip(path, -0.2, 1.2)
    tt = np.linspace(0, 1, len(path))
    fits = {k: float(np.sqrt(np.mean((path - f(tt)) ** 2))) for k, f in EASES.items()}
    best = min(fits, key=fits.get)
    kind = ("push_in" if zoom > 1 else "pull_out") if abs(zoom - 1) >= cfg["move_zoom"] else "pan"
    return {"kind": kind, "pan_px": round(pan, 1), "dir": [round(float(x[-1]), 1), round(float(y[-1]), 1)], "zoom": round(zoom, 3),
            "easing": best, "easing_rms": round(fits[best], 3), "linear_rms": round(fits["linear"], 3),
            "seconds": round(len(seg) / fps, 2)}


def animation(rows: list[dict], diff: np.ndarray, a: int, b: int, cfg: dict = CFG) -> dict:
    """Does anything move besides the camera, and on what drawing rate (ones, twos, threes)?"""
    seg = range(a + 1, b)
    if len(seg) < 6:
        return {"kind": "too_short"}
    local = np.array([rows[j]["local"] for j in seg])
    reps = np.array([diff[j] < cfg["repeat_diff"] for j in seg])
    moving = local > cfg["local_px"]
    still = reps.mean()
    rate = None
    if 0.2 < still < 0.85:
        # length of runs of repeated frames: 1 repeat between changes = twos, 2 = threes
        runs, k = [], 0
        for r in reps:
            if r:
                k += 1
            elif k:
                runs.append(k); k = 0
        if runs:
            rate = {1: "twos", 2: "threes"}.get(int(np.median(runs)), f"held {int(np.median(runs)) + 1} frames")
    kind = "held" if still > 0.95 else "animated" if moving.mean() > 0.3 else "camera_only"
    return {"kind": kind, "moving_frames": round(float(moving.mean()), 2), "repeated_frames": round(float(still), 2),
            "drawing_rate": rate or ("ones" if still < 0.2 else None), "local_p90_px": round(float(np.median(local)), 2)}


def analyze(video: Path, out: Path, cfg: dict = CFG) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    fps, th, luma, rows = _thumbs_and_motion(video)
    diff = _diffs(th)
    cuts, stepped = settle_cuts(hard_cuts(diff, cfg), th, cfg)
    grads = gradual(th, luma, cuts, rows, cfg)
    trans = [classify_cut(i, th, rows, fps, cfg) for i in cuts]
    for g in grads:
        trans.append({"frame": g["start"], "t": round(g["start"] / fps, 3), "kind": g["kind"], "frames": g["frames"],
                      "seconds": round(g["frames"] / fps, 2)})
    trans.sort(key=lambda x: x["frame"])
    bounds = sorted({0, len(th)} | {t["frame"] for t in trans} | {t["frame"] + t["frames"] for t in trans if t["frames"] > 1})
    shots = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < 2:
            continue
        shots.append({"start": round(a / fps, 3), "end": round(b / fps, 3), "frames": b - a,
                      "camera": camera_move(rows, a, b, fps, cfg), "animation": animation(rows, diff, a, b, cfg)})
    np.save(out / "per_frame.npy", np.array([[r["dx"], r["dy"], r["zoom"], r["rot"], r["fit"], r["local"], r["moving"]] for r in rows],
                                            dtype=np.float32))
    result = {"source": video.name, "fps": fps, "frames": len(th), "transitions": trans, "shots": shots,
              "stepped_animation": [{"t": round(r["start"] / fps, 3), "seconds": round((r["end"] - r["start"]) / fps, 2), "jumps": r["jumps"]} for r in stepped],
              "summary": summary(trans, shots, fps)}
    (out / "motion.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def summary(trans: list[dict], shots: list[dict], fps: float) -> dict:
    from collections import Counter
    kinds = Counter(t["kind"] for t in trans)
    grad_len = {k: round(float(np.median([t["frames"] for t in trans if t["kind"] == k])), 1) for k in kinds if k in ("dissolve", "dip_to_black", "flash", "wipe")}
    cams = Counter(s["camera"].get("kind") for s in shots)
    eases = Counter(s["camera"].get("easing") for s in shots if s["camera"].get("easing"))
    anim = Counter(s["animation"].get("kind") for s in shots)
    rates = Counter(s["animation"].get("drawing_rate") for s in shots if s["animation"].get("kind") == "animated")
    moves = [s["camera"] for s in shots if s["camera"].get("kind") in ("push_in", "pull_out", "pan")]
    return {"transitions": dict(kinds), "gradual_median_frames": grad_len, "camera": dict(cams), "easing": dict(eases),
            "animation": dict(anim), "drawing_rate": {str(k): v for k, v in rates.items()},
            "push_zoom_median": round(float(np.median([m["zoom"] for m in moves if m["kind"] != "pan"])), 3) if moves else None,
            "move_seconds_median": round(float(np.median([m["seconds"] for m in moves])), 2) if moves else None}
