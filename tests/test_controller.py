import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTRL = ROOT / "scripts" / "controller.py"
SHOT = ROOT / "scripts" / "build_shotspec.py"

def run(tmp, *args):
    return subprocess.run([sys.executable, str(CTRL), "--project", str(tmp), *args], capture_output=True, text=True)

def test_init_and_block(tmp_path):
    r = run(tmp_path, "--init")
    assert r.returncode == 0
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["current_stage"] == "INTAKE"
    r = run(tmp_path)
    assert r.returncode == 1
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["stage_status"] == "blocked"
    assert state["last_successful_stage"] is None

def test_intake_advances(tmp_path):
    run(tmp_path, "--init")
    (tmp_path / "project.yaml").write_text("project_id: test\n", encoding="utf-8")
    (tmp_path / "brief.md").write_text("A short test brief.\n", encoding="utf-8")
    assert run(tmp_path).returncode == 0
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_successful_stage"] == "INTAKE"
    assert state["current_stage"] == "STYLE_LOCK"

def test_shotspec_builder_is_planning_only(tmp_path):
    (tmp_path / "timeline.json").write_text(json.dumps({"shots":[{"shot_id":"S1","narration":"A storm approaches.","start":0,"end":3,"required_actions":["storm approaches"]}]}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SHOT), "--project", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0
    data = json.loads((tmp_path / "shot_specs.json").read_text())
    assert data["status"] == "planning_only"
    assert data["shots"][0]["required_actions"] == ["storm approaches"]
    assert data["shots"][0]["status"] == "needs_asset_review"
