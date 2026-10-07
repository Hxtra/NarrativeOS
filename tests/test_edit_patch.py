"""Typed edit patches: ripple, revision locality, transitions, interpreter phrasing and provider fallback."""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import edit_patch as ep  # noqa: E402


def ir():
    return {"ir_version": "3.0", "canvas": {"width": 320, "height": 180, "fps": 24, "sample_rate": 48000},
            "tracks": [
                {"id": "v_main", "kind": "video", "items": [
                    {"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 3.25},
                    {"id": "B", "asset_id": "blue", "timeline_in": 2.75, "timeline_out": 6.0, "source_in": 1.0,
                     "transition_in": {"type": "crossfade", "duration": 0.5}},
                    {"id": "C", "asset_id": "green", "timeline_in": 6.0, "timeline_out": 8.0, "transition_in": {"type": "dip_black", "duration": 0.8}},
                    {"id": "D", "asset_id": "red", "timeline_in": 8.0, "timeline_out": 10.0}]},
                {"id": "a_vo", "kind": "audio", "role": "narration", "items": [{"id": "VO", "asset_id": "vo", "timeline_in": 0.5, "timeline_out": 6.0}]},
                {"id": "a_music", "kind": "audio", "role": "music", "items": [{"id": "M", "asset_id": "music", "timeline_in": 0, "timeline_out": 10.0, "gain_db": -6}]},
                {"id": "a_sfx", "kind": "audio", "role": "sfx", "items": [{"id": "BEEP", "asset_id": "beep", "timeline_in": 7.0, "timeline_out": 7.3}]},
                {"id": "cc", "kind": "caption", "items": [{"id": "CAP", "timeline_in": 6.5, "timeline_out": 7.5, "text": "HELLO"}]}]}


def items(t):
    return {i["id"]: i for tr in t["tracks"] for i in tr["items"]}


def run(t, *ops):
    return ep.apply(t, {"operations": list(ops)}, check=False)


def test_shortening_a_shot_ripples_and_keeps_the_crossfade_exact():
    r = run(ir(), {"op": "set_duration", "item_id": "A", "duration": 2.0})
    it = items(r["timeline"])
    assert it["A"]["timeline_out"] == 2.0
    assert it["B"]["timeline_in"] == pytest.approx(1.5) and it["A"]["timeline_out"] - it["B"]["timeline_in"] == pytest.approx(0.5)
    assert it["CAP"]["timeline_in"] == pytest.approx(5.25) and it["BEEP"]["timeline_in"] == pytest.approx(5.75)
    d = r["diff"]
    # The music bed ended with the programme, so it is trimmed with it (an edit, reported), never left past the picture.
    assert [e["id"] for e in d["edited"]] == ["A", "M"] and it["M"]["timeline_out"] == pytest.approx(8.75)
    assert {s["id"] for s in d["shifted"]} == {"B", "C", "D", "CAP", "BEEP"} and all(s["by"] == pytest.approx(-1.25) for s in d["shifted"])
    assert d["untouched"] == 1  # narration never moves on its own
    assert any("VO" in w and "behind" in w for w in r["warnings"])  # narration spans the edit: sync warning
    assert any("M (music)" in w and "earlier" in w for w in r["warnings"])


def test_a_longer_programme_never_stretches_a_bed_silently():
    r = run(ir(), {"op": "set_duration", "item_id": "A", "duration": 4.0})
    it = items(r["timeline"])
    assert it["M"]["timeline_out"] == 10.0 and it["D"]["timeline_out"] == pytest.approx(10.75)
    assert any("M (music) now ends 0.75 s before the picture" in w for w in r["warnings"])
    # A bed that does not reach the programme end is left alone, with no warning.
    t = ir()
    items(t)["M"]["timeline_out"] = 5.0
    r = run(t, {"op": "set_duration", "item_id": "A", "duration": 2.0})
    assert items(r["timeline"])["M"]["timeline_out"] == 5.0 and not any("M (music)" in w for w in r["warnings"])


def test_pace_tightens_every_shot_starting_in_the_range():
    r = run(ir(), {"op": "pace", "from": 5.9, "to": 10, "factor": 0.5})
    it = items(r["timeline"])
    assert it["C"]["timeline_out"] - it["C"]["timeline_in"] == pytest.approx(1.0)
    assert it["D"]["timeline_in"] == pytest.approx(7.0) and it["D"]["timeline_out"] == pytest.approx(8.0)
    assert it["A"] == items(ir())["A"] and it["B"] == items(ir())["B"]  # outside the range: untouched
    with pytest.raises(ep.PatchError):
        run(ir(), {"op": "pace", "from": 20, "to": 30, "factor": 0.8})


def test_removing_a_shot_closes_the_gap_and_keeps_overlaps_representable():
    r = run(ir(), {"op": "remove", "item_id": "B"})
    it = items(r["timeline"])
    assert "B" not in it and r["diff"]["removed"] == ["B"]
    # A ended 0.5 s into B (crossfade); after closing the gap C starts at 2.75 and A still overlaps it by 0.5 s,
    # so C's transition becomes that crossfade rather than an unrepresentable overlap.
    assert it["C"]["timeline_in"] == pytest.approx(2.75) and it["C"]["transition_in"] == {"type": "crossfade", "duration": 0.5}
    assert it["D"]["timeline_in"] == pytest.approx(4.75)


def test_transition_changes_touch_only_the_two_shots_involved():
    r = run(ir(), {"op": "set_transition", "item_id": "D", "type": "crossfade", "duration": 0.6})
    it = items(r["timeline"])
    assert it["C"]["timeline_out"] == pytest.approx(8.6) and it["D"]["transition_in"]["type"] == "crossfade"
    assert {e["id"] for e in r["diff"]["edited"]} == {"C", "D"} and not r["diff"]["shifted"]
    r = run(ir(), {"op": "set_transition", "item_id": "B", "type": "cut"})
    assert items(r["timeline"])["A"]["timeline_out"] == pytest.approx(2.75) and "transition_in" not in items(r["timeline"])["B"]
    with pytest.raises(ep.PatchError):
        run(ir(), {"op": "set_transition", "item_id": "A", "type": "crossfade", "duration": 0.5})


def test_gain_text_motion_replace_and_move():
    r = run(ir(), {"op": "set_gain", "track_id": "a_music", "delta_db": -3}, {"op": "set_text", "item_id": "CAP", "text": "BYE"},
            {"op": "set_motion", "item_id": "D", "kind": "push_in", "scale_to": 1.1}, {"op": "replace_asset", "item_id": "C", "asset_id": "blue"},
            {"op": "move", "item_id": "BEEP", "timeline_in": 9.0})
    it = items(r["timeline"])
    assert it["M"]["gain_db"] == -9 and it["CAP"]["text"] == "BYE" and it["D"]["motion"]["kind"] == "push_in"
    assert it["C"]["asset_id"] == "blue" and it["BEEP"]["timeline_in"] == 9.0 and it["BEEP"]["timeline_out"] == pytest.approx(9.3)
    with pytest.raises(ep.PatchError):
        run(ir(), {"op": "move", "item_id": "A", "timeline_in": 1})  # main shots move by durations, not 'move'
    with pytest.raises(ep.PatchError):
        run(ir(), {"op": "set_duration", "item_id": "A", "duration": 0.2})


def test_a_patch_built_on_another_version_is_refused():
    base = ir()
    patch = ep.propose(base, "make this faster", {"item_id": "A"})["patch"]
    changed = copy.deepcopy(base)
    items(changed)["M"]["gain_db"] = -12
    with pytest.raises(ep.PatchError, match="changed since"):
        ep.apply(changed, patch, check=False)
    assert ep.apply(base, patch, check=False)["diff"]["edited"][0]["id"] == "A"


@pytest.mark.parametrize("message,selection,expected", [
    ("make this faster", {"item_id": "A"}, {"op": "set_duration", "item_id": "A", "duration": 2.6}),
    ("let it breathe", {"item_id": "D"}, {"op": "set_duration", "item_id": "D", "duration": 2.5}),
    ("speed up from 0:06 to 0:10", None, {"op": "pace", "from": 6.0, "to": 10.0, "factor": 0.8}),
    ("increase the pace in this part", {"from": 0, "to": 6}, {"op": "pace", "from": 0.0, "to": 6.0, "factor": 0.8}),
    ("remove shot 2", None, {"op": "remove", "item_id": "B"}),
    ("dip to black here", {"item_id": "D"}, {"op": "set_transition", "item_id": "D", "type": "dip_black", "duration": 0.8}),
    ("crossfade into this", {"item_id": "D"}, {"op": "set_transition", "item_id": "D", "type": "crossfade", "duration": 0.5}),
    ("music down 6 dB", None, {"op": "set_gain", "track_id": "a_music", "delta_db": -6.0}),
    ("narration a bit louder", None, {"op": "set_gain", "track_id": "a_vo", "delta_db": 3.0}),
    ('change the caption to "THE END"', {"item_id": "CAP"}, {"op": "set_text", "item_id": "CAP", "text": "THE END"}),
    ("push in a lot", {"item_id": "C"}, {"op": "set_motion", "item_id": "C", "kind": "push_in", "scale_from": 1.0, "scale_to": 1.12}),
    ("replace with blue", {"item_id": "D"}, {"op": "replace_asset", "item_id": "D", "asset_id": "blue"}),
    ("make it 2.5 s", {"item_id": "A"}, {"op": "set_duration", "item_id": "A", "duration": 2.5}),
])
def test_plain_words_become_typed_operations(message, selection, expected):
    r = ep.interpret(message, ir(), selection, asset_ids={"red", "blue", "green"})
    assert r["understood"] and r["operations"] == [expected], r


def test_unclear_requests_ask_instead_of_guessing():
    r = ep.interpret("make this faster", ir(), None)
    assert not r["operations"] and "Select" in r["reply"]
    r = ep.interpret("make it more cinematic", ir(), {"item_id": "A"})
    assert not r["understood"] and "Try" in r["reply"]


def test_a_reasoning_provider_is_asked_only_for_what_the_rules_cannot_parse():
    calls = []

    def fake(task, context):
        calls.append(task)
        return {"reply": "Shortening A for energy.", "operations": [{"op": "set_duration", "item_id": "A", "duration": 2.0}]}

    provider = {"type": "callable", "name": "test", "model": "fake-1", "callable": fake}
    p = ep.propose(ir(), "make it more cinematic", {"item_id": "A"}, provider=provider)
    assert calls == ["propose_edit_patch"] and p["patch"]["basis"] == "model:test/fake-1"
    assert ep.apply(ir(), p["patch"], check=False)["diff"]["edited"][0]["id"] == "A"
    p = ep.propose(ir(), "make this faster", {"item_id": "A"}, provider=provider)
    assert calls == ["propose_edit_patch"] and p["patch"]["basis"] == "rules"  # rules handled it; the model was not called


def test_patches_are_validated_by_the_compiler(tmp_path):
    from test_compile_timeline import clip
    (tmp_path / "m").mkdir()
    clip(tmp_path / "m" / "red.mp4", "0xC00000", None, 4)
    import json
    (tmp_path / "assets.json").write_text(json.dumps({"assets": [{"asset_id": "red", "local_path": "m/red.mp4", "status": "approved"}]}))
    t = {"ir_version": "3.0", "canvas": {"width": 320, "height": 180, "fps": 24, "sample_rate": 48000},
         "tracks": [{"id": "v", "kind": "video", "items": [{"id": "A", "asset_id": "red", "timeline_in": 0, "timeline_out": 2}]}]}
    ok = ep.apply(t, {"operations": [{"op": "set_duration", "item_id": "A", "duration": 3}]}, tmp_path)
    assert ok["validation"]["errors"] == []
    bad = ep.apply(t, {"operations": [{"op": "set_duration", "item_id": "A", "duration": 6}]}, tmp_path)
    assert any("asset is 4.000 s" in e for e in bad["validation"]["errors"])
