"""Full-frame-rate motion analysis against a synthetic film with every answer known, including the traps found on real films:
animation inside a shot must not be read as a transition, and pictures jumping a few frames apart are stepped animation."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from style_intel import motion  # noqa: E402

FPS, W, H = 24, 480, 270
RNG = np.random.default_rng(3)


def texture(seed: int, w: int = 1400, h: int = 800) -> np.ndarray:
    """A detailed picture (blurred noise + shapes) so tracking has features."""
    r = np.random.default_rng(seed)
    img = cv2.GaussianBlur((r.random((h, w, 3)) * 255).astype(np.uint8), (0, 0), 3)
    for _ in range(60):
        c = tuple(int(x) for x in r.integers(0, 255, 3))
        cv2.circle(img, (int(r.integers(0, w)), int(r.integers(0, h))), int(r.integers(10, 60)), c, -1)
    return img


def crop_zoom(img: np.ndarray, z: float) -> np.ndarray:
    h, w = img.shape[:2]
    cw, ch = int(w / z * 0.6), int(h / z * 0.6)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return cv2.resize(img[y0:y0 + ch, x0:x0 + cw], (W, H), interpolation=cv2.INTER_AREA)


A, B, C = texture(1), texture(2), texture(4)
# timeline (frames): shot A pushes in at constant speed 0-71; hard cut at 72 to B (locked, a dot animated on twos) until 143;
# dissolve B->C over 144-155; C locked 156-215, with stepped jumps at 180, 183, 186 (a pattern changing every 3 frames)
CUT, DIS0, DIS1, STEP = 72, 144, 156, (180, 183, 186)


def frame(i: int) -> np.ndarray:
    if i < CUT:
        return crop_zoom(A, 1 + 0.2 * i / (CUT - 1))
    if i < DIS0:
        f = crop_zoom(B, 1.0).copy()
        k = (i - CUT) // 2 * 2                      # the dot moves on twos
        cv2.circle(f, (60 + 5 * k, 200), 18, (255, 255, 255), -1)
        return f
    if i < DIS1:
        a = (i - DIS0 + 1) / (DIS1 - DIS0 + 1)
        return cv2.addWeighted(crop_zoom(B, 1.0), 1 - a, crop_zoom(C, 1.0), a, 0)
    f = crop_zoom(C, 1.0).copy()
    jumps = sum(i >= s for s in STEP)
    if jumps:
        cv2.rectangle(f, (0, 0), (W, H), (0, 0, 0), -1)
        r = np.random.default_rng(100 + jumps)
        for _ in range(40):
            cv2.circle(f, (int(r.integers(0, W)), int(r.integers(0, H))), int(r.integers(10, 40)), (200, 200, 255), -1)
    return f


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    d = tmp_path_factory.mktemp("motion")
    path = d / "synthetic.mp4"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(216):
        vw.write(frame(i))
    vw.release()
    return motion.analyze(path, d / "out")


def near(t: dict, f: int, tol: int = 2) -> bool:
    return abs(t["frame"] - f) <= tol


def test_hard_cut_found(result):
    assert any(t["kind"] == "hard_cut" and near(t, CUT) for t in result["transitions"])


def test_dissolve_found_with_length(result):
    d = [t for t in result["transitions"] if t["kind"] == "dissolve"]
    assert len(d) == 1 and abs(d[0]["frame"] - DIS0) <= 3 and 6 <= d[0]["frames"] <= 16


def test_stepped_jumps_are_not_a_montage(result):
    cuts_in_steps = [t for t in result["transitions"] if STEP[0] - 1 <= t["frame"] <= STEP[-1] + 1]
    assert len(cuts_in_steps) <= 1
    assert any(abs(s["t"] * FPS - STEP[0]) <= 2 for s in result["stepped_animation"])


def test_constant_speed_push_in(result):
    shot = next(s for s in result["shots"] if s["start"] < 0.1)
    cam = shot["camera"]
    assert cam["kind"] == "push_in" and 1.12 < cam["zoom"] < 1.3
    assert cam["easing"] == "linear"


def test_element_animated_on_twos(result):
    shot = next(s for s in result["shots"] if abs(s["start"] * FPS - CUT) <= 2)
    assert shot["camera"]["kind"] == "locked"
    assert shot["animation"]["drawing_rate"] == "twos"
