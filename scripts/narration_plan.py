#!/usr/bin/env python3
"""Validate a segment-level NarrativeOS narration plan."""
from __future__ import annotations
import argparse, json
from pathlib import Path

TYPES = {"NARRATION", "NATURAL_AUDIO", "INTERVIEW", "QUOTE", "MUSIC_ONLY", "SILENCE", "MIXED"}

def validate(plan: dict) -> list[dict]:
    errors=[]; seen=set(); previous_end=0.0
    if not isinstance(plan.get("segments"), list) or not plan["segments"]:
        return [{"error":"segments must be a non-empty list"}]
    for segment in plan["segments"]:
        sid=segment.get("segment_id")
        if not sid or sid in seen: errors.append({"segment_id":sid,"error":"missing or duplicate segment_id"})
        seen.add(sid)
        kind=segment.get("type")
        if kind not in TYPES: errors.append({"segment_id":sid,"error":"invalid segment type"})
        timing=segment.get("timing", {})
        start=float(timing.get("target_start", -1)); end=float(timing.get("target_end", -1))
        if start < 0 or end <= start: errors.append({"segment_id":sid,"error":"invalid timing"})
        if start < previous_end: errors.append({"segment_id":sid,"error":"overlapping narration segments"})
        previous_end=end
        if kind == "NARRATION" and not str(segment.get("text","")).strip():
            errors.append({"segment_id":sid,"error":"NARRATION requires text"})
        if kind in {"NATURAL_AUDIO","INTERVIEW","QUOTE"} and not segment.get("source_ref"):
            errors.append({"segment_id":sid,"error":f"{kind} requires source_ref"})
        if kind == "SILENCE" and not segment.get("reason"):
            errors.append({"segment_id":sid,"error":"SILENCE requires reason"})
    return errors

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--input",type=Path,required=True); ap.add_argument("--output",type=Path)
    args=ap.parse_args(); plan=json.loads(args.input.read_text()); errors=validate(plan)
    result={**plan,"validation":{"status":"passed" if not errors else "blocked","errors":errors}}
    out=args.output or args.input; out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result["validation"],indent=2)); return 0 if not errors else 1
if __name__ == "__main__": raise SystemExit(main())
