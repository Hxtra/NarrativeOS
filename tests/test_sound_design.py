"""sound_design.py on a small invented film with known answers: each rule fires where it should and only there."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import sound_design as sd  # noqa: E402


def _film(tmp: Path) -> dict:
    cuts = [("desk1", 5.0), ("forest", 10.0), ("city", 11.5), ("desk2", 20.0), ("beat", 30.0), ("logo", 40.0)]
    ev = {"dur": 44.0, "ev": [{"t": t, "type": "cut", "shot": s} for s, t in cuts] +
          [{"t": 6.0, "type": "pen"}, {"t": 13.0, "type": "reveal_x"}, {"t": 11.2, "type": "bloom"}, {"t": 26.0, "type": "bloom"}, {"t": 22.0, "type": "bend"}]}
    cues = {"cues": [{"t0": 0.0, "t1": 4.0, "text": "one"}, {"t0": 5.5, "t1": 12.9, "text": "two"}, {"t0": 13.0, "t1": 18.0, "text": "three"}]}
    words = [{"w": "look", "t0": 12.95, "t1": 13.3}, {"w": "here", "t0": 13.3, "t1": 13.6}, {"w": "now", "t0": 22.95, "t1": 23.4}]
    lib = {"records": [
        {"kind": "sfx", "role": "boom", "title": "Big Boom", "file": "sfx/boom.mp3"},
        {"kind": "sfx", "role": "wind", "title": "Forest wind", "file": "sfx/forest_wind.mp3"},
        {"kind": "sfx", "role": "pen", "title": "writing with pen", "file": "sfx/pen.mp3"},
        {"kind": "sfx", "role": "pen", "title": "bad pencil", "file": "sfx/bad.mp3", "rejected_reason": "sounds like a dog"},
        {"kind": "sfx", "role": "swell", "title": "Swell", "file": "sfx/swell.mp3"}]}
    for name, obj in [("events.json", ev), ("cues.json", cues), ("words.json", words), ("rights.json", lib)]:
        (tmp / name).write_text(json.dumps(obj), encoding="utf-8")
    brief = {"events": "events.json", "cues": "cues.json", "words": "words.json", "voice_start": 0.0, "library": "rights.json",
             "first_shot": "space", "bookend": "forest", "place_sounds": {"forest": ["forest"]},
             "shots": {"space": {"world": "space"}, "desk1": {"world": "desk", "home": True}, "forest": {"world": "forest", "place": "forest"},
                       "city": {"world": "city", "place": "city"}, "desk2": {"world": "desk", "home": True}, "beat": {"world": "desk", "home": True},
                       "logo": {"world": "brand"}},
             "moments": [{"event": "reveal_x", "purpose": "reveal", "word": "look"}, {"shot": "beat", "purpose": "placed_silence"}]}
    (tmp / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    return brief


def _run(tmp: Path) -> list[dict]:
    brief = _film(tmp)
    obs = sd.observe(brief, tmp)
    P = sd.constrain(sd.reason(obs, brief), obs)
    sd.select(P, json.loads((tmp / "rights.json").read_text())["records"], brief["place_sounds"])
    return P


def _at(P, t, rule=None):
    return [p for p in P if abs(p["t"] - t) < 0.01 and (rule is None or p["rule"] == rule)]


def test_world_jumps_and_home_base(tmp_path):
    P = _run(tmp_path)
    assert _at(P, 5.0, "same_world_cut")                     # space -> desk: the desk is home, no boom
    assert _at(P, 11.5, "world_jump")                        # forest -> city: a jump between story worlds
    assert _at(P, 20.0, "same_world_cut")                    # city -> desk (home)


def test_density_keeps_the_more_confident_hit(tmp_path):
    P = _run(tmp_path)
    jump, reveal = _at(P, 11.5, "world_jump")[0], [p for p in P if p["rule"] == "reveal"][0]
    assert reveal["t"] == 12.95                              # the reveal lands on its word
    assert jump["decision"] == "sound" and reveal["decision"] == "dropped"     # 1.45 s apart: the more confident (0.7 vs 0.6) stays
    assert "more confident" in reveal["dropped_because"]


def test_silence_pauses_places_and_selection(tmp_path):
    P = _run(tmp_path)
    assert _at(P, 30.0, "placed_silence")[0]["decision"] == "silence"
    pause = [p for p in P if p["rule"] == "pause"]
    assert pause and pause[0]["t"] == 4.0 and pause[0]["decision"] == "nothing"   # the 1.5 s gap between lines stays empty
    forest = [p for p in P if p["rule"] == "place" and p.get("place") == "forest"][0]
    assert forest["source"] == "Forest wind"
    city = [p for p in P if p["rule"] == "place" and p.get("place") == "city"][0]
    assert city["file"] is None and "find a real recording" in city["todo"]       # nothing fits: say what to find
    pen = [p for p in P if p["rule"] == "hand_action"][0]
    assert pen["source"] == "writing with pen"                                     # the rejected file is never chosen


def test_one_sound_per_transition(tmp_path):
    P = _run(tmp_path)
    before_jump = [p for p in P if p["role"] == "swell" and abs(p["t"] - 11.2) < 0.01][0]
    alone = [p for p in P if p["role"] == "swell" and abs(p["t"] - 26.0) < 0.01][0]
    assert before_jump["decision"] == "dropped" and "one sound per transition" in before_jump["dropped_because"]   # the boom at 11.5 carries it
    assert alone["decision"] == "sound"                      # no boom near: the swell carries this transition itself


def test_cli(tmp_path):
    _film(tmp_path)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sound_design.py"), str(tmp_path / "brief.json")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "SOUND_PROPOSALS.md").read_text(encoding="utf-8").count("|") > 20
