"""Local vision models for frame awareness, kept outside the repo (~/NarrativeOS-Models, or NARRATIVEOS_MODELS).

    python scripts/vision_models.py fetch     # download any missing model, record its sha256
    python scripts/vision_models.py status    # what is present, verified, and where

All three are Google MediaPipe models published under Apache-2.0. A model is downloaded once; its sha256 is recorded
in models.json on first download and checked on every later use, so a changed file is refused, not silently used.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

MODELS = {
    "face_detector": {"file": "blaze_face_short_range.tflite", "license": "Apache-2.0",
                      "url": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"},
    "hand_landmarker": {"file": "hand_landmarker.task", "license": "Apache-2.0",
                        "url": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"},
    "selfie_segmenter": {"file": "selfie_segmenter.tflite", "license": "Apache-2.0",
                         "url": "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite"},
}


class ModelError(Exception):
    pass


def root() -> Path:
    return Path(os.environ.get("NARRATIVEOS_MODELS") or Path.home() / "NarrativeOS-Models").expanduser().resolve()


def _manifest() -> dict:
    p = root() / "models.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def path(name: str) -> Path:
    """The verified local file for a model, or ModelError saying how to get it."""
    spec = MODELS[name]
    p = root() / spec["file"]
    if not p.is_file():
        raise ModelError(f"vision model {name} is not downloaded; run: python scripts/vision_models.py fetch")
    want = (_manifest().get(name) or {}).get("sha256")
    if want and _sha(p) != want:
        raise ModelError(f"vision model {name} changed on disk (sha256 mismatch); delete it and fetch again")
    return p


def fetch() -> dict:
    root().mkdir(parents=True, exist_ok=True)
    manifest = _manifest()
    for name, spec in MODELS.items():
        p = root() / spec["file"]
        if not p.is_file():
            tmp = p.with_suffix(p.suffix + ".part")
            urllib.request.urlretrieve(spec["url"], tmp)
            tmp.replace(p)
        digest = _sha(p)
        known = (manifest.get(name) or {}).get("sha256")
        if known and known != digest:
            raise ModelError(f"{name}: downloaded file does not match the recorded sha256")
        manifest[name] = {**spec, "sha256": digest, "bytes": p.stat().st_size}
    (root() / "models.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def status() -> dict:
    out = {}
    for name in MODELS:
        try:
            p = path(name)
            out[name] = {"status": "ready", "file": str(p)}
        except ModelError as e:
            out[name] = {"status": "missing", "reason": str(e)}
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(json.dumps(fetch() if cmd == "fetch" else status(), indent=2))
