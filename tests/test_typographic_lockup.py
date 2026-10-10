"""The typographic lockup (an opening sentence that builds word by word into a collage, key words cycling faces)
and the clean caption options, measured from rendered frames through the compiler, never assumed.

Needs Remotion (the project's node_modules); skipped where it is missing."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import compile_timeline as ct  # noqa: E402
import remotion_bridge as rb  # noqa: E402

S, FPS = 360, 30
pytestmark = pytest.mark.skipif(not rb.available()[0], reason="Remotion not available")


def plate(dest: Path, colour: str, seconds: float) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s={S}x{S}:r={FPS}:d={seconds}",
                    "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv444p", str(dest)], check=True)
    return dest


def frame(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(S, S, 3).astype(float)


def render(tmp: Path, graphic: dict, bg: str = "black", seconds: float = 3.0) -> Path:
    (tmp / "m").mkdir(exist_ok=True)
    plate(tmp / "m" / "bg.mp4", bg, seconds)
    (tmp / "assets.json").write_text(json.dumps({"assets": [{"asset_id": "bg", "local_path": "m/bg.mp4", "status": "approved"}]}))
    ir = {"ir_version": "3.0", "canvas": {"width": S, "height": S, "fps": FPS, "sample_rate": 48000}, "style": "documentary_general",
          "tracks": [{"id": "v", "kind": "video", "items": [{"id": "BG", "asset_id": "bg", "timeline_in": 0, "timeline_out": seconds}]},
                     {"id": "g", "kind": "graphic", "items": [{"id": "G", "timeline_in": 0, "timeline_out": seconds, **graphic}]}]}
    m = ct.compile_timeline(tmp, ir, Path("out.mp4"))
    assert m["status"] == "passed" and not m["unrendered"]
    return tmp / "out.mp4"


def lit(img: np.ndarray, region=None) -> int:
    """Text pixels on a black plate."""
    y0, y1, x0, x1 = region or (0, S, 0, S)
    return int((img[y0:y1, x0:x1].max(axis=2) > 128).sum())


def test_words_appear_when_spoken_and_stay(tmp_path):
    out = render(tmp_path, {"template": "typographic_lockup", "params": {"base": 0.12, "blocks": [
        {"anchor": "top-left", "color": "#ffffff", "words": [{"text": "first", "start": 0.0, "size": 1}, {"text": "second", "start": 1.0, "size": 1.4}]}]}})
    before, after, later = lit(frame(out, 0.6)), lit(frame(out, 1.4)), lit(frame(out, 2.6))
    assert before > 300                       # the first word is on screen
    assert after > before * 1.6               # the second appears once it is spoken ...
    assert abs(later - after) < 0.05 * after  # ... and stays


def test_a_cycling_key_word_never_moves_the_words_around_it(tmp_path):
    # The key word comes first; the words after it wrap to the rows below. If a wider face reflowed the block, those
    # rows would move. They must be identical while the key word cycles and after it settles.
    out = render(tmp_path, {"template": "typographic_lockup", "params": {"base": 0.11, "cycleSec": 0.9, "recycleSec": 5, "framesPerFace": 3, "blocks": [
        {"anchor": "top-left", "color": "#ffffff", "maxWidth": 0.55, "words": [
            {"text": "friends", "start": 0.0, "size": 1.3, "cycle": True}, {"text": "decide", "start": 0.0, "size": 1}, {"text": "everything", "start": 0.0, "size": 1}]}]}})
    rows = (int(S * 0.06 + 0.11 * S * 1.3 * 1.05), S)              # below the key word's row
    settled = frame(out, 1.6)[rows[0]:rows[1]]
    assert lit(settled) > 300
    cycling = [frame(out, t) for t in (0.12, 0.25, 0.42, 0.55, 0.72)]
    key_row = slice(0, rows[0])
    assert any(np.abs(f[key_row] - frame(out, 1.6)[key_row]).mean() > 1.0 for f in cycling)  # the key word does change faces
    for f in cycling:
        assert np.abs(f[rows[0]:rows[1]] - settled).mean() < 0.5, "the rows after the key word moved while it cycled"


def test_each_block_draws_in_its_own_colour(tmp_path):
    out = render(tmp_path, {"template": "typographic_lockup", "params": {"base": 0.12, "blocks": [
        {"anchor": "top-left", "color": "#ff2020", "words": [{"text": "warm", "start": 0.0, "size": 1.2}]},
        {"anchor": "bottom-right", "color": "#2040ff", "words": [{"text": "cool", "start": 0.0, "size": 1.2}]}]}})
    img = frame(out, 1.0)
    top, bottom = img[: S // 2, : S // 2], img[S // 2:, S // 2:]
    red = top[top.max(axis=2) > 128]
    blue = bottom[bottom.max(axis=2) > 128]
    assert len(red) > 200 and len(blue) > 200
    assert red[:, 0].mean() > red[:, 2].mean() + 80 and blue[:, 2].mean() > blue[:, 0].mean() + 80


def test_clean_captions_drop_the_outline(tmp_path):
    words = [{"text": "clean.", "start": 0.1, "end": 2.5}]
    base = {"words": words, "maxWords": 1, "position": "center", "fontScale": 1.4}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = render(tmp_path / "a", {"template": "kinetic_captions", "params": base}, bg="0x808080")
    b = render(tmp_path / "b", {"template": "kinetic_captions", "params": {**base, "outline": False, "lowercase": True, "stripPunctuation": True}}, bg="0x808080")
    # The outline is a ~1 px, 60 % black ring at this size: on a mid-grey plate it is the only thing darker than 80.
    # (Measured once: 132 such pixels with the outline, 0 without; the soft shadow never gets that dark.)
    dark = lambda img: int((img.max(axis=2) < 80).sum())  # noqa: E731
    fa, fb = frame(a, 1.0), frame(b, 1.0)
    assert int((fa.min(axis=2) > 200).sum()) > 300 and int((fb.min(axis=2) > 200).sum()) > 300  # both draw white words
    assert dark(fa) > 60 and dark(fb) < 10
