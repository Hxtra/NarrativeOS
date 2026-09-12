"""
Tests for timeline-editor/server/timeline_api_server.py

These tests run against a real copy of scripts/simulate_documentary.py
output, not synthetic fixtures, so a schema drift in the simulation
script will break these tests rather than being silently masked.

Run from repo root:
    pip install -r timeline-editor/requirements.txt -r timeline-editor/requirements-dev.txt
    pytest timeline-editor/tests/ -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
SIMULATE_SCRIPT = REPO_ROOT / "scripts" / "simulate_documentary.py"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("NARRATIVEOS_PROJECT_ROOT", str(root))
    return root


@pytest.fixture()
def simulated_project(project_root):
    """
    Run the REAL simulate_documentary.py script to produce a project.
    This is the same script that ships in scripts/, invoked the same way
    a Hermes agent or developer would invoke it.
    """
    project_dir = project_root / "sim"
    result = subprocess.run(
        [sys.executable, str(SIMULATE_SCRIPT), "--project", str(project_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"simulate_documentary.py failed:\n{result.stdout}\n{result.stderr}"
    assert (project_dir / "timeline.json").is_file()
    (project_dir / "state.json").write_text(
        json.dumps({"current_stage": "EDITORIAL_QA", "project_status": "in_progress"}) + "\n",
        encoding="utf-8",
    )
    return project_dir


@pytest.fixture()
def client(project_root):
    # Import after NARRATIVEOS_PROJECT_ROOT is set by the project_root fixture
    import importlib
    import timeline_api_server as mod
    importlib.reload(mod)
    return TestClient(mod.app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "ffmpeg_available" in body
        assert "controller_script_found" in body


class TestProjectLoading:
    def test_missing_project_returns_404(self, client):
        r = client.get("/api/project/does-not-exist")
        assert r.status_code == 404

    def test_real_simulation_project_loads(self, client, simulated_project):
        project_id = simulated_project.name
        r = client.get(f"/api/project/{project_id}")
        assert r.status_code == 200
        body = r.json()

        assert body["artifacts"]["timeline"]["present"] is True
        assert body["artifacts"]["approved_assets"]["present"] is True

    def test_assets_json_correctly_reported_absent(self, client, simulated_project):
        """
        scripts/simulate_documentary.py never writes assets.json (only
        controller.py --init does, as an empty stub). The API must report
        this as present=False, not fabricate an empty {"assets": []}.
        """
        project_id = simulated_project.name
        r = client.get(f"/api/project/{project_id}")
        body = r.json()
        assert body["artifacts"]["assets"]["present"] is False
        assert body["artifacts"]["assets"]["data"] is None

    def test_events_jsonl_absent_for_simulation(self, client, simulated_project):
        """
        simulate_documentary.py calls stage scripts directly, bypassing
        controller.py's run() — the only code path that writes events.jsonl.
        A fresh simulation project must report events as not present.
        """
        project_id = simulated_project.name
        r = client.get(f"/api/project/{project_id}")
        body = r.json()
        assert body["events"]["present"] is False
        assert body["events"]["items"] == []

    def test_evidence_computed_for_every_shot_in_timeline(self, client, simulated_project):
        project_id = simulated_project.name
        r = client.get(f"/api/project/{project_id}")
        body = r.json()

        timeline_shots = body["artifacts"]["timeline"]["data"]["shots"]
        for shot in timeline_shots:
            shot_id = shot["shot_id"]
            assert shot_id in body["evidence_by_shot"], f"missing evidence entry for {shot_id}"

    def test_simulation_shots_flagged_red_due_to_zero_evidence_frames(self, client, simulated_project):
        """
        scripts/simulate_documentary.py explicitly sets evidence_frame_paths
        to [] for every simulated asset (see 'evidence_frame_paths':[] in
        the script). The UI must show this honestly as blocked (red), not
        green, even though status is 'simulation_approved'.
        """
        project_id = simulated_project.name
        r = client.get(f"/api/project/{project_id}")
        body = r.json()

        for shot_id, evidence in body["evidence_by_shot"].items():
            assert evidence["level"] == "red", (
                f"{shot_id} should be red (0 evidence frames) but got {evidence['level']}"
            )
            assert evidence["evidence_frame_count"] == 0
            assert any("insufficient_evidence_frames" in r for r in evidence["reasons"])


class TestShotEvidenceEndpoint:
    def test_evidence_for_real_shot(self, client, simulated_project):
        project_id = simulated_project.name
        r = client.get(f"/api/project/{project_id}/evidence/B001")
        assert r.status_code == 200
        body = r.json()
        assert body["shot_id"] == "B001"
        assert body["shot"]["asset_id"] == "sim_asset_001"

    def test_evidence_for_nonexistent_shot_404s(self, client, simulated_project):
        project_id = simulated_project.name
        r = client.get(f"/api/project/{project_id}/evidence/NONEXISTENT")
        assert r.status_code == 404


class TestPathTraversalGuard:
    @pytest.mark.parametrize("bad_id", ["..", "../../etc", "a/b", "a/../b", "/etc/passwd"])
    def test_rejects_traversal_attempts(self, client, bad_id):
        r = client.get(f"/api/project/{bad_id}")
        assert r.status_code in (400, 404)
        if r.status_code == 400:
            assert "Invalid project_id" in r.json()["detail"]


class TestMediaProxy:
    def test_serves_project_media(self, client, simulated_project):
        media = simulated_project / "frames" / "shot-001.txt"
        media.parent.mkdir()
        media.write_text("verified media fixture", encoding="utf-8")

        r = client.get(f"/api/project/{simulated_project.name}/media/frames/shot-001.txt")
        assert r.status_code == 200
        assert r.text == "verified media fixture"

    def test_rejects_media_outside_allowed_roots(self, client, simulated_project):
        r = client.get(f"/api/project/{simulated_project.name}/media/state.json")
        assert r.status_code == 400


class TestRevisionEndpoint:
    def test_valid_trim_is_applied_and_persisted(self, client, simulated_project):
        project_id = simulated_project.name

        r = client.post(
            f"/api/project/{project_id}/revision",
            json={"shot_id": "B001", "new_end": 4.0, "reason": "tighten pacing"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "applied"
        assert body["after"]["end"] == 4.0

        on_disk = json.loads((simulated_project / "timeline.json").read_text())
        b001 = next(s for s in on_disk["shots"] if s["shot_id"] == "B001")
        assert b001["end"] == 4.0

    def test_revision_is_logged_to_events_jsonl(self, client, simulated_project):
        project_id = simulated_project.name
        client.post(
            f"/api/project/{project_id}/revision",
            json={"shot_id": "B001", "new_end": 4.0, "reason": "tighten pacing"},
        )

        events_path = simulated_project / "events.jsonl"
        assert events_path.is_file()
        lines = events_path.read_text().strip().split("\n")
        last_event = json.loads(lines[-1])
        assert last_event["action"] == "revision_applied"
        assert last_event["shot_id"] == "B001"
        assert last_event["reason"] == "tighten pacing"

    def test_end_before_start_rejected_without_touching_file(self, client, simulated_project):
        project_id = simulated_project.name
        before_text = (simulated_project / "timeline.json").read_text()

        r = client.post(
            f"/api/project/{project_id}/revision",
            json={"shot_id": "B002", "new_start": 100, "new_end": 50, "reason": "bad"},
        )
        assert r.status_code == 422

        after_text = (simulated_project / "timeline.json").read_text()
        assert before_text == after_text, "file must be untouched when rejected before validation"

    def test_overlap_causing_revision_is_reverted(self, client, simulated_project):
        """
        Extending B001 past B002's start time creates non-monotonic timing,
        which scripts/timeline_ir.py rejects. The API must revert
        timeline.json to its exact pre-revision bytes, not leave it
        half-mutated.
        """
        project_id = simulated_project.name
        before_text = (simulated_project / "timeline.json").read_text()
        before_data = json.loads(before_text)
        b002_start = next(s for s in before_data["shots"] if s["shot_id"] == "B002")["start"]

        r = client.post(
            f"/api/project/{project_id}/revision",
            json={
                "shot_id": "B001",
                "new_end": b002_start + 2.0,
                "reason": "force overlap",
            },
        )
        assert r.status_code == 422
        assert "reverted" in r.json()["detail"]["message"]

        after_text = (simulated_project / "timeline.json").read_text()
        assert after_text == before_text, "timeline.json must be byte-identical after a reverted revision"

    def test_unknown_shot_id_404s(self, client, simulated_project):
        project_id = simulated_project.name
        r = client.post(
            f"/api/project/{project_id}/revision",
            json={"shot_id": "GHOST", "new_end": 1.0, "reason": "x"},
        )
        assert r.status_code == 404

    def test_missing_reason_rejected_by_validation(self, client, simulated_project):
        project_id = simulated_project.name
        r = client.post(
            f"/api/project/{project_id}/revision",
            json={"shot_id": "B001", "new_end": 4.0, "reason": ""},
        )
        assert r.status_code == 422

    def test_negative_timing_rejected_by_validation(self, client, simulated_project):
        project_id = simulated_project.name
        r = client.post(
            f"/api/project/{project_id}/revision",
            json={"shot_id": "B001", "new_end": -5.0, "reason": "bad"},
        )
        assert r.status_code == 422


class TestListProjects:
    def test_empty_root_returns_empty_list(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert r.json()["projects"] == []

    def test_lists_real_simulated_project(self, client, simulated_project):
        r = client.get("/api/projects")
        body = r.json()
        ids = [p["project_id"] for p in body["projects"]]
        assert simulated_project.name in ids

        entry = next(p for p in body["projects"] if p["project_id"] == simulated_project.name)
        assert entry["has_timeline"] is True
        assert entry["is_simulation"] is True


class TestWebSocket:
    def test_ping_pong(self, client, simulated_project):
        project_id = simulated_project.name
        with client.websocket_connect(f"/ws/timeline/{project_id}") as ws:
            ws.send_json({"type": "ping"})
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_unknown_message_type_returns_error(self, client, simulated_project):
        project_id = simulated_project.name
        with client.websocket_connect(f"/ws/timeline/{project_id}") as ws:
            ws.send_json({"type": "do_something_arbitrary"})
            response = ws.receive_json()
            assert response["type"] == "error"

    def test_invalid_project_id_closes_connection(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/timeline/../../etc") as ws:
                ws.receive_json()
