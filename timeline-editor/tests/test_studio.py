"""
Tests for the Studio API (timeline-editor/server/studio.py): the live payload, thumbnails, the assistant's
typed-patch proposals, apply (with validation refusal and stale-patch refusal), versioned undo, and the
background preview render with progress. Real FFmpeg renders on tiny synthetic clips.

Run from repo root:
    pytest timeline-editor/tests/test_studio.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "server"), str(REPO_ROOT / "tests"), str(REPO_ROOT / "scripts")]
from test_compile_timeline import FPS, H, SR, W, clip  # noqa: E402

PID = "demo"


def timeline() -> dict:
    return {"ir_version": "3.0", "canvas": {"width": W, "height": H, "fps": FPS, "sample_rate": SR},
            "tracks": [
                {"id": "v_main", "kind": "video", "items": [
                    {"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 2.0},
                    {"id": "B", "asset_id": "blue", "timeline_in": 2.0, "timeline_out": 4.0}]},
                {"id": "cc", "kind": "caption", "items": [{"id": "CAP", "timeline_in": 0.5, "timeline_out": 1.5, "text": "HELLO"}]}]}


@pytest.fixture()
def project(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    p = root / PID
    (p / "media").mkdir(parents=True)
    clip(p / "media" / "red.mp4", "0xC00000", 440, 4)
    clip(p / "media" / "blue.mp4", "0x0000C0", 660, 4)
    (p / "assets.json").write_text(json.dumps({"assets": [
        {"asset_id": "red", "local_path": "media/red.mp4", "status": "approved"},
        {"asset_id": "blue", "local_path": "media/blue.mp4", "status": "approved"}]}), encoding="utf-8")
    (p / "timeline_v3.json").write_text(json.dumps(timeline()), encoding="utf-8")
    # An approved shot timeline the Studio must never touch.
    (p / "timeline.json").write_text(json.dumps({"shots": [], "approvals": {"timeline": "approved"}}), encoding="utf-8")
    monkeypatch.setenv("NARRATIVEOS_PROJECT_ROOT", str(root))
    return p


@pytest.fixture()
def client(project):
    import importlib
    import timeline_api_server as mod
    importlib.reload(mod)
    return TestClient(mod.app)


def wait_for_render(client, timeout=120) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/studio/{PID}/poll").json()["job"]
        if job and job["state"] in ("done", "failed") and not job["queued_next"]:
            return job
        time.sleep(0.25)
    raise AssertionError("render did not finish")


def items(ir: dict) -> dict:
    return {i["id"]: i for t in ir["tracks"] for i in t["items"]}


def probe_duration(f: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def test_payload_shows_the_timeline_validation_and_cheap_polling(client, project):
    r = client.get(f"/api/studio/{PID}")
    assert r.status_code == 200
    body = r.json()
    assert body["timeline_source"] == "timeline_v3.json" and body["validation"]["errors"] == []
    assert body["stats"]["clips"] == 2 and body["stats"]["duration"] == pytest.approx(4.0)
    assert body["preview_url"] is None and body["pipeline"] == {"present": False}
    assert set(body["assets"]) == {"red", "blue"}
    poll = client.get(f"/api/studio/{PID}/poll", params={"etag": body["etag"]}).json()
    assert poll["changed"] is False
    assert client.get("/api/studio/").json()["projects"][0]["project_id"] == PID
    assert client.get("/api/studio/nope").status_code == 404


def test_thumbnails_come_from_the_item_source(client):
    r = client.get(f"/api/studio/{PID}/thumb/A")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert client.get(f"/api/studio/{PID}/thumb/CAP").status_code == 404  # captions have no picture
    assert client.get(f"/api/studio/{PID}/thumb/ZZ").status_code == 404


def test_type_a_correction_apply_it_render_it_and_undo_it(client, project):
    approved_before = (project / "timeline.json").read_bytes()
    prop = client.post(f"/api/studio/{PID}/assistant", json={"message": "make this faster", "selection": {"item_id": "A"}}).json()
    assert prop["can_apply"] and prop["patch"]["operations"] == [{"op": "set_duration", "item_id": "A", "duration": 1.6}]
    assert [e["id"] for e in prop["diff"]["edited"]] == ["A"] and {s["id"] for s in prop["diff"]["shifted"]} == {"B"}
    # Proposing changes nothing on disk.
    assert json.loads((project / "timeline_v3.json").read_text()) == timeline()

    applied = client.post(f"/api/studio/{PID}/patches/{prop['patch']['patch_id']}/apply").json()
    assert applied["version"] == "v002"
    assert sorted(x.name for x in (project / "timeline_versions").iterdir()) == ["v001.json", "v002.json"]
    it = items(json.loads((project / "timeline_v3.json").read_text()))
    assert it["A"]["timeline_out"] == pytest.approx(1.6) and it["B"]["timeline_in"] == pytest.approx(1.6)

    job = wait_for_render(client)
    assert job["state"] == "done" and job["progress"] == 1.0, job
    # The job reports what the compiler actually did, phase by phase, with FFmpeg's own counters.
    assert [ph["name"] for ph in job["phases"]] == ["validate", "graph", "encode", "verify"] and job["for"] == "v002"
    assert job["phases"][2]["detail"]["frames"] == round(3.6 * FPS) and job["stats"]["frame"] > 0
    assert job["verification"]["passed"] and job["verification"]["av_delta_ms"] is None  # no audio in this timeline: nothing to compare
    assert probe_duration(project / "renders" / "preview.mp4") == pytest.approx(3.6, abs=0.1)
    body = client.get(f"/api/studio/{PID}").json()
    assert body["preview_url"] and body["versions"] == ["v001.json", "v002.json"]
    actions = [e["action"] for e in body["events"]]
    assert "patch_applied" in actions and "preview_rendered" in actions

    undone = client.post(f"/api/studio/{PID}/undo").json()
    assert undone["restored"] == "v001.json"
    assert json.loads((project / "timeline_v3.json").read_text()) == timeline()
    assert client.post(f"/api/studio/{PID}/undo").status_code == 400  # back at the starting point
    wait_for_render(client)

    # A new edit after an undo gets a fresh number: the undone version stays on disk, unchanged.
    prop = client.post(f"/api/studio/{PID}/assistant", json={"message": "music down 3 dB"}).json()
    assert prop["patch"] is None  # there is no music track: it says so instead of guessing
    prop = client.post(f"/api/studio/{PID}/assistant", json={"message": 'change the caption to "BYE"', "selection": {"item_id": "CAP"}}).json()
    assert client.post(f"/api/studio/{PID}/patches/{prop['patch']['patch_id']}/apply").json()["version"] == "v003"
    names = sorted(x.name for x in (project / "timeline_versions").iterdir())
    assert names == ["v001.json", "v002.undone.json", "v003.json"]
    assert client.post(f"/api/studio/{PID}/undo").json()["restored"] == "v001.json"
    wait_for_render(client)
    assert (project / "timeline.json").read_bytes() == approved_before  # the approved timeline was never written


def test_an_edit_that_breaks_the_timeline_is_shown_but_cannot_be_applied(client, project):
    prop = client.post(f"/api/studio/{PID}/assistant", json={"message": "make it 6 s", "selection": {"item_id": "A"}}).json()
    assert prop["can_apply"] is False and any("asset is 4.000 s" in e for e in prop["errors"])
    r = client.post(f"/api/studio/{PID}/patches/{prop['patch']['patch_id']}/apply")
    assert r.status_code == 400
    assert json.loads((project / "timeline_v3.json").read_text()) == timeline() and not (project / "timeline_versions").exists()


def test_a_patch_proposed_before_another_edit_is_refused(client, project):
    first = client.post(f"/api/studio/{PID}/assistant", json={"message": "make this faster", "selection": {"item_id": "A"}}).json()
    second = client.post(f"/api/studio/{PID}/assistant", json={"message": 'change the caption to "BYE"', "selection": {"item_id": "CAP"}}).json()
    assert client.post(f"/api/studio/{PID}/patches/{second['patch']['patch_id']}/apply").status_code == 200
    r = client.post(f"/api/studio/{PID}/patches/{first['patch']['patch_id']}/apply")
    assert r.status_code == 409 and "changed since" in r.json()["detail"]
    assert client.post(f"/api/studio/{PID}/patches/unknown/apply").status_code == 404
    wait_for_render(client)


def test_unclear_requests_get_a_question_not_an_edit(client):
    r = client.post(f"/api/studio/{PID}/assistant", json={"message": "make this faster"}).json()
    assert r["patch"] is None and "Select" in r["reply"]


def test_render_refuses_a_timeline_that_does_not_validate(client, project):
    bad = timeline()
    bad["tracks"][0]["items"][0]["asset_id"] = "missing"
    (project / "timeline_v3.json").write_text(json.dumps(bad), encoding="utf-8")
    r = client.post(f"/api/studio/{PID}/render")
    assert r.status_code == 400 and r.json()["detail"]["errors"]


def test_the_assistant_streams_each_real_step_then_the_result(client):
    r = client.post(f"/api/studio/{PID}/assistant/stream", json={"message": "dip to black here", "selection": {"item_id": "B"}})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    steps = [e for e in events if e["type"] == "step"]
    assert [s["id"] for s in steps] == ["read", "focus", "understand", "simulate", "validate"]
    assert "2 shots on 2 tracks" in steps[0]["detail"] and steps[1]["item_id"] == "B"
    assert steps[2]["detail"] == ["into B: cut → dip black 0.80 s"] and steps[2]["basis"] == "rules"
    assert all(s["status"] == "done" and s["ms"] >= 0 for s in steps)
    res = events[-1]
    assert res["type"] == "result" and res["can_apply"] and res["after"]["B"] == [2.0, 4.0]
    # A question stops after 'understand' and proposes nothing.
    events = [json.loads(x) for x in client.post(f"/api/studio/{PID}/assistant/stream", json={"message": "make this faster"}).text.splitlines()]
    assert events[-2]["status"] == "question" and events[-1]["patch"] is None


def test_waveforms_are_measured_from_the_samples(client, project):
    w = client.get(f"/api/studio/{PID}/wave/A", params={"n": 50}).json()
    assert w["has_audio"] and len(w["peaks"]) == 50
    # clip() uses FFmpeg's sine source, whose amplitude is 1/8: the measured peak is about -18 dBFS throughout.
    assert min(w["peaks"][1:-1]) > 0.1 and -19.5 < w["peak_dbfs"] < -15  # AAC overshoot lifts the single highest bucket a little
    assert client.get(f"/api/studio/{PID}/wave/CAP").status_code == 404
