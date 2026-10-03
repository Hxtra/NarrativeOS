#!/usr/bin/env python3
"""
Ingest downloaded overlay clips (light leaks, film burns, dust...) into the
local NarrativeOS VFX library, which lives OUTSIDE the public repo.

    python vfx_ingest.py ingest <folder-of-downloads> [--provenance <dir of per-file JSON records>]
                                                       [--source-url URL --license TEXT --rights-status verified --notes TEXT]
    python vfx_ingest.py reject <asset-id> --reason TEXT
    python vfx_ingest.py confirm <asset-id> [--category light_leak] [--blend multiply --reason TEXT]
    python vfx_ingest.py reanalyze [asset-id ...]   # re-measure, keeping review decisions
    python vfx_ingest.py credits [asset-id ...]     # attribution lines owed
    python vfx_ingest.py list
    python vfx_ingest.py catalog            # rebuild vfx_catalog.json from metadata/

Library root: $NARRATIVEOS_VFX_LIBRARY, default ~/NarrativeOS-VFX-Library.

What ingest measures, per clip (all via ffmpeg, never guessed from the name):
  - technical facts via media-library/tools/probe_asset.py (fps, size, codec, alpha)
  - per-frame mean luma -> the PEAK frame, where a transition should centre
  - background luma (median 10th-percentile) -> whether Screen/Add blend works
  - mean chroma -> warm / cool / neutral / mono tone
  - a 4x2 contact sheet for visual review

The category it assigns is only a SUGGESTION from those numbers. Recipes
resolve confirmed assets only, so every clip needs a person (or Claude) to
look at its contact sheet and run `confirm`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "media-library" / "tools"))
from probe_asset import probe  # noqa: E402

SCHEMA_PATH = HERE.parent / "schema" / "vfx_asset.schema.json"
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
CATEGORIES = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["properties"]["category"]["enum"]
ALPHA_PIX_FMTS = re.compile(r"(yuva|rgba|argb|bgra|abgr|gbrap|ya8|ya16|pal8)")


def library_root(arg: str | None) -> Path:
    root = arg or os.environ.get("NARRATIVEOS_VFX_LIBRARY") or str(Path.home() / "NarrativeOS-VFX-Library")
    return Path(root).expanduser().resolve()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def frame_stats(path: Path) -> list[dict[str, float]]:
    """Per-frame signalstats (YAVG, YLOW, YHIGH, UAVG, VAVG) on a downscaled copy."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", "scale=256:-2,signalstats,metadata=mode=print:file=-",
        "-an", "-f", "null", "-",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    frames: list[dict[str, float]] = []
    for line in out.splitlines():
        if line.startswith("frame:"):
            frames.append({})
        elif line.startswith("lavfi.signalstats.") and frames:
            key, _, value = line[len("lavfi.signalstats."):].partition("=")
            try:
                frames[-1][key] = float(value)
            except ValueError:
                pass
    return [f for f in frames if "YAVG" in f]


