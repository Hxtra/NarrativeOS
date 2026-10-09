"""Phase 1 of 'graphics into the final cut': retiming (constant speed and exact ramps), grading and LUTs, and the
Remotion segments (graphics over transparency, recipe transitions between real shots, sound cues), all measured
from rendered frames and samples, never assumed."""
import json
import struct
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import compile_timeline as ct  # noqa: E402

W, H, FPS, SR = 320, 180, 30, 48000


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def time_ramp_clip(dest: Path, seconds: float) -> Path:
    """Brightness encodes source time: luma = t / seconds * 255, so any frame tells which source moment it shows."""
    ff("-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={seconds},format=gray,geq=lum='T/{seconds}*255'",
       "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv444p", dest)
    return dest


def colour_clip(dest: Path, colour: str, seconds: float) -> Path:
    ff("-f", "lavfi", "-i", f"color=c={colour}:s={W}x{H}:r={FPS}:d={seconds}", "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv444p", dest)
    return dest


def frame(path: Path, t: float, fmt: str = "gray") -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", fmt, "-"],
                         capture_output=True, check=True).stdout
    ch = 3 if fmt == "rgb24" else 1
    w, h = (W, H) if len(raw) == W * H * ch else (W // 2, H // 2)
    return np.frombuffer(raw, np.uint8).reshape(h, w, ch).astype(float)


def project(tmp: Path, assets: dict[str, str]) -> Path:
    (tmp / "assets.json").write_text(json.dumps({"assets": [{"asset_id": k, "local_path": v, "status": "approved"} for k, v in assets.items()]}))
    return tmp


def timeline(*tracks, **extra) -> dict:
    return {"ir_version": "3.0", "canvas": {"width": W, "height": H, "fps": FPS, "sample_rate": SR}, "tracks": list(tracks), **extra}


def compile_(p: Path, ir: dict, name="out.mp4") -> tuple[Path, dict]:
    m = ct.compile_timeline(p, ir, Path(name))
    return p / name, m


# ----------------------------------------------------------------------------------------------- retiming
def test_constant_speed_shows_the_right_source_moment(tmp_path):
    (tmp_path / "m").mkdir()
    time_ramp_clip(tmp_path / "m" / "ramp.mp4", 4)
    p = project(tmp_path, {"r": "m/ramp.mp4"})
    ir = timeline({"id": "v", "kind": "video", "items": [{"id": "A", "asset_id": "r", "timeline_in": 0, "timeline_out": 1.5, "speed": 2.0}]})
    out, _ = compile_(p, ir)
    # Output 1.0 s at 2x shows source 2.0 s: half brightness.
    assert frame(out, 1.0).mean() == pytest.approx(2.0 / 4 * 255, abs=8)
    assert frame(out, 0.25).mean() == pytest.approx(0.5 / 4 * 255, abs=8)


def test_speed_ramp_follows_its_exact_integral(tmp_path):
    (tmp_path / "m").mkdir()
    time_ramp_clip(tmp_path / "m" / "ramp.mp4", 4)
    p = project(tmp_path, {"r": "m/ramp.mp4"})
    item = {"id": "A", "asset_id": "r", "timeline_in": 0, "timeline_out": 1.5,
            "speed_ramp": [{"t": 0, "speed": 1}, {"t": 0.5, "speed": 1}, {"t": 1, "speed": 3}]}
    assert ct.source_at(item, 1.5, 1.5) == pytest.approx(0.75 + 0.75 * 2)  # 1x for 0.75 s, then 1x->3x (mean 2x) for 0.75 s
    out, _ = compile_(p, timeline({"id": "v", "kind": "video", "items": [item]}))
    for t in (0.5, 1.0, 1.3):
        want = ct.source_at(item, t, 1.5) / 4 * 255
        assert frame(out, t).mean() == pytest.approx(want, abs=8), t


def test_retiming_is_validated(tmp_path):
    (tmp_path / "m").mkdir()
    time_ramp_clip(tmp_path / "m" / "ramp.mp4", 2)
    p = project(tmp_path, {"r": "m/ramp.mp4"})

    def errors(**kw):
        it = {"id": "A", "asset_id": "r", "timeline_in": 0, "timeline_out": 1.0, **kw}
        return " | ".join(ct.validate(timeline({"id": "v", "kind": "video", "items": [it]}), p)["errors"])

    assert "speed must be within" in errors(speed=20)
    assert "speed_ramp must be points" in errors(speed_ramp=[{"t": 0.2, "speed": 1}, {"t": 1, "speed": 2}])
    assert "use speed or speed_ramp" in errors(speed=2, speed_ramp=[{"t": 0, "speed": 1}, {"t": 1, "speed": 2}])
    assert "the asset is 2.000 s" in errors(speed=3)  # 1 s at 3x needs 3 s of source
    assert "can't follow a speed ramp" in errors(speed_ramp=[{"t": 0, "speed": 1}, {"t": 1, "speed": 2}], audio={"native": True})
    assert errors(speed=1.5, motion_blur={"frames": 3}, stabilize=True) == ""


# ----------------------------------------------------------------------------------------------- grade
def test_grade_and_lut_are_applied_to_the_picture_only(tmp_path):
    (tmp_path / "m").mkdir()
    colour_clip(tmp_path / "m" / "red.mp4", "0xC02020", 1)
    # A 2x2x2 LUT that swaps red and blue (R index varies fastest in .cube files).
    rows = [f"{b} {g} {r}" for b in (0, 1) for g in (0, 1) for r in (0, 1)]
    (tmp_path / "m" / "swap.cube").write_text("LUT_3D_SIZE 2\n" + "\n".join(rows) + "\n")
    p = project(tmp_path, {"red": "m/red.mp4", "swap": "m/swap.cube"})
    shot = {"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 1}
    plain, _ = compile_(p, timeline({"id": "v", "kind": "video", "items": [shot]}), "plain.mp4")
    lut, _ = compile_(p, timeline({"id": "v", "kind": "video", "items": [shot]}, grade={"lut": "swap"}), "lut.mp4")
    grey, _ = compile_(p, timeline({"id": "v", "kind": "video", "items": [shot]}, grade={"saturation": 0}), "grey.mp4")
    r0, g0, b0 = frame(plain, 0.5, "rgb24").reshape(-1, 3).mean(0)
    r1, g1, b1 = frame(lut, 0.5, "rgb24").reshape(-1, 3).mean(0)
    r2, g2, b2 = frame(grey, 0.5, "rgb24").reshape(-1, 3).mean(0)
    assert r0 > 150 and b0 < 60
    assert b1 == pytest.approx(r0, abs=12) and r1 == pytest.approx(b0, abs=12)  # red and blue swapped by the LUT
    assert max(r2, g2, b2) - min(r2, g2, b2) < 8  # saturation 0: neutral grey
    # An item can opt out of the timeline grade.
    off, _ = compile_(p, timeline({"id": "v", "kind": "video", "items": [{**shot, "grade": None}]}, grade={"lut": "swap"}), "off.mp4")
    assert frame(off, 0.5, "rgb24").reshape(-1, 3).mean(0)[0] > 150
    bad = ct.validate(timeline({"id": "v", "kind": "video", "items": [shot]}, grade={"contrast": 9, "lut": "red"}), p)["errors"]
    assert any("contrast must be within" in e for e in bad) and any("must be an existing .cube" in e for e in bad)


# ----------------------------------------------------------------------------------------------- Remotion segments
rb = pytest.importorskip("remotion_bridge")
needs_remotion = pytest.mark.skipif(not rb.available()[0], reason=f"Remotion not available: {rb.available()[1]}")


def beep(dest: Path, seconds: float = 0.4, freq: float = 1000) -> Path:
    t = np.arange(int(seconds * SR)) / SR
    y = (0.6 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(y.tobytes())
    return dest


def rms_at(path: Path, t: float, length: float = 0.1) -> float:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-ac", "1", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(float) / 32768
    return float(np.sqrt((a ** 2).mean())) if a.size else 0.0


@needs_remotion
def test_graphics_and_recipe_transitions_render_into_the_final_cut(tmp_path, monkeypatch):
    (tmp_path / "m").mkdir()
    colour_clip(tmp_path / "m" / "red.mp4", "0xB01010", 3)
    colour_clip(tmp_path / "m" / "blue.mp4", "0x1010B0", 3)
    lib = tmp_path / "sfx"
    lib.mkdir()
    beep(lib / "shutter.wav")
    (lib / "sfx_catalog.json").write_text(json.dumps({"sounds": [{"id": "s1", "cue": "shutter", "path": "shutter.wav", "status": "approved"}]}))
    monkeypatch.setenv("NARRATIVEOS_SFX_LIBRARY", str(lib))
    p = project(tmp_path, {"red": "m/red.mp4", "blue": "m/blue.mp4"})
    ir = timeline(
        {"id": "v", "kind": "video", "items": [
            {"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 1.5},
            {"id": "B", "asset_id": "blue", "timeline_in": 1.5, "timeline_out": 3.0, "transition_in": {"type": "recipe", "recipe": "flash_cut"}}]},
        {"id": "g", "kind": "graphic", "items": [
            {"id": "LT", "template": "speaker_lower_third", "timeline_in": 0.1, "timeline_out": 1.3,
             "params": {"name": "Test Speaker", "role": "Measured, not assumed", "isReturning": False}}]},
        style="documentary_general")
    plain_ir = json.loads(json.dumps(ir))
    plain_ir["tracks"] = [plain_ir["tracks"][0]]
    plain_ir["tracks"][0]["items"][1].pop("transition_in")
    plain, _ = compile_(p, plain_ir, "plain.mp4")
    out, m = compile_(p, ir)
    assert m["status"] == "passed" and {s["kind"] for s in m["segments"]} == {"graphic", "transition"}
    # The flash recipe whitens the cut; the straight cut does not.
    assert frame(out, 1.5).mean() > frame(plain, 1.5).mean() + 60
    # Away from the window the picture is untouched.
    assert abs(frame(out, 2.7).mean() - frame(plain, 2.7).mean()) < 4
    # The lower third draws light text in the lower-left of the frame while it is on screen (at 320x180 it is a few
    # pixels tall, so count text pixels rather than averaging), and nothing is drawn there once it has gone.
    lower = (slice(H // 2, H), slice(0, W // 2))

    def text_pixels(t):
        return int((frame(out, t)[lower] - frame(plain, t)[lower] > 60).sum())
    assert text_pixels(1.0) > 150
    assert text_pixels(2.7) == 0
    # The recipe's shutter cue was resolved from the SFX library and sits on the cut.
    assert [c["cue"] for c in m["sfx_cues"]] == ["shutter"] and not m["unresolved_sfx"]
    assert rms_at(out, 1.5) > 10 * max(rms_at(out, 0.5), 1e-4)
    # Nothing changed: every segment comes from the cache.
    _, again = compile_(p, ir, "again.mp4")
    assert all(s["cached"] for s in again["segments"])


@needs_remotion
def test_unknown_templates_recipes_and_unsupported_canvas_shapes_are_refused(tmp_path):
    (tmp_path / "m").mkdir()
    colour_clip(tmp_path / "m" / "red.mp4", "red", 2)
    p = project(tmp_path, {"red": "m/red.mp4"})
    ir = timeline({"id": "v", "kind": "video", "items": [
        {"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 1},
        {"id": "B", "asset_id": "red", "timeline_in": 1, "timeline_out": 2, "transition_in": {"type": "recipe", "recipe": "no_such_recipe"}}]},
        {"id": "g", "kind": "graphic", "items": [{"id": "G", "template": "no_such_template", "timeline_in": 0, "timeline_out": 1}]})
    errors = " | ".join(ct.validate(ir, p)["errors"])
    assert "unknown transition recipe 'no_such_recipe'" in errors and "unknown template 'no_such_template'" in errors
    ir["canvas"].update(width=240, height=180)  # 4:3: no design shape
    assert "need a 16:9, 9:16, 1:1, 4:5 canvas" in " | ".join(ct.validate(ir, p)["errors"])
    vertical = timeline({"id": "v", "kind": "video", "items": [{"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 1}]},
                        {"id": "g", "kind": "graphic", "items": [{"id": "T", "template": "title_card", "timeline_in": 0, "timeline_out": 1},
                                                                 {"id": "K", "template": "kinetic_captions", "timeline_in": 0, "timeline_out": 1,
                                                                  "params": {"words": [{"text": "hi", "start": 0, "end": 0.5}]}}]})
    vertical["canvas"].update(width=180, height=320, platform="reels")
    errs = ct.validate(vertical, p)["errors"]
    assert errs == ["T: title_card is laid out for 16:9, not 9:16"], errs  # the caption template works vertically
    vertical["canvas"]["platform"] = "myspace"
    assert any("canvas platform must be one of" in e for e in ct.validate(vertical, p)["errors"])
    ir = timeline({"id": "v", "kind": "video", "items": [
        {"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 0.2},
        {"id": "B", "asset_id": "red", "timeline_in": 0.2, "timeline_out": 2, "transition_in": {"type": "recipe", "recipe": "glitch_reveal"}}]})
    assert "needs 0.47 s of A" in " | ".join(ct.validate(ir, p)["errors"])
