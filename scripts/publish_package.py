#!/usr/bin/env python3
"""The publish package: title, description, tags, thumbnail and disclosures, checked against the platform's
real limits and the channel's own conventions, then approved by a human, bound to its hash.

    python publish_package.py build --project P --title "..." --description-file d.txt --tags a,b \\
        --thumbnail thumb.jpg --made-for-kids no [--category 27] [--publish-at 2026-10-12T15:00:00Z]
    python publish_package.py approve --project P --by "owner"

Limits checked (YouTube Data API v3 / Help Center): title 1-100 characters and no '<' or '>'; description at
most 5000 bytes and no '<' or '>'; tags at most 500 characters in total; thumbnail JPG or PNG, at most 2 MB,
at least 640 px wide, 16:9 (1280x720 recommended). The "made for kids" declaration has no default: an upload
needs an explicit answer.

`containsSyntheticMedia` (YouTube's altered or synthetic content flag) is derived from the provenance of the
assets the timeline actually uses, never typed in by hand:
- realistic generated media (GENERATED_RECONSTRUCTION, generated voice) -> true;
- only clearly non-realistic generated media (GENERATED_CONCEPT, music, SFX) -> false, flagged for review;
- no generated media -> false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from media_semantics import is_generated  # noqa: E402

TITLE_MAX, DESCRIPTION_MAX_BYTES, TAGS_MAX_CHARS = 100, 5000, 500
THUMB_MAX_BYTES, THUMB_MIN_WIDTH = 2 * 1024 * 1024, 640
REALISTIC = {"GENERATED_RECONSTRUCTION", "GENERATED_VOICE"}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (json.JSONDecodeError, OSError):
        return default


def package_hash(pkg: dict) -> str:
    core = {k: v for k, v in pkg.items() if k not in ("approval", "status", "checks", "built_at", "package_sha256")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def synthetic_disclosure(project: Path) -> dict:
    """From provenance: which generated assets are in the cut, and whether they are realistic."""
    timeline = _load(project / "timeline_ir.json", None) or _load(project / "timeline.json", {})
    used = {s.get("asset_id") for s in timeline.get("shots", [])}
    assets = _load(project / "approved_assets.json", {}).get("assets", []) + _load(project / "assets.json", {}).get("assets", [])
    jobs = [_load(f, {}) for f in sorted((project / "generation" / "jobs").glob("*.json"))] if (project / "generation" / "jobs").is_dir() else []
    generated = []
    for a in assets:
        if a.get("asset_id") in used and is_generated(a):
            generated.append({"asset_id": a.get("asset_id"), "media_class": a.get("media_class")})
    voice = [j for j in jobs if j.get("kind") == "voice" and j.get("state") in ("GENERATED", "REGISTERED")]
    if voice:
        generated.append({"asset_id": "narration", "media_class": "GENERATED_VOICE", "jobs": [j.get("request_id") for j in voice]})
    realistic = [g for g in generated if g.get("media_class") in REALISTIC]
    return {
        "containsSyntheticMedia": bool(realistic),
        "basis": "provenance of the assets in the timeline",
        "generated_in_cut": generated,
        "review": bool(generated and not realistic),
        "note": ("realistic generated media in the cut" if realistic else
                 "generated media in the cut, none marked realistic: confirm nothing could be mistaken for real" if generated else
                 "no generated media in the cut"),
    }


def _thumbnail_checks(path: Path | None) -> tuple[list[str], list[str], dict]:
    errors, warnings, info = [], [], {}
    if path is None:
        return ["no thumbnail"], [], info
    if not path.is_file():
        return [f"thumbnail not found: {path}"], [], info
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        errors.append("thumbnail must be JPG or PNG")
    size = path.stat().st_size
    info["bytes"] = size
    if size > THUMB_MAX_BYTES:
        errors.append(f"thumbnail is {size} bytes; the limit is 2 MB")
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
        info.update(width=w, height=h, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if w < THUMB_MIN_WIDTH:
            errors.append(f"thumbnail is {w} px wide; the minimum is 640")
        if abs(w / h - 16 / 9) > 0.02:
            errors.append(f"thumbnail is {w}x{h}; it must be 16:9")
        elif (w, h) != (1280, 720):
            warnings.append(f"thumbnail is {w}x{h}; 1280x720 is recommended")
    except ImportError:
        warnings.append("Pillow not installed: thumbnail size not measured")
    return errors, warnings, info


def check(pkg: dict, project: Path) -> dict:
    errors, warnings = [], []
    title, desc, tags = pkg.get("title", ""), pkg.get("description", ""), pkg.get("tags", [])
    if not 1 <= len(title) <= TITLE_MAX:
        errors.append(f"title is {len(title)} characters; it must be 1-{TITLE_MAX}")
    if any(c in title + desc for c in "<>"):
        errors.append("title and description may not contain '<' or '>'")
    nbytes = len(desc.encode("utf-8"))
    if nbytes > DESCRIPTION_MAX_BYTES:
        errors.append(f"description is {nbytes} bytes; the limit is {DESCRIPTION_MAX_BYTES}")
    tag_chars = len(",".join(tags))
    if tag_chars > TAGS_MAX_CHARS:
        errors.append(f"tags total {tag_chars} characters; the limit is {TAGS_MAX_CHARS}")
    if pkg.get("made_for_kids") not in (True, False):
        errors.append("made_for_kids must be declared explicitly (yes or no); it has no default")
    if pkg.get("publish_at") and pkg.get("privacy") != "private":
        errors.append("a scheduled publish_at requires privacy 'private' until the scheduled time")
    profile = _load(project / "channel_profile.json", {})
    limit = (profile.get("packaging") or {}).get("title_max_chars")
    if limit and len(title) > limit:
        warnings.append(f"title is {len(title)} characters; the channel convention is at most {limit} (longer titles are cut off in browse and search)")
    if desc and len(desc.split("\n", 1)[0]) > 170:
        warnings.append("the first line of the description runs past ~170 characters, which is all that shows above the fold")
    t_err, t_warn, t_info = _thumbnail_checks(Path(pkg["thumbnail"]) if pkg.get("thumbnail") else None)
    errors += t_err
    warnings += t_warn
    if pkg.get("disclosure", {}).get("review"):
        warnings.append(pkg["disclosure"]["note"])
    return {"errors": errors, "warnings": warnings, "thumbnail": t_info}


def build(project: Path, title: str, description: str, tags: list[str], thumbnail: str | None, made_for_kids: bool | None,
          category: str | None = None, publish_at: str | None = None, privacy: str | None = None) -> dict:
    profile = _load(project / "channel_profile.json", {})
    pkg = {
        "schema_version": 1, "platform": (profile.get("publishing") or {}).get("platform", "youtube"),
        "channel": (profile.get("pin") or {}), "title": title, "description": description, "tags": tags,
        "thumbnail": str(Path(thumbnail).resolve()) if thumbnail else None, "made_for_kids": made_for_kids,
        "category_id": category, "publish_at": publish_at,
        "privacy": privacy or (profile.get("publishing") or {}).get("default_privacy", "private"),
        "language": (profile.get("identity") or {}).get("language"),
        "disclosure": synthetic_disclosure(project),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    pkg["checks"] = check(pkg, project)
    pkg["status"] = "blocked" if pkg["checks"]["errors"] else "review_required"
    pkg["package_sha256"] = package_hash(pkg)
    (project / "publish_package.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return pkg


def approve(project: Path, by: str) -> dict:
    pkg = _load(project / "publish_package.json", None)
    if pkg is None:
        raise ValueError("no publish_package.json; run build first")
    if pkg["checks"]["errors"]:
        raise ValueError(f"the package has errors: {pkg['checks']['errors']}")
    if package_hash(pkg) != pkg["package_sha256"]:
        raise ValueError("publish_package.json was edited after it was built; rebuild it")
    pkg["approval"] = {"approved": True, "approved_by": by, "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "package_sha256": pkg["package_sha256"]}
    pkg["status"] = "passed"
    (project / "publish_package.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return pkg


def approved(project: Path) -> tuple[bool, str]:
    pkg = _load(project / "publish_package.json", None)
    if not pkg:
        return False, "no publish package"
    a = pkg.get("approval") or {}
    if not a.get("approved"):
        return False, "the publish package is not approved"
    if a.get("package_sha256") != package_hash(pkg):
        return False, "the publish package changed after it was approved"
    return True, "approved"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--project", type=Path, required=True)
    b.add_argument("--title", required=True)
    b.add_argument("--description-file", type=Path)
    b.add_argument("--tags", default="")
    b.add_argument("--thumbnail")
    b.add_argument("--made-for-kids", choices=["yes", "no"])
    b.add_argument("--category")
    b.add_argument("--publish-at")
    b.add_argument("--privacy", choices=["private", "unlisted", "public"])
    a2 = sub.add_parser("approve")
    a2.add_argument("--project", type=Path, required=True)
    a2.add_argument("--by", required=True)
    a = ap.parse_args()
    try:
        if a.cmd == "build":
            desc = a.description_file.read_text(encoding="utf-8") if a.description_file else ""
            mfk = None if a.made_for_kids is None else a.made_for_kids == "yes"
            out = build(a.project, a.title, desc, [t.strip() for t in a.tags.split(",") if t.strip()], a.thumbnail, mfk, a.category, a.publish_at, a.privacy)
            print(json.dumps({"status": out["status"], "checks": out["checks"], "disclosure": out["disclosure"]}, indent=2))
            return 0 if out["status"] != "blocked" else 1
        out = approve(a.project, a.by)
        print(json.dumps({"status": out["status"], "approval": out["approval"]}, indent=2))
        return 0
    except ValueError as e:
        print(json.dumps({"status": "blocked", "error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
