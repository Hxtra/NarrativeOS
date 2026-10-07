#!/usr/bin/env python3
"""Render an approved shot timeline. Kept for its CLI; the work is done by compile_timeline.py.

The old implementation encoded every shot to its own file, concatenated them and laid one audio file on top,
which could not represent overlaps, transitions, layered audio or J/L cuts. This now converts the shot
timeline (plus --audio as the narration track) to the multi-track IR and renders it in one FFmpeg pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import compile_timeline as ct  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--timeline", default="timeline.json")
    ap.add_argument("--output", default="renders/preview.mp4")
    ap.add_argument("--audio", default="", help="narration audio (project-relative or absolute)")
    ap.add_argument("--captions", default="", help="captions.json to burn in")
    a = ap.parse_args()
    p = a.project.resolve()
    tl = json.loads((p / a.timeline).read_text(encoding="utf-8"))
    if not tl.get("shots"):
        raise SystemExit("timeline has no shots")
    bad = [s.get("shot_id") for s in tl["shots"] if s.get("status") != "approved"]
    if bad:
        raise SystemExit(f"shots not approved: {bad}")
    caps = json.loads((p / a.captions).read_text(encoding="utf-8")) if a.captions else None
    try:
        ir = ct.from_shot_timeline(tl, p, narration=a.audio or None, captions=caps)
        (p / "timeline_v3.json").write_text(json.dumps(ir, indent=2) + "\n", encoding="utf-8")
        m = ct.compile_timeline(p, ir, Path(a.output), release=True)
    except ct.CompileError as e:
        raise SystemExit(str(e))
    print(json.dumps({k: m[k] for k in ("status", "output_path", "duration", "has_audio", "unrendered")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
