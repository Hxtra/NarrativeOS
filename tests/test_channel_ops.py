"""Channel operating layer: profiles, creative memory, the visible production graph, repetition guard,
packaging, the publish plan and provenance lineage."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import channel  # noqa: E402
import creative_memory as cm  # noqa: E402
import publish_package as packaging  # noqa: E402
import publish_youtube  # noqa: E402
import repetition_guard  # noqa: E402

PY = sys.executable
CTRL = ROOT / "scripts" / "controller.py"


def save(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def ctrl(project, *args):
    return subprocess.run([PY, str(CTRL), "--project", str(project), *args], capture_output=True, text=True)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "channels"
    channel.create("history_now", "History Now", "unsolved history", root=str(r))
    return str(r)


# --- channel profiles ---------------------------------------------------------------------------------
def test_profile_versions_are_immutable_and_every_change_has_a_reason(root):
    v2 = channel.update("history_now", {"visual.aspect_ratio": "9:16", "audio.ducking_db": -14}, "moving to Shorts", root=root)
    assert v2["profile_version"] == 2 and v2["parent_version"] == 1 and v2["change_reason"] == "moving to Shorts"
    assert channel.load("history_now", 1, root)["visual"]["aspect_ratio"] == "16:9"  # v1 untouched
    with pytest.raises(ValueError):
        channel.update("history_now", {"visual.aspect_ratio": "1:1"}, "  ", root=root)
    with pytest.raises(KeyError):
        channel.update("history_now", {"rules": []}, "sneak a rule in", root=root)  # rules only come from promote
    with pytest.raises(Exception):
        channel.update("history_now", {"visual.aspect_ratio": "21:9"}, "not an allowed ratio", root=root)  # schema


def test_apply_pins_a_version_and_the_controller_refuses_an_edited_pin(root, tmp_path):
    proj = tmp_path / "video1"
    assert ctrl(proj, "--init").returncode == 0
    (proj / "project.yaml").write_text("project_id: v1\n", encoding="utf-8")
    (proj / "brief.md").write_text("A brief.\n", encoding="utf-8")
    assert ctrl(proj).returncode == 0  # INTAKE
    pin = channel.apply("history_now", proj, root=root)["pin"]
    assert pin["profile_version"] == 1
    assert ctrl(proj).returncode == 0  # STYLE_LOCK passes with an intact pin
    prof = json.loads((proj / "channel_profile.json").read_text())
    prof["audio"]["ducking_db"] = -3  # hand edit
    save(proj / "channel_profile.json", prof)
    r = ctrl(proj, "--stage", "STYLE_LOCK")
    assert r.returncode == 1
    assert "pinned_profile_edited" in json.dumps(json.loads((proj / "state.json").read_text())["blocking_findings"])


# --- creative memory ----------------------------------------------------------------------------------
def test_one_correction_is_never_a_rule(root):
    with pytest.raises(ValueError):
        cm.record("history_now", "v1", "TIMELINE", "shot:S1", "corrected", "", after={"dur": 2.4}, root=root)  # no reason
    d1 = cm.record("history_now", "v1", "TIMELINE", "shot:S4", "corrected", "landscape needs to breathe", {"dur": 1.2}, {"dur": 2.5}, ["pacing", "landscape"], root)
    with pytest.raises(ValueError, match="at least 2"):
        cm.promote("history_now", [d1["id"]], "Hold landscapes >= 2.4 s", "TIMELINE", root)
    d2 = cm.record("history_now", "v1", "TIMELINE", "shot:S9", "corrected", "same again", {"dur": 1.0}, {"dur": 2.4}, ["pacing", "landscape"], root)
    with pytest.raises(ValueError, match="2 different videos"):
        cm.promote("history_now", [d1["id"], d2["id"]], "Hold landscapes >= 2.4 s", "TIMELINE", root)
    d3 = cm.record("history_now", "v2", "TIMELINE", "shot:S3", "corrected", "breathe", {"dur": 1.1}, {"dur": 2.6}, ["landscape"], root)
    out = cm.promote("history_now", [d1["id"], d3["id"]], "Hold landscapes >= 2.4 s", "TIMELINE", root)
    prof = channel.load("history_now", root=root)
    assert out["rule"]["id"] == "R001" and prof["profile_version"] == out["profile_version"] == 2
    assert prof["rules"][0]["source_decisions"] == [d1["id"], d3["id"]]
    pre = cm.precedents("history_now", "TIMELINE", ["landscape"], root=root)
    assert pre["basis"] == "ADVISORY" and pre["channel_rules"][0]["id"] == "R001" and len(pre["precedents"]) == 3
    assert cm.retire("history_now", "R001", "faster format now", root)["profile_version"] == 3
    assert channel.load("history_now", root=root)["rules"] == []


def test_disagreeing_decisions_cannot_be_promoted(root):
    a = cm.record("history_now", "v1", "TRANSITIONS", "m:3", "accepted", "", tags=["glitch"], root=root)
    b = cm.record("history_now", "v2", "TRANSITIONS", "m:7", "rejected", "too loud for this story", tags=["glitch"], root=root)
    with pytest.raises(ValueError, match="disagree"):
        cm.promote("history_now", [a["id"], b["id"]], "Use glitch cuts", "TRANSITIONS", root)


# --- production graph ----------------------------------------------------------------------------------
def _through_style_lock(proj, root):
    ctrl(proj, "--init")
    (proj / "project.yaml").write_text("project_id: g\n", encoding="utf-8")
    (proj / "brief.md").write_text("Brief.\n", encoding="utf-8")
    assert ctrl(proj).returncode == 0
    channel.apply("history_now", proj, root=root)
    assert ctrl(proj).returncode == 0


def test_edited_upstream_artifact_makes_its_stage_stale_and_blocks_downstream(root, tmp_path):
    proj = tmp_path / "g"
    _through_style_lock(proj, root)
    (proj / "brief.md").write_text("A different brief.\n", encoding="utf-8")  # INTAKE's artifact changed after it passed
    ctrl(proj, "--graph")
    g = json.loads((proj / "production_graph.json").read_text())
    nodes = {n["stage"]: n for n in g["nodes"]}
    assert nodes["INTAKE"]["status"] == "stale" and nodes["INTAKE"]["stale"]["artifacts_changed"] == ["brief.md"]
    for a in ("director_strategy.json", "emotional_arc.json", "retention_plan.json"):
        save(proj / a, {"status": "passed"})
    r = ctrl(proj, "--stage", "DIRECTOR_STRATEGY")
    assert r.returncode == 1
    assert "stale_dependency" in json.dumps(json.loads((proj / "state.json").read_text())["blocking_findings"])
    assert ctrl(proj, "--stage", "INTAKE").returncode == 0  # re-run the stale stage ...
    ctrl(proj, "--graph")
    nodes = {n["stage"]: n for n in json.loads((proj / "production_graph.json").read_text())["nodes"]}
    assert nodes["STYLE_LOCK"]["status"] == "stale"  # ... and what it feeds is now stale in turn
    assert nodes["STYLE_LOCK"]["stale"]["upstream_passed_later"] == ["INTAKE"]


def test_revise_reopens_downstream_and_pause_blocks(root, tmp_path):
    proj = tmp_path / "r"
    _through_style_lock(proj, root)
    assert ctrl(proj, "--revise", "INTAKE", "--reason", "new angle on the story").returncode == 0
    state = json.loads((proj / "state.json").read_text())
    assert state["completed_stages"] == [] and state["current_stage"] == "INTAKE"
    assert state["revisions"][0]["reopened"] == ["INTAKE", "STYLE_LOCK"]
    assert ctrl(proj, "--pause").returncode != 0  # a pause needs a reason
    assert ctrl(proj, "--pause", "--reason", "waiting on legal").returncode == 0
    assert ctrl(proj).returncode == 1
    assert ctrl(proj, "--resume").returncode == 0
    assert ctrl(proj).returncode == 0


# --- repetition guard -------------------------------------------------------------------------------------
def _video(proj: Path, text: str, transitions: list[str], assets: list[str]):
    save(proj / "script.json", {"beats": [{"narration": text}]})
    save(proj / "timeline.json", {"shots": [{"shot_id": f"S{i}", "asset_id": a, "start": i * 3, "end": i * 3 + 3, "transition": t}
                                            for i, (t, a) in enumerate(zip(transitions, assets))]})
    save(proj / "assets.json", {"assets": [{"asset_id": a, "sha256": f"{a}sha"} for a in assets]})


def test_repetition_guard_flags_a_near_copy_but_not_a_new_video(root, tmp_path):
    base = ("In 1872 the crew of the Mary Celeste vanished without a trace and the ship was found drifting near the Azores "
            "with its cargo intact and a lifeboat missing, and nobody has ever explained why they left")
    first = tmp_path / "ep1"
    _video(first, base, ["hard_cut", "light_leak_warm", "hard_cut"], ["a1", "a2", "a3"])
    channel.record_video("history_now", first, root=root)
    copy = tmp_path / "ep2"
    _video(copy, base.replace("1872", "1873"), ["hard_cut", "light_leak_warm", "hard_cut"], ["a1", "a2", "a9"])
    rep = repetition_guard.check(copy, "history_now", root)
    assert rep["status"] == "review_required"
    sims = rep["flagged"][0]["similarity"]
    assert sims["script"] >= 0.6 and sims["assets"] == pytest.approx(2 / 3, abs=0.01)
    fresh = tmp_path / "ep3"
    _video(fresh, "The Dyatlov Pass incident in 1959 left nine hikers dead in the northern Ural mountains under circumstances still argued about",
           ["dip_to_black", "hard_cut"], ["b1", "b2"])
    assert repetition_guard.check(fresh, "history_now", root)["status"] == "passed"
    assert "script_minhash" in channel.history("history_now", root)[0] and "narration" not in json.dumps(channel.history("history_now", root))


# --- packaging and publishing ---------------------------------------------------------------------------
def _thumb(path: Path, size=(1280, 720)) -> Path:
    Image.new("RGB", size, (30, 40, 50)).save(path)
    return path


def test_packaging_limits_and_disclosure_from_provenance(root, tmp_path):
    proj = tmp_path / "p"
    channel.apply("history_now", proj, root=root)
    save(proj / "timeline.json", {"shots": [{"shot_id": "S1", "asset_id": "gen1"}, {"shot_id": "S2", "asset_id": "photo"}]})
    save(proj / "assets.json", {"assets": [{"asset_id": "gen1", "media_class": "GENERATED_RECONSTRUCTION"}, {"asset_id": "photo"}]})
    bad = packaging.build(proj, "x" * 101, "has <b>tags</b>", ["t"] * 300, str(_thumb(tmp_path / "small.jpg", (600, 400))), None)
    errs = " ".join(bad["checks"]["errors"])
    assert bad["status"] == "blocked"
    for needle in ("1-100", "'<' or '>'", "tags total", "made_for_kids", "640", "16:9"):
        assert needle in errs, needle
    ok = packaging.build(proj, "What happened on the Mary Celeste", "The ship was found drifting.", ["history"], str(_thumb(tmp_path / "t.jpg")), False)
    assert ok["status"] == "review_required" and ok["disclosure"]["containsSyntheticMedia"] is True
    assert ok["privacy"] == "private"  # channel default
    save(proj / "assets.json", {"assets": [{"asset_id": "gen1", "media_class": "GENERATED_CONCEPT"}, {"asset_id": "photo"}]})
    concept = packaging.build(proj, "Title", "", [], str(_thumb(tmp_path / "t.jpg")), False)
    assert concept["disclosure"]["containsSyntheticMedia"] is False and concept["disclosure"]["review"] is True


def test_approval_is_bound_to_the_package_and_publishing_never_uploads(root, tmp_path):
    proj = tmp_path / "pub"
    channel.apply("history_now", proj, root=root)
    save(proj / "timeline.json", {"shots": []})
    packaging.build(proj, "A title", "Desc", [], str(_thumb(tmp_path / "t.jpg")), False)
    plan = publish_youtube.plan(proj)
    assert not plan["all_gates_passed"] and plan["upload"]["status"] == "BLOCKED"
    packaging.approve(proj, "owner")
    assert packaging.approved(proj)[0]
    pkg = json.loads((proj / "publish_package.json").read_text())
    pkg["title"] = "Edited after approval"
    save(proj / "publish_package.json", pkg)
    assert packaging.approved(proj) == (False, "the publish package changed after it was approved")
    packaging.build(proj, "A title", "Desc", [], str(_thumb(tmp_path / "t.jpg")), False)
    packaging.approve(proj, "owner")
    save(proj / "state.json", {"delivery_ready": True, "publish_authorized": True})
    save(proj / "repetition_report.json", {"status": "passed"})
    (proj / "renders").mkdir(exist_ok=True)
    (proj / "renders" / "final.mp4").write_bytes(b"x")
    plan = publish_youtube.plan(proj)
    assert plan["all_gates_passed"] and plan["upload"]["status"] == "BLOCKED"
    st = plan["videos_insert"]["body"]["status"]
    assert st == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False}
    assert not (proj / "publish_manifest.json").exists()  # only a real, confirmed upload may write it


def test_provenance_lineage_records_unknowns_instead_of_guessing(root, tmp_path):
    proj = tmp_path / "prov"
    channel.apply("history_now", proj, root=root)
    save(proj / "script.json", {"beats": []})
    r = subprocess.run([PY, str(ROOT / "scripts" / "build_provenance.py"), "--project", str(proj)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = json.loads((proj / "provenance_manifest.json").read_text())
    lin = m["lineage"]
    assert lin["channel_profile"]["profile_version"] == 1 and lin["script"]["sha256"]
    assert {"narration", "timeline", "render"} <= set(m["lineage_unknown"])
    assert lin["narration"] == {"status": "unknown", "reason": "no tts_manifest.json"}
