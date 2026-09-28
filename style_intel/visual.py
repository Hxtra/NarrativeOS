"""Per-shot look (colour, contrast, grain, letterbox) and camera motion (push/pull/pan/handheld)."""
from __future__ import annotations

import statistics
from pathlib import Path

import cv2
import numpy as np

from .media import frame_at

MAX_SHOTS_SAMPLED = 60


def sample_shots(shots: list[dict]) -> list[dict]:
    if len(shots) <= MAX_SHOTS_SAMPLED:
        return shots
    step = len(shots) / MAX_SHOTS_SAMPLED
    return [shots[int(i * step)] for i in range(MAX_SHOTS_SAMPLED)]


IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)


def grain_sigma(rgb: np.ndarray) -> float:
    """Noise standard deviation (0-255) by Immerkaer's estimator, skipping edges so detail and text don't count as grain."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    edges = np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    flat = edges <= np.percentile(edges, 50)
    response = np.abs(cv2.filter2D(gray, -1, IMMERKAER))
    return float(np.sqrt(np.pi / 2) * response[flat].mean() / 6) if flat.sum() > 1000 else float("nan")


def look(rgb: np.ndarray) -> dict:
    """Colour and tone measurements of one frame (values 0-1 unless noted)."""
    img = rgb.astype(np.float32) / 255.0
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    sat = hsv[..., 1] / 255.0
    # Hue concentration of the coloured pixels: ~1 when everything shares one tint (duotone / toned B&W).
    hue = hsv[..., 0] * (2 * np.pi / 180)
    weight = sat * (luma > 0.05)
    cx, cy = (weight * np.cos(hue)).sum(), (weight * np.sin(hue)).sum()
    hue_concentration = float(np.hypot(cx, cy) / max(weight.sum(), 1e-6))
    dominant_hue = float(np.degrees(np.arctan2(cy, cx)) % 360)
    # Hasler & Suesstrunk colourfulness, on 0-255 scale.
    rg, yb = (r - g) * 255, (0.5 * (r + g) - b) * 255
    colourfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    rows = luma.mean(axis=1)
    dark = rows < 0.03
    top = int(np.argmax(~dark)) if (~dark).any() else 0
    bottom = int(np.argmax(~dark[::-1])) if (~dark).any() else 0
    return {
        "luma_mean": float(luma.mean()),
        "contrast": float(luma.std()),
        "saturation": float(sat.mean()),
        "hue_concentration": hue_concentration,
        "dominant_hue_deg": dominant_hue,
        "warmth": float((r - b).mean()),
        "colourfulness": colourfulness,
        "letterbox_fraction": float((top + bottom) / len(rows)),
    }


def circular_median_hue(hues: list[float]) -> float:
    """Hue (degrees) closest to all others around the colour wheel."""
    return round(min(hues, key=lambda h: sum(min(abs(h - o), 360 - abs(h - o)) for o in hues)), 1)


def camera_motion(path: Path, shot: dict) -> dict | None:
    """Camera move over the middle of a shot: fit zoom + pan to matched feature points (ORB + RANSAC).

    RANSAC follows the dominant (background) motion, so a subject moving on its
    own does not read as a camera move; a low inlier share means the frame is
    moving in ways one camera transform can't explain (handheld, action).
    Returns None when the shot is too short or too featureless to measure.
    """
    if shot["duration"] < 0.5:
        return None
    dt = min(3.0, shot["duration"] * 0.6)  # a longer baseline makes slow Ken Burns moves measurable
    mid = shot["start"] + shot["duration"] / 2
    a = cv2.cvtColor(frame_at(path, mid - dt / 2, 480), cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(frame_at(path, mid + dt / 2, 480), cv2.COLOR_RGB2GRAY)
    if a.shape != b.shape:
        return None
    orb = cv2.ORB_create(1500)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 40 or len(kb) < 40:
        return None
    # Lowe's ratio test: keep a match only if it is clearly better than the runner-up.
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    matches = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(matches) < 30:
        return None
    pa = np.float32([ka[m.queryIdx].pt for m in matches])
    pb = np.float32([kb[m.trainIdx].pt for m in matches])
    M, inliers = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None:
        return None
    h, w = a.shape
    centre = np.array([w / 2, h / 2, 1.0])

    def move(m: np.ndarray) -> tuple[float, float]:
        return float(np.hypot(m[0, 0], m[1, 0])), float(np.hypot(*(m @ centre - centre[:2])))

    scale, shift = move(M)
    support = float(inliers.mean())
    overlay = False
    # Captions, logos, borders and other fixed overlays can win the RANSAC vote with "no motion".
    # If so, fit the points that did not fit: consistent motion there is the footage under the overlay.
    if abs(scale - 1) < 0.002 and shift < 0.5:
        rest = inliers.ravel() == 0
        if rest.sum() >= 30:
            M2, in2 = cv2.estimateAffinePartial2D(pa[rest], pb[rest], method=cv2.RANSAC, ransacReprojThreshold=2.0)
            if M2 is not None and in2.sum() >= max(20, 0.2 * len(matches)):
                s2, sh2 = move(M2)
                if abs(s2 - 1) >= 0.002 or sh2 >= 0.5:
                    scale, shift, support, overlay = s2, sh2, float(in2.sum() / len(matches)), True
    return {
        "zoom_per_sec": (scale - 1) / dt,  # fractional scale change per second (+ = push in)
        "pan_px_per_sec": shift / dt,  # on a 480px-wide frame
        "inlier_share": support,
        "matches": len(matches),
        "static_overlay_detected": overlay,
    }


def classify_motion(m: dict | None) -> str:
    if m is None:
        return "unmeasured"
    if m["inlier_share"] < 0.35 and not m.get("static_overlay_detected"):
        return "handheld_or_action"
    if m["zoom_per_sec"] > 0.006:
        return "push_in"
    if m["zoom_per_sec"] < -0.006:
        return "pull_out"
    if m["pan_px_per_sec"] > 6:
        return "pan"
    return "static"


def analyze(path: Path, shots: list[dict]) -> tuple[dict, list[dict], list[np.ndarray]]:
    """Summary, per-shot measurements, and one mid-shot thumbnail per sampled shot (for the contact sheet)."""
    sampled = sample_shots(shots)
    per_shot = []
    thumbs = []
    for s in sampled:
        mid = s["start"] + s["duration"] / 2
        frame = frame_at(path, mid)
        thumbs.append(frame)
        entry = {"index": s["index"], "look": {**look(frame), "grain": grain_sigma(frame_at(path, mid, width=None, crop=(640, 360)))}}
        motion = camera_motion(path, s)
        entry["motion"] = motion
        entry["motion_class"] = classify_motion(motion)
        per_shot.append(entry)
    def med(k: str) -> float | None:
        vals = [v for e in per_shot if not np.isnan(v := e["look"][k])]
        return round(statistics.median(vals), 4) if vals else None

    classes = [e["motion_class"] for e in per_shot if e["motion_class"] != "unmeasured"]
    fractions = {c: round(classes.count(c) / len(classes), 3) for c in ("static", "push_in", "pull_out", "pan", "handheld_or_action")} if classes else {}
    mono = sum(1 for e in per_shot if e["look"]["saturation"] < 0.06) / len(per_shot)
    tinted = sum(1 for e in per_shot if e["look"]["saturation"] >= 0.06 and e["look"]["hue_concentration"] > 0.85) / len(per_shot)
    summary = {
        "shots_sampled": len(per_shot),
        "luma_mean": med("luma_mean"),
        "contrast": med("contrast"),
        "saturation": med("saturation"),
        "warmth": med("warmth"),
        "colourfulness": med("colourfulness"),
        "grain": med("grain"),
        "letterbox_fraction": med("letterbox_fraction"),
        "hue_concentration": med("hue_concentration"),
        "dominant_hue_deg": circular_median_hue([e["look"]["dominant_hue_deg"] for e in per_shot]),
        "monochrome_shot_fraction": round(mono, 3),
        "tinted_monochrome_shot_fraction": round(tinted, 3),
        "camera_motion": {
            "shots_measured": len(classes),
            "fractions": fractions,
            "dominant": max(fractions, key=fractions.get) if fractions else None,
        },
    }
    return summary, per_shot, thumbs
