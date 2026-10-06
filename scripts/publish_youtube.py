#!/usr/bin/env python3
"""YouTube publish adapter: plans the upload exactly, refuses until every gate is met, and does not upload.

    python publish_youtube.py --project P            # writes publish_plan.json (a dry run, always)

The plan is the real videos.insert request body (snippet + status) and the thumbnails.set call, built
from the approved publish package. Gates, all required:
- delivery review passed (state.json delivery_ready) and the owner set publish_authorized;
- the publish package is approved and unchanged since approval (publish_package.py);
- the repetition guard passed or its report was reviewed (repetition_report.json);
- the final render exists.

Platform facts the plan accounts for (YouTube Data API v3, checked 2026-10-05):
- default quota: 100 videos.insert calls per day; thumbnails.set costs 50 of the 10,000 daily units;
- uploads from an API project that has not passed YouTube's compliance audit are forced to private,
  whatever privacyStatus is sent;
- status.containsSyntheticMedia declares altered/synthetic content (set from provenance by publish_package.py).

Actually uploading needs the owner's OAuth client and consent for their channel. That is not configured, so
the upload step is BLOCKED and says so; nothing is sent anywhere. publish_manifest.json (which the
controller's PUBLISH stage requires) is only ever written by a real, confirmed upload.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from publish_package import approved  # noqa: E402

QUOTA = {"videos.insert_per_day": 100, "units_per_day": 10000, "thumbnails.set_units": 50}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (json.JSONDecodeError, OSError):
        return default


def gates(project: Path) -> list[dict]:
    state = _load(project / "state.json", {})
    rep = _load(project / "repetition_report.json", None)
    ok_pkg, why_pkg = approved(project)
    render = project / "renders" / "final.mp4"
    return [
        {"gate": "delivery_review", "passed": state.get("delivery_ready") is True, "detail": "state.json delivery_ready"},
        {"gate": "publish_authorized", "passed": state.get("publish_authorized") is True, "detail": "the owner sets this; never automatic"},
        {"gate": "publish_package", "passed": ok_pkg, "detail": why_pkg},
        {"gate": "repetition_guard", "passed": bool(rep) and (rep.get("status") == "passed" or (rep.get("review") or {}).get("approved") is True),
         "detail": "repetition_report.json missing" if not rep else rep.get("status")},
        {"gate": "final_render", "passed": render.is_file(), "detail": str(render)},
    ]


def request_body(pkg: dict) -> dict:
    snippet = {"title": pkg["title"], "description": pkg.get("description", ""), "tags": pkg.get("tags", [])}
    if pkg.get("category_id"):
        snippet["categoryId"] = str(pkg["category_id"])
    if pkg.get("language"):
        snippet["defaultLanguage"] = pkg["language"]
    status = {"privacyStatus": pkg.get("privacy", "private"), "selfDeclaredMadeForKids": pkg["made_for_kids"],
              "containsSyntheticMedia": pkg["disclosure"]["containsSyntheticMedia"]}
    if pkg.get("publish_at"):
        status["publishAt"] = pkg["publish_at"]
    return {"part": "snippet,status", "body": {"snippet": snippet, "status": status}}


def plan(project: Path) -> dict:
    g = gates(project)
    pkg = _load(project / "publish_package.json", None)
    credentials = os.environ.get("NARRATIVEOS_YOUTUBE_CLIENT_SECRETS")
    out = {
        "schema_version": 1, "planned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": "dry_run",
        "gates": g, "all_gates_passed": all(x["passed"] for x in g),
        "videos_insert": request_body(pkg) if pkg and pkg.get("title") and pkg.get("made_for_kids") in (True, False) else None,
        "thumbnails_set": {"file": pkg.get("thumbnail")} if pkg and pkg.get("thumbnail") else None,
        "quota": {**QUOTA, "this_upload": {"videos.insert_calls": 1, "units": QUOTA["thumbnails.set_units"] if pkg and pkg.get("thumbnail") else 0}},
        "platform_notes": [
            "Uploads from an API project that has not passed YouTube's compliance audit are forced to private, whatever privacyStatus says.",
            "containsSyntheticMedia comes from the asset provenance (publish_package.py), not from a manual answer.",
        ],
        "upload": {"status": "BLOCKED", "reason": ("no OAuth client configured (NARRATIVEOS_YOUTUBE_CLIENT_SECRETS) and no channel consent; "
                                                    "uploading is not implemented until the owner sets that up") if not credentials else
                   "an OAuth client is configured, but the uploader is not implemented yet: nothing was sent"},
    }
    (project / "publish_plan.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, required=True)
    a = ap.parse_args()
    out = plan(a.project)
    print(json.dumps({"all_gates_passed": out["all_gates_passed"], "gates": out["gates"], "upload": out["upload"]}, indent=2))
    return 0 if out["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
