#!/usr/bin/env python3
"""Frame awareness: where the subject is, where their hands are, which parts of the frame are empty, and a cut-out
of the person, all measured from the pictures with local MediaPipe models (scripts/vision_models.py).

    python scripts/frame_awareness.py analyze CLIP [--start S] [--length L]     # JSON summary
    python scripts/frame_awareness.py reframe CLIP --aspect 9:16               # deadzone camera keys

Used by the talking-head pass (reframing 16:9 footage to 9:16 around the speaker, caption placement, finger
anchors) and by the compiler (mattes for text behind the subject). Everything here is MEASURED by a detector at
sampled frames, with its confidence; the camera path is a deterministic rule over those measurements.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vision_models  # noqa: E402

SAMPLE_FPS = 6.0
ANALYSIS_W = 384          # analysis width in pixels; boxes are reported normalised to 0..1
GRID = (6, 4)             # rows x columns for the empty-space map


def _identity(path: Path) -> str:
    st = path.stat()
    return hashlib.sha256(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def probe_size(path: Path) -> tuple[int, int, float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    return int(s["width"]), int(s["height"]), float((d.get("format") or {}).get("duration") or 0)


def frames(path: Path, start: float, length: float, fps: float, width: int) -> tuple[list[float], list[np.ndarray]]:
    """RGB frames sampled at fps over [start, start + length], scaled to `width` (aspect kept)."""
    sw, sh, _ = probe_size(path)
    h = int(round(sh * width / sw / 2)) * 2
    image = path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    src = ["-loop", "1", "-t", f"{length:.3f}"] if image else ["-ss", f"{start:.3f}", "-t", f"{length:.3f}"]
    raw = subprocess.run(["ffmpeg", "-v", "error", *src, "-i", str(path), "-vf", f"fps={fps:g},scale={width}:{h}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    n = len(raw) // (width * h * 3)
    arr = np.frombuffer(raw[: n * width * h * 3], np.uint8).reshape(n, h, width, 3)
    return [round(start + i / fps, 3) for i in range(n)], [arr[i] for i in range(n)]


def _detectors():
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    mode = vision.RunningMode.VIDEO
    # The face model squashes its input to a square, so it runs on square crops (IMAGE mode: the crop moves).
    face = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(vision_models.path("face_detector"))), running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=0.5))
    hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(vision_models.path("hand_landmarker"))), running_mode=mode, num_hands=2))
    seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(vision_models.path("selfie_segmenter"))), running_mode=mode, output_confidence_masks=True))
    return mp, face, hands, seg


def _squares(w: int, h: int, person: Optional[list[float]]) -> list[tuple[int, int, int]]:
    """Square crops (x, y, side) to run the face model on: one around the person when segmentation found one,
    otherwise overlapping squares across the frame."""
    side = min(w, h)
    if person:
        px, py, pw, ph = person
        cx = int((px + pw / 2) * w)
        x = min(max(0, cx - side // 2), w - side)
        return [(x, 0, side)] if w >= h else [(0, min(max(0, int(py * h) - side // 8), h - side), side)]
    step = max(1, side // 2)
    if w >= h:
        return [(x, 0, side) for x in sorted({*range(0, w - side + 1, step), w - side})]
    return [(0, y, side) for y in sorted({*range(0, h - side + 1, step), h - side})]


def _faces(mp, face, rgb: np.ndarray, person: Optional[list[float]]) -> list[dict]:
    h, w = rgb.shape[:2]
    found = []
    for x0, y0, side in _squares(w, h, person):
        crop = np.ascontiguousarray(rgb[y0:y0 + side, x0:x0 + side])
        for d in face.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)).detections:
            b = d.bounding_box
            found.append({"box": [round((x0 + b.origin_x) / w, 4), round((y0 + b.origin_y) / h, 4), round(b.width / w, 4), round(b.height / h, 4)],
                          "score": round(d.categories[0].score, 3)})
    keep = []  # the same face seen in two overlapping squares counts once
    for f in sorted(found, key=lambda f: -f["score"]):
        x, y, bw, bh = f["box"]
        if all(abs(x + bw / 2 - (k["box"][0] + k["box"][2] / 2)) > max(bw, k["box"][2]) / 2 or
               abs(y + bh / 2 - (k["box"][1] + k["box"][3] / 2)) > max(bh, k["box"][3]) / 2 for k in keep):
            keep.append(f)
    return sorted(keep, key=lambda f: -f["box"][2] * f["box"][3])


def _empty_space(mask: np.ndarray, rgb: np.ndarray) -> list[list[float]]:
    """Per grid cell: how free it is (1 = empty), from the person mask and edge clutter."""
    import cv2
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 160) > 0
    rows, cols = GRID
    h, w = mask.shape
    out = []
    for r in range(rows):
        row = []
        for c in range(cols):
            ys, xs = slice(r * h // rows, (r + 1) * h // rows), slice(c * w // cols, (c + 1) * w // cols)
            person = float(mask[ys, xs].mean())
            clutter = min(1.0, float(edges[ys, xs].mean()) * 6)
            row.append(round(max(0.0, 1 - person - 0.5 * clutter), 3))
        out.append(row)
    return out


def analyze(path: Path, start: float, length: float, cache_dir: Optional[Path] = None, fps: float = SAMPLE_FPS) -> dict:
    """Per sampled frame: faces (normalised boxes + score), hands (index fingertip, wrist), the person's box from the
    segmentation mask, and the empty-space grid. Cached per clip content and range."""
    key = f"{path.stem}-{_identity(path)}-{start:.3f}-{length:.3f}-{fps:g}"
    cache = (cache_dir / f"{key}.json") if cache_dir else None
    if cache and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    times, imgs = frames(path, start, length, fps, ANALYSIS_W)
    mp, face, hands, seg = _detectors()
    samples = []
    try:
        for t, rgb in zip(times, imgs):
            h, w = rgb.shape[:2]
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            ms = int(round((t - start) * 1000))
            hr = hands.detect_for_video(img, ms)
            hand_list = [{"index_tip": [round(lm[8].x, 4), round(lm[8].y, 4)], "wrist": [round(lm[0].x, 4), round(lm[0].y, 4)],
                          "side": hr.handedness[i][0].category_name, "score": round(hr.handedness[i][0].score, 3)}
                         for i, lm in enumerate(hr.hand_landmarks)]
            sr = seg.segment_for_video(img, ms)
            mask = sr.confidence_masks[0].numpy_view().astype(np.float32)
            if mask.ndim == 3:
                mask = mask[..., 0]
            on = mask > 0.5
            ys, xs = np.nonzero(on)
            person = [round(xs.min() / w, 4), round(ys.min() / h, 4), round((xs.max() - xs.min()) / w, 4), round((ys.max() - ys.min()) / h, 4)] \
                if ys.size > 0.01 * on.size else None
            faces = _faces(mp, face, rgb, person)
            samples.append({"t": t, "faces": faces, "hands": hand_list, "person": person, "person_area": round(float(on.mean()), 4),
                            "empty": _empty_space(mask, rgb)})
    finally:
        for d in (face, hands, seg):
            d.close()
    out = {"file": path.name, "start": start, "length": length, "fps": fps, "status": "MEASURED",
           "models": {k: vision_models.MODELS[k]["file"] for k in vision_models.MODELS}, "samples": samples}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def subject_centres(analysis: dict) -> list[tuple[float, float, float]]:
    """(t, x, y) of the subject at each sample: the largest face, else the person box's upper third, else None skipped."""
    out = []
    for s in analysis["samples"]:
        if s["faces"]:
            x, y, w, h = s["faces"][0]["box"]
            out.append((s["t"], x + w / 2, y + h / 2))
        elif s["person"]:
            x, y, w, h = s["person"]
            out.append((s["t"], x + w / 2, y + h / 3))
    return out


