"""Editor-instinct features: music shapes, accents, J/L-cuts, speech trims, rhythm review, styled generation."""
import sys
import wave
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from director_brain import plan_edit  # noqa: E402
from editorial_style import fingerprint, resolve_style  # noqa: E402
from event_graph import compile_graph, validate  # noqa: E402
import generation  # noqa: E402
import perception  # noqa: E402
from style_intel.audio import temporal_map  # noqa: E402


# --- Music: builds, impacts, breakdowns -------------------------------------------------

def shaped_audio(path: Path) -> Path:
    """Quiet 4 s, 8 s ramp up, hit at 12 s, loud until 16 s, sudden quiet after."""
    sr = 22050
    t = np.arange(int(20 * sr)) / sr
    env = np.piecewise(t, [t < 4, (t >= 4) & (t < 12), (t >= 12) & (t < 16), t >= 16],
                       [0.02, lambda x: 0.02 + 0.1 * (x - 4) / 8, 0.9, 0.02])
    y = np.sin(2 * np.pi * 220 * t) * env
    with wave.open(str(path), "wb") as w:
        w.setparams((1, 2, sr, 0, "NONE", ""))
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return path


def test_music_build_impact_breakdown(tmp_path):
    events = temporal_map(shaped_audio(tmp_path / "shape.wav"))["events"]
    get = lambda kind: [e for e in events if e["type"] == kind]  # noqa: E731
    build = get("BUILD_CANDIDATE")
    assert len(build) == 1 and build[0]["start"] == pytest.approx(4, abs=0.6) and build[0]["evidence"]["end_sec"] == pytest.approx(12, abs=0.6)
    assert [e["start"] for e in get("IMPACT_CANDIDATE")] == pytest.approx([12], abs=0.1)
    assert [e["start"] for e in get("BREAKDOWN_CANDIDATE")] == pytest.approx([16], abs=0.1)


# --- Director: reveals land on hits; beats don't always mean CUT ------------------------

def timeline():
    return {"shots": [
        {"shot_id": "SHOT_1", "asset_id": "a", "start": 0, "end": 4.0, "source_start": 0, "media_type": "image", "status": "simulation_approved"},
        {"shot_id": "SHOT_2", "asset_id": "b", "start": 4.0, "end": 9.0, "source_start": 0, "media_type": "image", "status": "simulation_approved", "editorial_intent": "reveal"}]}


def music(*events):
    return {"music": {"status": "measured", "events": list(events)}, "speech": {"events": []}}


def test_reveal_prefers_the_impact_over_a_closer_onset():
    p = music({"event_id": "M1", "type": "ONSET", "start": 4.02, "confidence": 0.9},
              {"event_id": "M2", "type": "IMPACT_CANDIDATE", "start": 4.15, "confidence": 0.5})
    graph = plan_edit(timeline(), p, {"editing": {"rhythm_mode": "phrase_aware", "snap_window_sec": 0.2, "min_shot_sec": 1}})
    reveal = next(e for e in graph["events"] if e["type"] == "REVEAL")
    assert reveal["evidence_refs"] == ["M2"] and reveal["timing"]["start"] == 4.15


def test_impact_inside_a_shot_is_emphasized_not_cut():
    hit = {"event_id": "M1", "type": "IMPACT_CANDIDATE", "start": 6.5, "confidence": 0.6}
    off = plan_edit(timeline(), music(hit), {"editing": {}})
    assert off["events"] == []  # accents are opt-in per style
    graph = plan_edit(timeline(), music(hit), {"editing": {"accent_action": "emphasize"}})
    assert [(e["type"], e["affected_objects"], e["timing"]["start"]) for e in graph["events"]] == [("EMPHASIZE", ["SHOT_2"], 6.5)]
    assert validate(graph) == []
    compiled = compile_graph(graph)
    assert [s["end"] for s in compiled["shots"]] == [4.0, 9.0]  # no cut was added
    assert compiled["markers"][0]["type"] == "EMPHASIZE"
    pause = {"event_id": "S1", "type": "SPEECH_PAUSE", "start": 6.0, "end": 7.0, "preserve": True}
    quiet = plan_edit(timeline(), {**music(hit), "speech": {"events": [pause]}}, {"editing": {"accent_action": "emphasize"}})
    assert quiet["events"] == []  # never punch through a meaningful pause


