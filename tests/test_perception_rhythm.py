"""Offline engineering fixtures: no production media or provider calls."""
import importlib.util
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from style_intel import audio


def click_audio(path, duration=12, silent=False):
    sr = 22050
    y = np.zeros(round(duration * sr))
    if not silent:
        pulse = np.sin(2 * np.pi * 1000 * np.arange(441) / sr) * np.hanning(441)
        for t in np.arange(0.5, duration - 0.1, 0.5):
            start = round(t * sr)
            y[start:start + len(pulse)] = pulse * (0.12 if t < 6 else 0.8)
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, sr, 0, "NONE", "not compressed"))
        out.writeframes((y * 32767).astype("<i2").tobytes())
    return path


def test_actual_audio_exposes_temporal_evidence_not_semantic_guesses(tmp_path):
    assert callable(getattr(audio, "temporal_map", None)), "audio needs a temporal event map"
    result = audio.temporal_map(click_audio(tmp_path / "click.wav"))
    assert result["status"] == "measured"
    assert result["tempo_bpm"] == pytest.approx(120, abs=3)
    onsets = [e for e in result["events"] if e["type"] == "ONSET"]
    assert len(onsets) >= 20
    assert min(abs(e["start"] - 6) for e in onsets) < 0.1
    assert result["energy"][16]["rms_dbfs"] > result["energy"][4]["rms_dbfs"] + 12
    sections = [e for e in result["events"] if e["type"] == "SECTION_CANDIDATE"]
    assert any(abs(e["start"] - 6) < 0.6 for e in sections)
    assert any(e["type"] == "PHRASE_CANDIDATE" for e in result["events"])
    assert {e["type"] for e in result["events"]} <= {"ONSET", "BEAT", "SECTION_CANDIDATE", "PHRASE_CANDIDATE",
                                                    "BUILD_CANDIDATE", "IMPACT_CANDIDATE", "BREAKDOWN_CANDIDATE"}
    # The click track jumps from quiet to loud at 6 s: that is an impact.
    assert any(abs(e["start"] - 6) < 0.6 for e in result["events"] if e["type"] == "IMPACT_CANDIDATE")
    assert all(0 <= e["confidence"] <= 1 and e["evidence"] for e in result["events"])
    assert len(result["source"]["sha256"]) == 64
    assert "chorus" in result["not_measured"]
    json.dumps(result, allow_nan=False)


def test_silence_has_no_invented_beats_or_sections(tmp_path):
    result = audio.temporal_map(click_audio(tmp_path / "silence.wav", duration=3, silent=True))
    assert result["status"] == "silent"
    assert result["tempo_bpm"] is None
    assert result["events"] == []
    assert result["tempo_confidence"] == 0


def test_speech_preserves_explicit_meaningful_pause_with_alignment_evidence():
    assert importlib.util.find_spec("perception") is not None, "missing perception adapter"
    from perception import speech_map
    alignment = {"status": "passed", "alignment_model": "explicit-user-timing", "captions": [
        {"start": 0, "end": 1, "text": "Wait.", "words": [{"start": 0, "end": 1, "word": "Wait."}]},
        {"start": 2.2, "end": 3, "text": "There.", "words": [{"start": 2.2, "end": 3, "word": "There."}]}]}
    plan = {"segments": [{"segment_id": "N2", "type": "SILENCE", "reason": "delayed reveal", "timing": {"target_start": 1, "target_end": 2.2}}]}
    result = speech_map(alignment, plan, duration=3)
    pause = next(e for e in result["events"] if e["type"] == "SPEECH_PAUSE")
    assert (pause["start"], pause["end"]) == (1, 2.2)
    assert pause["preserve"] is True
    assert pause["meaning_source"] == "narration_plan:N2"
    assert pause["reason"] == "delayed reveal"
    assert len([e for e in result["events"] if e["type"] == "WORD"]) == 2
    assert "emotion" in result["not_measured"]


@pytest.mark.parametrize("alignment", [
    {"status": "blocked", "captions": []},
    {"status": "passed", "captions": []},
    {"status": "passed", "captions": [{"start": 2, "end": 1}]},
    {"status": "passed", "captions": [{"start": 0, "end": float("nan")}]},
    {"status": "passed", "captions": [{"start": 0, "end": 4}]},
    {"status": "passed", "captions": [{"start": 0, "end": 2}, {"start": 1, "end": 3}]},
])
def test_bad_or_missing_alignment_cannot_become_measured_speech(alignment):
    from perception import speech_map
    result = speech_map(alignment, {}, duration=3)
    assert result["status"] in {"blocked", "not_measured"}
    assert result["events"] == []


