"""ffprobe/ffmpeg helpers shared by the analyzers."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _rate(r: str | None) -> float | None:
    if not r or r == "0/0":
        return None
    num, _, den = r.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: Path) -> dict:
    data = json.loads(run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
        "-of", "json", str(path),
    ]))
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError(f"{path} has no video stream")
    return {
        "duration_sec": float(data["format"]["duration"]),
        "fps": _rate(video.get("r_frame_rate")),
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "has_audio": audio is not None,
    }


def frame_at(path: Path, t: float, width: int | None = 480, crop: tuple[int, int] | None = None) -> np.ndarray:
    """One RGB frame at time t (seconds) as an HxWx3 uint8 array.

    width: scale to this width (None keeps native resolution).
    crop: (w, h) centre crop at native resolution, e.g. for grain measurement.
    ffmpeg returns a PNG, so the output size never has to be predicted.
    """
    filters = []
    if crop:
        filters.append(f"crop='min({crop[0]},iw)':'min({crop[1]},ih)'")
    if width:
        filters.append(f"scale={width}:-2")
    png = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1",
         "-vf", ",".join(filters) or "null", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, check=True,
    ).stdout
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR) if png else None
    if img is None:
        raise ValueError(f"no frame at {t:.3f}s")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def extract_audio(path: Path, dest: Path, sr: int = 22050) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), str(dest)], check=True)
    return dest
