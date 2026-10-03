"""End-to-end tests for vfx_ingest.py against synthetic clips with known properties."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from make_test_overlays import make  # noqa: E402

INGEST = [sys.executable, str(TOOLS / "vfx_ingest.py")]


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    inbox = tmp_path_factory.mktemp("inbox")
    lib = tmp_path_factory.mktemp("lib")
    make(inbox)
    subprocess.run(INGEST + ["--library", str(lib), "ingest", str(inbox)], check=True)
    return inbox, lib


def records(lib: Path) -> dict[str, dict]:
    return {r["original_filename"]: r for r in json.loads((lib / "vfx_catalog.json").read_text())["assets"]}


def test_peak_frames_detected(library):
    _, lib = library
    recs = records(lib)
    assert abs(recs["synthetic_leak_warm.mp4"]["analysis"]["peak_frame"] - 45) <= 1
    assert abs(recs["synthetic_leak_cool.mp4"]["analysis"]["peak_frame"] - 20) <= 1
    assert 60 <= recs["synthetic_flash.mp4"]["analysis"]["peak_frame"] <= 62


def test_blend_tone_and_suggestions(library):
    _, lib = library
    recs = records(lib)
    warm, cool = recs["synthetic_leak_warm.mp4"], recs["synthetic_leak_cool.mp4"]
    assert warm["analysis"]["recommended_blend"] == "screen"
    assert (warm["tone"], warm["category"]) == ("warm", "light_leak")
    assert (cool["tone"], cool["category"]) == ("cool", "light_leak")
    assert recs["synthetic_flash.mp4"]["category"] == "flash"
    assert recs["synthetic_texture.mp4"]["analysis"]["recommended_blend"] == "multiply"
    assert all(r["category_status"] == "suggested" for r in recs.values())
    assert all(r["rights"]["redistributable"] is False for r in recs.values())


def test_files_sheets_and_naming(library):
    _, lib = library
    for r in records(lib).values():
        assert (lib / r["library_path"]).is_file()
        assert (lib / r["contact_sheet"]).is_file()
        assert r["library_path"].startswith(f"{r['category']}/{r['id']}")


def test_reingest_is_deduplicated(library):
    inbox, lib = library
    before = len(records(lib))
    subprocess.run(INGEST + ["--library", str(lib), "ingest", str(inbox)], check=True)
    assert len(records(lib)) == before


def test_confirm_recategorizes_and_renames(library):
    _, lib = library
    texture = records(lib)["synthetic_texture.mp4"]
    subprocess.run(INGEST + ["--library", str(lib), "confirm", texture["id"], "--category", "grain"], check=True)
    moved = records(lib)["synthetic_texture.mp4"]
    assert moved["category"] == "grain" and moved["category_status"] == "confirmed"
    assert moved["id"].startswith("vfx_grain_")
    assert (lib / moved["library_path"]).is_file()
    assert not (lib / texture["library_path"]).exists()


def test_confirm_rejects_unclassified(library):
    _, lib = library
    rec = records(lib)["synthetic_leak_warm.mp4"]
    r = subprocess.run(INGEST + ["--library", str(lib), "confirm", rec["id"], "--category", "unclassified"])
    assert r.returncode == 1


# --- Per-file provenance and rejection -------------------------------------------------------------

def source_record(path: Path, checksum: str, license_: str, category: str, attribution: bool) -> dict:
    return {"id": path.stem, "filename": path.name, "category": category, "name": path.stem, "checksum": checksum,
            "source": {"provider": "Example Archive", "source_url": f"https://example.org/{path.stem}", "asset_url": f"https://cdn.example.org/{path.name}"},
            "rights": {"status": "verified", "license": license_, "license_url": "https://example.org/license",
                       "commercial_use": True, "attribution_required": attribution, "attribution_text": "Example Author" if attribution else None,
                       "redistribution": "Inside larger works only."}}


def test_provenance_records_are_matched_by_checksum_not_filename(tmp_path):
    import hashlib
    inbox, lib, meta = tmp_path / "inbox", tmp_path / "lib", tmp_path / "meta"
    inbox.mkdir(); meta.mkdir()
    warm, cool = make(inbox)[:2]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    (meta / "a.json").write_text(json.dumps(source_record(warm, digest(warm), "CC BY-SA 4.0", "light_leaks", True)))
    # A record that claims the cool clip but with the wrong checksum must not lend it any rights.
    (meta / "b.json").write_text(json.dumps(source_record(cool, "0" * 64, "CC0", "glitches", False)))
    subprocess.run(INGEST + ["--library", str(lib), "ingest", str(inbox), "--provenance", str(meta)], check=True)
    recs = records(lib)
    w, c = recs[warm.name], recs[cool.name]
    assert w["rights"]["rights_status"] == "verified" and w["rights"]["provenance_checksum_verified"] is True
    assert w["rights"]["attribution_required"] is True and w["rights"]["share_alike"] is True
    assert w["rights"]["redistributable"] is False
    assert w["category"] == "light_leak" and w["category_status"] == "suggested"  # source label is only a hint
    assert w["source_metadata"]["category"] == "light_leaks"
    assert c["rights"]["rights_status"] == "unknown" and "source_metadata" not in c


def test_rejected_clips_stay_on_record_but_are_never_confirmed(library):
    _, lib = library
    rec = records(lib)["synthetic_flash.mp4"]
    subprocess.run(INGEST + ["--library", str(lib), "reject", rec["id"], "--reason", "not an overlay"], check=True)
    after = records(lib)["synthetic_flash.mp4"]
    assert after["category_status"] == "rejected" and after["rejection_reason"] == "not an overlay"
    assert (lib / after["library_path"]).is_file()


def test_review_can_override_the_blend_and_it_is_recorded(library):
    _, lib = library
    rec = records(lib)["synthetic_leak_cool.mp4"]
    assert rec["analysis"]["recommended_blend"] == "screen"
    subprocess.run(INGEST + ["--library", str(lib), "confirm", rec["id"], "--blend", "add", "--reason", "test"], check=True)
    after = records(lib)["synthetic_leak_cool.mp4"]
    assert after["analysis"]["recommended_blend"] == "add" and after["blend_override"] == {"from": "screen", "to": "add", "reason": "test"}
    bad = subprocess.run(INGEST + ["--library", str(lib), "confirm", rec["id"], "--blend", "sparkle"])
    assert bad.returncode == 1


def test_credits_list_only_clips_that_require_attribution(tmp_path):
    import hashlib
    inbox, lib, meta = tmp_path / "inbox", tmp_path / "lib", tmp_path / "meta"
    inbox.mkdir(); meta.mkdir()
    warm, cool = make(inbox)[:2]
    for clip, attr in ((warm, True), (cool, False)):
        digest = hashlib.sha256(clip.read_bytes()).hexdigest()
        (meta / f"{clip.stem}.json").write_text(json.dumps(source_record(clip, digest, "CC BY 3.0" if attr else "CC0", "light_leaks", attr)))
    subprocess.run(INGEST + ["--library", str(lib), "ingest", str(inbox), "--provenance", str(meta)], check=True)
    for r in records(lib).values():
        subprocess.run(INGEST + ["--library", str(lib), "confirm", r["id"]], check=True)
    out = subprocess.run(INGEST + ["--library", str(lib), "credits"], capture_output=True, text=True, check=True).stdout
    assert out.count("\n") == 1 and "Example Author (CC BY 3.0" in out


def test_peak_is_never_a_clip_edge_frame():
    """A lone white tail frame must not become the peak: peak alignment needs footage on both sides of the cut."""
    from vfx_ingest import analyze
    stats = [{"YAVG": 40.0, "YLOW": 16.0} for _ in range(300)]
    stats[120]["YAVG"] = 130.0  # a real burst
    stats[299]["YAVG"] = 235.0  # white final frame
    a = analyze(stats, 30.0, False)
    assert a["peak_frame"] == 120 and a["peak_search_margin_frames"] == 15
    short = analyze([{"YAVG": float(y), "YLOW": 0.0} for y in (10, 50, 90, 60, 20)], 30.0, False)
    assert short["peak_frame"] == 2  # short clips shrink the margin instead of losing the peak


def test_reanalyze_keeps_review_decisions(tmp_path):
    inbox, lib = tmp_path / "in", tmp_path / "lib"
    make(inbox)
    subprocess.run(INGEST + ["--library", str(lib), "ingest", str(inbox)], check=True)
    rec = records(lib)["synthetic_leak_warm.mp4"]
    subprocess.run(INGEST + ["--library", str(lib), "confirm", rec["id"], "--blend", "add", "--reason", "test"], check=True)
    subprocess.run(INGEST + ["--library", str(lib), "reanalyze"], check=True)
    after = records(lib)["synthetic_leak_warm.mp4"]
    assert after["category_status"] == "confirmed" and after["analysis"]["recommended_blend"] == "add"
    assert abs(after["analysis"]["peak_frame"] - 45) <= 1


def test_purge_deletes_rejected_clips_and_reingest_skips_them(tmp_path):
    inbox, lib = tmp_path / "in", tmp_path / "lib"
    make(inbox)
    subprocess.run(INGEST + ["--library", str(lib), "ingest", str(inbox)], check=True)
    rec = records(lib)["synthetic_flash.mp4"]
    subprocess.run(INGEST + ["--library", str(lib), "reject", rec["id"], "--reason", "test"], check=True)
    subprocess.run(INGEST + ["--library", str(lib), "purge-rejected"], check=True)
    assert "synthetic_flash.mp4" not in records(lib)
    assert not (lib / rec["library_path"]).exists() and not (lib / "metadata" / f"{rec['id']}.json").exists()
    assert json.loads((lib / "purged.json").read_text())[rec["sha256"]]["reason"] == "test"
    subprocess.run(INGEST + ["--library", str(lib), "ingest", str(inbox)], check=True)
    assert "synthetic_flash.mp4" not in records(lib)
