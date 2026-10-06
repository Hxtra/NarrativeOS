#!/usr/bin/env python3
"""Creative memory: what a human accepted, rejected or corrected, in context and with the reason.

Each decision is one record in the channel's memory.jsonl (see channel.py), scoped to the video it was made
on. Memory informs later proposals as PRECEDENT (advisory: "last time on a shot like this you said it
needed to breathe"), never as an automatic rule. A decision becomes a channel rule only by an explicit
`promote` that cites at least MIN_PROMOTE consistent decisions; that writes a new profile version, and
`retire` removes it the same way. One correction is never silently turned into a universal rule.

    python creative_memory.py record --channel C --project P --stage TIMELINE --target shot:S012 \\
        --decision corrected --reason "the shot needs to breathe" --before '{"duration":1.2}' --after '{"duration":2.4}' --tags pacing,landscape
    python creative_memory.py precedents --channel C --stage TIMELINE [--tags pacing]
    python creative_memory.py promote --channel C --decisions D0003,D0007 --rule "Hold landscape shots >= 2 s" --stage TIMELINE
    python creative_memory.py retire --channel C --rule R001 --reason "new format is faster"

Legacy (kept for older projects): python creative_memory.py --project P --preference key=value [--version-a ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import channel as channel_mod  # noqa: E402

DECISIONS = ("accepted", "rejected", "corrected")
MIN_PROMOTE = 2


def _path(channel_id: str, root: str | None = None) -> Path:
    d = channel_mod.channel_dir(channel_id, root)
    if not channel_mod.versions(channel_id, root):
        raise FileNotFoundError(f"no channel {channel_id!r}; create it with channel.py create")
    return d / "memory.jsonl"


def load(channel_id: str, root: str | None = None) -> list[dict]:
    p = _path(channel_id, root)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.is_file() else []


def record(channel_id: str, project: str, stage: str, target: str, decision: str, reason: str, before=None, after=None,
           tags: list[str] | None = None, root: str | None = None) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if decision in ("rejected", "corrected") and not reason.strip():
        raise ValueError("a rejection or correction needs the reason: that is what makes it reusable")
    if decision == "corrected" and after is None:
        raise ValueError("a correction needs --after (what it was changed to)")
    rows = load(channel_id, root)
    profile = channel_mod.load(channel_id, root=root)
    rec = {"id": f"D{len(rows) + 1:04d}", "recorded_at": channel_mod.now(), "channel_id": channel_id, "project": project,
           "profile_version": profile["profile_version"], "stage": stage, "target": target, "decision": decision,
           "reason": reason, "before": before, "after": after, "tags": sorted(set(tags or [])), "scope": "this_video"}
    with _path(channel_id, root).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def precedents(channel_id: str, stage: str, tags: list[str] | None = None, limit: int = 10, root: str | None = None) -> dict:
    """Earlier decisions at this stage, most tag overlap first, newest first. ADVISORY: the caller decides."""
    want = set(tags or [])
    rows = [r for r in load(channel_id, root) if r["stage"] == stage]
    rows.sort(key=lambda r: (len(want & set(r["tags"])), r["recorded_at"]), reverse=True)
    profile = channel_mod.load(channel_id, root=root)
    rules = [r for r in profile["rules"] if r["stage"] == stage]
    return {"basis": "ADVISORY", "note": "Precedents inform a proposal; they are not rules. Channel rules are listed separately.",
            "precedents": rows[:limit], "channel_rules": rules}


def promote(channel_id: str, decision_ids: list[str], rule_text: str, stage: str, root: str | None = None) -> dict:
    rows = {r["id"]: r for r in load(channel_id, root)}
    missing = [d for d in decision_ids if d not in rows]
    if missing:
        raise ValueError(f"unknown decisions: {missing}")
    cited = [rows[d] for d in decision_ids]
    if len(cited) < MIN_PROMOTE:
        raise ValueError(f"a channel rule needs at least {MIN_PROMOTE} consistent decisions; one correction is not a rule")
    if any(r["stage"] != stage for r in cited):
        raise ValueError("every cited decision must be from the rule's stage")
    if len({r["project"] for r in cited}) < 2:
        raise ValueError("cited decisions must come from at least 2 different videos, or it is one video's taste")
    if len({r["decision"] for r in cited}) > 1:
        raise ValueError("the cited decisions disagree (accepted vs rejected/corrected); resolve that before making a rule")
    profile = channel_mod.load(channel_id, root=root)
    rules = list(profile["rules"])
    rid = f"R{max([int(r['id'][1:]) for r in rules] + [0]) + 1:03d}"
    tags = sorted(set().union(*(set(r["tags"]) for r in cited)))
    rules.append({"id": rid, "text": rule_text, "stage": stage, "tags": tags, "source_decisions": decision_ids, "promoted_at": channel_mod.now()})
    new = channel_mod.write_version_with_rules(channel_id, rules, f"promoted {rid} from {', '.join(decision_ids)}: {rule_text}", root)
    return {"rule": rules[-1], "profile_version": new["profile_version"]}


def retire(channel_id: str, rule_id: str, reason: str, root: str | None = None) -> dict:
    if not reason.strip():
        raise ValueError("retiring a rule needs a reason")
    profile = channel_mod.load(channel_id, root=root)
    if rule_id not in {r["id"] for r in profile["rules"]}:
        raise ValueError(f"no active rule {rule_id}")
    new = channel_mod.write_version_with_rules(channel_id, [r for r in profile["rules"] if r["id"] != rule_id], f"retired {rule_id}: {reason}", root)
    return {"retired": rule_id, "profile_version": new["profile_version"]}


def legacy(project: Path, preferences: list[str], version_a: str, version_b: str) -> dict:
    taste = project / "taste_profile.json"
    profile = json.loads(taste.read_text()) if taste.exists() else {"schema_version": 1, "preferences": {}}
    for item in preferences:
        if "=" in item:
            k, v = item.split("=", 1)
            profile["preferences"][k] = v
    profile["status"] = "review_required" if not profile["preferences"] else "passed"
    taste.write_text(json.dumps(profile, indent=2) + "\n")
    ab = {"schema_version": 1, "status": "review_required",
          "variants": [{"id": "A", "timeline": version_a, "style": "fast/high-SFX"}, {"id": "B", "timeline": version_b, "style": "slow/atmospheric"}],
          "comparison_metrics": ["pacing", "visual diversity", "caption load", "audio design", "narrative clarity", "human preference"]}
    (project / "ab_edit_manifest.json").write_text(json.dumps(ab, indent=2) + "\n")
    return {"status": "passed", "taste_profile": str(taste), "ab_manifest": "ab_edit_manifest.json"}


def _json_or_none(text: str | None):
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main() -> int:
    if "--project" in sys.argv[1:2] or (len(sys.argv) > 1 and sys.argv[1] == "--project"):
        ap = argparse.ArgumentParser()
        ap.add_argument("--project", type=Path, required=True)
        ap.add_argument("--preference", action="append", default=[])
        ap.add_argument("--version-a", default="")
        ap.add_argument("--version-b", default="")
        a = ap.parse_args()
        print(json.dumps(legacy(a.project, a.preference, a.version_a, a.version_b), indent=2))
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="channels folder (default $NARRATIVEOS_CHANNELS or ~/NarrativeOS-Channels)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("record")
    for k in ("--channel", "--project", "--stage", "--target", "--decision"):
        p.add_argument(k, required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--before")
    p.add_argument("--after")
    p.add_argument("--tags", default="")
    p = sub.add_parser("precedents")
    p.add_argument("--channel", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--tags", default="")
    p = sub.add_parser("promote")
    p.add_argument("--channel", required=True)
    p.add_argument("--decisions", required=True)
    p.add_argument("--rule", required=True)
    p.add_argument("--stage", required=True)
    p = sub.add_parser("retire")
    p.add_argument("--channel", required=True)
    p.add_argument("--rule", required=True)
    p.add_argument("--reason", required=True)
    a = ap.parse_args()
    tags = [t for t in getattr(a, "tags", "").split(",") if t]
    try:
        if a.cmd == "record":
            out = record(a.channel, a.project, a.stage, a.target, a.decision, a.reason, _json_or_none(a.before), _json_or_none(a.after), tags, a.root)
        elif a.cmd == "precedents":
            out = precedents(a.channel, a.stage, tags, root=a.root)
        elif a.cmd == "promote":
            out = promote(a.channel, [d.strip() for d in a.decisions.split(",") if d.strip()], a.rule, a.stage, a.root)
        else:
            out = retire(a.channel, a.rule, a.reason, a.root)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"status": "blocked", "error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