def camera_keys(centres: list[tuple[float, float, float]], crop_w: float, crop_h: float, deadzone: float = 0.12,
                move_sec: float = 0.5, lead_sec: float = 0.2) -> list[list[float]]:
    """A camera operator's path for a crop window (crop_w, crop_h as fractions of the source frame).

    The camera holds still while the subject stays inside a deadzone around the frame centre. When the subject
    leaves it, the camera eases to where the subject will be move_sec later. The whole clip is known (we edit
    offline), so the move starts lead_sec early and arrives with the subject instead of chasing it. Returns
    keyframes [t, cx, cy] (crop centre, normalised source coordinates), clamped so the crop stays inside the frame."""
    if not centres:
        return [[0.0, 0.5, 0.5]]
    clamp = lambda v, half: min(1 - half, max(half, v))  # noqa: E731
    ts = [c[0] for c in centres]
    xs = [c[1] for c in centres]
    ys = [c[2] for c in centres]

    def med(a: list[float], i: int) -> float:  # a 3-sample median keeps one-frame detector jitter from moving the camera
        w = sorted(a[max(0, i - 1): i + 2])
        return w[len(w) // 2]

    def at(t: float) -> tuple[float, float]:  # the subject (median-filtered) at the nearest sample to t
        i = min(range(len(ts)), key=lambda k: abs(ts[k] - t))
        return med(xs, i), med(ys, i)

    cx, cy = clamp(med(xs, 0), crop_w / 2), clamp(med(ys, 0), crop_h / 2)
    keys = [[ts[0], round(cx, 4), round(cy, 4)]]
    free_at = ts[0]
    for i, t in enumerate(ts):
        if t < free_at:
            continue
        sx, sy = med(xs, i), med(ys, i)
        if abs(sx - cx) > deadzone * crop_w or (crop_h < 1 and abs(sy - cy) > deadzone * crop_h):
            begin = max(free_at, t - lead_sec)
            fx, fy = at(t + move_sec)
            keys.append([round(begin, 3), round(cx, 4), round(cy, 4)])  # hold until the move begins
            cx, cy = clamp(fx, crop_w / 2), clamp(fy, crop_h / 2)
            keys.append([round(begin + move_sec, 3), round(cx, 4), round(cy, 4)])
            free_at = begin + move_sec
    keys.sort(key=lambda k: k[0])
    out: list[list[float]] = []
    for k in keys:  # one key per instant
        if out and abs(out[-1][0] - k[0]) < 1e-6:
            out[-1] = k
        else:
            out.append(k)
    return out


def matte(path: Path, start: float, length: float, fps: float, width: int, height: int, dest: Path) -> Path:
    """A grey person matte (white = person) for a picture window, at the given size and frame rate. `path` must already
    be the window as it appears on screen (render_window output), so the matte lines up pixel for pixel."""
    from mediapipe.tasks.python import BaseOptions, vision
    import mediapipe as mp
    times, imgs = frames(path, start, length, fps, width)
    seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(vision_models.path("selfie_segmenter"))), running_mode=vision.RunningMode.VIDEO,
        output_confidence_masks=True))
    dest.parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{imgs[0].shape[0]}",
                            "-r", f"{fps:g}", "-i", "-", "-vf", f"scale={width}:{height}", "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p",
                            str(dest)], stdin=subprocess.PIPE)
    try:
        for t, rgb in zip(times, imgs):
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            m = seg.segment_for_video(img, int(round((t - start) * 1000))).confidence_masks[0].numpy_view().astype(np.float32)
            if m.ndim == 3:
                m = m[..., 0]
            # Firm up the edge a little: confidence 0.35 -> 0, 0.65 -> 1, smooth in between.
            a = np.clip((m - 0.35) / 0.3, 0, 1)
            enc.stdin.write((a * 255).astype(np.uint8).tobytes())
    finally:
        seg.close()
        enc.stdin.close()
        enc.wait()
    if enc.returncode:
        raise RuntimeError("matte encode failed")
    return dest


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["analyze", "reframe"])
    ap.add_argument("clip", type=Path)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--length", type=float)
    ap.add_argument("--aspect", default="9:16")
    a = ap.parse_args()
    w, h, dur = probe_size(a.clip)
    an = analyze(a.clip, a.start, a.length or (dur - a.start))
    if a.cmd == "analyze":
        faces = sum(1 for s in an["samples"] if s["faces"])
        hands = sum(1 for s in an["samples"] if s["hands"])
        print(json.dumps({"samples": len(an["samples"]), "with_face": faces, "with_hands": hands,
                          "person_area_mean": round(float(np.mean([s["person_area"] for s in an["samples"]] or [0])), 3)}, indent=2))
    else:
        aw, ah = (int(x) for x in a.aspect.split(":"))
        crop_w = min(1.0, (h * aw / ah) / w)
        crop_h = min(1.0, (w * ah / aw) / h)
        print(json.dumps(camera_keys(subject_centres(an), crop_w, crop_h)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
