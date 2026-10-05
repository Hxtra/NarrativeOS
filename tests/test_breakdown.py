"""Effect breakdown against a synthetic edit whose every effect and sound is placed at a known time."""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from style_intel import breakdown  # noqa: E402

FPS, W, H, SR = 30, 640, 360, 22050
DURATION = 12.0
PHOTOS = Path(__file__).parents[1] / "templates/narrativeos-video-templates/media-library/processed"

# What the edit contains, in seconds (frame = round(t * FPS)).
CUT_1 = 2.0             # hard cut, shot A -> shot B
RGB_SPLIT = (3.0, 3.2)  # red +6 px, blue -6 px (12 px apart on 640 = 36 px on a 1080p frame); click at 3.0
WHIP = (3.9, 4.2)       # picture flies left with horizontal blur, cut back to A at 4.1; whoosh into 4.0
CUT_2 = 4.1
GLITCH = (6.0, 6.13)    # four frames of displaced bands inside shot A; impact at 6.0
HALFTONE = (7.0, 7.6)
LEAK = (8.5, 9.3)       # warm light from the left, peak at 8.9; riser climbing into it
HOLD = (10.0, 10.17)    # frame 300 held for 5 more frames while the shot pans
ZOOM = (11.0, 11.2)     # 6 frames at +5 %/frame, then a cut
SOUND_ONLY = 1.0       # a click with nothing on screen
EFFECT_WINDOWS = [RGB_SPLIT, WHIP, GLITCH, HALFTONE, LEAK, HOLD, ZOOM]


def _plate(name: str) -> np.ndarray:
    img = cv2.cvtColor(cv2.imread(str(PHOTOS / name)), cv2.COLOR_BGR2RGB)
    return cv2.resize(img, (1100, 700), interpolation=cv2.INTER_AREA)


