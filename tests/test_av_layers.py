"""av_layers on synthetic videos with known answers: which element answers which instrument, and the strategy.

- element_specific: a cyan square flashes on every kick and a magenta square on every hi-hat, over a busy grey background;
  the mapping must be kick -> cyan, hats -> magenta, and with the cyan taken out the rest must not follow the kick.
- whole_image: the whole frame flashes on every kick.
- none: flashes at random times.
Band splits of the mix are used (no Demucs) so the test is fast; the stem path is exercised by the real-clip runs."""
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from style_intel import av_layers  # noqa: E402

FPS, SR, DUR, W, H = 30, 22050, 12.0, 160, 120
BEAT = 0.5                                                        # 120 BPM: kicks on the beat, hats on the off-beat
KICKS = np.arange(0.5, DUR - 0.5, BEAT)
HATS = KICKS + BEAT / 2


def _audio(kicks, hats) -> np.ndarray:
    rng = np.random.default_rng(1); y = 0.003 * rng.standard_normal(int(DUR * SR))
    k = np.arange(int(0.12 * SR))
    for t in kicks:                                               # a low thump
        s = int(t * SR); y[s:s + len(k)] += 0.7 * np.sin(2 * np.pi * 55 * k / SR) * np.exp(-k / (0.03 * SR))
    for t in hats:                                                # a short bright noise burst
        s = int(t * SR); n = int(0.03 * SR); hp = rng.standard_normal(n); hp = np.diff(hp, prepend=0)
        y[s:s + n] += 0.25 * hp * np.exp(-np.arange(n) / (0.006 * SR))
    return y


def _video(tmp: Path, name: str, paint) -> Path:
    n = int(DUR * FPS); rng = np.random.default_rng(2)
    frames = np.zeros((n, H, W, 3), np.uint8)
    for i in range(n):
        f = frames[i]; f[:] = 25
        f[:, :] += rng.integers(0, 25, (H, W, 1)).astype(np.uint8)   # busy grey background, unrelated to the music
        paint(f, i)
    y = _audio(KICKS, HATS); wav = tmp / f"{name}.f32"; wav.write_bytes(y.astype("<f4").tobytes())
    out = tmp / f"{name}.mp4"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(wav), "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv444p",
                          "-c:a", "aac", "-shortest", str(out)], stdin=subprocess.PIPE)
    p.communicate(frames.tobytes()); assert p.returncode == 0
    return out


def _pulse(i: int, times: np.ndarray, lag: int = 1) -> float:
    """Brightness of a flash that starts `lag` frames after each event and decays over 3 frames."""
    d = i - (np.round(times * FPS).astype(int) + lag); d = d[(d >= 0) & (d < 3)]
    return float(max([1.0, 0.55, 0.25][k] for k in d)) if len(d) else 0.0


def test_elements_answer_their_instruments(tmp_path):
    def paint(f, i):
        k, h = _pulse(i, KICKS), _pulse(i, HATS)
        if k: f[10:50, 10:60] = (int(230 * k), int(230 * k), 0)          # cyan (BGR) on the kick
        if h: f[70:110, 100:150] = (int(230 * h), 0, int(230 * h))       # magenta on the hats
    r = av_layers.analyze(_video(tmp_path, "elements", paint), tmp_path / "o", use_stems=False)
    m = r["strategy"]["mapping"]
    assert m["kick"]["element"] == "cyan element", m
    assert m["hats"]["element"] == "magenta element", m
    assert r["strategy"]["strategy"] == "element_specific", r["strategy"]


def test_whole_image_follows_the_kick(tmp_path):
    def paint(f, i):
        k = _pulse(i, KICKS)
        if k: f[:] = np.clip(f.astype(int) + int(150 * k), 0, 255).astype(np.uint8)
    r = av_layers.analyze(_video(tmp_path, "whole", paint), tmp_path / "o", use_stems=False)
    assert r["strategy"]["strategy"] == "whole_image", r["strategy"]


def test_random_flashes_are_not_a_strategy(tmp_path):
    rnd = np.sort(np.random.default_rng(5).uniform(0.3, DUR - 0.3, len(KICKS)))
    def paint(f, i):
        k = _pulse(i, rnd)
        if k: f[10:50, 10:60] = (int(230 * k), int(230 * k), 0)
    r = av_layers.analyze(_video(tmp_path, "random", paint), tmp_path / "o", use_stems=False)
    assert r["strategy"]["strategy"] in ("none", "energy_only"), r["strategy"]
