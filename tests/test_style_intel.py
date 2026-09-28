"""Style Intelligence against synthetic videos whose answers are known in advance."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from style_intel import dna, profile  # noqa: E402

FPS = 30
SHOTS = [1.0, 1.5, 0.5, 1.0, 2.0, 1.0]  # cuts at 1.0, 2.5, 3.0, 4.0, 6.0 -- all on a 120 BPM beat grid
CUTS = [1.0, 2.5, 3.0, 4.0, 6.0]
WARM = ["0xE07020", "0xC04818", "0xF0A040", "0xB03010", "0xE08830", "0xD05820"]
COOL = ["0x2060D0", "0x1840A0", "0x40A0E0", "0x103070", "0x3080C0", "0x2050B0"]


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def cut_video(dest: Path, colours: list[str], click_offset: float) -> Path:
    """Solid-colour shots with a click track at 120 BPM, shifted by click_offset seconds."""
    inputs, labels = [], []
    for i, (c, d) in enumerate(zip(colours, SHOTS)):
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:size=320x180:rate={FPS}:duration={d}"]
        labels.append(f"[{i}:v]")
    total = sum(SHOTS)
    click = f"aevalsrc='0.8*sin(2*PI*1000*t)*lt(mod(t-{click_offset}+10,0.5),0.015)':s=22050:d={total}"
    inputs += ["-f", "lavfi", "-i", click]
    ffmpeg(*inputs, "-filter_complex", f"{''.join(labels)}concat=n={len(SHOTS)}:v=1:a=0,format=yuv420p[v]",
           "-map", "[v]", "-map", f"{len(SHOTS)}:a", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(dest))
    return dest


def push_in_video(dest: Path) -> Path:
    """One 3 s shot: a steady zoom into a real photograph (the repo's public-domain NASA portrait), in greyscale."""
    photo = Path(__file__).parents[1] / "templates/narrativeos-video-templates/media-library/processed/nasa_eileen_collins_001.jpg"
    ffmpeg("-loop", "1", "-i", str(photo), "-t", "3",
           "-vf", "scale=1280:-2,format=gray,zoompan=z='1+0.004*on':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=640x360:fps=30,format=yuv420p",
           "-frames:v", "90", "-c:v", "libx264", "-crf", "16", str(dest))
    return dest


def flash_video(dest: Path) -> Path:
    """4 s of mid-grey with white flash frames at 1.0 s and 2.5 s and a dip to black at 3.2-3.4 s."""
    lum = "if(between(N,30,31)+between(N,75,76),235,if(between(N,96,101),16,110))"
    ffmpeg("-f", "lavfi", "-i", "color=black:size=320x180:rate=30:duration=4",
           "-vf", f"format=yuv444p,geq=lum='{lum}':cb=128:cr=128,format=yuv420p", "-c:v", "libx264", "-crf", "16", str(dest))
    return dest


def gradual_video(dest: Path) -> Path:
    """Four 3 s shots joined by three 0.8 s transitions: a plain dissolve, a fade through white, a fade through black."""
    src = [f"color=c={c}:size=320x180:rate=30:duration=3" for c in ("0x806040", "0x305080", "0x607030", "0x804060")]
    inputs = [x for s_ in src for x in ("-f", "lavfi", "-i", s_)]
    chain = ("[0][1]xfade=transition=fade:duration=0.8:offset=2.2[a];"
             "[a][2]xfade=transition=fadewhite:duration=0.8:offset=4.4[b];"
             "[b][3]xfade=transition=fadeblack:duration=0.8:offset=6.6,format=yuv420p[v]")
    ffmpeg(*inputs, "-filter_complex", chain, "-map", "[v]", "-c:v", "libx264", "-crf", "16", str(dest))
    return dest


@pytest.fixture(scope="module")
def analysed(tmp_path_factory):
    d = tmp_path_factory.mktemp("style")
    videos = {
        "synced": cut_video(d / "synced.mp4", WARM, 0.0),
        "offbeat": cut_video(d / "offbeat.mp4", COOL, 0.25),
        "push": push_in_video(d / "push.mp4"),
        "flash": flash_video(d / "flash.mp4"),
        "gradual": gradual_video(d / "gradual.mp4"),
    }
    results = {}
    for k, v in videos.items():
        results[k] = dna.analyze(v, d / k, with_speech=False)
        results[k]["_out"] = d / k  # test-only: where shots.json and the contact sheet were written
    return results


def test_cuts_and_shot_lengths(analysed):
    shots = json.loads((analysed["synced"]["_out"] / "shots.json").read_text())
    assert shots["cuts_sec"] == pytest.approx(CUTS, abs=1 / FPS)
    assert (analysed["synced"]["_out"] / "shots_contact_sheet.jpg").is_file()
    ed = analysed["synced"]["editing"]
    assert ed["shot_count"] == len(SHOTS)
    assert ed["shot_duration_sec"]["median"] == pytest.approx(1.0, abs=0.05)
    assert ed["cuts_per_minute"] == pytest.approx(len(CUTS) / sum(SHOTS) * 60, rel=0.02)


def test_cuts_on_the_beat_vs_off_the_beat(analysed):
    on = analysed["synced"]["audio"]
    off = analysed["offbeat"]["audio"]
    assert on["tempo_bpm"] == pytest.approx(120, abs=3)
    assert on["cut_sync_to_beats"]["synced"] is True
    assert off["cut_sync_to_beats"]["synced"] is False


def test_warm_and_cool_tone(analysed):
    assert analysed["synced"]["visual"]["bands"]["tone"] == "warm"
    assert analysed["offbeat"]["visual"]["bands"]["tone"] == "cool"


def test_push_in_and_monochrome(analysed):
    look = analysed["push"]["visual"]
    assert look["camera_motion"]["dominant"] == "push_in"
    assert look["bands"]["colour"] == "monochrome"


def test_flashes_and_dip(analysed):
    ed = analysed["flash"]["editing"]
    assert ed["flash_frames_per_minute"] == pytest.approx(2 / 4 * 60, abs=0.1)
    assert ed["dips_to_black"] == 1


def test_unmeasured_traits_are_labelled_not_guessed(analysed):
    d = analysed["synced"]
    assert d["typography"]["status"] == "not_measured" and d["typography"]["reason"]
    assert d["speech"]["status"] == "not_measured"


def test_profile_maps_measurements_to_real_settings(analysed):
    prof = profile.build(analysed["flash"], "test_flash_style")
    assert set(prof["vfx"]["allowedTransitions"]) <= profile.known_transitions()
    assert "flash_cut" in prof["vfx"]["allowedTransitions"]
    assert "dip_to_black" in prof["vfx"]["allowedTransitions"]
    assert "grayscale(1)" in prof["grade"]["filter"]
    assert "typography" in prof["unmeasured"]
    fast = profile.build(analysed["synced"], "test_fast_style")
    assert fast["pacing"] == {"targetShotSec": pytest.approx(1.0, abs=0.05), "cutsPerMinute": pytest.approx(42.9, abs=1), "beatSync": True}
    assert fast["vfx"]["density"] == "bold"
    # Only hard cuts in the reference: nothing flashier may be switched on.
    assert fast["vfx"]["allowedTransitions"] == ["hard_cut"]


def test_profile_rejects_bad_ids(analysed):
    with pytest.raises(ValueError):
        profile.build(analysed["synced"], "Bad-Id")


def test_gradual_transitions_found_and_classified(analysed):
    ed = analysed["gradual"]["editing"]
    shots = json.loads((analysed["gradual"]["_out"] / "shots.json").read_text())
    assert ed["hard_cuts"] == 0
    assert shots["gradual_sec"] == pytest.approx([2.6, 4.8, 7.0], abs=0.25)  # transition centres
    assert shots["gradual_kinds"] == ["dissolve", "light", "dark"]


def test_profile_writes_loadable_typescript(analysed, tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "GENERATED", tmp_path)
    ts = profile.write_ts(profile.build(analysed["gradual"], "test_gradual_style"))
    text = ts.read_text()
    assert "export const style: StyleProfile" in text and '"id": "test_gradual_style"' in text
    index = (tmp_path / "index.ts").read_text()
    assert "import {style as s0} from './test_gradual_style';" in index
    allowed = profile.build(analysed["gradual"], "x")["vfx"]["allowedTransitions"]
    assert {"crossfade_soft", "light_leak_warm", "dip_to_black"} <= set(allowed)
