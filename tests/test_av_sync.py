"""av_sync on synthetic videos with known answers: a picture that flashes one frame after every click is found synced with a
+1 frame lag, in the right region; the same flashes at random times are not."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from style_intel import av_sync  # noqa: E402

FPS, SR, DUR = 30, 22050, 8.0


def _make(tmp: Path, name: str, flash_frames: list[int], click_times: list[float]) -> Path:
    n = int(DUR * FPS); W, H = 160, 120
    frames = np.full((n, H, W), 30, np.uint8)
    for f in flash_frames:                                        # the flash lives in the bottom-left quarter and decays
        for k, a in enumerate((200, 120, 60)):
            if f + k < n:
                frames[f + k, H // 2:, :W // 2] = np.maximum(frames[f + k, H // 2:, :W // 2], 30 + a)
    rng = np.random.default_rng(3)
    frames = np.clip(frames.astype(int) + rng.integers(-6, 7, frames.shape), 0, 255).astype(np.uint8)   # sensor noise
    y = 0.01 * rng.standard_normal(int(DUR * SR))
    for t in click_times:                                        # a short low thump per click
        s = int(t * SR); k = np.arange(int(0.08 * SR)); y[s:s + len(k)] += 0.8 * np.sin(2 * np.pi * 70 * k / SR) * np.exp(-k / (0.02 * SR))
    wav = tmp / f"{name}.f32"; wav.write_bytes(y.astype("<f4").tobytes())
    out = tmp / f"{name}.mp4"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(wav), "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-shortest", str(out)], stdin=subprocess.PIPE)
    p.communicate(frames.tobytes()); assert p.returncode == 0
    return out


@pytest.fixture(scope="module")
def clicks():
    rng = np.random.default_rng(7)
    return [t for t in sorted(set(np.round(np.cumsum(rng.uniform(0.35, 0.8, 14)) + 0.3, 2))) if t < DUR - 0.3]


def test_flashes_one_frame_after_clicks_are_synced(tmp_path, clicks):
    flashes = [int(round(t * FPS)) + 1 for t in clicks if t < DUR - 0.2]
    r = av_sync.analyze(_make(tmp_path, "synced", flashes, clicks), tmp_path / "out")
    x = r["lags"]["bass->flash"]
    assert x["lag_frames"] in (1, 2) and x["p"] <= 0.01 and x["corr"] > x["chance_95"]
    assert r["hits"]["with_picture_event_pm2f"] > r["hits"]["chance_95"]
    assert r["regions_synced"] and r["regions_synced"][0]["cell"][0] >= 3 and r["regions_synced"][0]["cell"][1] <= 1   # bottom-left


def test_random_flashes_are_not_synced(tmp_path, clicks):
    rng = np.random.default_rng(11)
    flashes = sorted(rng.choice(np.arange(5, int(DUR * FPS) - 5), len(clicks), replace=False).tolist())
    r = av_sync.analyze(_make(tmp_path, "random", flashes, clicks), tmp_path / "out")
    x = r["lags"]["bass->flash"]
    assert not (x["p"] <= 0.01 and x["corr"] > x["chance_95"])
