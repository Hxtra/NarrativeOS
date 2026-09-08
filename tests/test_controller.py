import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTRL = ROOT / "scripts" / "controller.py"

def run(tmp, *args):
    return subprocess.run([sys.executable, str(CTRL), "--project", str(tmp), *args], capture_output=True, text=True)

def test_init_and_block(tmp_path):
    r = run(tmp_path, "--init")
    assert r.returncode == 0
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["current_stage"] == "INTAKE"
    # INTAKE is blocked until a real project.yaml exists.
    r = run(tmp_path)
    assert r.returncode == 1
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["stage_status"] == "blocked"
    assert state["last_successful_stage"] is None

def test_intake_advances(tmp_path):
    run(tmp_path, "--init")
    (tmp_path / "project.yaml").write_text("project_id: test\n", encoding="utf-8")
    assert run(tmp_path).returncode == 0
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_successful_stage"] == "INTAKE"
    assert state["current_stage"] == "STYLE_LOCK"