# --- J/L-cuts ---------------------------------------------------------------------------

def av_timeline():
    t = timeline()
    for s in t["shots"]:
        s.update(media_type="video", has_native_audio=True, source_start=2.0, usable_interval=[0, 20])
    return t


@pytest.mark.parametrize("mode,kind,split", [("j_cut", "J_CUT", 3.4), ("l_cut", "L_CUT", 4.6)])
def test_j_and_l_cuts_split_sound_from_picture(mode, kind, split):
    style = {"editing": {"audio_overlap": {"mode": mode, "offset_sec": 0.6}}}
    graph = plan_edit(av_timeline(), music(), style)
    assert [e["type"] for e in graph["events"]] == [kind]
    assert validate(graph) == []
    compiled = compile_graph(graph)
    a, b = compiled["shots"]
    assert a["end"] == b["start"] == 4.0  # the picture cut does not move
    assert a["native_audio_end"] == b["native_audio_start"] == split
    assert a["native_audio_execution"] == "ir_only_renderer_pending"


def test_j_cut_needs_real_sound_and_source_room():
    style = {"editing": {"audio_overlap": {"mode": "j_cut", "offset_sec": 0.6}}}
    silent = av_timeline()
    silent["shots"][1]["has_native_audio"] = False
    assert plan_edit(silent, music(), style)["events"] == []
    no_room = av_timeline()
    no_room["shots"][1]["source_start"] = 0.2  # B's source has no audio 0.6 s before its in-point
    assert plan_edit(no_room, music(), style)["events"] == []
    graph = plan_edit(av_timeline(), music(), style)
    bad = deepcopy(graph)
    bad["events"][0]["audio_overlap"]["offset_sec"] = 5  # longer than the shot carrying the sound
    assert validate(bad)
    with pytest.raises(ValueError):
        compile_graph(bad)


# --- Speech: trim candidates, never automatic trims --------------------------------------

def test_fillers_and_repeats_are_flagged_for_review_only():
    words = [("So", 0.0, 0.3), ("um", 0.4, 0.6), ("the", 0.7, 0.8), ("the", 0.85, 1.0), ("like", 1.1, 1.3), ("story", 1.4, 1.9)]
    alignment = {"status": "passed", "captions": [{"start": 0, "end": 2, "words": [{"word": w, "start": a, "end": b} for w, a, b in words]}]}
    events = perception.speech_map(alignment, {}, duration=3)["events"]
    flagged = [(e["type"], e["start"]) for e in events if e.get("action") == "trim_candidate"]
    assert flagged == [("SPEECH_FILLER", 0.4), ("SPEECH_REPEAT", 0.85)]  # "like" is never flagged
    assert sum(e["type"] == "WORD" for e in events) == len(words)  # nothing removed


# --- Rhythm review --------------------------------------------------------------------------

def test_rhythm_review_flags_monotony_and_mechanical_cutting():
    shots = [{"shot_id": f"SHOT_{i}", "asset_id": "clip", "start": i * 2.0, "end": i * 2.0 + 2.0, "source_start": i * 2.0} for i in range(7)]
    beats = {"events": [{"type": "BEAT", "start": t} for t in np.arange(0, 14.01, 0.5)]}
    visual = [{"asset_id": "clip", "shots": [{"motion_class": "push_in", "evidence": {"source_interval": [0, 100]}}]}]
    kinds = {w["kind"] for w in perception.rhythm_review({"shots": shots}, beats, visual)["warnings"]}
    assert kinds == {"mechanical_shot_lengths", "every_cut_on_the_beat", "repeated_camera_motion"}
    varied = [{"shot_id": f"S{i}", "asset_id": "x", "start": s, "end": e} for i, (s, e) in enumerate([(0, 1.7), (1.7, 4.9), (4.9, 5.8), (5.8, 9.1), (9.1, 10.3)])]
    assert perception.rhythm_review({"shots": varied}, {"events": []}, [])["warnings"] == []


