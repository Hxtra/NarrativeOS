#!/usr/bin/env python3
"""Build the smallest real NarrativeOS editorial vertical slice from a JSON brief."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from narration_plan import validate as validate_narration
from visual_coverage import validate as validate_coverage
from event_graph import validate as validate_graph, compile_graph

def build(project:Path)->dict:
    brief=json.loads((project/"editorial_slice_input.json").read_text())
    narration=brief["narration_plan"]; coverage=brief["visual_coverage"]; graph=brief["event_graph"]
    errors=[]
    for name, result in (("narration_plan",validate_narration(narration)),("visual_coverage",validate_coverage(coverage)),("event_graph",validate_graph(graph))):
        if result: errors.append({"artifact":name,"errors":result})
    if errors:
        report={"status":"blocked","errors":errors}; (project/"editorial_slice_report.json").write_text(json.dumps(report,indent=2)+"\n"); return report
    (project/"narration_plan.json").write_text(json.dumps({**narration,"validation":{"status":"passed","errors":[]}},indent=2)+"\n")
    (project/"visual_coverage.json").write_text(json.dumps({**coverage,"validation":{"status":"passed","errors":[]}},indent=2)+"\n")
    (project/"editorial_event_graph.json").write_text(json.dumps(graph,indent=2)+"\n")
    ir=compile_graph(graph); (project/"timeline_ir.json").write_text(json.dumps(ir,indent=2)+"\n")
    report={"status":"passed","artifacts":["narration_plan.json","visual_coverage.json","editorial_event_graph.json","timeline_ir.json"],"renderer":"FFmpeg_PRIMARY_PENDING_RENDER"}
    (project/"editorial_slice_report.json").write_text(json.dumps(report,indent=2)+"\n"); return report

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--project",type=Path,required=True); args=ap.parse_args(); report=build(args.project); print(json.dumps(report,indent=2)); return 0 if report["status"]=="passed" else 1
if __name__=="__main__": raise SystemExit(main())
