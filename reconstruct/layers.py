"""Per-frame placement of a sourced layer inside the edit (MEASURED).

For each reference frame of a layer's life: the source frame it shows (searched around the expected source time,
so speed changes and freezes show up) and the homography placing it, matched only inside the layer's region of
the reference frame (so another layer's features cannot vote). The result is a keyframe per frame: source time,
the four corners in reference pixels, scale and centre. Frames that do not match are reported, never filled.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from .source_match import MIN_INLIERS

_orb = cv2.ORB_create(3000)


def grey(video: Path, t: float, size: tuple[int, int] | None = None) -> np.ndarray:
    vf = f"scale={size[0]}:{size[1]}" if size else "null"
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", str(video), "-frames:v", "1", "-vf", vf, "-f", "image2pipe",
                          "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)


def _features(img: np.ndarray, mask: np.ndarray | None = None):
    return _orb.detectAndCompute(img, mask)


def homography(src: np.ndarray, ref: np.ndarray, ref_mask: np.ndarray | None) -> tuple[int, np.ndarray | None]:
    ks, ds = _features(src)
    kr, dr = _features(ref, ref_mask)
    if ds is None or dr is None or len(ks) < 10 or len(kr) < 10:
        return 0, None
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(ds, dr, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.78 * p[1].distance]
    if len(good) < 8:
        return 0, None
    ps = np.float32([ks[m.queryIdx].pt for m in good])
    pr = np.float32([kr[m.trainIdx].pt for m in good])
    H, inl = cv2.findHomography(ps, pr, cv2.RANSAC, 3.0)
    return (int(inl.sum()) if inl is not None else 0), H


def region_mask(shape: tuple[int, int], quad_frac: list[list[float]] | None, exclude: list[list[list[float]]] = ()) -> np.ndarray:
    h, w = shape
    m = np.zeros((h, w), np.uint8)
    if quad_frac is None:
        m[:] = 255
    else:
        cv2.fillPoly(m, [np.int32([[x * w, y * h] for x, y in quad_frac])], 255)
    for q in exclude:
        cv2.fillPoly(m, [np.int32([[x * w, y * h] for x, y in q])], 0)
    return m


def track(ref_video: Path, fps: float, frames: range, source: Path, src_t0: float, region: list[list[float]] | None,
          exclude: list[list[list[float]]] = (), search: int = 3, ref_size: tuple[int, int] = (1276, 718)) -> list[dict]:
    """region: the layer's quad in the first frame (fractions of the reference frame), followed frame to frame."""
    out = []
    expected = src_t0
    quad = region
    for k, f in enumerate(frames):
        ref = grey(ref_video, f / fps + 0.5 / fps, ref_size)
        mask = region_mask(ref.shape, _grow(quad, 0.06) if quad else None, exclude)
        best = (0, None, None)
        for d in range(-search, search + 1):
            ts = expected + d / fps
            if ts < 0:
                continue
            src = grey(source, ts + 0.5 / fps)
            n, H = homography(src, ref, mask)
            if n > best[0]:
                best = (n, ts, H)
        n, ts, H = best
        if n < MIN_INLIERS // 2 or H is None:
            out.append({"frame": f, "status": "NO_MATCH", "inliers": n})
            expected += 1 / fps
            continue
        sh, sw = grey(source, ts).shape
        corners = cv2.perspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]).reshape(-1, 1, 2), H).reshape(-1, 2)
        W, Hh = ref.shape[1], ref.shape[0]
        quad = [[float(x / W), float(y / Hh)] for x, y in corners]
        top = corners[1] - corners[0]
        left = corners[3] - corners[0]
        out.append({"frame": f, "status": "MATCHED", "inliers": n, "source_t": round(ts, 4),
                    "corners_px": [[round(float(x), 1), round(float(y), 1)] for x, y in corners],
                    "width_px": round(float(np.hypot(*top)), 1), "height_px": round(float(np.hypot(*left)), 1),
                    "rotation_deg": round(float(np.degrees(np.arctan2(top[1], top[0]))), 2),
                    "centre_px": [round(float(corners[:, 0].mean()), 1), round(float(corners[:, 1].mean()), 1)]})
        expected = ts + 1 / fps
    return out


def _grow(quad: list[list[float]], by: float) -> list[list[float]]:
    cx = sum(p[0] for p in quad) / 4
    cy = sum(p[1] for p in quad) / 4
    return [[cx + (x - cx) * (1 + by), cy + (y - cy) * (1 + by)] for x, y in quad]
