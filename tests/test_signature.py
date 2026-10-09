"""Signatures: discovering moves from a reference, firing them on a new cut, rules as constraints, the lifecycle.

Rule tests use hand-built moments and items (exact, fast); the Signature library is a temporary folder. The
end-to-end test (a reference edit with a known style, studied, verified by recreation and applied to a different
take) needs the Windows speech engine, faster-whisper and Remotion, and is skipped where any is missing."""
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import signature as sig  # noqa: E402
import talking_head as th  # noqa: E402

CFG = dict(th.CONFIG)


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("NARRATIVEOS_SIGNATURES", str(tmp_path / "signatures"))
    return tmp_path / "signatures"


def vis(t: float, recipe: str = "flash_cut", n: int = 0) -> dict:
    """A breakdown moment: a cut at t with a flash, suggested as `recipe`."""
    return {"id": f"M{n:03d}", "time": t, "events": [{"type": "hard_cut"}, {"type": "flash_frame"}],
            "suggestion": {"recipe": recipe, "why": "a white flash on the cut"}}


def said(kind: str, t: float, text: str = "x") -> dict:
    return {"type": kind, "text": text, "start": t, "end": t + 0.3, "word_index": [0], "emphasis": []}


# ----------------------------------------------------------------------------------------------- discovery
def test_an_effect_that_keeps_landing_on_numbers_becomes_a_move_that_fires_on_numbers():
    speech = [said("NUMBER", 1.0, "three"), said("NUMBER", 4.0, "five"), said("NUMBER", 7.0, "12"), said("LINE_START", 9.0)]
    moves = sig.discover_moves([vis(1.05, n=1), vis(4.1, n=2), vis(6.95, n=3), vis(12.0, "glitch_cut", n=4)], speech)
    flash = next(m for m in moves if m["does"] == {"transition": "flash_cut"})
    assert flash["fires"]["on"] == "NUMBER"
    assert (flash["fires"]["support"], flash["fires"]["of"], flash["fires"]["precision"]) == (3, 3, 1.0)
    assert flash["name"] == "flash cut on number" and [o["said"] for o in flash["evidence"]] == ["three", "five", "12"]
    # Seen once, with nothing said near it: kept, but it does not fire on anything.
    glitch = next(m for m in moves if m["does"] == {"transition": "glitch_cut"})
    assert glitch["fires"]["on"] == "UNCLASSIFIED" and glitch["fires"]["where"] == ["12.00s (no speech moment)"]


def test_a_coincidence_is_not_a_trigger():
    # Flashes on 2 of 6 numbers: support is there, precision (0.33) is not.
    speech = [said("NUMBER", float(t)) for t in range(0, 12, 2)]
    moves = sig.discover_moves([vis(0.1, n=1), vis(4.1, n=2)], speech)
    assert moves[0]["fires"]["on"] == "UNCLASSIFIED" and moves[0]["fires"]["seen"] == 2


def test_a_zoom_without_a_cut_is_a_punch_in_move_with_its_measured_scale():
    m = {"id": "M1", "time": 2.0, "events": [{"type": "zoom", "evidence": {"total_scale": 1.18}}], "suggestion": {}}
    m2 = copy.deepcopy(m) | {"id": "M2", "time": 5.0}
    moves = sig.discover_moves([m, m2], [said("CONTRAST", 2.1), said("CONTRAST", 5.0)])
    assert moves[0]["does"] == {"punch_in": 1.18} and moves[0]["fires"]["on"] == "CONTRAST"


# ----------------------------------------------------------------------------------------------- firing
def cut_of(segs: list[tuple[float, float]], words_at: list[tuple[str, float, int]]):
    items = [{"id": f"T{n + 1:03d}", "asset_id": "raw", "timeline_in": a, "timeline_out": b, "source_in": a + 10.0}
             | ({"motion": {"kind": "push_in", "scale_from": 1.12, "scale_to": 1.12}} if n % 2 else {}) for n, (a, b) in enumerate(segs)]
    cap = [{"text": w, "t_in": t, "t_out": t + 0.3, "index": i, "segment": s} for i, (w, t, s) in enumerate(words_at)]
    return items, cap


MOVE = {"id": "MV01", "name": "flash cut on number", "does": {"transition": "flash_cut"},
        "fires": {"on": "NUMBER", "support": 3, "of": 3, "precision": 1.0}, "status": "draft"}


