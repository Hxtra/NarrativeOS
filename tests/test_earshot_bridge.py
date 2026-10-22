"""earshot_bridge.py: it never runs the upload command, says clearly when Earshot is missing, keeps going past a failing job,
and (when Earshot is installed) runs a model-free job end to end."""
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts")]
import earshot_bridge as eb  # noqa: E402


def test_upload_command_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="llm_critique"):
        eb.run([{"id": "x", "op": "llm_critique", "args": ["a.wav"]}], tmp_path / "out.json")


def test_missing_install_says_where(tmp_path, monkeypatch):
    monkeypatch.setenv("EARSHOT_PY", str(tmp_path / "nowhere" / "python.exe"))
    b = importlib.reload(eb)
    with pytest.raises(SystemExit, match="not installed"):
        b.run([{"id": "x", "op": "measure", "args": ["a.wav"]}], tmp_path / "out.json")
    monkeypatch.delenv("EARSHOT_PY"); importlib.reload(eb)


@pytest.mark.skipif(not eb.EARSHOT_PY.is_file(), reason="Earshot is not installed on this machine")
def test_measure_runs_and_a_bad_job_does_not_stop_the_batch(tmp_path):
    t = np.arange(48000) / 48000
    sf.write(tmp_path / "tone.wav", (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 48000)
    res = eb.run([{"id": "missing", "op": "measure", "args": [str(tmp_path / "missing.wav")]},
                  {"id": "tone", "op": "measure", "args": [str(tmp_path / "tone.wav")]}], tmp_path / "out.json")
    assert [r["ok"] for r in res] == [False, True]
    assert json.loads((tmp_path / "out.json").read_text())[1]["result"]