def test_visual_perception_reuses_real_cut_and_motion_measurements(tmp_path):
    import perception
    assert callable(getattr(perception, "visual_map", None)), "missing visual perception adapter"
    video = tmp_path / "two_shots.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=320x180:r=24:d=2", "-f", "lavfi", "-i", "color=blue:s=320x180:r=24:d=2", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264", str(video)], check=True)
    result = perception.visual_map(video, asset_id="fixture", timeline_start=10)
    assert result["cuts_sec"] == pytest.approx([12], abs=0.05)
    assert len(result["shots"]) == 2
    assert all(s["motion"] is None and s["motion_class"] == "unmeasured" for s in result["shots"])
    assert result["shots"][0]["evidence"]["source_interval"] == [0, 2]
    assert result["shots"][0]["asset_id"] == "fixture"
    assert "gaze" in result["not_measured"]


def base_timeline():
    return {"shots": [
        {"shot_id": "SHOT_1", "asset_id": "a", "start": 0, "end": 3.9, "source_start": 0, "media_type": "image", "motion": "static", "transition": "cut", "status": "simulation_approved"},
        {"shot_id": "SHOT_2", "asset_id": "b", "start": 3.9, "end": 8, "source_start": 0, "media_type": "image", "motion": "static", "transition": "cut", "status": "simulation_approved", "editorial_intent": "reveal"}]}


def test_director_routes_measured_phrase_reveal_through_existing_graph():
    import director_brain
    from event_graph import compile_graph, validate
    assert callable(getattr(director_brain, "plan_edit", None)), "director needs perception-to-edit integration"
    perception = {"music": {"events": [{"event_id": "M1", "type": "PHRASE_CANDIDATE", "start": 4, "confidence": 0.6, "evidence": {"method": "engineering_fixture"}}]}, "speech": {"events": []}, "visual": []}
    style = {"editing": {"rhythm_mode": "phrase_aware", "snap_window_sec": 0.2, "min_shot_sec": 1, "anticipation_sec": 0.25}}
    graph = director_brain.plan_edit(base_timeline(), perception, style)
    assert validate(graph) == []
    assert {e["type"] for e in graph["events"]} == {"REVEAL", "ANTICIPATE"}
    assert graph["events"][0]["evidence_refs"] == ["M1"]
    compiled = compile_graph(graph)
    assert len(compiled["shots"]) == 2
    assert compiled["shots"][0]["end"] == compiled["shots"][1]["start"] == 4
    assert compiled["shots"][1]["end"] == 8
    assert compiled["shots"][1]["asset_id"] == "b"
    assert compiled["status"] == "review_required"
    assert compiled["review"]["required"] is True
    assert all(s["status"] != "approved" for s in compiled["shots"])
    assert compiled["markers"][0]["start"] == 3.75
    assert graph["director"]["mode"] == "deterministic"


@pytest.mark.parametrize("protection", ["pause", "hold", "free", "source_handle"])
def test_director_does_not_cut_mechanically_through_editorial_constraints(protection):
    from director_brain import plan_edit
    from event_graph import compile_graph
    timeline = base_timeline()
    perception = {"music": {"events": [{"event_id": "M1", "type": "ONSET", "start": 4, "confidence": 0.8}]}, "speech": {"events": []}}
    style = {"editing": {"rhythm_mode": "phrase_aware"}}
    if protection == "pause":
        perception["speech"]["events"] = [{"event_id": "S1", "type": "SPEECH_PAUSE", "start": 3.8, "end": 4.5, "preserve": True, "meaning_source": "narration_plan:N1"}]
    elif protection == "hold":
        timeline["shots"][0]["editorial_intent"] = "hold"
    elif protection == "free":
        style["editing"]["rhythm_mode"] = "free"
    else:
        timeline["shots"][0].update(media_type="video", usable_interval=[0, 3.9])
    graph = plan_edit(timeline, perception, style)
    assert all("boundary" not in e for e in graph["events"])
    assert compile_graph(graph)["shots"][0]["end"] == 3.9
    if protection in {"hold", "pause"}:
        assert any(e["type"] == "HOLD" for e in graph["events"])
