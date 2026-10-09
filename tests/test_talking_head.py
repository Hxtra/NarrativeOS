"""Talking-head core: best takes, the tight cut, firing moments and vertical captions inside platform safe zones.

Rule tests use hand-built word lists (exact, fast). The end-to-end test speaks a scripted raw take with the Windows
speech engine, transcribes it with faster-whisper and renders it 9:16; it is skipped where either is missing."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import talking_head as th  # noqa: E402

CFG = dict(th.CONFIG)


def words(spec: str, start: float = 0.0, gap: float = 0.05, dur: float = 0.3) -> list[dict]:
    """'so the|0.9 real' -> words; '|x' after a word adds an x-second pause after it."""
    out, t = [], start
    for tok in spec.split():
        text, _, pause = tok.partition("|")
        out.append({"text": text, "start": round(t, 3), "end": round(t + dur, 3), "prob": 0.95})
        t += dur + gap + (float(pause) if pause else 0.0)
    return out


def test_lines_split_at_pauses_and_sentence_ends():
    ls = th.lines_of(words("So the real problem is|0.9 um|0.7 So the real problem is quality. It costs|0.3 nothing."), "c", CFG)
    assert [ln["text"] for ln in ls] == ["So the real problem is", "um", "So the real problem is quality.", "It costs nothing."]
    assert ls[1]["content"] == []  # a hesitation-only line


def test_a_pause_inside_a_sentence_does_not_make_a_separate_attempt():
    # "I posted" alone would look like an earlier attempt at "Then I posted" and be dropped.
    ls = th.lines_of(words("I posted|0.86 three videos a week. Nothing happened. Then I posted|0.8 five a day."), "c", CFG)
    assert [ln["text"] for ln in ls] == ["I posted three videos a week.", "Nothing happened.", "Then I posted five a day."]
    assert len(th.lines_of(words("I posted|2.5 three videos."), "c", CFG)) == 2  # a very long pause still ends the line


def test_false_starts_lose_and_the_later_complete_take_wins():
    ls = th.lines_of(words("So the real|1.0 So the real problem is quality.|1.2 This took three years to figure out.|1.5 "
                           "This took three years to learn."), "c", CFG)
    groups, off = th.group_takes(ls, None, CFG)
    d = th.choose_takes(groups, None)
    kept = [x["kept"]["text"] for x in d]
    assert kept == ["So the real problem is quality.", "This took three years to learn."] and not off
    reasons = {t["text"]: t["reason"] for x in d for t in x["takes"] if t["decision"] == "dropped"}
    assert reasons["So the real"].startswith("false start")
    assert "later takes usually land better" in reasons["This took three years to figure out."]


def test_a_script_decides_which_lines_belong_and_their_order():
    script = th.script_lines("It costs nothing. The real problem is quality.")
    ls = th.lines_of(words("The real problem is quality.|1.0 Hold on, let me check my notes.|1.0 It costs nothing."), "c", CFG)
    groups, off = th.group_takes(ls, script, CFG)
    d = th.choose_takes(groups, script)
    assert [x["kept"]["text"] for x in d] == ["It costs nothing.", "The real problem is quality."]  # script order
    assert [o["text"] for o in off] == ["Hold on, let me check my notes."]


def test_the_cut_removes_hesitations_and_repeats_without_leaking_them_back_in():
    take = th.lines_of(words("This is the the|0.6 um|0.6 real answer."), "c", CFG)
    merged = {**take[0], "words": [w for ln in take for w in ln["words"]], "id": "c#1"}
    segs, removed = th.cut_take(merged, 30.0, CFG)
    assert [r["text"] for r in removed] == ["the", "um"] and [r["why"] for r in removed] == ["repeated word", "hesitation"]
    # Each removal is a jump cut: the stumbled "the", then the pause and the "um".
    assert [" ".join(w["text"] for w in s["words"]) for s in segs] == ["This is", "the", "real answer."]
    um = next(r for r in removed if r["text"] == "um")
    assert segs[1]["src_out"] <= um["start"] and segs[2]["src_in"] >= um["end"]  # pads stop at the cut-out word
    assert segs[0]["src_out"] <= removed[0]["start"] + 1e-9  # and at the dropped repeat


def test_back_to_back_segments_never_replay_audio():
    a = {"clip": "c", "src_in": 0.9, "src_out": 2.14, "words": [{"start": 1.0, "end": 2.0}], "take": "c#1"}
    b = {"clip": "c", "src_in": 2.02, "src_out": 3.14, "words": [{"start": 2.1, "end": 3.0}], "take": "c#2"}
    assert th.join_segments([dict(a), dict(b)], []) == [{**a, "src_out": 3.14, "words": a["words"] + b["words"]}]  # merged
    um = {"clip": "c", "start": 2.03, "end": 2.08, "text": "um"}
    split = th.join_segments([dict(a), dict(b)], [um])
    assert len(split) == 2 and split[0]["src_out"] == split[1]["src_in"] == 2.05  # cut at the midpoint, no overlap


def test_moments_fire_on_what_is_said():
    ws = words("First, it is not quantity, it is quality. Look at this. It took 3 years. Coffee or tea? Ask Sarah.")
    tl = [{"text": w["text"], "t_in": w["start"], "t_out": w["end"], "index": i, "segment": 0} for i, w in enumerate(ws)]
    lines, cur = [], []
    for w in tl:  # one spoken line per sentence, as lines_of() makes them
        cur.append(w)
        if w["text"][-1] in ".?!":
            lines.append(cur)
            cur = []
    ms = th.find_moments(tl, lines)
    by = {}
    for m in ms:
        by.setdefault(m["type"], []).append(m)
    assert {"HOOK", "LIST", "CONTRAST", "CUE", "NUMBER", "QUESTION", "NAME"} <= set(by)
    contrast = next(m for m in by["CONTRAST"] if "quantity" in m["text"])
    assert [tl[i]["text"] for i in contrast["emphasis"]] == ["quantity,", "quality."]
    assert [m["text"] for m in by["NUMBER"]] == ["3"] and by["NAME"][0]["text"].startswith("Sarah")
    assert "Phase 3" in by["CUE"][0]["evidence"] and by["CUE"][0]["status"] == "MEASURED"


def test_word_times_come_from_the_phrase_they_were_said_in():
    # Measured from a real decode: whole-take, the model put "three" before the pause; phrase by phrase, after it.
    whole = [{"text": "I", "start": 0.0, "end": 0.2}, {"text": "posted", "start": 0.2, "end": 0.6}, {"text": "three", "start": 0.6, "end": 1.66},
             {"text": "videos", "start": 1.66, "end": 2.06}, {"text": "uh", "start": 2.06, "end": 2.2}, {"text": "week.", "start": 2.3, "end": 2.64}]
    phrase = [{"text": "I", "start": 0.0, "end": 0.22}, {"text": "posted.", "start": 0.22, "end": 0.6}, {"text": "3", "start": 1.36, "end": 1.68},
              {"text": "videos", "start": 1.68, "end": 2.08}, {"text": "did", "start": 2.1, "end": 2.2}, {"text": "week.", "start": 2.4, "end": 2.6}]
    out = th.align_to_phrases(whole, phrase)
    assert [w["text"] for w in out] == ["I", "posted", "three", "videos", "uh", "week."]  # text and punctuation from the whole take
    assert (out[2]["start"], out[2]["end"], out[2]["model_times"]) == (1.36, 1.68, [0.6, 1.66])  # "three" = "3", after the pause
    assert (out[4]["start"], out[4]["end"]) == (2.08, 2.4)  # unmatched, did not fit between its neighbours: their gap


def test_word_edges_are_trimmed_to_the_measured_sound():
    db = np.full(300, -90.0)
    db[10:88] = -15.0   # "I posted"
    db[148:269] = -16.0  # "three videos a week"
    assert th.phrases_of(db) == [[0.1, 0.88], [1.48, 2.69]]
    w = th.refine_words([{"text": "three", "start": 1.36, "end": 1.68}, {"text": "posted", "start": 0.2, "end": 1.3}], db)
    assert (w[0]["start"], w[0]["end"]) == (1.46, 1.68) and w[0]["model_times"] == [1.36, 1.68]
    assert (w[1]["start"], w[1]["end"]) == (0.2, 0.91)  # the pause after it is not part of the word
    assert th.phrases_of(np.full(300, -30.0)) is None  # no speech/silence contrast: pauses cannot be measured


def test_one_as_a_pronoun_is_not_a_number():
    def nums(text):
        ws = [{"text": x, "t_in": i, "t_out": i + 0.3, "index": i, "segment": 0} for i, x in enumerate(text.split())]
        return [m["text"] for m in th.find_moments(ws, [ws]) if m["type"] == "NUMBER"]
    assert nums("The cheap one won.") == nums("One of them failed.") == nums("Which one is better?") == []
    assert nums("I had one job.") == nums("It took one year.") == ["one"]


# ----------------------------------------------------------------------------------------------- end to end
def _has_sapi() -> bool:
    if sys.platform != "win32" or not shutil.which("powershell"):
        return False
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; 'ok'"], capture_output=True, text=True)
    return r.returncode == 0 and "ok" in r.stdout


def _has_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


SSML = ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">So the real problem is<break time="900ms"/>'
        'um<break time="700ms"/>So the real problem is not quantity, it is quality.<break time="1300ms"/>This took me three years to '
        'figure out.<break time="1500ms"/>This took me three years to learn.<break time="1200ms"/>It costs nothing.<break time="600ms"/></speak>')


def speak(ssml: str, wav: Path) -> None:
    ps = wav.with_suffix(".ps1")
    ps.write_text("Add-Type -AssemblyName System.Speech\n$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                  f"$s.SetOutputToWaveFile('{wav}')\n$s.SpeakSsml('{ssml}')\n$s.Dispose()\n", encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], check=True, capture_output=True)


@pytest.mark.skipif(not (_has_sapi() and _has_whisper()), reason="needs the Windows speech engine and faster-whisper")
def test_raw_take_to_vertical_cut_with_captions_inside_the_safe_area(tmp_path):
    import compile_timeline as ct
    import remotion_bridge as rb
    (tmp_path / "media").mkdir()
    speak(SSML, tmp_path / "media" / "raw.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x404040:s=640x360:r=30", "-i", str(tmp_path / "media" / "raw.wav"),
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp_path / "media" / "raw.mp4")], check=True)
    ir, report = th.build(tmp_path, [tmp_path / "media" / "raw.mp4"], None, "9:16", "reels", "documentary_general", dict(th.CONFIG))
    th.register_clips(tmp_path, [tmp_path / "media" / "raw.mp4"], approve=False)
    kept = [ln["takes"][[t["decision"] for t in ln["takes"]].index("kept")]["text"].lower() for ln in report["lines"]]
    assert any("quality" in k for k in kept) and any("learn" in k for k in kept) and not any("figure out" in k for k in kept)
    dropped = [t["reason"] for ln in report["lines"] for t in ln["takes"] if t["decision"] == "dropped"]
    assert any(r.startswith("false start") for r in dropped)
    assert any(o["reason"] == "only hesitation sounds" for o in report["off_script"])
    assert report["cut"]["cut_duration"] < 0.6 * report["cut"]["raw_duration"]
    assert any(m["type"] == "NUMBER" for m in report["moments"])
    (tmp_path / "timeline_v3.json").write_text(json.dumps(ir))
    assert ct.validate(ir, tmp_path)["errors"] == []
    if not rb.available()[0]:
        pytest.skip("Remotion not available for the caption render")
    out = tmp_path / "cut.mp4"
    m = ct.compile_timeline(tmp_path, ir, Path("cut.mp4"), preview=True)
    assert m["status"] == "passed" and m["canvas"]["width"] < m["canvas"]["height"]
    bare = json.loads(json.dumps(ir))
    bare["tracks"] = [t for t in bare["tracks"] if t["id"] != "captions"]
    ct.compile_timeline(tmp_path, bare, Path("bare.mp4"), preview=True)
    W, H = m["canvas"]["width"], m["canvas"]["height"]
    safe = ct.PLATFORM_SAFE["reels"]
    inside_hits = 0
    for t in np.arange(0.3, m["duration"] - 0.2, 0.5):
        frames = []
        for f in (out, tmp_path / "bare.mp4"):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(f), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                                 capture_output=True, check=True).stdout
            frames.append(np.frombuffer(raw, np.uint8).reshape(H, W).astype(float))
        text = np.abs(frames[0] - frames[1]) > 40
        ys, xs = np.nonzero(text)
        if ys.size:
            inside_hits += 1
            # Captions never enter the platform's UI bands (a pixel of anti-aliasing tolerance).
            assert ys.max() <= (1 - safe["bottom"]) * H + 2 and ys.min() >= safe["top"] * H - 2
            assert xs.max() <= (1 - safe["right"]) * W + 2 and xs.min() >= safe["left"] * W - 2
    assert inside_hits >= 4  # captions were on screen for most of the samples


def test_captions_follow_the_picture_through_any_edit():
    import compile_timeline as ct
    import edit_patch as ep
    ir = {"ir_version": "3.0", "canvas": {"width": 1080, "height": 1920, "fps": 30, "sample_rate": 48000}, "tracks": [
        {"id": "v", "kind": "video", "items": [
            {"id": "T1", "asset_id": "raw", "timeline_in": 0, "timeline_out": 2.0, "source_in": 1.0},
            {"id": "T2", "asset_id": "raw", "timeline_in": 2.0, "timeline_out": 3.5, "source_in": 6.0}]},
        {"id": "captions", "kind": "graphic", "items": [{"id": "CAPS", "template": "kinetic_captions", "follow": "main", "timeline_in": 0,
                                                          "timeline_out": 3.5, "params": {"words": [
            {"text": "first", "asset_id": "raw", "src_start": 1.2, "src_end": 1.6},
            {"text": "cut", "asset_id": "raw", "src_start": 4.0, "src_end": 4.3},      # outside every shot: was cut out
            {"text": "second", "asset_id": "raw", "src_start": 6.5, "src_end": 7.0, "emphasis": True}]}}]}]}
    words = lambda t: ct.resolve_dynamic(t)["tracks"][1]["items"][0]["params"]["words"]  # noqa: E731
    assert words(ir) == [{"text": "first", "start": 0.2, "end": 0.6}, {"text": "second", "emphasis": True, "start": 2.5, "end": 3.0}]
    # Remove T1 in the Studio: its word leaves with it, the rest moves up with the picture, the span shrinks.
    edited = ep.apply(ir, {"operations": [{"op": "remove", "item_id": "T1"}]}, check=False)["timeline"]
    caps = ct.resolve_dynamic(edited)["tracks"][1]["items"][0]
    assert caps["params"]["words"] == [{"text": "second", "emphasis": True, "start": 0.5, "end": 1.0}]
    assert (caps["timeline_in"], caps["timeline_out"]) == (0.0, 1.5)
    # Slow T2 to half speed: the word lands twice as late into the shot.
    slowed = ep.apply(edited, {"operations": [{"op": "set_duration", "item_id": "T2", "duration": 3.0}]}, check=False)["timeline"]
    slowed["tracks"][0]["items"][0]["speed"] = 0.5
    assert ct.resolve_dynamic(slowed)["tracks"][1]["items"][0]["params"]["words"][0]["start"] == pytest.approx(1.0, abs=0.01)