def test_a_move_uses_the_cut_already_at_its_moment():
    items, cap = cut_of([(0, 2), (2, 4)], [("we", 0.2, 0), ("tested", 0.6, 0), ("two", 2.05, 1), ("cameras", 2.5, 1)])
    fired, _ = sig.fire_moves([MOVE], [said("NUMBER", 2.05, "two") | {"word_index": [2]}], items, cap, CFG)
    assert len(items) == 2 and items[1]["transition_in"]["recipe"] == "flash_cut"
    assert fired[0]["result"] == "flash_cut into T002" and "3/3" in fired[0]["why"]


def test_a_move_cuts_the_segment_before_its_word_when_the_reference_did():
    items, cap = cut_of([(0, 4)], [("it", 0.2, 0), ("cost", 0.6, 0), ("forty", 1.6, 0), ("dollars", 2.0, 0)])
    fired, _ = sig.fire_moves([MOVE], [said("NUMBER", 1.6, "forty") | {"word_index": [2]}], items, cap, CFG)
    a, b = items
    # The cut sits in the pause before "forty" (0.12 s before it), the source continues seamlessly, and the new piece
    # takes the other framing so the cut reads.
    assert a["timeline_out"] == b["timeline_in"] == 1.48 and b["source_in"] == 11.48
    assert b["transition_in"]["recipe"] == "flash_cut" and "motion" not in a and b["motion"]["scale_from"] == 1.12
    assert [w["segment"] for w in cap] == [0, 0, 1, 1] and b["id"] == "T001b"
    assert fired[0]["result"] == "flash_cut into T001b (cut made here)"


def test_a_moment_at_a_segment_edge_is_skipped_and_said_so():
    items, cap = cut_of([(0, 4)], [("forty", 0.1, 0), ("dollars", 0.5, 0)])
    fired, _ = sig.fire_moves([MOVE], [said("NUMBER", 0.1, "forty")], items, cap, CFG)
    assert len(items) == 1 and "transition_in" not in items[0]
    assert fired[0]["result"] == "skipped" and "edge" in fired[0]["reason"]


def test_rejected_and_unclassified_moves_never_fire():
    items, cap = cut_of([(0, 2), (2, 4)], [("two", 2.05, 1)])
    moves = [MOVE | {"status": "rejected"}, MOVE | {"id": "MV02", "fires": {"on": "UNCLASSIFIED"}}]
    fired, _ = sig.fire_moves(moves, [said("NUMBER", 2.05, "two")], items, cap, CFG)
    assert fired == [] and "transition_in" not in items[1]


# ----------------------------------------------------------------------------------------------- rules and captions
def test_rules_constrain_the_built_timeline():
    items = [{"id": f"T{n}", "timeline_in": n * 6.0, "timeline_out": n * 6.0 + 6.0} for n in range(10)]  # one minute
    for it in items[1:]:
        it["transition_in"] = {"type": "recipe", "recipe": "glitch_cut" if it["id"] == "T3" else "flash_cut"}
    ir = {"tracks": [{"kind": "video", "items": items}, {"kind": "graphic", "items": [{"template": "kinetic_captions", "params": {"maxWords": 3}}]}]}
    s = {"rules": [{"id": "R01", "constraint": {"avoid": ["glitch_cut"]}}, {"id": "R02", "constraint": {"max_transitions_per_minute": 4}},
                   {"id": "R03", "constraint": {"captions": {"maxWords": 2}}}]}
    changes = sig.apply_rules(s, ir, [])
    assert [it["id"] for it in items if "transition_in" in it] == ["T1", "T2", "T4", "T5"]
    assert ir["tracks"][1]["items"][0]["params"]["maxWords"] == 2
    assert changes[0] == {"rule": "R01", "change": "removed glitch_cut into T3"} and len(changes) == 1 + 4 + 1


def test_a_signature_caption_position_never_covers_the_face():
    frame = {"face_y": 0.32, "captions_position": "lower"}
    assert th.caption_position({"position": "upper", "maxWords": 2}, frame) == {"position": "lower", "maxWords": 2}
    assert frame["caption_conflict"]["wanted"] == "upper" and frame["caption_conflict"]["used"] == "lower"
    clear = {"face_y": 0.32, "captions_position": "lower"}
    assert th.caption_position({"position": "lower"}, clear) == {"position": "lower"} and "caption_conflict" not in clear
    assert th.caption_position({"position": "upper"}, {"status": "NOT_MEASURED"}) == {"position": "upper"}  # no face measured


