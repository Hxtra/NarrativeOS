#!/usr/bin/env python3
"""Validate visual coverage plans without treating keyword overlap as evidence."""
from __future__ import annotations
import argparse, json
from pathlib import Path
MODES={"LITERAL","CONTEXTUAL","ATMOSPHERIC","EVIDENCE","EVENT","REACTION"}

def validate(plan: dict)->list[dict]:
    errors=[]
    if not plan.get("coverage_id"): errors.append({"error":"missing coverage_id"})
    if not plan.get("beat_id"): errors.append({"error":"missing beat_id"})
    if not plan.get("viewer_objective"): errors.append({"error":"missing viewer_objective"})
    if plan.get("mode") not in MODES: errors.append({"error":"invalid coverage mode"})
    if not isinstance(plan.get("literal_word_matching"),bool): errors.append({"error":"literal_word_matching must be boolean"})
    if plan.get("mode")=="EVIDENCE" and not plan.get("evidence_requirements"):
        errors.append({"error":"EVIDENCE coverage requires evidence_requirements"})
    if plan.get("mode") in {"CONTEXTUAL","ATMOSPHERIC"} and plan.get("literal_word_matching") is True:
        errors.append({"error":"contextual/atmospheric coverage cannot require literal word matching"})
    return errors

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--input",type=Path,required=True); ap.add_argument("--output",type=Path); args=ap.parse_args()
    plan=json.loads(args.input.read_text()); errors=validate(plan); result={**plan,"validation":{"status":"passed" if not errors else "blocked","errors":errors}}
    (args.output or args.input).write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result["validation"],indent=2)); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main())