# --- Styled generation, continuity lock, pluggable generator ------------------------------

def crime_style():
    return resolve_style({"editorial_intent": {"tone": "tense true-crime", "avoid": ["bright cheerful colours"],
                                               "image": {"lighting": "low-key", "palette": "desaturated teal"}}})


def bible():
    return {"entities": [{"entity_id": "E1", "attributes": {"appearance": "grey coat, short dark hair"}, "reference_images": []}],
            "locations": [{"location_id": "NYC_STREET", "attributes": {"layout": "brownstones, fire escape on the right"}, "reference_images": []}],
            "generation_lock": {"lens": "35mm", "grain": "fine"}}


def test_happy_moment_prompt_keeps_the_videos_look():
    request = generation.plan_request({"request_id": "IMG1", "kind": "image", "visual_role": "conceptual",
                                       "purpose": "The family laughing at dinner before the disappearance",
                                       "entity_ids": ["E1"], "location_id": "NYC_STREET", "width": 1920, "height": 1080}, crime_style(), bible())
    prompt = generation.compose_prompt(request)
    for needed in ("laughing at dinner", "tense true-crime", "low-key", "desaturated teal", "grey coat", "brownstones", "35mm", "Avoid: bright cheerful colours"):
        assert needed in prompt


def test_video_generation_stays_disabled_and_missing_provider_is_blocked():
    with pytest.raises(ValueError, match="disabled"):
        generation.load_adapter({"video": {"type": "command"}}, "video")
    with pytest.raises(ValueError, match="BLOCKED"):
        generation.load_adapter({}, "image")


def stub_generator(tmp_path: Path) -> Path:
    """A stand-in for a real local image model: writes a PNG and records the prompt it was given."""
    script = tmp_path / "stub_gen.py"
    script.write_text(
        "import sys, cv2, numpy as np, shutil\n"
        "prompt, out = sys.argv[1], sys.argv[2]\n"
        "cv2.imwrite(out, np.full((16, 16, 3), 90, np.uint8))\n"
        "shutil.copy(prompt, out + '.prompt.txt')\n", encoding="utf-8")
    return script


def test_generated_image_becomes_the_reference_for_the_next_one(tmp_path):
    providers = {"image": {"type": "command", "provider": "local-stub", "model": "stub-1", "rights_terms": "owner-run local model",
                           "work_dir": str(tmp_path / "gen"), "output_ext": ".png",
                           "command": [sys.executable, str(stub_generator(tmp_path)), "{prompt_file}", "{out}"]}}
    need = {"request_id": "IMG1", "kind": "image", "visual_role": "conceptual", "purpose": "Night street where it happened",
            "location_id": "NYC_STREET", "width": 1920, "height": 1080}
    request = generation.plan_request(need, crime_style(), bible())
    quote = {"version": "v1", "request_hash": request["request_hash"], "provider": "local-stub", "model": "stub-1",
             "amount": 0, "currency": "USD", "basis": "local_zero_cost", "rights_terms": "owner-run local model"}
    approval = {"quote_hash": fingerprint(quote), "cost_approved": True, "rights_approved": True}
    job = generation.execute_request(request, quote, approval, generation.load_adapter(providers, "image"))
    assert job["state"] == "GENERATED" and "Night street" in Path(job["output"]["path"] + ".prompt.txt").read_text()

    with pytest.raises(ValueError, match="REGISTERED"):
        generation.register_generated_reference(bible(), job, location_id="NYC_STREET")  # not reviewed/registered yet
    generation.review(job, "owner", approved=True)
    generation.register(job)
    locked = generation.register_generated_reference(bible(), job, location_id="NYC_STREET")
    assert bible()["locations"][0]["reference_images"] == []  # input untouched

    later = generation.plan_request({**need, "request_id": "IMG2", "purpose": "Same street, next morning"}, crime_style(), locked)
    assert [r["sha256"] for r in later["reference_images"]] == [job["output"]["sha256"]]
    assert later["reference_images"][0]["role"] == "approved_reference"
    assert later["continuity"]["style_lock"]["first_reference_sha256"] == job["output"]["sha256"]
    assert "Match the 1 attached reference image" in later["prompt"]
