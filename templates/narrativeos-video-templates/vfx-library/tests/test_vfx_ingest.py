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
