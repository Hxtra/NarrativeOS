"""On-screen text against a synthetic edit whose every text line, animation and text effect is placed at a known frame."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
from style_intel import breakdown, typography  # noqa: E402
from style_intel.media import probe  # noqa: E402
from test_breakdown import _plate, _view  # noqa: E402

pytest.importorskip("rapidocr")

FPS, W, H = 30, 640, 360
DURATION = 10.0
FONT = cv2.FONT_HERSHEY_DUPLEX

TYPE_ON = ("WELCOME HOME", 0.5, 2.6)      # one character every 3 frames from 0.5 s (10 chars/s), cut out at 2.6 s
FADE = ("THE EXPLORATION", 3.0, 5.0)      # orange; fades in over 3.0-3.5 s and out over 4.5-5.0 s
SLIDE = ("BERGEN NORWAY", 5.5, 7.4)       # lower third sliding in from the left over 5.5-5.9 s, cut out at 7.4 s
GLITCH = ("SIGNAL LOST", 8.0, 9.6)        # RGB split and band tear on the TEXT ONLY at 9.0-9.2 s
GLITCH_FX = (9.0, 9.2)
PERSISTENT = "COPYRIGHT 2026"            # small, bottom right, the whole video


def _text_layer(text: str, scale: float, thick: int, org: tuple[int, int], colour=(255, 255, 255)) -> tuple[np.ndarray, np.ndarray]:
    layer = np.zeros((H, W, 3), np.uint8)
    cv2.putText(layer, text, org, FONT, scale, colour, thick, cv2.LINE_AA)
    alpha = (cv2.cvtColor(layer, cv2.COLOR_RGB2GRAY) > 0).astype(np.float32)
    return layer, cv2.GaussianBlur(alpha, (3, 3), 0)


def _centred(text: str, scale: float, thick: int, y: int) -> tuple[int, int]:
    (tw, _), _ = cv2.getTextSize(text, FONT, scale, thick)
    return (W - tw) // 2, y


def _over(img: np.ndarray, layer: np.ndarray, alpha: np.ndarray, opacity: float = 1.0) -> np.ndarray:
    a = (alpha * opacity)[..., None]
    return (img * (1 - a) + layer * a).astype(np.uint8)


def frames() -> list[np.ndarray]:
    plate = _plate("nasa_hubble_deep_field_001.jpg")
    out = []
    for i in range(int(DURATION * FPS)):
        t = i / FPS
        img = (_view(plate, 1.5 * i) * 0.45).astype(np.uint8)  # darkened moving background so the text reads
        lay, al = _text_layer(PERSISTENT, 0.6, 1, (W - 175, H - 14))
        img = _over(img, lay, al)
        text, t0, t1 = TYPE_ON
        if t0 <= t < t1:
            n = min(len(text), int((i - round(t0 * FPS)) / 3) + 1)
            org = _centred(text, 1.5, 3, 170)  # anchored as the full line, so letters appear in place
            lay, al = _text_layer(text[:n], 1.5, 3, org)
            img = _over(img, lay, al)
        text, t0, t1 = FADE
        if t0 <= t < t1:
            op = min(1.0, (t - t0) / 0.5, (t1 - t) / 0.5)
            lay, al = _text_layer(text, 1.3, 3, _centred(text, 1.3, 3, 190), colour=(255, 170, 0))
            img = _over(img, lay, al, op)
        text, t0, t1 = SLIDE
        if t0 <= t < t1:
            k = min(1.0, (t - t0) / 0.4)
            x = int(-330 + (40 + 330) * (1 - (1 - k) ** 3))
            lay, al = _text_layer(text, 1.0, 2, (x, 300))
            img = _over(img, lay, al)
        text, t0, t1 = GLITCH
        if t0 <= t < t1:
            lay, al = _text_layer(text, 1.6, 3, _centred(text, 1.6, 3, 180))
            if GLITCH_FX[0] <= t < GLITCH_FX[1]:
                lay = lay.copy()
                lay[..., 0] = np.roll(lay[..., 0], 7, axis=1)
                lay[..., 2] = np.roll(lay[..., 2], -7, axis=1)
                al = np.maximum.reduce([np.roll(al, 7, axis=1), al, np.roll(al, -7, axis=1)])
                if t < GLITCH_FX[0] + 0.14:  # tear: two bands of the title jump sideways
                    for (a, b), dx in (((140, 160), 30), ((170, 185), -25)):
                        lay[a:b] = np.roll(lay[a:b], dx, axis=1)
                        al[a:b] = np.roll(al[a:b], dx, axis=1)
            img = _over(img, lay, al)
        out.append(img)
    return out


def make_video(dest: Path) -> Path:
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                             "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(dest)], stdin=subprocess.PIPE)
    for img in frames():
        proc.stdin.write(np.ascontiguousarray(img).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return dest


@pytest.fixture(scope="module")
def typo(tmp_path_factory):
    v = make_video(tmp_path_factory.mktemp("typo") / "text.mp4")
    return typography.analyze(v, probe(v)), v


def line(res: dict, text: str) -> dict:
    found = [ln for ln in res["lines"] if typography.similar(ln["text"], text) >= 0.8]
    assert len(found) == 1, (text, [ln["text"] for ln in res["lines"]])
    return found[0]


def test_every_line_is_read_and_timed(typo):
    res, _ = typo
    assert res["status"] == "MEASURED"
    for text, t0, t1 in (TYPE_ON, FADE, SLIDE, GLITCH):
        ln = line(res, text)
        # A fading or typing line is detected once it is legible, so starts may lag; ends of cuts are frame-exact.
        assert t0 - 1 / FPS <= ln["start"] <= t0 + 0.5, (text, ln["start"])
        assert t1 - 0.5 <= ln["end"] <= t1 + 1 / FPS, (text, ln["end"])
    assert line(res, TYPE_ON[0])["end"] == pytest.approx(TYPE_ON[2], abs=1.5 / FPS)
    assert line(res, SLIDE[0])["end"] == pytest.approx(SLIDE[2], abs=1.5 / FPS)


def test_position_size_colour(typo):
    res, _ = typo
    assert line(res, TYPE_ON[0])["region"] == "middle_center"
    assert line(res, SLIDE[0])["region"] == "bottom_left"
    cop = line(res, PERSISTENT)
    assert cop["region"] == "bottom_right" and cop["persistent"]
    r, g, b = (int(line(res, FADE[0])["colour"][i : i + 2], 16) for i in (1, 3, 5))
    assert r > 200 and 120 < g < 210 and b < 80  # orange
    assert all(int(line(res, TYPE_ON[0])["colour"][i : i + 2], 16) > 200 for i in (1, 3, 5))  # white
    assert line(res, TYPE_ON[0])["uppercase"]


def test_animations_in_and_out(typo):
    res, _ = typo
    t = line(res, TYPE_ON[0])
    assert "type_on" in t["in"]["kinds"] and t["in"]["evidence"]["chars_per_sec"] == pytest.approx(10, abs=4)
    assert t["out"]["kinds"] == ["cut"]
    f = line(res, FADE[0])
    assert "fade" in f["in"]["kinds"] and "fade" in f["out"]["kinds"]
    s = line(res, SLIDE[0])
    assert "slide" in s["in"]["kinds"] and s["in"]["evidence"]["slide_direction"] == "right"
    assert s["out"]["kinds"] == ["cut"]


def test_effects_on_the_text_not_the_frame(typo):
    res, _ = typo
    fx = {f["type"]: f for f in line(res, GLITCH[0])["effects"]}
    assert "rgb_split" in fx and GLITCH_FX[0] - 0.05 <= fx["rgb_split"]["peak"] <= GLITCH_FX[1] + 0.05
    for text in (TYPE_ON[0], FADE[0], SLIDE[0]):
        assert not line(res, text)["effects"], text


def test_breakdown_reports_text_moments(typo, tmp_path):
    _, video = typo
    res = breakdown.analyze(video, tmp_path / "out", strips=False, with_speech=False)
    ins = [e for m in res["moments"] for e in m["events"] if e["type"] == "text_in"]
    assert any(typography.similar(e["evidence"]["text"], SLIDE[0]) >= 0.8 and "slide" in e["evidence"]["animation"] for e in ins)
    assert "typography" not in res["not_measured"] and "font_family" in res["not_measured"]
    assert "## On-screen text" in (tmp_path / "out" / "breakdown.md").read_text(encoding="utf-8")