def _view(plate: np.ndarray, x: float, scale: float = 1.0) -> np.ndarray:
    """A W x H window into the plate at horizontal offset x, optionally zoomed in about its centre."""
    cx, cy = 230 + x + W / 2, 170 + H / 2
    M = np.float32([[scale, 0, W / 2 - cx * scale], [0, scale, H / 2 - cy * scale]])
    return cv2.warpAffine(plate, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _halftone(rgb: np.ndarray, cell: int = 8) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    out = np.full((H, W, 3), 255, np.uint8)
    for y in range(cell // 2, H, cell):
        for x in range(cell // 2, W, cell):
            r = (1 - gray[y, x] / 255) * cell * 0.55
            if r > 0.5:
                cv2.circle(out, (x, y), int(round(r)), (0, 0, 0), -1, cv2.LINE_AA)
    return out


def frames() -> list[np.ndarray]:
    a, b = _plate("nasa_eileen_collins_001.jpg"), _plate("nasa_hubble_deep_field_001.jpg")
    f = lambda t: int(round(t * FPS))  # noqa: E731
    out = []
    for i in range(int(DURATION * FPS)):
        t = i / FPS
        plate = b if CUT_1 <= t < CUT_2 or t >= ZOOM[1] else a  # the zoom punches into a cut to the other photo
        x = 1.5 * i  # a slow pan everywhere, so holds have motion to stop
        img = _view(plate, x)
        if f(RGB_SPLIT[0]) <= i < f(RGB_SPLIT[1]):
            img = img.copy()
            img[..., 0] = np.roll(img[..., 0], 6, axis=1)
            img[..., 2] = np.roll(img[..., 2], -6, axis=1)
        if f(WHIP[0]) <= i < f(WHIP[1]):
            k = i - f(WHIP[0]) + 1
            img = cv2.blur(_view(plate, x + 45 * k), (41, 1))
        if f(GLITCH[0]) <= i < f(GLITCH[1]):
            img = img.copy()
            band = H // 8
            for j, dx in enumerate([0, 40, 0, -30, 0, 0, 50, 0]):
                img[j * band : (j + 1) * band] = np.roll(img[j * band : (j + 1) * band], dx, axis=1)
        if f(HALFTONE[0]) <= i < f(HALFTONE[1]):
            img = _halftone(img)
        if f(LEAK[0]) <= i < f(LEAK[1]):
            k = (i - f(LEAK[0])) / (f(LEAK[1]) - f(LEAK[0]))
            amp = np.sin(np.pi * k)
            ramp = np.clip(1 - np.linspace(0, 1.6, W), 0, 1)[None, :, None]
            glow = ramp * np.array([255, 150, 40])[None, None, :] * amp
            img = np.clip(255 - (255 - img.astype(np.float32)) * (255 - glow) / 255, 0, 255).astype(np.uint8)  # Screen blend
        if f(HOLD[0]) < i <= f(HOLD[0]) + 5:
            img = out[f(HOLD[0])]
        if f(ZOOM[0]) <= i < f(ZOOM[1]):
            img = _view(plate, x, 1.05 ** (i - f(ZOOM[0]) + 1))
        out.append(img)
    return out


def audio() -> np.ndarray:
    rng = np.random.default_rng(7)
    n = int(DURATION * SR)
    at = lambda t: int(t * SR)  # noqa: E731
    # A steady chord bed under everything, like the music an edit's effects sit on: sounds must be found OUT of it.
    tt_all = np.arange(n) / SR
    y = 0.08 * sum(np.sin(2 * np.pi * f * tt_all) for f in (220.0, 277.2, 329.6, 440.0)) / 4 + rng.normal(0, 0.0005, n)
    # click with no visual event: a sound-only moment
    y[at(SOUND_ONLY) : at(SOUND_ONLY) + 110] += rng.normal(0, 0.5, 110)
    # click: 5 ms broadband burst
    y[at(3.0) : at(3.0) + 110] += rng.normal(0, 0.5, 110)
    # whoosh: band-passed noise swelling over 0.7 s, peaking at 4.0
    w = rng.normal(0, 1, at(0.7))
    spec = np.fft.rfft(w)
    fr = np.fft.rfftfreq(len(w), 1 / SR)
    spec[(fr < 400) | (fr > 4000)] = 0
    w = np.fft.irfft(spec, len(w))
    env = np.concatenate([np.linspace(0, 1, at(0.45)) ** 2, np.linspace(1, 0, at(0.7) - at(0.45)) ** 2])
    y[at(3.55) : at(3.55) + len(w)] += 0.4 * w / np.abs(w).max() * env
    # impact: low boom with an instant attack
    tt = np.arange(at(1.2)) / SR
    y[at(6.0) : at(6.0) + len(tt)] += 0.8 * (np.sin(2 * np.pi * 55 * tt) + 0.5 * np.sin(2 * np.pi * 82 * tt)) * np.exp(-tt / 0.3)
    # riser: noise climbing 24 dB over 2.4 s into the leak's peak
    r = rng.normal(0, 1, at(2.4))
    y[at(6.5) : at(8.9)] += 0.3 * r * 10 ** ((np.linspace(-24, 0, len(r))) / 20)
    return np.clip(y, -1, 1)


def make_video(dest: Path) -> Path:
    wav = dest.with_suffix(".wav")
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((audio() * 32767).astype(np.int16).tobytes())
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                             "-i", str(wav), "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(dest)],
                            stdin=subprocess.PIPE)
    for img in frames():
        proc.stdin.write(np.ascontiguousarray(img).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return dest


def keyboard_video(dest: Path) -> Path:
    """A piano-keyboard-like periodic texture panning slowly: the trap that faked tears and halftones on real footage."""
    img = np.full((H, W * 2, 3), 245, np.uint8)
    for x in range(0, W * 2, 20):
        cv2.line(img, (x, 0), (x, H), (40, 40, 40), 2)
        if (x // 20) % 7 not in (2, 6):
            cv2.rectangle(img, (x + 13, 0), (x + 27, H // 2), (15, 15, 15), -1)
    _write([img[:, 2 * i : 2 * i + W].copy() for i in range(90)], dest)
    return dest


def slideshow_video(dest: Path) -> Path:
    """Three still photos, one second each: still shots, so no 'frame holds'."""
    a, b = _plate("nasa_eileen_collins_001.jpg"), _plate("nasa_hubble_deep_field_001.jpg")
    _write([_view(p, 0) for p in (a, b, a) for _ in range(FPS)], dest)
    return dest


def _write(imgs: list[np.ndarray], dest: Path) -> None:
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                             "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(dest)], stdin=subprocess.PIPE)
    for img in imgs:
        proc.stdin.write(np.ascontiguousarray(img).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    d = tmp_path_factory.mktemp("breakdown")
    return breakdown.analyze(make_video(d / "edit.mp4"), d / "out", with_speech=False), d / "out"


def events(res: dict, kind: str) -> list[dict]:
    return [e for m in res["moments"] for e in m["events"] if e["type"] == kind]


def moment_at(res: dict, t: float) -> dict:
    return min(res["moments"], key=lambda m: 0 if m["start"] - 0.05 <= t <= m["end"] + 0.05 else abs(m["time"] - t))


def overlaps(e: dict, window: tuple[float, float], slack: float = 0.1) -> bool:
    return e["start"] <= window[1] + slack and e["end"] >= window[0] - slack


@pytest.mark.parametrize("kind,window", [("rgb_split", RGB_SPLIT), ("whip_pan", WHIP), ("glitch_tear", GLITCH), ("halftone", HALFTONE),
                                         ("light_leak", LEAK), ("frame_hold", HOLD), ("zoom", ZOOM)])
def test_every_placed_effect_is_found_at_its_time(result, kind, window):
    res, _ = result
    found = [e for e in events(res, kind) if overlaps(e, window)]
    assert len(found) == 1, (kind, events(res, kind))
    assert found[0]["basis"] == breakdown.MEASUREMENTS[kind]["status"]


def test_measured_parameters_match_what_was_applied(result):
    res, _ = result
    ev = lambda k: events(res, k)[0]["evidence"]  # noqa: E731
    assert ev("rgb_split")["max_offset_px_at_1920"] == pytest.approx(36, abs=4)  # 12 px apart on a 640 frame
    assert ev("whip_pan")["direction"] == "left" and ev("whip_pan")["axis"] == "x"
    assert ev("zoom")["direction"] == "in" and ev("zoom")["total_scale"] == pytest.approx(1.05 ** 6, abs=0.03)
    assert ev("light_leak")["tone"] == "warm" and ev("light_leak")["brightest_side"] == "left"
    assert ev("frame_hold")["held_frames"] == 6


def test_nothing_is_reported_where_nothing_happened(result):
    res, _ = result
    for m in res["moments"]:
        for e in m["events"]:
            if e["type"] == "hard_cut":
                # The halftone section is a different picture, so it is cut in and out.
                assert any(abs(e["start"] - c) <= 1.5 / FPS for c in (CUT_1, CUT_2, HALFTONE[0], HALFTONE[1], ZOOM[1])), e
            else:
                assert any(overlaps(e, w) for w in EFFECT_WINDOWS), e
    cuts = [e["start"] for e in events(res, "hard_cut")]
    for c in (CUT_1, CUT_2, ZOOM[1]):
        assert any(abs(x - c) <= 1.5 / FPS for x in cuts), (c, cuts)


def test_sounds_are_found_and_classified_by_their_shape(result):
    res, _ = result
    sound = lambda t: moment_at(res, t)["sound"]  # noqa: E731
    assert sound(RGB_SPLIT[0])["sound_class"]["label"] == "click"
    assert sound(WHIP[0])["sound_class"]["label"] == "whoosh"
    assert sound(GLITCH[0])["sound_class"]["label"] == "impact"
    assert sound(LEAK[0] + 0.3)["riser_into_moment"]["rise_db"] >= 8
    assert sound(CUT_1)["onset"] is None  # no sound was placed on the first cut
    only = [m for m in res["moments"] if m.get("sound_only")]
    assert len(only) == 1 and abs(only[0]["time"] - SOUND_ONLY) < 0.1 and only[0]["sound"]["sound_class"]["label"] == "click"
    for m in res["moments"]:
        if m["sound"].get("onset"):
            assert m["sound"]["onset"]["basis"] == "MEASURED" and m["sound"]["sound_class"]["basis"] == "INFERRED"


def test_each_moment_maps_to_a_registered_recipe(result):
    res, _ = result
    expected = {RGB_SPLIT[0]: "rgb_split_hit", WHIP[0]: "whip_pan_left", GLITCH[0]: "digital_tear", HALFTONE[0]: "halftone_reveal",
                LEAK[0] + 0.3: "light_leak_warm", HOLD[0]: "stutter_cut", ZOOM[0]: "whip_zoom", CUT_1: "hard_cut"}
    for t, recipe in expected.items():
        assert moment_at(res, t)["suggestion"]["recipe"] == recipe, (t, moment_at(res, t)["suggestion"])
    known = breakdown.known_transitions()
    assert all(m["suggestion"]["recipe"] in known for m in res["moments"] if m["suggestion"]["recipe"])
    layer = next(l for l in moment_at(res, RGB_SPLIT[0])["suggestion"]["layers"] if l["kind"] == "rgb_split")  # noqa: E741
    assert layer["px"] == pytest.approx(36, abs=4)


def test_outputs_are_reviewable_and_honest(result):
    res, out = result
    assert (out / "breakdown.json").is_file() and "| time |" in (out / "breakdown.md").read_text(encoding="utf-8")
    for m in res["moments"]:
        assert m["review"] == "UNREVIEWED" and (out / m["strip"]).is_file()
    assert {"font_family", "speed_ramp", "sound_identity", "music_vs_sfx"} <= set(res["not_measured"])


def test_periodic_texture_is_not_a_glitch_or_halftone(tmp_path):
    res = breakdown.analyze(keyboard_video(tmp_path / "keys.mp4"), tmp_path / "out", strips=False, with_speech=False)
    kinds = {e["type"] for m in res["moments"] for e in m["events"]}
    assert not kinds & {"glitch_tear", "halftone", "whip_pan", "blur"}, res["moments"]


def test_still_shots_are_not_frame_holds(tmp_path):
    res = breakdown.analyze(slideshow_video(tmp_path / "stills.mp4"), tmp_path / "out", strips=False, with_speech=False)
    assert [e["type"] for m in res["moments"] for e in m["events"]] == ["hard_cut", "hard_cut"]


if __name__ == "__main__":  # python tests/test_breakdown.py <out.mp4>: write the fixture to look at
    print(make_video(Path(sys.argv[1])))
