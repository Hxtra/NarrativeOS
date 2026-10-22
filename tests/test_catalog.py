"""catalog.py: the repo's catalog passes its own checks; local paths are stripped; a media file or a local path in the catalog
fails the check; a study built from measurement files follows the schema; curated capabilities survive a rescan."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts")]
import catalog as cat  # noqa: E402


def test_repo_catalog_is_clean():
    assert cat.check() == []


def test_local_paths_are_stripped_but_urls_kept():
    x = cat.strip_paths({"a": "C:/Users/someone/NarrativeOS-Data/analysis/x/clip.mp4", "b": ["/c/Users/someone/f.wav"],
                         "url": "https://github.com/Leonxlnx/earshot"})
    assert x["a"] == "clip.mp4" and x["b"] == ["f.wav"] and x["url"] == "https://github.com/Leonxlnx/earshot"


def _tmp_catalog(tmp, monkeypatch):
    monkeypatch.setattr(cat, "CAT", tmp / "catalog"); monkeypatch.setattr(cat, "STUDIES", tmp / "catalog" / "studies")
    monkeypatch.setattr(cat, "CAPS", tmp / "catalog" / "capabilities.json")


def test_study_from_measurements_follows_the_schema(tmp_path, monkeypatch):
    _tmp_catalog(tmp_path, monkeypatch)
    src = tmp_path / "analysis" / "ref"; src.mkdir(parents=True)
    (src / "av_layers.json").write_text(json.dumps({"fps": 30, "frames": 300, "tempo_bpm": 120, "strategy": {"strategy": "none", "why": "x",
                                         "mapping": {}}, "grid": {}, "camera": {"path": "C:/Users/someone/x.mp4"}}))
    (src / "FINDINGS.md").write_text("MEASURED: something. ![frame](C:/Users/someone/a.jpg)")
    a = SimpleNamespace(title="Ref", creator=None, kind="code_art", platform=None, url=None, findings=str(src / "FINDINGS.md"),
                        picked_by_owner=False, used_for=None, excerpt=None, date="2026-10-23", width=None, height=None, observation=None)
    p = cat.add_study("ref", src, a)
    s = json.loads(p.read_text())
    jsonschema.validate(s, json.loads((ROOT / "schemas" / "study.schema.json").read_text()))
    assert s["format"]["duration_s"] == 10.0 and s["measurements"]["sync"]["camera"]["path"] == "x.mp4"
    text = (p.parent / "FINDINGS.md").read_text()
    assert "C:/Users" not in text and "![" not in text                # image links and local paths never reach the repo


def test_media_and_local_paths_fail_the_check(tmp_path, monkeypatch):
    _tmp_catalog(tmp_path, monkeypatch)
    d = tmp_path / "catalog" / "studies" / "x"; d.mkdir(parents=True)
    (d / "frame.jpg").write_bytes(b"\xff\xd8")
    (d / "notes.md").write_text("see C:\\Users\\someone\\clip.mp4")
    (tmp_path / "catalog" / "capabilities.json").write_text("[]")
    errs = cat.check()
    assert any("media file" in e for e in errs) and any("local path" in e for e in errs)


def test_curated_entries_survive_a_rescan(tmp_path, monkeypatch):
    _tmp_catalog(tmp_path, monkeypatch)
    caps = cat.scan()
    target = next(c for c in caps if c["id"] == "script.sound_mix")
    target.update({"status": "VALIDATED", "evidence": "checked by a person", "curated": True})
    (tmp_path / "catalog").mkdir(parents=True, exist_ok=True)
    cat.save(cat.CAPS, caps)
    again = {c["id"]: c for c in cat.scan()}
    assert again["script.sound_mix"]["status"] == "VALIDATED" and again["script.sound_mix"]["evidence"] == "checked by a person"
    assert again["script.catalog"]["status"] == "TESTED"              # this very test file runs it
