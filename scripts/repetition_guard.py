#!/usr/bin/env python3
"""Repetition guard: how much a new video repeats the channel's earlier ones, measured before publishing.

YouTube's monetisation policy (renamed "inauthentic content", effective 15 July 2025) targets mass-produced,
repetitive videos: templated formats repeated with little variation. An automated channel is exactly where
that happens, so before a video ships it is compared with every video in the channel history on:

- script wording: Jaccard similarity of word 5-gram shingles, estimated from a 128-value MinHash (the
  history keeps the signature, never the script text);
- structure: the sequence of shots as (transition, motion, duration band) tokens;
- transitions: the sequence of transition recipes alone;
- assets: share of this video's assets (by sha256, else asset id) already used in an earlier video;
- title: word Jaccard.

The similarities are MEASURED. Whether a platform would call the video repetitive is not something this
can know: the verdict is `review_required` above the channel's thresholds, never a prediction.

    python repetition_guard.py --project P --channel C
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PERMUTATIONS = 128
SHINGLE = 5
THRESHOLDS = {"script": 0.6, "structure": 0.9, "transitions": 0.9, "assets": 0.5, "title": 0.7}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (json.JSONDecodeError, OSError):
        return default


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def minhash(text: str) -> list[int]:
    words = _words(text)
    shingles = {" ".join(words[i : i + SHINGLE]) for i in range(max(1, len(words) - SHINGLE + 1))} if words else set()
    if not shingles:
        return []
    sig = []
    for k in range(PERMUTATIONS):
        salt = k.to_bytes(8, "little")
        sig.append(min(int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8, salt=salt).digest(), "little") for s in shingles))
    return sig


def minhash_similarity(a: list[int], b: list[int]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def _band(seconds: float) -> str:
    return "s" if seconds < 2 else ("m" if seconds < 5 else "l")


def fingerprint(project: Path) -> dict:
    """What is compared, read from the project's own artifacts (missing artifacts give empty parts)."""
    script = _load(project / "script.json", {})
    text = " ".join(b.get("narration", "") for b in script.get("beats", []))
    timeline = _load(project / "timeline_ir.json", None) or _load(project / "timeline.json", {})
    shots = timeline.get("shots", [])
    assets = {a.get("asset_id"): a for a in (_load(project / "approved_assets.json", {}).get("assets", []) + _load(project / "assets.json", {}).get("assets", []))}
    used = []
    for s in shots:
        a = assets.get(s.get("asset_id"), {})
        used.append(a.get("sha256") or f"id:{s.get('asset_id')}")
    package = _load(project / "publish_package.json", {})
    return {
        "script_minhash": minhash(text),
        "structure": [f"{s.get('transition', 'cut')}|{s.get('motion', 'static')}|{_band(float(s.get('end', 0)) - float(s.get('start', 0)))}" for s in shots],
        "transitions": [s.get("transition", "cut") for s in shots],
        "assets": sorted(set(u for u in used if u)),
        "title_words": sorted(set(_words(package.get("title", "")))),
    }


def _seq(a: list[str], b: list[str]) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def compare(fp: dict, past: dict) -> dict:
    a_assets = set(fp["assets"])
    tw_a, tw_b = set(fp["title_words"]), set(past.get("title_words", []))
    return {
        "script": round(minhash_similarity(fp["script_minhash"], past.get("script_minhash", [])), 3),
        "structure": round(_seq(fp["structure"], past.get("structure", [])), 3),
        "transitions": round(_seq(fp["transitions"], past.get("transitions", [])), 3),
        "assets": round(len(a_assets & set(past.get("assets", []))) / len(a_assets), 3) if a_assets else 0.0,
        "title": round(len(tw_a & tw_b) / len(tw_a | tw_b), 3) if tw_a and tw_b else 0.0,
    }


def check(project: Path, channel_id: str, root: str | None = None) -> dict:
    import channel as channel_mod

    profile = channel_mod.load(channel_id, root=root)
    thresholds = {**THRESHOLDS, "script": profile.get("qa", {}).get("repetition_max_similarity", THRESHOLDS["script"])}
    fp = fingerprint(project)
    rows = []
    for past in channel_mod.history(channel_id, root):
        if Path(past.get("project", "")).resolve() == project.resolve():
            continue
        sims = compare(fp, past)
        over = [k for k, v in sims.items() if v >= thresholds[k]]
        # Structure alone is a format, which a channel is allowed to have; it only counts together with transitions.
        if "structure" in over and "transitions" not in over:
            over.remove("structure")
        rows.append({"project": past.get("project"), "recorded_at": past.get("recorded_at"), "similarity": sims, "over_threshold": over})
    rows.sort(key=lambda r: max(r["similarity"].values()), reverse=True)
    flagged = [r for r in rows if r["over_threshold"]]
    report = {
        "schema_version": 1, "channel_id": channel_id, "basis": "MEASURED similarities; the verdict is a review flag, not a platform prediction",
        "thresholds": thresholds, "compared_with": len(rows), "closest": rows[:5], "flagged": flagged,
        "status": "review_required" if flagged else "passed",
        "policy_context": "YouTube Partner Program 'inauthentic content' (mass-produced or repetitive), effective 2025-07-15",
    }
    (project / "repetition_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--channel", required=True)
    ap.add_argument("--root")
    a = ap.parse_args()
    report = check(a.project, a.channel, a.root)
    print(json.dumps({k: report[k] for k in ("status", "compared_with", "flagged")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
