"""Multi-track compiler against synthetic media whose colours and tones are known, so every claim about the render
(crossfade, dip, blend, ducking, SFX placement, J/L audio, captions, timing) is checked by measurement."""
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import compile_timeline as ct  # noqa: E402

W, H, FPS, SR = 320, 180, 24, 48000


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def clip(dest: Path, colour: str, tone: float | None, seconds: float) -> Path:
    args = ["-f", "lavfi", "-i", f"color=c={colour}:s={W}x{H}:r={FPS}:d={seconds}"]
    if tone:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate={SR}:duration={seconds}", "-shortest", "-c:a", "aac"]
    ff(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest))
    return dest


def tone(dest: Path, freq: float, seconds: float, amp: float = 0.5) -> Path:
    t = np.arange(int(seconds * SR)) / SR
    y = (amp * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(y.tobytes())
    return dest


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("proj")
    m = d / "media"
    m.mkdir()
    clip(m / "red.mp4", "0xC00000", 440, 6)
    clip(m / "blue.mp4", "0x0000C0", 880, 6)
    clip(m / "grey.mp4", "0x808080", None, 3)
    ff("-f", "lavfi", "-i", f"color=c=0x00A000:s={W}x{H}:d=1", "-frames:v", "1", str(m / "green.png"))
    tone(m / "vo.wav", 300, 6.0)
    tone(m / "music.wav", 1000, 9.0)
    tone(m / "beep.wav", 2000, 0.3)
    assets = [{"asset_id": k, "local_path": f"media/{f}", "status": "approved"} for k, f in
              (("red", "red.mp4"), ("blue", "blue.mp4"), ("grey", "grey.mp4"), ("green", "green.png"),
               ("vo", "vo.wav"), ("music", "music.wav"), ("beep", "beep.wav"))]
    (d / "assets.json").write_text(json.dumps({"assets": assets}), encoding="utf-8")
    return d


def base_ir(**extra):
    ir = {"ir_version": "3.0", "canvas": {"width": W, "height": H, "fps": FPS, "sample_rate": SR},
          "tracks": [
              {"id": "v_main", "kind": "video", "items": [
                  {"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 3.25, "source_in": 0,
                   "audio": {"native": True, "gain_db": -6, "native_in": 0, "native_out": 3.75}},          # L-cut
                  {"id": "B", "asset_id": "blue", "timeline_in": 2.75, "timeline_out": 6.0, "source_in": 1.0,
                   "transition_in": {"type": "crossfade", "duration": 0.5}},
                  {"id": "C", "asset_id": "green", "timeline_in": 6.0, "timeline_out": 8.0,
                   "transition_in": {"type": "dip_black", "duration": 0.8}}]},
              {"id": "v_fx", "kind": "overlay", "items": [
                  {"id": "G", "asset_id": "grey", "timeline_in": 4.0, "timeline_out": 5.0, "blend": "screen", "opacity": 1.0}]},
              {"id": "a_vo", "kind": "audio", "role": "narration", "items": [
                  {"id": "VO", "asset_id": "vo", "timeline_in": 0.5, "timeline_out": 6.0}]},
              {"id": "a_music", "kind": "audio", "role": "music", "duck_under": "a_vo", "items": [
                  {"id": "M", "asset_id": "music", "timeline_in": 0, "timeline_out": 8.0, "gain_db": -6}]},
              {"id": "a_sfx", "kind": "audio", "role": "sfx", "items": [
                  {"id": "BEEP", "asset_id": "beep", "timeline_in": 7.0, "timeline_out": 7.3}]},
              {"id": "cc", "kind": "caption", "items": [
                  {"id": "CAP", "timeline_in": 6.5, "timeline_out": 7.5, "text": "HELLO WORLD"}]}],
          "mix": {"loudnorm": None}}
    ir.update(extra)
    return ir


@pytest.fixture(scope="module")
def rendered(media):
    m = ct.compile_timeline(media, base_ir(), Path("renders/out.mp4"))
    return media, m


def frame(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(float)


def audio(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(float) / 32768


def band_db(y: np.ndarray, t0: float, t1: float, freq: float) -> float:
    seg = y[int(t0 * SR):int(t1 * SR)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    return float(20 * np.log10(spec[(f > freq - 20) & (f < freq + 20)].max() / len(seg) + 1e-12))


def test_one_ffmpeg_pass_and_probe_agrees(rendered):
    proj, m = rendered
    assert m["status"] == "passed" and m["verification"]["passed"]
    assert m["duration"] == pytest.approx(8.0) and m["has_audio"]
    assert m["renderer"].startswith("compile_timeline.py")
    assert (proj / m["compile_dir"] / "filtergraph.txt").is_file() and (proj / m["compile_dir"] / "command.json").is_file()
    assert "concat" not in (proj / m["compile_dir"] / "filtergraph.txt").read_text()  # no stitching


def test_crossfade_is_a_real_overlap(rendered):
    proj, m = rendered
    out = proj / m["output_path"]
    r_before, mid, b_after = frame(out, 2.6), frame(out, 3.0), frame(out, 3.4)
    assert r_before[..., 0].mean() > 150 and r_before[..., 2].mean() < 30   # still red
    assert 50 < mid[..., 0].mean() < 140 and 50 < mid[..., 2].mean() < 140  # both, mid-fade
    assert b_after[..., 2].mean() > 150 and b_after[..., 0].mean() < 30     # blue


def test_dip_and_screen_blend(rendered):
    proj, m = rendered
    out = proj / m["output_path"]
    assert frame(out, 6.0).mean() < 25                    # through black at the dip
    assert frame(out, 7.0)[20:60, :, 1].mean() > 120       # green after it (above the caption)
    blue, screened = frame(out, 3.6), frame(out, 4.5)
    # Screen of mid-grey (128) over blue (192): R,G rise from ~0 to ~128; B rises towards 255 but never falls.
    assert screened[..., 0].mean() > blue[..., 0].mean() + 80 and screened[..., 2].mean() >= blue[..., 2].mean() - 5


def test_captions_are_burned_in_at_their_time(rendered):
    proj, m = rendered
    out = proj / m["output_path"]
    def white(f):
        return (f[int(H * 0.6):, :, :].min(axis=2) > 220).sum()
    assert white(frame(out, 7.0)) > 50 and white(frame(out, 6.3)) == 0


def test_audio_buses_ducking_sfx_and_l_cut(rendered):
    proj, m = rendered
    y = audio(proj / m["output_path"])
    music_under_vo = band_db(y, 1.0, 5.0, 1000)
    music_alone = band_db(y, 6.5, 6.95, 1000)
    assert music_alone - music_under_vo >= 6               # ducked under narration
    assert band_db(y, 1.0, 5.0, 300) > band_db(y, 7.5, 8.0, 300) + 30   # narration only where placed
    assert band_db(y, 7.05, 7.25, 2000) > band_db(y, 5.0, 6.5, 2000) + 30  # beep exactly at 7.0-7.3
    # L-cut: A's 440 Hz sound runs to 3.75 s, past its picture (3.25 s), and stops there.
    assert band_db(y, 3.4, 3.7, 440) > band_db(y, 4.0, 5.0, 440) + 30


def test_validation_fails_closed(media, tmp_path):
    def errs(ir, release=False):
        return " ".join(ct.validate(ir, media, release)["errors"])
    ir = base_ir()
    ir["tracks"][0]["items"][1].pop("transition_in")
    assert "unintended overlap" in errs(ir)
    ir = base_ir()
    ir["tracks"][0]["items"][1]["source_in"] = 5.0          # B needs 5.0 + 3.25 s of a 6 s clip
    assert "not enough handle" in errs(ir)
    ir = base_ir()
    ir["tracks"][0]["items"][0]["audio"]["native_out"] = 7.0  # L-cut window past the end of the red clip
    assert "native audio" in errs(ir)
    ir = base_ir()
    ir["tracks"][5]["items"].append({"id": "CAP2", "timeline_in": 7.0, "timeline_out": 8.0, "text": "x"})
    assert "overlap" in errs(ir)
    ir = base_ir()
    ir["tracks"][1]["items"][0]["blend"] = "dodge"
    assert "blend must be" in errs(ir)
    ir = base_ir()
    ir["tracks"][3]["duck_under"] = "nope"
    assert "duck_under" in errs(ir)
    assets = json.loads((media / "assets.json").read_text())
    outside = tmp_path / "elsewhere.png"
    ff("-f", "lavfi", "-i", f"color=c=red:s={W}x{H}:d=1", "-frames:v", "1", str(outside))
    ir = base_ir(assets=[{"asset_id": "red", "local_path": str(outside), "status": "approved"}])
    assert "outside the project" in errs(ir)
    sim = base_ir(assets=[{**next(a for a in assets["assets"] if a["asset_id"] == "red"), "status": "simulation_approved"}])
    assert not errs(sim) and "simulation_approved" in errs(sim, release=True)
    with pytest.raises(ct.CompileError):
        bad = base_ir()
        bad["tracks"][0]["items"][1].pop("transition_in")
        ct.compile_timeline(media, bad, Path("renders/never.mp4"))
    assert not (media / "renders" / "never.mp4").exists()


def test_same_timeline_renders_the_same_frames(media):
    a = ct.compile_timeline(media, base_ir(), Path("renders/r1.mp4"), preview=True)
    b = ct.compile_timeline(media, base_ir(), Path("renders/r2.mp4"), preview=True)
    assert a["timeline_sha256"] == b["timeline_sha256"] and a["filtergraph_sha256"] == b["filtergraph_sha256"]
    md5 = [subprocess.run(["ffmpeg", "-v", "error", "-i", str(media / x), "-map", "0:v", "-f", "framemd5", "-"], capture_output=True, text=True, check=True).stdout
           for x in ("renders/r1.mp4", "renders/r2.mp4")]
    assert md5[0] == md5[1]
    assert a["canvas"]["width"] == W // 2  # preview is half size


def test_shot_timeline_converts_transitions_motion_and_lists_what_it_cannot_render(media):
    tl = {"output": {"width": W, "height": H, "fps": FPS},
          "shots": [{"shot_id": "S1", "asset_id": "red", "start": 0, "end": 3, "source_start": 0, "motion": "slow_zoom_in"},
                    {"shot_id": "S2", "asset_id": "blue", "start": 3, "end": 5, "source_start": 1.0, "transition": "crossfade"},
                    {"shot_id": "S3", "asset_id": "green", "start": 5, "end": 7}],
          "markers": [{"event_id": "ED0007", "type": "TRANSITION", "start": 5.0,
                       "transition": {"left_shot_id": "S2", "right_shot_id": "S3", "recipe": "glitch_cut"}}]}
    ir = ct.from_shot_timeline(tl, media, narration="media/vo.wav", music="music")
    items = {it["id"]: it for it in ir["tracks"][0]["items"]}
    assert items["S1"]["motion"]["kind"] == "push_in"
    assert items["S2"]["transition_in"]["type"] == "crossfade" and items["S2"]["timeline_in"] == pytest.approx(2.75)
    assert items["S1"]["timeline_out"] == pytest.approx(3.25)
    assert ir["compile"]["unrendered"][0]["recipe"] == "glitch_cut" and "TransitionStack" in ir["compile"]["unrendered"][0]["reason"]
    assert [t["id"] for t in ir["tracks"]] == ["v_main", "a_narration", "a_music"] and ir["tracks"][2]["duck_under"] == "a_narration"
    m = ct.compile_timeline(media, ir, Path("renders/converted.mp4"), preview=True)
    assert m["status"] == "passed" and m["unrendered"][0]["recipe"] == "glitch_cut"


def test_render_ffmpeg_no_longer_stitches(media):
    tl = {"output": {"width": W, "height": H, "fps": FPS},
          "shots": [{"shot_id": "S1", "asset_id": "red", "start": 0, "end": 2, "status": "approved"},
                    {"shot_id": "S2", "asset_id": "green", "start": 2, "end": 4, "status": "approved", "motion": "slow_zoom_in"}]}
    (media / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_ffmpeg.py"), "--project", str(media), "--audio", "media/vo.wav",
                        "--output", "renders/legacy.mp4"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = json.loads((media / "renders" / "render_manifest.json").read_text())
    assert m["renderer"].startswith("compile_timeline.py") and m["has_audio"] and m["duration"] == pytest.approx(4.0)


def test_a_late_only_sound_still_gives_full_length_audio(media):
    """Regression: the only sound is a clip's own audio starting at 3 s. adelay shifts timestamps rather than
    writing silence, so without a silent bed the audio stream started at 3 s and was 4 s long (caught by verify())."""
    ir = {"ir_version": "3.0", "canvas": {"width": W, "height": H, "fps": FPS, "sample_rate": SR},
          "tracks": [{"id": "v", "kind": "video", "items": [
              {"id": "G", "asset_id": "green", "timeline_in": 0, "timeline_out": 3.0},
              {"id": "R", "asset_id": "red", "timeline_in": 3.0, "timeline_out": 5.0, "audio": {"native": True}}]}]}
    m = ct.compile_timeline(media, ir, Path("renders/late.mp4"), preview=True)
    assert m["verification"]["passed"]
    y = audio(media / m["output_path"])
    assert len(y) / SR == pytest.approx(5.0, abs=0.05)
    assert band_db(y, 0.5, 2.5, 440) < band_db(y, 3.5, 4.5, 440) - 30  # silence first, then the clip's tone


def test_ir_examples_match_the_published_schema(media):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schemas" / "timeline_ir_v3.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(base_ir(), schema)
    tl = {"output": {"width": W, "height": H, "fps": FPS},
          "shots": [{"shot_id": "S1", "asset_id": "red", "start": 0, "end": 2}, {"shot_id": "S2", "asset_id": "blue", "start": 2, "end": 4, "source_start": 1, "transition": "crossfade"}]}
    jsonschema.validate(ct.from_shot_timeline(tl, media, narration="media/vo.wav"), schema)
