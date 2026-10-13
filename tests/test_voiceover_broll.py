"""Voiceover + footage: script alignment, cut placement against speech, shot planning, camera allocation, edit-type
detection with faces, asset merging, and an end-to-end cut measured from the rendered frames.

Rule tests use hand-built words (exact, fast). The end-to-end test needs the Windows speech engine, faster-whisper
and Remotion, and is skipped where any is missing."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import signature as sig  # noqa: E402
import talking_head as th  # noqa: E402
import voiceover_broll as vb  # noqa: E402


def W(text: str, start: float, end: float) -> dict:
    return {"text": text, "start": start, "end": end}


def sentences(spec: list[tuple[str, float]], word_sec: float = 0.3) -> list[dict]:
    """Words for sentences starting at the given times, one word every word_sec."""
    out = []
    for text, t in spec:
        for k, tok in enumerate(text.split()):
            out.append(W(tok, round(t + k * word_sec, 3), round(t + k * word_sec + word_sec - 0.05, 3)))
    return out


# ----------------------------------------------------------------------------------------------- words
def test_the_script_spelling_goes_on_the_heard_words_and_misses_are_reported():
    heard = [W("The", 0, .2), W("five", .2, .5), W("friends", .5, .9), W("at", 1.0, 1.1), W("22.", 1.1, 1.6), W("um", 1.7, 1.9), W("Done.", 2.0, 2.4)]
    words, rep = vb.align_script(heard, "The five friends you keep at twenty-two. Done.")
    assert [w["text"] for w in words] == ["The", "five", "friends", "you", "keep", "at", "twenty-two.", "Done."]
    assert rep["respelled"] == [{"heard": "22.", "script": "twenty-two.", "at": 1.1}]
    assert rep["interpolated"] == ["you", "keep"] and all(w["status"] == "INTERPOLATED" for w in words[3:5])
    assert 0.9 <= words[3]["start"] < words[4]["start"] < 1.0  # between "friends" and "at"
    assert rep["dropped_not_in_script"] == [{"heard": "um", "at": 1.7}]


# ----------------------------------------------------------------------------------------------- placement
def test_cut_placement_is_measured_against_phrase_onsets():
    words = sentences([("One two three.", 0.0), ("Four five, six seven.", 2.0), ("Eight nine ten.", 4.0)])
    # cuts: at the second sentence's onset (+0.05), at the clause "six" (+0.0), and mid-phrase on "nine".
    six = next(w for w in words if w["text"] == "six")
    nine = next(w for w in words if w["text"] == "nine")
    p = vb.cut_placement([2.05, six["start"], nine["start"] + 0.02], words)
    assert p["status"] == "MEASURED" and p["fractions"] == {"sentence": 0.333, "clause": 0.333, "pause": 0.0, "mid_phrase": 0.333}
    assert p["offset_sec"] == pytest.approx(0.02)


def test_shots_are_cut_at_sentence_onsets_with_lengths_near_the_reference():
    words = sentences([("A b c d e f.", 0.0), ("G h i.", 2.2), ("J k l m n.", 3.4), ("O p q.", 5.2), ("R s t u.", 6.4)])
    placement = {"status": "MEASURED", "fractions": {"sentence": 1.0, "clause": 0.0, "pause": 0.0, "mid_phrase": 0.0}, "offset_sec": 0.0}
    shots, rep = vb.plan_shots(words, 7.6, {"median": 2.4, "p10": 1.8, "p90": 3.2}, placement, n_shots=3)
    assert [s["in"] for s in shots] == [0.0, 2.2, 5.2]  # the sentence onsets that give lengths 2.2, 3.0, 2.4
    assert [s["cut_after"] for s in shots] == ["sentence", "sentence", None]
    assert shots[-1]["out"] == 7.6 and shots[1]["says"] == "G h i. J k l m n."


def test_the_first_shot_holds_the_hook_sentence_whatever_its_length():
    words = sentences([("A b c d e f g h i j k l m n o p.", 0.0), ("Q r.", 5.0), ("S t.", 7.0), ("U v.", 9.0)])
    placement = {"status": "MEASURED", "fractions": {"sentence": 1.0}, "offset_sec": 0.0}
    hook = vb.hook_end(words)
    assert words[hook]["text"] == "Q"
    shots, _ = vb.plan_shots(words, 11.0, {"median": 2.0, "p10": 1.5, "p90": 2.5}, placement, None, hook)
    assert shots[0]["out"] == 5.0 and shots[0]["says"].endswith("p.")


def test_an_impossible_plan_is_an_error_not_a_forced_cut():
    words = sentences([("A b.", 0.0), ("C d.", 1.0)])
    with pytest.raises(ValueError, match="no cut fits"):
        vb.plan_shots(words, 2.0, {"median": 4.0, "p10": 3.0, "p90": 5.0}, {}, n_shots=5)


# ----------------------------------------------------------------------------------------------- footage
def test_a_clip_shorter_than_its_shot_is_an_error_and_the_head_is_skipped_when_it_can_be():
    with pytest.raises(ValueError, match="never looped"):
        vb.source_window(3.0, 4.0)
    assert vb.source_window(10.0, 4.0) == 1.0
    assert vb.source_window(4.6, 4.0) == 0.1  # keeps 0.5 s at the end
    assert vb.source_window(10.0, 4.0, 5.5) == 5.5


def test_camera_moves_are_added_to_static_clips_only_toward_the_measured_fractions():
    shots = [{"length": 4.0}] * 10
    measured = ["static", "push_in", "static", "static", "handheld_or_action", "static", "static", "static", "static", "pan"]
    plan = vb.plan_camera(shots, measured, {"fractions": {"push_in": 0.3, "pan": 0.2}}, protect={0})
    assert plan["want"] == {"push_in": 3, "pan": 2} and plan["already_in_clips"] == {"push_in": 1, "pan": 1}
    assert len(plan["push_in"]) == 2 and len(plan["pan"]) == 1
    chosen = plan["push_in"] + plan["pan"]
    assert all(measured[i] == "static" and i != 0 for i in chosen) and len(set(chosen)) == 3


def test_an_asset_already_registered_keeps_its_id_and_rights(tmp_path):
    clip = tmp_path / "media" / "a.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"clip bytes")
    (tmp_path / "assets.json").write_text(json.dumps({"assets": [{"asset_id": "px1", "local_path": "media/a.mp4", "status": "approved",
                                                                   "sha256": vb.sha256(clip), "rights": {"status": "RIGHTS_VERIFIED"}}]}))
    other = tmp_path / "media" / "b.mp4"
    other.write_bytes(b"other bytes")
    assets = vb.Assets(tmp_path)
    assert assets.use(clip, "footage", "clip_")["asset_id"] == "px1"
    new = assets.use(other, "footage", "clip_")
    assert new["asset_id"] == "clip_b" and new["status"] == "simulation_approved" and new["rights"]["status"] == "UNVERIFIED"
    assets.save()
    assert [a["asset_id"] for a in json.loads((tmp_path / "assets.json").read_text())["assets"]] == ["px1", "clip_b"]


def test_a_face_in_foliage_is_not_a_subject_but_a_face_on_a_person_is():
    import frame_awareness as fa
    leafy = {"t": 0, "person": None, "faces": [{"box": [0.4, 0.4, 0.12, 0.22], "score": 0.56}]}
    sure = {"t": 1, "person": None, "faces": [{"box": [0.4, 0.4, 0.12, 0.22], "score": 0.9}]}
    on_person = {"t": 2, "person": [0.3, 0.2, 0.3, 0.7], "faces": [{"box": [0.4, 0.3, 0.1, 0.15], "score": 0.55}]}
    assert fa.trusted_faces(leafy) == [] and fa.trusted_faces(sure) and fa.trusted_faces(on_person)
    assert [round(c[0]) for c in fa.subject_centres({"samples": [leafy, sure, on_person]})] == [1, 2]


def test_a_lockup_block_never_ends_on_a_function_word(monkeypatch):
    monkeypatch.setattr(vb, "region_luma", lambda *a, **k: 200.0)
    hook = sentences([("the five friends you keep at twenty-two", 0.0)]) + sentences([("will decide your bank account at forty.", 2.6)])
    hook[8]["start"] += 0.8  # the longest pause is before "decide", after the function word "will"
    params, rep = vb.lockup_params(hook, Path("clip.mp4"), 1.0, 0.5, (1, 1), {"friends"})
    assert rep["split_before"] == "will" and params["blocks"][1]["words"][0]["text"] == "will"
    assert params["blocks"][0]["words"][2] == {"text": "friends", "start": 0.6, "size": vb.LOCKUP["key"], "cycle": True}
    assert params["blocks"][0]["color"] == "#111111"  # dark text over a bright region


# ----------------------------------------------------------------------------------------------- edit type
def test_the_edit_type_needs_a_face_on_screen_to_be_a_talking_head(tmp_path, monkeypatch):
    import frame_awareness as fa
    monkeypatch.setattr(th, "vision_ready", lambda: (True, ""))
    face = {"box": [0.4, 0.2, 0.2, 0.3], "score": 0.9}
    tiny = {"box": [0.1, 0.1, 0.02, 0.03], "score": 0.9}  # a passer-by in the background
    for faces, kind in (([face] * 8 + [] * 2, "talking_head"), ([tiny] * 8 + [] * 2, "voiceover_broll")):
        monkeypatch.setattr(fa, "analyze", lambda *a, _f=faces, **k: {"samples": [{"t": i, "faces": [_f[i]] if i < len(_f) else []} for i in range(10)]})
        assert sig.edit_type(tmp_path / "ref.mp4", 20.0, 0.9, tmp_path)["kind"] == kind
    assert sig.edit_type(tmp_path / "ref.mp4", 20.0, 0.1, tmp_path)["kind"] == "documentary"
    monkeypatch.setattr(th, "vision_ready", lambda: (False, "no models"))
    out = sig.edit_type(tmp_path / "ref.mp4", 20.0, 0.9, tmp_path)
    assert out["faces"]["status"] == "NOT_MEASURED" and "warning" in out


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


def speak(ssml_body: str, wav: Path) -> Path:
    wav.parent.mkdir(parents=True, exist_ok=True)
    ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">{ssml_body}</speak>'
    ps = wav.parent / "speak.ps1"
    ps.write_text("Add-Type -AssemblyName System.Speech\n$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                  f"$s.SetOutputToWaveFile('{wav}')\n$s.SpeakSsml('{ssml}')\n$s.Dispose()\n", encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], check=True, capture_output=True)
    return wav


def frames_of(video: Path, size: int = 64) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={size}:{size}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, size, size, 3).astype(np.float32)


@pytest.mark.skipif(not _has_tools(), reason="needs the Windows speech engine, faster-whisper and Remotion")
def test_a_voice_and_three_clips_become_a_cut_on_its_sentences_graded_and_captioned(tmp_path):
    import compile_timeline as ct
    import grade_match as gm
    b = '<break time="{}ms"/>'
    voice = speak(f"The river rose at dawn.{b.format(500)}Nobody in the village was awake.{b.format(500)}By noon, the bridge was gone.",
                  tmp_path / "media" / "voice.wav")
    colours = ["0x6a5a4a", "0x4a5a6a", "0x5a6a4a"]
    clips = []
    for n, c in enumerate(colours):
        clips.append(tmp_path / "media" / f"clip{n + 1}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={c}:s=1280x720:r=30:d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(clips[-1])], check=True)
    target = {"status": "MEASURED", "mean": [55.0, 12.0, 18.0], "std": [20.0, 10.0, 12.0], "chroma": 24.0}
    signature = {"id": "test_vo", "version": 1, "status": "experimental", "moves": [],
                 "pipeline": {"kind": "voiceover_broll", "aspect": "1:1", "style": "documentary_general",
                              "captions": {"position": "center", "maxWords": 1, "lowercase": True, "outline": False},
                              "placement": {"status": "MEASURED", "fractions": {"sentence": 1.0, "clause": 0.0, "pause": 0.0, "mid_phrase": 0.0}, "offset_sec": 0.0},
                              "measured": {"shot_duration_sec": {"median": 2.5, "p10": 1.6, "p90": 3.6}},
                              "camera": {"fractions": {"static": 1.0, "push_in": 0.0, "pan": 0.0}}, "grade_target": target}}
    script = "The river rose at dawn. Nobody in the village was awake. By noon, the bridge was gone."
    ir, rep = vb.build(signature, tmp_path, voice, clips, script)
    shots = ir["tracks"][0]["items"]
    words, _ = vb.voice_words(voice, tmp_path / "analysis" / "transcripts", script)
    onsets = [next(w["start"] for w in words if w["text"] == t) for t in ("Nobody", "By")]
    assert [s["timeline_in"] for s in shots[1:]] == pytest.approx(onsets, abs=0.06)  # cut on each sentence's first word
    assert rep["words"]["script"]["dropped_not_in_script"] == [] and rep["lockup"]["status"] == "NOT_USED"
    assert all(it["grade"]["lut"].startswith("lut_") for it in shots) and (tmp_path / "luts" / "S01.cube").is_file()

    ct.compile_timeline(tmp_path, ir, tmp_path / "out.mp4")
    f = frames_of(tmp_path / "out.mp4")
    assert len(f) / 30 == pytest.approx(vb.probe(voice)["duration"], abs=0.1)
    edge = f[:, :8, :8].mean(axis=(1, 2, 3))  # a corner the centred caption never reaches
    jumps = [i / 30 for i in range(1, len(edge)) if abs(edge[i] - edge[i - 1]) > 2]
    assert jumps == pytest.approx([s["timeline_in"] for s in shots[1:]], abs=1.5 / 30)  # the render cuts where the plan does
    # Each shot is graded toward the target colour: closer in Lab than the ungraded clip.
    for it, clip in zip(shots, clips):
        mid = int((it["timeline_in"] + it["timeline_out"]) / 2 * 30)
        before = gm.measure(gm.frames(clip, 2.0, 2.6))["mean"]
        after = gm.measure(f[mid:mid + 1, :8, :8].astype(np.uint8))["mean"]
        assert np.linalg.norm(np.subtract(after, target["mean"])) < np.linalg.norm(np.subtract(before, target["mean"]))
    # Captions: bright text in the centre while a word is spoken, none in the frame's corner.
    w = next(w for w in words if w["text"] == "village")
    k = int((w["start"] + w["end"]) / 2 * 30)
    assert f[k, 26:38, 8:56].max() > f[k, :8, :8].max() + 80  # white text (antialiased at 64 px) over the ~120 background
