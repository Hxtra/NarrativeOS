"""Department analysis against synthetic sound placed at known times over a music bed that would fool simpler detectors."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from style_intel import departments as dep  # noqa: E402

SR = dep.SR
DUR = 14.0
BOOMS = [2.0, 7.0, 11.5]
PINGS = [(3.0, 1760.0), (8.5, 1568.0)]   # A6, G6, ringing 0.5 s
TICKS = [4.2, 9.6]                       # 15 ms clicks at 6 kHz
WHOOSH = 5.5                             # 0.4 s noise swell, 2-10 kHz
RISER = (12.2, 600.0, 3000.0, 1.0)       # start, from Hz, to Hz, length


def tone(f, length, decay=None):
    n = int(length * SR)
    x = np.sin(2 * np.pi * f * np.arange(n) / SR)
    return x * (np.exp(-np.arange(n) / (decay * SR)) if decay else 1.0)


def add(y, t, x, gain):
    i = int(t * SR)
    y[i:i + len(x)] += gain * x[:len(y) - i]


def bed(rng):
    """A music-like bed: sustained C-major chord tones, plus a short E5 note repeating every 0.28 s (like a ticking cue)."""
    y = np.zeros(int(DUR * SR))
    for f in (261.6, 329.6, 392.0, 523.3):
        y += 0.05 * tone(f, DUR)
    note = tone(659.3, 0.12, decay=0.05)
    for t in np.arange(0.1, DUR - 0.2, 0.28):
        add(y, t, note, 0.08)
    return y + 0.002 * rng.standard_normal(len(y))


@pytest.fixture(scope="module")
def mix():
    rng = np.random.default_rng(7)
    y = bed(rng)
    for t in BOOMS:
        add(y, t, tone(45, 0.5, decay=0.15), 0.9)
    for t, f in PINGS:
        add(y, t, tone(f, 0.6, decay=0.25), 0.3)
    for t in TICKS:
        add(y, t, tone(6000, 0.015), 0.4)
    n = int(0.4 * SR)
    from scipy.signal import butter, sosfilt
    noise = sosfilt(butter(4, [2000, 10000], btype="band", fs=SR, output="sos"), rng.standard_normal(n))
    add(y, WHOOSH, noise * np.hanning(n), 0.6)
    t0, f0, f1, ln = RISER
    k = np.arange(int(ln * SR)) / SR
    add(y, t0, np.sin(2 * np.pi * (f0 * ln / np.log(f1 / f0)) * ((f1 / f0) ** (k / ln) - 1)), 0.15)
    return y


@pytest.fixture(scope="module")
def events(mix):
    return dep.sound_events(mix)


def times(events, fam):
    return [e["t"] for e in events if e["family"] == fam]


def near(found, want, tol=0.12):
    return [any(abs(f - w) <= tol for f in found) for w in want]


def test_booms_found(events):
    assert all(near(times(events, "boom"), BOOMS))
    assert len(times(events, "boom")) == len(BOOMS)


def test_pings_found_with_pitch_and_bed_notes_ignored(events):
    pings = [e for e in events if e["family"] == "ping"]
    assert all(near([p["t"] for p in pings], [t for t, _ in PINGS]))
    assert sorted(p["pitch"]["note"] for p in pings) == ["A6", "G6"]
    # the bed's repeating E5 note is not reported as a sound effect
    assert not any(e["pitch"]["note"].startswith("E5") for e in events if "pitch" in e)


def test_ticks_found(events):
    assert all(near(times(events, "tick"), TICKS))


def test_whoosh_found(events):
    assert all(near(times(events, "whoosh"), [WHOOSH], tol=0.25))


def test_riser_found(events):
    found = times(events, "riser")
    assert len(found) == 1 and RISER[0] - 0.1 <= found[0] <= RISER[0] + RISER[3]


def test_sync_ranks_sounds_on_picture_changes():
    fps, n = 30.0, 420
    change = np.full(n, 1.0)
    for t in (2.0, 5.0, 9.0):
        change[int(t * fps) - 3:int(t * fps) + 4] = 20.0
    ev = [{"t": 2.0, "family": "boom"}, {"t": 5.02, "family": "boom"}, {"t": 9.0, "family": "boom"},
          {"t": 1.1, "family": "tick"}, {"t": 6.3, "family": "tick"}, {"t": 12.0, "family": "tick"}]
    fam = dep.sync(ev, change, fps)
    assert fam["boom"]["on_picture_change"] == 3 and fam["tick"]["on_picture_change"] == 0
    assert fam["boom"]["median_rank"] > fam["tick"]["median_rank"]


def test_picture_change_sees_a_card_arriving_on_a_moving_background(tmp_path):
    """The before/after measure must rank a card's arrival above a slowly drifting background. (A fast-moving background
    swamps it: MEASURED with a 0.4 rad/frame drift.)"""
    path = tmp_path / "card.mp4"
    fps, w, h = 30, 320, 180
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    xs = np.arange(w)
    for i in range(120):
        img = np.tile((127 + 60 * np.sin(xs / 40 + i * 0.05)).astype(np.uint8), (h, 1))  # slow drift, like a silk background
        frame = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if i >= 60:
            cv2.rectangle(frame, (100, 60), (220, 120), (255, 255, 255), -1)
        vw.write(frame)
    vw.release()
    change, got_fps = dep.picture_change(path)
    assert abs(int(np.argmax(change)) - 60) <= 9


def test_note_and_key_and_tuning():
    assert dep.note_of(440.0)["note"] == "A4" and dep.note_of(1760.0)["note"] == "A6"
    rng = np.random.default_rng(1)
    key = dep.music_key(bed(rng))
    assert key["key"] in ("C major", "A minor")
    pings = [{"pitch": dep.note_of(f)} for f in (1760.0, 1568.0, 1318.5)]   # A, G, E: all in C major
    assert dep.tuning(pings, {"tonic": 0, "mode": "major"})["in_key"] == "3/3"


def test_sound_groups_need_three_uses():
    ev = [{"t": t, "family": "ping", "pitch": dep.note_of(1760.0)} for t in (1.0, 2.0, 3.0)]
    ev += [{"t": 4.0, "family": "ping", "pitch": dep.note_of(1568.0)}]
    assert dep.sound_groups(ev) == [{"family": "ping", "note": "A6", "times": [1.0, 2.0, 3.0]}]
