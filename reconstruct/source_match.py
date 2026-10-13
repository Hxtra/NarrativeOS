"""Find where a reference shot's picture comes from in a candidate source video, and how it was placed (MEASURED).

A reference frame is matched against frames sampled from the candidate: ORB features, Lowe's ratio test, and a
RANSAC homography from source to reference. The best-supported candidate frame is then refined frame by frame.
The homography is the placement: where the source picture sits in the edit (scale, position, rotation, crop),
so an inset's keyframes are fitted, not guessed. A match needs MIN_INLIERS consistent points; fewer is "no
match", never a weak guess.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

MIN_INLIERS = 25
ANALYSIS_W = 640


def frame_at(video: Path, t: float, width: int = ANALYSIS_W) -> np.ndarray:
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2",
                          "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)


def sampled(video: Path, fps: float, width: int = 320):
    """(t, grey frame) at fps through the whole video."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, check=True)
    w, h = (int(x) for x in r.stdout.strip().split(","))
    hh = int(round(h * width / w / 2) * 2)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={width}:{hh}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, hh, width)
    return [(k / fps, f) for k, f in enumerate(frames)]


_orb = cv2.ORB_create(2000)


def match(ref: np.ndarray, src: np.ndarray) -> tuple[int, np.ndarray | None]:
    """(inliers, homography src->ref)."""
    kr, dr = _orb.detectAndCompute(ref, None)
    ks, ds = _orb.detectAndCompute(src, None)
    if dr is None or ds is None or len(kr) < 10 or len(ks) < 10:
        return 0, None
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(ds, dr, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 8:
        return 0, None
    ps = np.float32([ks[m.queryIdx].pt for m in good])
    pr = np.float32([kr[m.trainIdx].pt for m in good])
    H, inl = cv2.findHomography(ps, pr, cv2.RANSAC, 4.0)
    return (int(inl.sum()) if inl is not None else 0), H


def find(ref_frame: np.ndarray, candidate: Path, coarse_fps: float = 2.0) -> dict:
    """Where ref_frame's picture is in the candidate: best time, inliers, and the placement."""
    best = (0, None, None)
    scale = 320 / ref_frame.shape[1]
    ref_small = cv2.resize(ref_frame, (320, int(ref_frame.shape[0] * scale)))
    for t, f in sampled(candidate, coarse_fps):
        n, H = match(ref_small, f)
        if n > best[0]:
            best = (n, t, H)
    if best[0] < 12:
        return {"status": "NO_MATCH", "best_inliers": best[0]}
    # refine around the best coarse time at full frame rate, full analysis size
    t0 = best[1]
    fine = []
    for dt in np.arange(-0.6, 0.61, 1 / 30):
        t = max(0.0, t0 + dt)
        n, H = match(ref_frame, frame_at(candidate, t, ref_frame.shape[1]))
        fine.append((n, t, H))
    n, t, H = max(fine, key=lambda x: x[0])
    if n < MIN_INLIERS:
        return {"status": "NO_MATCH", "best_inliers": n, "coarse_time": round(t0, 2)}
    return {"status": "MATCHED", "time": round(float(t), 3), "inliers": n, "placement": placement(H, ref_frame.shape[1], ref_frame.shape[0])}


def placement(H: np.ndarray, w: int, h: int) -> dict:
    """The source frame's corners in the reference frame (fractions), and the scale/rotation they imply."""
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)  # same analysis width for both
    pts = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
    frac = [[round(float(x / w), 4), round(float(y / h), 4)] for x, y in pts]
    top = pts[1] - pts[0]
    return {"corners_frac": frac, "scale": round(float(np.hypot(*top) / w), 4),
            "rotation_deg": round(float(np.degrees(np.arctan2(top[1], top[0]))), 2),
            "centre_frac": [round(float(pts[:, 0].mean() / w), 4), round(float(pts[:, 1].mean() / h), 4)]}