def analyze(stats: list[dict[str, float]], fps: float | None, has_alpha: bool) -> dict:
    if not stats:
        raise ValueError("ffmpeg produced no per-frame statistics")
    yavg = [f["YAVG"] for f in stats]
    # The peak is where the overlay is centred on a cut, so it needs footage on both sides:
    # search away from the clip's edges (a lone white tail frame is not the clip's peak).
    margin = min(round(fps / 2) if fps else 15, (len(yavg) - 1) // 4)
    peak = max(range(margin, len(yavg) - margin), key=lambda i: yavg[i])
    lmin, lmax = min(yavg), max(yavg)
    background = statistics.median(f.get("YLOW", 0.0) for f in stats)
    bright = [y for y in yavg if lmax > 0 and y >= lmin + 0.6 * (lmax - lmin)]

    # Tone from the brightest quarter of frames: that's where an overlay is visible.
    top = sorted(range(len(yavg)), key=lambda i: yavg[i], reverse=True)[: max(1, len(yavg) // 4)]
    u = statistics.mean(stats[i].get("UAVG", 128.0) for i in top)
    v = statistics.mean(stats[i].get("VAVG", 128.0) for i in top)

    if has_alpha:
        blend = "normal"
    elif background < 24:
        blend = "screen"
    elif statistics.mean(yavg) > 170:
        blend = "multiply"
    else:
        blend = "overlay"

    return {
        "frames_analyzed": len(stats),
        "peak_frame": peak,
        "peak_search_margin_frames": margin,
        "peak_time_sec": round(peak / fps, 4) if fps else 0.0,
        "luma_mean": round(statistics.mean(yavg), 2),
        "luma_min": round(lmin, 2),
        "luma_max": round(lmax, 2),
        "background_luma_p10": round(background, 2),
        "bright_frame_fraction": round(len(bright) / len(yavg), 3),
        "chroma_u_mean": round(u, 2),
        "chroma_v_mean": round(v, 2),
        "recommended_blend": blend,
    }


def tone_of(a: dict) -> str:
    du, dv = a["chroma_u_mean"] - 128, a["chroma_v_mean"] - 128
    if abs(du) < 2 and abs(dv) < 2:
        return "mono"
    if dv > du + 3:
        return "warm"
    if du > dv + 3:
        return "cool"
    return "neutral"


def suggest_category(a: dict, tone: str, has_alpha: bool) -> str:
    """Coarse heuristic only; the contact sheet decides."""
    if has_alpha:
        return "unclassified"
    if a["recommended_blend"] == "screen":
        swing = a["luma_max"] - a["luma_min"]
        if a["luma_max"] > 180 and a["bright_frame_fraction"] < 0.2:
            return "flash"
        # Dust/specks are untinted; a strongly coloured dim clip (e.g. a blue
        # leak, which barely moves luma) is not dust.
        if a["luma_mean"] < 35 and swing < 40 and tone in ("mono", "neutral"):
            return "dust"
        if swing > 30 and tone in ("warm", "cool"):
            return "light_leak"
        return "unclassified"
    return "texture"


def contact_sheet(src: Path, dest: Path, frame_count: int) -> None:
    step = max(1, frame_count // 8)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-vf", f"select='not(mod(n\\,{step}))',scale=320:-2,tile=4x2",
         "-frames:v", "1", "-update", "1", str(dest)],
        check=True,
    )


def next_id(root: Path, category: str, tone: str) -> str:
    taken = {p.stem for p in (root / "metadata").glob(f"vfx_{category}_{tone}_*.json")}
    n = 1
    while f"vfx_{category}_{tone}_{n:03d}" in taken:
        n += 1
    return f"vfx_{category}_{tone}_{n:03d}"


def load_records(root: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "metadata").glob("*.json"))]


