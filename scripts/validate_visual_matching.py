#!/usr/bin/env python3
"""Validate evidence records; this does not invent or calculate semantic scores."""
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("record",type=Path); args=ap.parse_args()
    data=json.loads(args.record.read_text(encoding="utf-8")); candidates=data.get("candidates",[]); failures=[]
    for c in candidates:
        required=["candidate_id","source_path","decision","evidence_frame_paths","vision_descriptions","comparison"]
        missing=[k for k in required if not c.get(k)]
        frames=[Path(x) for x in c.get("evidence_frame_paths",[])]
        if len(frames)<3 or any(not x.is_file() for x in frames): missing.append("three_existing_evidence_frames")
        if c.get("description_source") not in {"vision-analysis","verified-human-review"}: missing.append("real_description_source")
        if missing: failures.append({"candidate_id":c.get("candidate_id"),"missing":missing})
    status="passed" if candidates and not failures and data.get("no_synthetic_scores") is True else "blocked"
    report={"status":status,"candidate_count":len(candidates),"failures":failures,"no_synthetic_scores":data.get("no_synthetic_scores") is True}
    print(json.dumps(report,indent=2)); raise SystemExit(0 if status=="passed" else 1)
if __name__=="__main__": main()
