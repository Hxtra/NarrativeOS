#!/usr/bin/env python3
"""Channel profiles: the persistent identity a channel's videos are made under.

A profile is a versioned production constitution (voice, pacing, visual language, audience promise,
cadence, music policy, packaging conventions, QA, and the rules a human has explicitly promoted from
creative memory). Every change writes a new immutable version with a reason; a project pins the exact
version and hash it was made under, so a later profile change never silently rewrites an earlier video.

Channel data is the owner's, not the engine's: it lives outside the public repo, in
$NARRATIVEOS_CHANNELS (default ~/NarrativeOS-Channels), one folder per channel:

    <root>/<channel_id>/profile.v001.json, profile.v002.json, ...   (immutable versions)
    <root>/<channel_id>/memory.jsonl                                 (creative memory, see creative_memory.py)
    <root>/<channel_id>/history.jsonl                                (videos made, for the repetition guard)

    python channel.py create <id> --name "..." --niche "..." [--from profile.json]
    python channel.py show <id> [--version N]
    python channel.py update <id> --set visual.aspect_ratio='"9:16"' --reason "..."
    python channel.py history <id>
    python channel.py apply <id> --project <dir>
    python channel.py record-video <id> --project <dir>
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "channel_profile.schema.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

DEFAULT_PROFILE = {
    "schema_version": 1,
    "identity": {"name": "", "niche": "", "audience_promise": "", "language": "en", "production_profile": "documentary",
                 "cadence": {"videos_per_week": None}},
    "narrative": {"hook_seconds": 10, "pattern_interrupt_interval_sec": None, "voice_rules": [], "structure": ""},
    "voice": {"provider": None, "voice_id": None, "style": "", "words_per_minute": None},
    "visual": {"style_profile": "documentary_general", "aspect_ratio": "16:9", "visual_grammar": [], "forbidden": []},
    "editing": {"allowed_transitions": [], "target_shot_sec": None, "vfx_density": None},
    "audio": {"music_policy": "", "ducking_db": -12, "beat_sync": False},
    "captions": {"style": "", "safe_area": True},
    "packaging": {"title_max_chars": 70, "title_rules": [], "thumbnail_rules": [], "description_template": ""},
    "publishing": {"platform": "youtube", "default_privacy": "private", "synthetic_media_disclosure": "from_provenance"},
    "qa": {"required_checks": [], "repetition_max_similarity": 0.6},
    "rules": [],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def channels_root(override: str | None = None) -> Path:
    root = Path(override or os.environ.get("NARRATIVEOS_CHANNELS") or Path.home() / "NarrativeOS-Channels").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def channel_dir(channel_id: str, root: str | None = None) -> Path:
    if not ID_RE.match(channel_id):
        raise ValueError(f"channel id {channel_id!r}: lowercase letters, digits, - and _ only (2-64 chars)")
    return channels_root(root) / channel_id


def canonical(data: dict) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha(data: dict) -> str:
    return hashlib.sha256(canonical(data).encode("utf-8")).hexdigest()


def validate(profile: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    jsonschema.validate(profile, json.loads(SCHEMA.read_text(encoding="utf-8")))


def versions(channel_id: str, root: str | None = None) -> list[int]:
    d = channel_dir(channel_id, root)
    return sorted(int(m.group(1)) for f in d.glob("profile.v*.json") if (m := re.match(r"profile\.v(\d+)\.json$", f.name)))


def load(channel_id: str, version: int | None = None, root: str | None = None) -> dict:
    vs = versions(channel_id, root)
    if not vs:
        raise FileNotFoundError(f"no channel {channel_id!r} in {channels_root(root)}")
    v = version or vs[-1]
    if v not in vs:
        raise FileNotFoundError(f"channel {channel_id!r} has no version {v} (has {vs})")
    return json.loads((channel_dir(channel_id, root) / f"profile.v{v:03d}.json").read_text(encoding="utf-8"))


def _write_version(channel_id: str, profile: dict, reason: str, root: str | None = None) -> dict:
    d = channel_dir(channel_id, root)
    d.mkdir(parents=True, exist_ok=True)
    vs = versions(channel_id, root)
    profile = copy.deepcopy(profile)
    profile.update(channel_id=channel_id, profile_version=(vs[-1] + 1) if vs else 1, parent_version=vs[-1] if vs else None,
                   change_reason=reason, created_at=now())
    profile.pop("profile_sha256", None)
    validate(profile)
    profile["profile_sha256"] = sha({k: v for k, v in profile.items() if k not in ("created_at",)})
    path = d / f"profile.v{profile['profile_version']:03d}.json"
    if path.exists():
        raise FileExistsError(f"{path} already exists; profile versions are immutable")
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return profile


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def create(channel_id: str, name: str = "", niche: str = "", from_profile: dict | None = None, root: str | None = None) -> dict:
    if versions(channel_id, root):
        raise FileExistsError(f"channel {channel_id!r} already exists; use update")
    profile = _merge(DEFAULT_PROFILE, from_profile or {})
    if name:
        profile["identity"]["name"] = name
    if niche:
        profile["identity"]["niche"] = niche
    return _write_version(channel_id, profile, "created", root)


def set_path(profile: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    node = profile
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            raise KeyError(f"{dotted}: {k} is not a section")
        node = node[k]
    if keys[-1] in ("rules",) or keys[0] in ("channel_id", "profile_version", "parent_version", "profile_sha256", "created_at"):
        raise KeyError(f"{dotted} is managed by the system (rules come from creative_memory.py promote)")
    node[keys[-1]] = value


def update(channel_id: str, changes: dict[str, object], reason: str, root: str | None = None) -> dict:
    if not reason.strip():
        raise ValueError("every profile change needs a reason")
    profile = load(channel_id, root=root)
    for dotted, value in changes.items():
        set_path(profile, dotted, value)
    return _write_version(channel_id, profile, reason, root)


def write_version_with_rules(channel_id: str, rules: list[dict], reason: str, root: str | None = None) -> dict:
    """Used by creative_memory.py promote/retire: the only way rules change."""
    profile = load(channel_id, root=root)
    profile["rules"] = rules
    return _write_version(channel_id, profile, reason, root)


def apply(channel_id: str, project: Path, version: int | None = None, root: str | None = None) -> dict:
    """Pin a project to an exact profile version (STYLE_LOCK writes channel_profile.json)."""
    profile = load(channel_id, version, root)
    project.mkdir(parents=True, exist_ok=True)
    pinned = {**profile, "status": "passed", "pinned_at": now(),
              "pin": {"channel_id": channel_id, "profile_version": profile["profile_version"], "profile_sha256": profile["profile_sha256"]}}
    (project / "channel_profile.json").write_text(json.dumps(pinned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return pinned


def pinned_profile(project: Path) -> dict | None:
    p = project / "channel_profile.json"
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if data.get("pin") else None


def history(channel_id: str, root: str | None = None) -> list[dict]:
    p = channel_dir(channel_id, root) / "history.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.is_file() else []


def record_video(channel_id: str, project: Path, root: str | None = None) -> dict:
    """Add a finished video's fingerprint to the channel history (what the repetition guard compares against)."""
    from repetition_guard import fingerprint

    fp = fingerprint(project)
    pin = (pinned_profile(project) or {}).get("pin") or {}
    entry = {"recorded_at": now(), "project": str(project), "profile_version": pin.get("profile_version"), **fp}
    with (channel_dir(channel_id, root) / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="channels folder (default $NARRATIVEOS_CHANNELS or ~/NarrativeOS-Channels)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("channel_id")
    p.add_argument("--name", default="")
    p.add_argument("--niche", default="")
    p.add_argument("--from", dest="from_file", type=Path)
    p = sub.add_parser("show")
    p.add_argument("channel_id")
    p.add_argument("--version", type=int)
    p = sub.add_parser("update")
    p.add_argument("channel_id")
    p.add_argument("--set", action="append", default=[], help="section.key=<json value>")
    p.add_argument("--reason", required=True)
    p = sub.add_parser("history")
    p.add_argument("channel_id")
    p = sub.add_parser("apply")
    p.add_argument("channel_id")
    p.add_argument("--project", type=Path, required=True)
    p.add_argument("--version", type=int)
    p = sub.add_parser("record-video")
    p.add_argument("channel_id")
    p.add_argument("--project", type=Path, required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "create":
            extra = json.loads(args.from_file.read_text(encoding="utf-8")) if args.from_file else None
            out = create(args.channel_id, args.name, args.niche, extra, args.root)
        elif args.cmd == "show":
            out = load(args.channel_id, args.version, args.root)
        elif args.cmd == "update":
            changes = {}
            for item in args.set:
                key, _, value = item.partition("=")
                changes[key.strip()] = _parse_value(value)
            out = update(args.channel_id, changes, args.reason, args.root)
        elif args.cmd == "history":
            out = [{k: load(args.channel_id, v, args.root).get(k) for k in ("profile_version", "created_at", "change_reason", "profile_sha256")}
                   for v in versions(args.channel_id, args.root)]
        elif args.cmd == "apply":
            out = apply(args.channel_id, args.project, args.version, args.root)["pin"]
        else:
            out = record_video(args.channel_id, args.project, args.root)
    except (ValueError, KeyError, FileNotFoundError, FileExistsError) as e:
        print(json.dumps({"status": "blocked", "error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
