"""Behaviour of the music-aware Director: labelled music evidence, configurable tolerances, every action type,
measured-only transitions, and the provider-agnostic reasoning-model interface."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from director_brain import plan_edit  # noqa: E402
from editing_config import director_config  # noqa: E402
from event_graph import compile_graph, validate  # noqa: E402
from style_intel.audio import temporal_map  # noqa: E402
from test_editing_intelligence import shaped_audio  # noqa: E402


def shots(boundary=12.1):
    return {"shots": [
        {"shot_id": "SHOT_1", "asset_id": "a", "start": 0, "end": boundary, "media_type": "image", "status": "simulation_approved"},
        {"shot_id": "SHOT_2", "asset_id": "b", "start": boundary, "end": 20, "media_type": "image", "status": "simulation_approved"}]}


def music(*events):
    return {"music": {"status": "measured", "events": list(events)}, "speech": {"events": []}}


# --- Music evidence is labelled, never overstated ---------------------------------------------

def test_every_music_event_says_whether_it_was_measured_or_inferred(tmp_path):
    result = temporal_map(shaped_audio(tmp_path / "s.wav"))
    basis = {e["type"]: e["basis"] for e in result["events"]}
    assert basis["ONSET"] == "MEASURED"
    assert all(basis[k] == "INFERRED" for k in basis if k != "ONSET")
    assert result["measurements"]["energy"]["status"] == "MEASURED"
    for feature in ("kick", "snare", "downbeat", "meter", "chorus"):
        assert result["measurements"][feature]["status"] == "NOT_MEASURED" and result["measurements"][feature]["reason"]
        assert feature in result["not_measured"]
    assert not any(e["type"] in {"KICK", "SNARE", "DOWNBEAT", "CHORUS"} for e in result["events"])


def test_music_thresholds_are_configurable(tmp_path):
    audio = shaped_audio(tmp_path / "s.wav")
    assert any(e["type"] == "IMPACT_CANDIDATE" for e in temporal_map(audio)["events"])
    strict = temporal_map(audio, {"impact_jump_db": 40})
    assert not any(e["type"] == "IMPACT_CANDIDATE" for e in strict["events"])
    assert strict["config"]["impact_jump_db"] == 40


# --- Tolerances live in one validated config -----------------------------------------------------

@pytest.mark.parametrize("bad", [{"snap_window_sec": -1}, {"snap_window_sec": float("nan")}, {"rhythm_mode": "every_beat"},
                                 {"audio_overlap": {"mode": "x_cut"}}, {"allowed_transitions": "flash_cut"}])
def test_bad_director_settings_are_rejected(bad):
    with pytest.raises(ValueError):
        director_config(bad)


def test_snap_window_is_honoured():
    hit = {"event_id": "M1", "type": "PHRASE_CANDIDATE", "start": 12.0, "confidence": 0.6, "evidence": {}}
    wide = plan_edit(shots(), music(hit), {"editing": {"rhythm_mode": "phrase_aware", "snap_window_sec": 0.2}})
    narrow = plan_edit(shots(), music(hit), {"editing": {"rhythm_mode": "phrase_aware", "snap_window_sec": 0.05}})
    assert [e["type"] for e in wide["events"]] == ["CUT"]
    assert narrow["events"] == []


# --- A musical event can become several different actions ------------------------------------------

def test_build_inside_a_shot_becomes_motion():
    build = {"event_id": "M1", "type": "BUILD_CANDIDATE", "start": 4.0, "confidence": 0.5, "evidence": {"end_sec": 12.0}}
    graph = plan_edit(shots(), music(build), {"editing": {"build_motion": "push_in"}})
    motion = [e for e in graph["events"] if e["type"] == "MOTION"]
    assert len(motion) == 1 and motion[0]["affected_objects"] == ["SHOT_1"]
    assert motion[0]["timing"] == {"start": 4.0, "duration": 8.0} and motion[0]["motion"]["kind"] == "push_in"
    assert validate(graph) == []
    marker = compile_graph(graph)["markers"][0]
    assert marker["type"] == "MOTION" and marker["motion"]["scale_to"] == pytest.approx(1.06)


def energy(kind, t=12.0, delta=10.0):
    return {"event_id": f"M_{kind}", "type": kind, "start": t, "confidence": 0.6, "evidence": {"delta_db": delta}}


@pytest.mark.parametrize("event,allowed,expected", [
    (energy("IMPACT_CANDIDATE"), ["hard_cut", "flash_cut"], "flash_cut"),
    (energy("BREAKDOWN_CANDIDATE"), ["hard_cut", "dip_to_black"], "dip_to_black"),
    (energy("SECTION_CANDIDATE", delta=8), ["hard_cut", "leak_crossfade"], "leak_crossfade"),
    (energy("IMPACT_CANDIDATE"), ["hard_cut", "dip_to_black"], None),   # impact family not in the style: no transition invented
    (energy("IMPACT_CANDIDATE"), ["hard_cut"], None),                   # hard cuts only
])
def test_energy_change_at_a_cut_uses_only_allowed_transitions(event, allowed, expected):
    graph = plan_edit(shots(), music(event), {"editing": {"transition_policy": "energy", "allowed_transitions": allowed}})
    found = [e["transition"]["recipe"] for e in graph["events"] if e["type"] == "TRANSITION"]
    assert found == ([expected] if expected else [])
    assert validate(graph) == []


def test_transition_validation_rejects_unregistered_or_disallowed_recipes():
    graph = plan_edit(shots(), music(energy("IMPACT_CANDIDATE")), {"editing": {"transition_policy": "energy", "allowed_transitions": ["hard_cut", "flash_cut"]}})
    graph["events"][0]["transition"]["recipe"] = "made_up_swoosh"
    assert validate(graph)
    graph["events"][0]["transition"]["recipe"] = "glitch_cut"  # real recipe, but the style did not allow it
    assert validate(graph)


# --- Reasoning models plug in through a provider interface; none is assumed ------------------------

def test_model_assisted_director_keeps_only_valid_proposals():
    calls = []

    def fake_model(task, context):
        calls.append(task)
        return {"events": [
            {"type": "EMPHASIZE", "purpose": "Land the key word.", "timing": {"start": 5.0, "duration": 0.5}, "affected_objects": ["SHOT_1"]},
            {"type": "EMPHASIZE", "purpose": "Invalid: unknown shot.", "timing": {"start": 5.0, "duration": 0.5}, "affected_objects": ["SHOT_9"]},
        ]}
    provider = {"type": "callable", "name": "any-provider", "model": "any-model", "callable": fake_model}
    graph = plan_edit(shots(), music(), {"editing": {}}, {"mode": "model_assisted", "provider": provider})
    assert calls == ["propose_edit_events"]
    assert [e["source"]["model"] for e in graph["events"]] == ["any-model"]
    assert len(graph["rejected_model_events"]) == 1
    assert graph["director"]["model"] == {"type": "callable", "name": "any-provider", "model": "any-model"}
    assert validate(graph) == []


def test_command_reasoning_provider(tmp_path):
    script = tmp_path / "reasoner.py"
    script.write_text("import json,sys\n"
                      "task=json.load(open(sys.argv[1]))\n"
                      "assert task['task']=='propose_edit_events' and 'EMPHASIZE' in task['context']['allowed_event_types']\n"
                      "json.dump({'events':[{'type':'HOLD','purpose':'Let it breathe.','timing':{'start':0,'duration':3},'affected_objects':['SHOT_1']}]},open(sys.argv[2],'w'))\n",
                      encoding="utf-8")
    provider = {"type": "command", "name": "local", "model": "reasoner-x", "command": [sys.executable, str(script), "{input_file}", "{output_file}"]}
    graph = plan_edit(shots(), music(), {"editing": {}}, {"mode": "model_assisted", "provider": provider})
    assert [e["type"] for e in graph["events"]] == ["HOLD"] and graph["events"][0]["source"]["kind"] == "model"


@pytest.mark.parametrize("director", [{"mode": "model"}, {"mode": "deterministic", "model": "some-model"}, {"mode": "model_assisted"}])
def test_director_mode_must_be_explicit(director):
    with pytest.raises(ValueError):
        plan_edit(shots(), music(), {"editing": {}}, director)
