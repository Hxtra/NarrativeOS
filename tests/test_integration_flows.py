"""End-to-end flows through the real entry points (CLIs as subprocesses), with local fixtures in place of
external providers. These prove the pieces connect; unit behaviour lives in the other test files."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from evidence_links import build_links  # noqa: E402
import generation  # noqa: E402
from editorial_style import resolve_style  # noqa: E402
from test_editing_intelligence import shaped_audio  # noqa: E402
from test_style_intel import gradual_video  # noqa: E402

PY = sys.executable


def run(*args, ok=True):
    r = subprocess.run([PY, *map(str, args)], capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stderr
    return r


def save(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- 1. music/audio -> analysis -> music map -> editorial proposal -> timeline proposal -------------

def test_music_to_timeline_proposal_end_to_end(tmp_path):
    audio = shaped_audio(tmp_path / "score.wav")          # ramp 4-12 s, hit at 12 s, breakdown at 16 s
    reference = gradual_video(tmp_path / "reference.mp4")  # dissolve, fade through white, fade through black
    run("-m", "style_intel", "analyze", reference, "--out", tmp_path / "dna", "--no-speech")
    timeline = {"status": "approved", "shots": [
        {"shot_id": "SHOT_1", "asset_id": "clip", "start": 0, "end": 12.1, "source_start": 0, "media_type": "image", "status": "approved"},
        {"shot_id": "SHOT_2", "asset_id": "clip", "start": 12.1, "end": 20, "source_start": 0, "media_type": "image", "status": "approved"}]}
    profile = {"editorial_intent": {"editing": {"rhythm_mode": "phrase_aware", "transition_policy": "energy",
                                                "build_motion": "push_in", "snap_window_sec": 0.25}}}
    alignment = {"status": "passed", "captions": [{"start": 0.5, "end": 3.0, "words": [
        {"word": "Everything", "start": 0.5, "end": 1.1}, {"word": "um", "start": 1.3, "end": 1.5}, {"word": "changed", "start": 1.7, "end": 2.4}]}]}
    inputs = {name: save(tmp_path / f"{name}.json", data) for name, data in
              [("timeline", timeline), ("profile", profile), ("alignment", alignment), ("visuals", {"assets": [{"asset_id": "clip", "path": str(reference)}]})]}
    before = inputs["timeline"].read_bytes()
    out = tmp_path / "proposal"
    run(ROOT / "scripts/director_pipeline.py", "--timeline", inputs["timeline"], "--music", audio, "--alignment", inputs["alignment"],
        "--visuals", inputs["visuals"], "--profile", inputs["profile"], "--dna", tmp_path / "dna/style_dna.json", "--out", out)

    perception = json.loads((out / "perception.json").read_text())
    assert perception["music"]["status"] == "measured"
    assert {e["basis"] for e in perception["music"]["events"]} <= {"MEASURED", "INFERRED"}
    assert any(e["type"] == "SPEECH_FILLER" for e in perception["speech"]["events"])
    vocab = perception["visual"][0]["transition_vocabulary"]
    assert vocab["dissolve"]["count"] >= 1 and vocab["light_burn"]["count"] >= 1 and vocab["dip_through_black"]["count"] >= 1

    style = json.loads((out / "editorial_style.json").read_text())
    assert style["editing"]["allowed_transitions_source"] == "style_dna"
    assert "flash_cut" not in style["editing"]["allowed_transitions"]  # the reference never flashed

    graph = json.loads((out / "event_graph.json").read_text())
    kinds = {e["type"] for e in graph["events"]}
    assert {"MOTION", "TRANSITION"} <= kinds
    transition = next(e for e in graph["events"] if e["type"] == "TRANSITION")
    assert transition["transition"]["recipe"] in style["editing"]["allowed_transitions"]
    assert graph["director"] == {"mode": "deterministic", "model": None}

    proposal = json.loads((out / "timeline.proposed.json").read_text())
    assert proposal["review"]["required"] is True and proposal["approved"] is False
    assert {m["type"] for m in proposal["markers"]} >= {"MOTION", "TRANSITION"}
    assert (out / "rhythm_review.json").is_file()
    assert inputs["timeline"].read_bytes() == before  # approved input untouched


# --- 2-4. generation request -> quote -> approval -> ready -> generate -> register -> continuity reuse ----

STUB = '''import sys, json, wave
import numpy as np, cv2
prompt, spec, out = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]
if out.endswith(".png"):
    cv2.imwrite(out, np.full((spec["height"] // 60, spec["width"] // 60, 3), 90, np.uint8))
else:
    sr = 22050; n = int(sr * spec.get("duration_sec", 1.0))
    y = (np.sin(2 * np.pi * 330 * np.arange(n) / sr) * 0.3 * 32767).astype("<i2")
    with wave.open(out, "wb") as w:
        w.setparams((1, 2, sr, 0, "NONE", "")); w.writeframes(y.tobytes())
'''


def providers(tmp_path: Path) -> Path:
    script = tmp_path / "stub_gen.py"
    script.write_text(STUB, encoding="utf-8")
    cmd = [PY, str(script), "{prompt_file}", "{spec_file}", "{out}"]
    base = {"type": "command", "work_dir": str(tmp_path / "gen_work"), "command": cmd, "rights_terms": "owner-run local model, commercial use"}
    return save(tmp_path / "providers.json", {
        "image": {**base, "provider": "local-image", "model": "img-1", "output_ext": ".png", "price": {"amount_per_unit": 0.04, "unit": "item", "currency": "USD"}},
        "voice": {**base, "provider": "local-voice", "model": "tts-1", "output_ext": ".wav", "price": {"amount_per_unit": 0, "unit": "character"}, "rights_review_required": False},
        "video": {**base, "provider": "local-video", "model": "vid-1", "output_ext": ".mp4", "price": {"amount_per_unit": 1, "unit": "item"}}})


def cli(project, *args, ok=True):
    return run(ROOT / "scripts/generation_cli.py", args[0], "--project", project, *args[1:], ok=ok)


def test_generation_state_machine_and_continuity_end_to_end(tmp_path):
    project, prov = tmp_path / "project", providers(tmp_path)
    profile = save(tmp_path / "profile.json", {"editorial_intent": {"tone": "tense true-crime", "avoid": ["cheerful colours"], "image": {"lighting": "low-key"}}})
    bible = save(tmp_path / "bible.json", {"entities": [
        {"entity_id": "NYC_STREET", "kind": "location", "visual_description": "narrow Brooklyn street at night",
         "environment_constraints": {"layout": "brownstones left, fire escape right"}}], "style_lock": {"lens": "35mm"}})
    need = {"kind": "image", "visual_role": "reconstruction", "purpose": "The street the night it happened",
            "entity_ids": ["NYC_STREET"], "width": 1920, "height": 1080}
    cli(project, "plan", "--need", save(tmp_path / "need1.json", {**need, "request_id": "IMG1"}), "--profile", profile, "--bible", bible)

    # Gates cannot be skipped.
    assert cli(project, "ready", "--id", "IMG1", ok=False).returncode == 1
    assert cli(project, "run", "--id", "IMG1", "--providers", prov, ok=False).returncode == 1
    shown = json.loads(cli(project, "quote", "--id", "IMG1", "--providers", prov, "--version", "q1").stdout)
    assert shown["state"] == "QUOTED" and shown["quote"]["amount"] == 0.04 and shown["quote"]["basis"] == "price_table_estimate"
    assert cli(project, "waive-cost", "--id", "IMG1", "--reason", "free?", ok=False).returncode == 1  # paid quote
    assert cli(project, "approve-cost", "--id", "IMG1", "--by", "owner", "--quote-hash", "stale", ok=False).returncode == 1
    qh = shown["quote_hash"]
    cli(project, "approve-cost", "--id", "IMG1", "--by", "owner", "--quote-hash", qh)
    cli(project, "approve-rights", "--id", "IMG1", "--by", "owner", "--quote-hash", qh)
    assert json.loads(cli(project, "ready", "--id", "IMG1").stdout)["state"] == "READY"
    generated = json.loads(cli(project, "run", "--id", "IMG1", "--providers", prov).stdout)
    assert generated["state"] == "GENERATED" and generated["media_class"] == "GENERATED_RECONSTRUCTION"
    assert cli(project, "register", "--id", "IMG1", ok=False).returncode == 1  # not reviewed yet
    cli(project, "review", "--id", "IMG1", "--by", "owner", "--approve")
    cli(project, "register", "--id", "IMG1", "--bible", bible, "--entity", "NYC_STREET")

    job = json.loads((project / "generation/jobs/IMG1.json").read_text())
    assert [h["state"] for h in job["history"]] == generation.FLOW
    assert job["asset"]["can_support_claim"] is False and job["asset"]["provenance"]["model"] == "img-1"
    assert "tense true-crime" in job["prompt"] and "brownstones" in job["prompt"] and "Avoid: cheerful colours" in job["prompt"]

    # Second request for the same place resolves continuity from the bible by id alone.
    cli(project, "plan", "--need", save(tmp_path / "need2.json", {**need, "request_id": "IMG2", "purpose": "Same street at dawn"}),
        "--profile", profile, "--bible", bible)
    second = json.loads((project / "generation/jobs/IMG2.json").read_text())
    entity = second["continuity"]["entities"][0]
    assert entity["approved_reference"] == "gen_IMG1" and entity["generation_history"][0]["request_id"] == "IMG1"
    assert second["reference_images"][0]["role"] == "approved_reference" and second["reference_images"][0]["sha256"] == job["output"]["sha256"]
    assert "Match the 1 attached reference image" in second["prompt"]


def test_free_voice_job_records_not_applicable_gates(tmp_path):
    project, prov = tmp_path / "project", providers(tmp_path)
    profile = save(tmp_path / "profile.json", {"editorial_intent": {"narration": {"pace": 0.9}}})
    cli(project, "plan", "--need", save(tmp_path / "n.json", {"request_id": "VO1", "kind": "voice", "purpose": "Cold open line", "text": "It was never meant to be found."}), "--profile", profile)
    qh = json.loads(cli(project, "quote", "--id", "VO1", "--providers", prov).stdout)["quote_hash"]
    assert cli(project, "rights-na", "--id", "VO1", "--reason", "x", ok=False).returncode == 1  # cost gate first
    cli(project, "waive-cost", "--id", "VO1", "--reason", "local model, zero cost")
    cli(project, "rights-na", "--id", "VO1", "--reason", "provider terms need no review")
    cli(project, "ready", "--id", "VO1")
    job = json.loads(cli(project, "run", "--id", "VO1", "--providers", prov).stdout)
    assert job["state"] == "GENERATED" and job["media_class"] == "GENERATED_VOICE"
    assert job["gates"]["cost"]["state"] == "not_applicable" and job["gates"]["rights"]["state"] == "not_applicable"
    assert qh and job["quote"]["basis"] == "local_zero_cost"


# --- AI video request -> blocked -------------------------------------------------------------------

def test_ai_video_request_is_blocked_at_every_step(tmp_path):
    project, prov = tmp_path / "project", providers(tmp_path)
    profile = save(tmp_path / "profile.json", {})
    planned = json.loads(cli(project, "plan", "--need", save(tmp_path / "v.json", {"request_id": "VID1", "kind": "video", "purpose": "Drone shot"}), "--profile", profile).stdout)
    assert planned["state"] == "DISABLED"
    for step in (["quote", "--id", "VID1", "--providers", prov], ["ready", "--id", "VID1"], ["run", "--id", "VID1", "--providers", prov]):
        r = cli(project, *step, ok=False)
        assert r.returncode == 1 and "disabled" in r.stderr
    with pytest.raises(ValueError, match="disabled"):
        generation.load_adapter(json.loads(prov.read_text()), "video")  # even with a video provider configured


# --- Generated image -> classified -> cannot satisfy factual evidence ---------------------------------

def test_generated_images_never_satisfy_evidence(tmp_path):
    style = resolve_style({})
    plan = lambda role: generation.plan_request({"request_id": f"I_{role}", "kind": "image", "visual_role": role, "purpose": "x", "width": 64, "height": 64}, style)  # noqa: E731
    assert plan("reconstruction")["media_class"] == "GENERATED_RECONSTRUCTION"
    assert plan("conceptual")["media_class"] == "GENERATED_CONCEPT"
    assert plan("abstract")["media_class"] == "ABSTRACT"
    evidence_request = plan("archival_evidence")
    assert evidence_request["state"] == "BLOCKED_SOURCING" and evidence_request["media_class"] is None

    claims = [{"claim_id": "C1", "source_refs": ["S1"]}] * 4
    specs = [{"shot_id": f"SHOT_{i}"} for i in range(4)]
    real = {"media_class": "ARCHIVAL", "rights_status": "verified", "source_url": "https://archive.org/details/x", "sha256": "a" * 64}
    assets = [
        {"shot_id": "SHOT_0", "asset_id": "gen", "media_class": "GENERATED_RECONSTRUCTION", "generated": True, "rights_status": "verified", "sha256": "b" * 64},
        {"shot_id": "SHOT_1", "asset_id": "liar", **real, "generated": True},  # mislabelled generated image
        {"shot_id": "SHOT_2", "asset_id": "stock", **real, "media_class": "STOCK"},
        {"shot_id": "SHOT_3", "asset_id": "archive", **real},
    ]
    status = {l["asset_id"]: l["status"] for l in build_links(claims, specs, assets)}
    assert status == {"gen": "illustrative_only", "liar": "illustrative_only", "stock": "illustrative_only", "archive": "evidence_supported"}