def validate(record: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        print("warning: jsonschema not installed; skipping schema validation", file=sys.stderr)
        return
    jsonschema.validate(record, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def write_record(root: Path, record: dict) -> None:
    validate(record)
    path = root / "metadata" / f"{record['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def rebuild_catalog(root: Path) -> Path:
    records = load_records(root)
    catalog = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asset_count": len(records),
        "assets": records,
    }
    out = root / "vfx_catalog.json"
    out.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return out


# Downloaders' category labels -> library categories. Only a SUGGESTION: the contact sheet decides.
SOURCE_CATEGORY_HINTS = {
    "light_leaks": "light_leak", "glitches": "glitch", "snow": "weather", "rain": "weather", "textures": "texture",
    "particles": "particles", "sparks": "particles", "film_dust": "dust", "lens_flares": "lens_flare",
    "film_grain": "grain", "film_scratches": "scratches", "film_flicker": "flicker", "crt": "crt",
}


def load_provenance(folder: Path | None) -> dict[str, dict]:
    """Per-file source records (one JSON per clip), keyed by their stated sha256 checksum."""
    if folder is None:
        return {}
    records = {}
    for path in sorted(Path(folder).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("checksum"):
            records[data["checksum"].lower()] = {**data, "_file": path.name}
    return records


def rights_from_provenance(rec: dict) -> dict:
    """Rights block from a source record. 'verified' needs an explicit licence that allows commercial use."""
    r, src = rec.get("rights", {}), rec.get("source", {})
    license_ = r.get("license")
    verified = bool(license_) and r.get("commercial_use") is True and r.get("status", "verified") == "verified"
    return {
        "source_url": src.get("source_url"), "license": license_, "rights_status": "verified" if verified else "unknown",
        "redistributable": False,  # never re-shared as standalone files (Pixabay forbids it; the repo is public)
        "provider": src.get("provider"), "asset_url": src.get("asset_url"), "license_url": r.get("license_url"),
        "commercial_use": r.get("commercial_use"), "attribution_required": r.get("attribution_required"),
        "attribution_text": r.get("attribution_text"), "share_alike": "-SA" in (license_ or "").upper(),
        "redistribution_terms": r.get("redistribution"), "provenance_checksum_verified": True,
        "notes": "Use only inside larger works; keep attribution where required.",
    }


def ingest_file(root: Path, src: Path, known: dict[str, str], source_url: str | None, license_: str | None, rights_status: str = "unknown",
                notes: str | None = None, provenance: dict[str, dict] | None = None) -> dict | None:
    digest = sha256(src)
    if digest in known:
        print(f"skip  {src.name}: already in library as {known[digest]}")
        return None
    source = (provenance or {}).get(digest)
    tech = probe(str(src))
    has_alpha = bool(tech.get("pix_fmt") and ALPHA_PIX_FMTS.search(tech["pix_fmt"]))
    a = analyze(frame_stats(src), tech.get("source_fps"), has_alpha)
    tone = tone_of(a)
    category = SOURCE_CATEGORY_HINTS.get((source or {}).get("category"), None) or suggest_category(a, tone, has_alpha)
    asset_id = next_id(root, category, tone)
    rel = f"{category}/{asset_id}{src.suffix.lower()}"
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    sheet = f"contact_sheets/{asset_id}.jpg"
    contact_sheet(dest, root / sheet, a["frames_analyzed"])
    record = {
        "schema_version": 1,
        "id": asset_id,
        "sha256": digest,
        "original_filename": src.name,
        "library_path": rel,
        "category": category,
        "category_status": "suggested",
        "tone": tone,
        "technical": {
            "duration_sec": tech.get("duration_sec"),
            "width": tech.get("width"),
            "height": tech.get("height"),
            "source_fps": tech.get("source_fps"),
            "real_source_frame_count": tech.get("real_source_frame_count"),
            "video_codec": tech.get("video_codec"),
            "pix_fmt": tech.get("pix_fmt"),
            "has_alpha": has_alpha,
            "has_audio": bool(tech.get("has_audio")),
            "audio_codec": tech.get("audio_codec"),
            "file_size_bytes": dest.stat().st_size,
        },
        "analysis": a,
        "rights": rights_from_provenance(source) if source else {
            "source_url": source_url,
            "license": license_,
            "rights_status": rights_status,
            "redistributable": False,
            "notes": notes or "Local use only until the download source and licence are recorded.",
        },
        "contact_sheet": sheet,
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if source:
        record["source_metadata"] = {"id": source.get("id", ""), "category": source.get("category", ""), "name": source.get("name", ""), "metadata_file": source["_file"]}
    write_record(root, record)
    print(f"added {src.name} -> {asset_id}  (suggested {category}, {tone}, peak frame {a['peak_frame']}, blend {a['recommended_blend']})")
    return record


def cmd_ingest(args) -> int:
    root = library_root(args.library)
    inbox = Path(args.folder).expanduser().resolve()
    files = sorted(p for p in inbox.rglob("*") if p.suffix.lower() in VIDEO_EXTS and root not in p.parents)
    if not files:
        print(f"no video files found under {inbox}", file=sys.stderr)
        return 1
    known = {r["sha256"]: r["id"] for r in load_records(root)}
    provenance = load_provenance(Path(args.provenance) if args.provenance else None)
    if args.provenance and not provenance:
        print(f"no provenance records with checksums found in {args.provenance}", file=sys.stderr)
        return 1
    failed = 0
    for f in files:
        try:
            rec = ingest_file(root, f, known, args.source_url, args.license, args.rights_status, args.notes, provenance)
            if rec:
                known[rec["sha256"]] = rec["id"]
        except (subprocess.CalledProcessError, ValueError) as e:
            failed += 1
            print(f"FAIL  {f.name}: {e}", file=sys.stderr)
    print(f"catalog: {rebuild_catalog(root)}")
    return 1 if failed else 0


def cmd_confirm(args) -> int:
    root = library_root(args.library)
    meta = root / "metadata" / f"{args.asset_id}.json"
    if not meta.is_file():
        print(f"unknown asset {args.asset_id}", file=sys.stderr)
        return 1
    rec = json.loads(meta.read_text(encoding="utf-8"))
    category = args.category or rec["category"]
    if category not in CATEGORIES:
        print(f"unknown category {category}; choose from {', '.join(CATEGORIES)}", file=sys.stderr)
        return 1
    if category == "unclassified":
        print("pick a real category before confirming", file=sys.stderr)
        return 1
    if category != rec["category"]:
        new_id = next_id(root, category, rec["tone"])
        old_file = root / rec["library_path"]
        new_rel = f"{category}/{new_id}{old_file.suffix}"
        (root / new_rel).parent.mkdir(parents=True, exist_ok=True)
        old_file.rename(root / new_rel)
        if rec.get("contact_sheet") and (root / rec["contact_sheet"]).is_file():
            new_sheet = f"contact_sheets/{new_id}.jpg"
            (root / rec["contact_sheet"]).rename(root / new_sheet)
            rec["contact_sheet"] = new_sheet
        meta.unlink()
        rec.update(id=new_id, library_path=new_rel, category=category)
    if args.blend:
        blends = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["properties"]["analysis"]["properties"]["recommended_blend"]["enum"]
        if args.blend not in blends:
            print(f"unknown blend {args.blend}; choose from {', '.join(blends)}", file=sys.stderr)
            return 1
        if args.blend != rec["analysis"]["recommended_blend"]:
            rec["blend_override"] = {"from": rec["analysis"]["recommended_blend"], "to": args.blend, "reason": args.reason or "set in contact-sheet review"}
            rec["analysis"]["recommended_blend"] = args.blend
    rec["category_status"] = "confirmed"
    rec.pop("rejection_reason", None)
    write_record(root, rec)
    rebuild_catalog(root)
    print(f"confirmed {rec['id']} as {category}" + (f" (blend {args.blend})" if args.blend else ""))
    return 0


def cmd_reject(args) -> int:
    """Keep the record (and the reason), but never let a recipe use this clip."""
    root = library_root(args.library)
    meta = root / "metadata" / f"{args.asset_id}.json"
    if not meta.is_file() or not args.reason:
        print("reject needs a known asset id and --reason", file=sys.stderr)
        return 1
    rec = json.loads(meta.read_text(encoding="utf-8"))
    rec.update(category_status="rejected", rejection_reason=args.reason)
    write_record(root, rec)
    rebuild_catalog(root)
    print(f"rejected {rec['id']}: {args.reason}")
    return 0


def cmd_credits(args) -> int:
    """Attribution lines owed by the clips a video uses (or by every confirmed clip that needs one)."""
    import re as _re
    recs = [r for r in load_records(library_root(args.library)) if r["category_status"] == "confirmed"]
    if args.ids:
        wanted = set(args.ids)
        recs = [r for r in recs if r["id"] in wanted]
        missing = wanted - {r["id"] for r in recs}
        if missing:
            print(f"unknown or unconfirmed assets: {sorted(missing)}", file=sys.stderr)
            return 1
    for r in recs:
        rights = r["rights"]
        if rights.get("attribution_required"):
            text = _re.sub(r"<[^>]+>", "", rights.get("attribution_text") or "").strip()
            print(f"{r['id']}: {text} ({rights.get('license')}, {rights.get('source_url')})")
    return 0


def cmd_reanalyze(args) -> int:
    """Re-measure clips after an analysis change. Review decisions (category, status, blend override) are kept."""
    root = library_root(args.library)
    recs = [r for r in load_records(root) if not args.ids or r["id"] in set(args.ids)]
    for rec in recs:
        old = rec["analysis"]
        a = analyze(frame_stats(root / rec["library_path"]), rec["technical"].get("source_fps"), rec["technical"]["has_alpha"])
        if rec.get("blend_override"):
            a["recommended_blend"] = rec["blend_override"]["to"]
        rec["analysis"] = a
        write_record(root, rec)
        if old.get("peak_frame") != a["peak_frame"]:
            print(f"{rec['id']}: peak frame {old.get('peak_frame')} -> {a['peak_frame']}")
    rebuild_catalog(root)
    print(f"reanalyzed {len(recs)} clips")
    return 0


def cmd_list(args) -> int:
    for r in load_records(library_root(args.library)):
        a = r["analysis"]
        print(f"{r['id']:34} {r['category_status']:9} peak={a['peak_time_sec']:6.2f}s  {a['recommended_blend']:8} {r['original_filename']}")
    return 0


def cmd_catalog(args) -> int:
    print(rebuild_catalog(library_root(args.library)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--library", help="library root (default: $NARRATIVEOS_VFX_LIBRARY or ~/NarrativeOS-VFX-Library)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("folder")
    p.add_argument("--source-url")
    p.add_argument("--license")
    p.add_argument("--rights-status", choices=["unknown", "verified", "restricted"], default="unknown",
                   help="verified = the recorded licence permits use in the owner's productions")
    p.add_argument("--notes")
    p.add_argument("--provenance", help="folder of per-file source records (JSON with a sha256 'checksum'); matched by checksum, never by filename")
    p.set_defaults(func=cmd_ingest)
    p = sub.add_parser("reject")
    p.add_argument("asset_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_reject)
    p = sub.add_parser("confirm")
    p.add_argument("asset_id")
    p.add_argument("--category")
    p.add_argument("--blend", help="override the analysis blend after looking at the clip (screen, add, overlay, multiply, normal)")
    p.add_argument("--reason", help="why the blend was overridden")
    p.set_defaults(func=cmd_confirm)
    p = sub.add_parser("credits", help="print attribution lines owed (all confirmed clips, or the given ids)")
    p.add_argument("ids", nargs="*")
    p.set_defaults(func=cmd_credits)
    p = sub.add_parser("reanalyze", help="re-measure clips (all, or the given ids), keeping review decisions")
    p.add_argument("ids", nargs="*")
    p.set_defaults(func=cmd_reanalyze)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("catalog").set_defaults(func=cmd_catalog)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # attribution text has dashes and accents; Windows consoles default to cp1252
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