def test_caption_style_is_read_from_measured_text_and_skips_the_cover_frame():
    bd = {"typography": {"status": "MEASURED", "lines": [
        {"text": "THE BIG TITLE", "box_frac": [0.1, 0.1, 0.9, 0.3], "height_frac": 0.2, "uppercase": True, "cover_frame": True},
        {"text": "IT COST", "box_frac": [0.3, 0.7, 0.7, 0.78], "height_frac": 0.08, "uppercase": True},
        {"text": "FORTY", "box_frac": [0.3, 0.7, 0.7, 0.8], "height_frac": 0.1, "uppercase": True},
        {"text": "DOLLARS NOW", "box_frac": [0.3, 0.72, 0.7, 0.8], "height_frac": 0.09, "uppercase": True}]}}
    c = sig._caption_style(bd)
    assert c["lines_read"] == 3 and c["params"] == {"position": "lower", "maxWords": 2, "uppercase": True, "fontScale": 1.02}
    assert sig._caption_style({})["status"] == "NOT_MEASURED"


# ----------------------------------------------------------------------------------------------- lifecycle
def saved(sig_id: str = "s1") -> dict:
    return sig.save({"schema": sig.SCHEMA, "id": sig_id, "label": sig_id, "status": "experimental", "version": 0,
                     "pipeline": {"kind": "talking_head"}, "moves": [MOVE], "rules": [], "shipped": []}, "test")


def test_every_change_is_a_new_version_and_studies_never_overwrite(library, tmp_path):
    saved()
    sig.set_status("s1", "pending", "under review")
    assert sig.load("s1")["version"] == 2 and sorted(p.name for p in (library / "s1" / "versions").iterdir()) == ["v001.json", "v002.json"]
    with pytest.raises(sig.SignatureError, match="never overwritten"):
        sig.study(tmp_path / "any.mp4", "s1")
    with pytest.raises(sig.SignatureError):
        sig.sig_dir("../escape")


def test_proven_needs_two_approved_shipped_edits(tmp_path):
    saved()
    for name, ok in (("p1", True), ("p2", False)):
        (tmp_path / name).mkdir()
        sig.ship("s1", tmp_path / name, approved=ok)
    with pytest.raises(sig.SignatureError, match="has 1"):
        sig.set_status("s1", "proven")
    (tmp_path / "p3").mkdir()
    sig.ship("s1", tmp_path / "p3", approved=True)
    assert sig.set_status("s1", "proven")["status"] == "proven"


def test_a_rule_needs_notes_from_two_projects():
    saved()
    a = sig.note("s1", "p1", "no glitch on numbers")
    b = sig.note("s1", "p1", "still no glitch")
    with pytest.raises(sig.SignatureError, match="at least two projects"):
        sig.promote_rule("s1", [a["id"], b["id"]], "no glitches")
    c = sig.note("s1", "p2", "glitch again, remove")
    rule = sig.promote_rule("s1", [a["id"], c["id"]], "no glitches", {"avoid": ["glitch_cut"]})["rules"][0]
    assert rule["projects"] == ["p1", "p2"] and rule["constraint"] == {"avoid": ["glitch_cut"]}


def test_studio_shows_the_pin_and_keeps_corrections_as_signature_notes(tmp_path):
    sys.path.insert(0, str(ROOT / "timeline-editor" / "server"))
    import studio
    saved()
    p = tmp_path / "proj"
    p.mkdir()
    (p / "signature_pin.json").write_text(json.dumps({"id": "s1", "version": 1, "sha": "x", "status": "experimental"}))
    shown = studio._signature(p)
    assert shown["moves"] == [{"id": "MV01", "name": "flash cut on number", "fires": "NUMBER"}] and shown["current_version"] == 1
    nid = studio._record_signature_note(p, {"request": "no flash here", "operations": [{"op": "set_transition"}]})
    assert [n["id"] for n in sig.notes("s1")] == [nid] and sig.notes("s1")[0]["project"] == "proj"
    assert studio._signature(tmp_path) is None


# ----------------------------------------------------------------------------------------------- end to end
def _has_tools() -> bool:
    if sys.platform != "win32" or not shutil.which("powershell"):
        return False
    try:
        import faster_whisper  # noqa: F401
        import remotion_bridge as rb
    except ImportError:
        return False
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; 'ok'"], capture_output=True, text=True)
    return r.returncode == 0 and rb.available()[0]


