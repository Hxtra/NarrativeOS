import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from tts.audio_cache import cache_key
from tts.router import run


def test_cache_key_changes_with_voice_direction():
    segment={"segment_id":"N1","text":"Hello","voice_direction":{"energy":0.2}}
    a=cache_key(segment,"openrouter","model-a","voice-a")
    segment["voice_direction"]["energy"]=0.8
    b=cache_key(segment,"openrouter","model-a","voice-a")
    assert a != b


def test_router_blocks_without_provider_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path/"narration_plan.json").write_text(json.dumps({"segments":[{"segment_id":"N1","type":"NARRATION","text":"A sentence.","voice_direction":{"pace":0.9},"timing":{"target_start":0,"target_end":2}},{"segment_id":"N2","type":"SILENCE","reason":"pause","timing":{"target_start":2,"target_end":3}}]}))
    manifest=run(tmp_path,"documentary_investigative")
    assert manifest["status"]=="blocked"
    assert manifest["blocked"][0]["error"]=="OPENROUTER_API_KEY is not configured"
    saved=json.loads((tmp_path/"tts_manifest.json").read_text())
    assert saved["status"]=="blocked"
    assert saved["segments"][1]["status"]=="not_applicable"
