"""Style-consistent offline requests and fail-closed provider contracts."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]


def dark_profile():
    return {"profile_version": "v2", "editorial_intent": {
        "tone": "restrained investigative", "avoid": ["cheerful celebration"],
        "narration": {"pace": 0.9}, "captions": {"font_size": 36, "animation": "none"},
        "image": {"lighting": "cool low-key", "palette": "muted"},
        "music": {"instrumentation": "sparse strings"}, "sfx": {"density": "subtle"},
        "editing": {"rhythm_mode": "phrase_aware", "anticipation_sec": 0.2}}}


def test_one_versioned_intent_drives_all_modalities_without_retiming_speech():
    assert importlib.util.find_spec("editorial_style") is not None, "missing shared editorial intent"
    from editorial_style import resolve_style, production_directions
    dna = {"source": {"sha256": "a" * 64}, "editing": {"shot_duration_sec": {"median": 5.5}}}
    style = resolve_style(dark_profile(), dna)
    narration = {"segments": [{"segment_id": "N1", "type": "NARRATION", "text": "Words.", "timing": {"target_start": 0, "target_end": 2}}]}
    captions = {"captions": [{"start": 0, "end": 2, "text": "Words."}]}
    result = production_directions(narration, captions, style)
    assert style["editing"]["target_shot_sec"] == 5.5
    assert style["measurement_source"] == dna["source"]["sha256"]
    for kind in ("narration", "captions", "editing", "image", "music", "sfx"):
        assert style[kind]["tone"] == "restrained investigative"
        assert style[kind]["avoid"] == ["cheerful celebration"]
    assert result["narration_plan"]["segments"][0]["voice_direction"]["pace"] == 0.9
    assert result["narration_plan"]["segments"][0]["timing"] == narration["segments"][0]["timing"]
    assert result["caption_request"]["captions"] == captions["captions"]
    assert result["caption_request"]["style"]["font_size"] == 36
    assert result["style_id"] == style["style_id"]
    changed = dark_profile()
    changed["editorial_intent"]["tone"] = "joyful"
    assert resolve_style(changed, dna)["style_id"] != style["style_id"]
    assert "voice_direction" not in narration["segments"][0]


def continuity_fixture():
    return {"entities": [{"entity_id": "E1", "attributes": {"appearance": "same coat and short hair"}, "reference_images": []}],
            "locations": [{"location_id": "L1", "attributes": {"layout": "brick facade, door on left"},
                           "reference_images": [{"asset_id": "ref1", "local_path": "references/first.png", "sha256": "b" * 64, "rights_status": "verified", "use_approved": True}]}],
            "generation_lock": {"lighting": "cool low-key", "style": "restrained illustration"}}


def test_conceptual_image_routes_directly_with_locked_continuity_and_reference():
    assert importlib.util.find_spec("generation") is not None, "missing generation request adapter"
    from generation import plan_request
    from editorial_style import resolve_style
    need = {"request_id": "IMG1", "kind": "image", "purpose": "Visualize an imagined crossroads", "visual_role": "conceptual", "entity_ids": ["E1"], "location_id": "L1", "width": 1920, "height": 1080}
    style = resolve_style(dark_profile())
    first = plan_request(need, style, continuity_fixture())
    again = plan_request({**need, "request_id": "IMG2", "purpose": "Return to the same crossroads"}, style, continuity_fixture())
    assert first["route"] == "generate_direct"
    assert first["status"] == "blocked"  # configured provider + quote + approvals still required
    assert first["style_id"] == style["style_id"]
    assert first["direction"]["tone"] == "restrained investigative"
    assert first["continuity"] == again["continuity"]
    assert first["reference_images"][0]["asset_id"] == "ref1"
    assert first["continuity"]["generation_lock"]["lighting"] == "cool low-key"
    assert first["representation"] == "generated_illustration_not_factual_evidence"
    assert first["can_support_claim"] is False
    assert first["request_hash"] != again["request_hash"]


@pytest.mark.parametrize("role,search,route", [
    ("illustration", None, "stock_search_required"),
    ("illustration", {"status": "no_suitable_assets", "search_id": "stock-1", "rejections": [{"asset_id": "a", "reason": "wrong location"}]}, "generate_fallback"),
    ("archival_evidence", {"status": "no_suitable_assets"}, "blocked_factual_evidence"),
])
def test_image_fallback_requires_sourcing_evidence_and_cannot_replace_facts(role, search, route):
    from generation import plan_request
    from editorial_style import resolve_style
    need = {"request_id": "I", "kind": "image", "purpose": "Location", "visual_role": role, "stock_search": search, "width": 1920, "height": 1080}
    result = plan_request(need, resolve_style(dark_profile()), {})
    assert result["route"] == route
    assert result["status"] == "blocked"
    assert result["stock_search"] == search
