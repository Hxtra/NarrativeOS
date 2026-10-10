"""Reference-to-render comparison: synthetic edits whose differences are known by construction."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from style_intel import compare as cmp  # noqa: E402

PATTERNS = ["testsrc2", "smptehdbars", "testsrc", "pal75bars"]


def edit(dest: Path, lengths: list[float], tints: list[str] | None = None) -> Path:
    """Shots of different test patterns (so every join is a real cut), each optionally tinted."""
    args, chains = [], []
    for i, L in enumerate(lengths):
        args += ["-f", "lavfi", "-i", f"{PATTERNS[i % len(PATTERNS)]}=s=320x320:r=30:d={L}"]
        tint = (tints or [])[i] if tints else ""
        chains.append(f"[{i}:v]scale=320:320,format=rgb24{(',' + tint) if tint else ''},format=yuv420p,setsar=1[v{i}]")
    graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(len(lengths))) + f"concat=n={len(lengths)}:v=1:a=0[out]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", graph, "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)], check=True)
    return dest


WARM = "colorchannelmixer=rr=1.25:gg=1.0:bb=0.7"
COOL = "colorchannelmixer=rr=0.7:gg=1.0:bb=1.25"


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    d = tmp_path_factory.mktemp("cmp")
    vids = {
        "ref": edit(d / "ref.mp4", [1.5] * 8, [WARM] * 8),
        "slow": edit(d / "slow.mp4", [3.0] * 4, [WARM] * 4),               # same look, half the cuts
        "jumpy": edit(d / "jumpy.mp4", [1.5] * 8, [WARM, COOL] * 4),         # same rhythm, the look jumps every shot
    }
    return {k: cmp.measure(v, d / k, with_text=False, with_speech=False) for k, v in vids.items()}


def score(rep: dict, metric: str) -> float:
    return next(m["score"] for m in rep["metrics"] if m["metric"] == metric)


def test_a_video_compared_with_itself_scores_one(measured):
    rep = cmp.compare(measured["ref"], measured["ref"])
    assert rep["overall"] == 1.0
    assert all(m["score"] == 1.0 for m in rep["metrics"] if m["score"] is not None)


def test_a_slower_rhythm_lowers_editing_and_leaves_colour_alone(measured):
    rep = cmp.compare(measured["ref"], measured["slow"])
    assert measured["ref"]["cuts"] and len(measured["slow"]["cuts"]) < len(measured["ref"]["cuts"])
    assert score(rep, "median shot length") < 0.2                    # 1.5 s -> 3 s is a 100 % change
    assert rep["groups"]["editing"] < 0.6
    assert score(rep, "overall colour (Lab mean)") > 0.85
    assert any(m["metric"] == "median shot length" for m in rep["largest_differences"])


def test_a_look_that_jumps_between_shots_is_caught(measured):
    rep = cmp.compare(measured["ref"], measured["jumpy"])
    assert score(rep, "median shot length") > 0.9                    # the rhythm is the same
    spread = score(rep, "shot-to-shot spread of blue-yellow (b)")
    assert spread < 0.5, spread                                      # but the look jumps every cut
    assert "per-shot grade" in next(m for m in rep["metrics"] if m["metric"] == "shot-to-shot spread of blue-yellow (b)")["advice"]


def test_unread_text_is_not_measured_and_left_out_of_the_score(measured):
    rep = cmp.compare(measured["ref"], measured["slow"])
    text = [m for m in rep["metrics"] if m["group"] == "text"]
    assert text and all(m["status"] == "NOT_MEASURED" and m["score"] is None for m in text)
    assert rep["groups"]["text"] is None and rep["overall"] is not None
