#!/usr/bin/env python3
"""Drive generation jobs through their state machine, one explicit step at a time.

Jobs live in <project>/generation/jobs/<request_id>.json. Each command is one transition:

  plan           --need need.json --profile profile.json [--dna style_dna.json] [--bible bible.json]
  quote          --id X (--quote quote.json | --providers providers.json --version v1)
  show           --id X                         prints state, gates and the quote hash to approve
  approve-cost   --id X --by NAME --quote-hash H
  waive-cost     --id X --reason TEXT           zero-cost quotes only
  approve-rights --id X --by NAME --quote-hash H
  rights-na      --id X --reason TEXT           only if the quote says rights_review_required: false
  ready          --id X
  run            --id X --providers providers.json
  review         --id X --by NAME (--approve | --reject) [--note TEXT]
  register       --id X [--bible bible.json --entity ID ...]   updates the continuity bible in place

Nothing runs a generator except `run`, and `run` only works on a READY job.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generation as gen  # noqa: E402
from editorial_style import fingerprint, resolve_style  # noqa: E402


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, allow_nan=False) + "\n")
    os.replace(tmp, path)


def job_path(project: Path, request_id: str) -> Path:
    return project / "generation" / "jobs" / f"{request_id}.json"


def summary(job: dict) -> dict:
    return {"request_id": job["request_id"], "kind": job["kind"], "state": job["state"], "status": job["status"],
            "media_class": job.get("media_class"), "route": job.get("route"), "gates": job.get("gates"),
            "provider": job.get("provider"), "model": job.get("model"),
            "quote": job.get("quote"), "quote_hash": fingerprint(job["quote"]) if job.get("quote") else None,
            "reason": job.get("reason"), "output": job.get("output"), "asset_id": (job.get("asset") or {}).get("asset_id")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["plan", "quote", "show", "approve-cost", "waive-cost", "approve-rights", "rights-na", "ready", "run", "review", "register"])
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--id")
    for flag in ("need", "profile", "dna", "bible", "quote", "providers"):
        ap.add_argument(f"--{flag}", type=Path)
    ap.add_argument("--version")
    ap.add_argument("--by")
    ap.add_argument("--quote-hash")
    ap.add_argument("--reason")
    ap.add_argument("--note", default="")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--entity", action="append", default=[])
    a = ap.parse_args()
    try:
        if a.command == "plan":
            need = read(a.need)
            path = job_path(a.project, need["request_id"])
            if path.exists():
                raise ValueError(f"job {need['request_id']} already exists; plan a new request_id")
            style = resolve_style(read(a.profile), read(a.dna) if a.dna else None)
            job = gen.plan_request(need, style, read(a.bible) if a.bible else {})
            write_atomic(path, job)
            print(json.dumps(summary(job), indent=2))
            return 0
        path = job_path(a.project, a.id or "")
        if not a.id or not path.is_file():
            raise ValueError(f"no job {a.id!r} in {a.project}")
        job = read(path)
        if a.command == "show":
            print(json.dumps(summary(job), indent=2))
            return 0
        if a.command == "quote":
            if a.quote:
                quote = read(a.quote)
            else:
                providers = read(a.providers)
                if job["kind"] not in providers:
                    raise ValueError(f"No {job['kind']} generator configured (BLOCKED)")
                quote = gen.build_quote(job, providers[job["kind"]], a.version or "v1")
            gen.attach_quote(job, quote)
        elif a.command == "approve-cost":
            gen.approve_cost(job, a.by, a.quote_hash)
        elif a.command == "waive-cost":
            gen.waive_cost(job, a.reason)
        elif a.command == "approve-rights":
            gen.approve_rights(job, a.by, a.quote_hash)
        elif a.command == "rights-na":
            gen.rights_not_applicable(job, a.reason)
        elif a.command == "ready":
            gen.mark_ready(job)
        elif a.command == "run":
            try:
                gen.run(job, gen.load_adapter(read(a.providers), job["kind"]))
            finally:
                write_atomic(path, job)  # a FAILED state is recorded too
        elif a.command == "review":
            if a.approve == a.reject:
                raise ValueError("review needs exactly one of --approve or --reject")
            gen.review(job, a.by, approved=a.approve, note=a.note)
        elif a.command == "register":
            gen.register(job)
            if a.bible:
                write_atomic(a.bible, gen.register_generated_reference(read(a.bible), job, a.entity))
        write_atomic(path, job)
        print(json.dumps(summary(job), indent=2))
        return 0
    except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
