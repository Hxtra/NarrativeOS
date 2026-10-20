"""sound_mix.py on synthetic audio with known answers: the music is levelled 24 dB under the speaking voice and comes up in the
gaps, an effect's peak lands where the plan says, and dead air inside the film is reported."""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import sound_mix as sm  # noqa: E402

SR = 48000


def _voice(dur=12.0):
    """Speech-like bursts: 2 s 'lines' of a modulated tone, 1 s gaps."""
    t = np.arange(int(dur * SR)) / SR
    y = 0.3 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))
    y *= ((t % 3.0) < 2.0)
    return y


def _write(tmp, name, y):
    sf.write(tmp / name, y.astype(np.float32), SR); return name


def _plan(tmp, music_gain=None, voice_start=0.5):
    rng = np.random.default_rng(1)
    _write(tmp, "vo.wav", _voice())
    _write(tmp, "music.wav", 0.2 * rng.standard_normal(14 * SR))
    hit = np.zeros(SR); hit[int(0.3 * SR):int(0.32 * SR)] = 0.9            # a click whose peak is 0.3 s into the file
    _write(tmp, "hit.wav", hit)
    return {"duration": 13.0, "sr": SR, "voice": {"file": "vo.wav", "start": voice_start},
            "music": [{"file": "music.wav", "start": 0.0, "gain": music_gain or [[0, 1], [13, 1]]}],
            "sfx": [{"file": "hit.wav", "t": 6.0, "peak": 0.3, "rel_db": 6, "fade": [0, 0]}], "out": "mix.wav"}


def test_music_sits_24_db_under_the_voice_and_rises_in_gaps(tmp_path):
    rep = sm.mix(_plan(tmp_path), tmp_path)
    assert abs(rep["music_under_voice_db"] - (-24.0)) < 1.0
    assert 1.5 < rep["music_in_gaps_db"] - rep["music_under_voice_db"] < 4.5    # the measured gap lift is about 3.5 dB
    assert rep["ok"] and rep["dead_air_windows"] == 0


def test_effect_peak_lands_on_its_time(tmp_path):
    plan = _plan(tmp_path); plan["music"] = []; plan["voice"]["start"] = 20.0   # nothing but the click inside the film
    sm.mix(plan, tmp_path)
    y, _ = sf.read(tmp_path / "mix.wav")
    assert abs(np.argmax(np.abs(y[:, 0])) / SR - 6.0) < 0.01


def test_dead_air_is_reported(tmp_path):
    plan = _plan(tmp_path, music_gain=[[0, 1], [4.0, 1], [4.01, 0], [9.0, 0], [9.01, 1], [13, 1]], voice_start=20.0)
    plan["sfx"] = []
    rep = sm.mix(plan, tmp_path)
    assert not rep["ok"] and rep["dead_air_windows"] > 30


def test_cli_writes_report(tmp_path):
    import subprocess
    (tmp_path / "plan.json").write_text(json.dumps(_plan(tmp_path)), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sound_mix.py"), str(tmp_path / "plan.json")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "plan_report.json").read_text())["ok"]