def take(ssml_body: str, folder: Path) -> Path:
    """A raw take: a test pattern with spoken audio (Windows speech engine)."""
    (folder / "media").mkdir(parents=True)
    wav = folder / "media" / "raw.wav"
    ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">{ssml_body}</speak>'
    ps = folder / "speak.ps1"
    ps.write_text("Add-Type -AssemblyName System.Speech\n$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                  f"$s.SetOutputToWaveFile('{wav}')\n$s.SpeakSsml('{ssml}')\n$s.Dispose()\n", encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], check=True, capture_output=True)
    out = folder / "media" / "raw.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30", "-i", str(wav), "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
    return out


@pytest.mark.skipif(not _has_tools(), reason="needs the Windows speech engine, faster-whisper and Remotion")
def test_a_style_is_learned_from_a_reference_verified_by_recreation_and_applied_to_a_new_take(tmp_path):
    import compile_timeline as ct
    b = '<break time="{}ms"/>'
    ref = tmp_path / "ref"
    raw = take(f"I posted{b.format(700)}three videos a week.{b.format(800)}Nothing happened.{b.format(800)}Then I posted{b.format(700)}"
               f"five a day.{b.format(800)}And after{b.format(700)}twelve weeks,{b.format(600)}it finally worked.", ref)
    # The reference's style, known by construction: a flash_cut right before every number, nowhere else.
    ir, rep = th.build(ref, [raw], None, "16:9", None, "documentary_general", dict(CFG))
    items = ir["tracks"][0]["items"]
    caps = ir["tracks"][1]["items"][0]["params"]["words"]
    for m in (m for m in rep["moments"] if m["type"] == "NUMBER"):
        w = caps[m["word_index"][0]]
        k = next(i for i, it in enumerate(items) if it["source_in"] <= w["src_start"] < it["source_in"] + it["timeline_out"] - it["timeline_in"])
        it, s_src = items[k], w["src_start"] - 0.06
        if k and s_src - it["source_in"] < 0.3:  # the number already starts a segment (the pause before it was cut)
            it["transition_in"] = {"type": "recipe", "recipe": "flash_cut"}
            continue
        new = copy.deepcopy(it) | {"id": it["id"] + "n", "source_in": round(s_src, 3), "transition_in": {"type": "recipe", "recipe": "flash_cut"}}
        new["timeline_in"] = it["timeline_out"] = round(it["timeline_in"] + s_src - it["source_in"], 3)
        items.insert(k + 1, new)
    assert sum(1 for it in items if "transition_in" in it) == 3
    th.register_clips(ref, [raw], approve=True)
    ct.compile_timeline(ref, ir, tmp_path / "reference.mp4")

    s = sig.study(tmp_path / "reference.mp4", "flash_numbers")
    flash = next(m for m in s["moves"] if m["does"].get("transition") == "flash_cut")
    assert flash["fires"]["on"] == "NUMBER" and flash["fires"]["support"] == 3 and flash["fires"]["precision"] == 1.0
    assert flash["recreation"]["status"] == "verified"
    assert s["pipeline"]["kind"] == "talking_head" and s["status"] == "experimental"
    assert not any((ROOT / "templates/narrativeos-video-templates/project/src/styles/generated").glob("flash_numbers*"))

    new = tmp_path / "new"
    raw2 = take(f"We tested{b.format(700)}two cameras.{b.format(800)}The cheap one won.{b.format(800)}It cost{b.format(700)}forty dollars."
                f"{b.format(800)}The other cost{b.format(700)}nine hundred.", new)
    ir2, rep2 = sig.apply("flash_numbers", new, [raw2])
    flashed = [f for f in rep2["fired"] if f["move"] == flash["id"] and f["result"] != "skipped"]
    assert {th._tok(f["text"]) for f in flashed} == {"2", "40", "900"}  # every number in the new take ("$40." as written)
    assert len(flashed) == len([m for m in rep2["moments"] if m["type"] == "NUMBER"])
    v = ir2["tracks"][0]["items"]
    assert sum(1 for it in v if (it.get("transition_in") or {}).get("recipe") == "flash_cut") == len(flashed)
    assert json.loads((new / "signature_pin.json").read_text())["version"] == s["version"]
