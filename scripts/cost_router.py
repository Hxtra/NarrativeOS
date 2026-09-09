#!/usr/bin/env python3
"""Record cost/quality routing decisions before expensive provider operations."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--task',required=True); ap.add_argument('--estimated-cost',type=float,default=0.0); ap.add_argument('--force-provider',default='local-or-cache'); args=ap.parse_args(); p=args.project
    decision={'schema_version':1,'status':'review_required' if args.estimated_cost>0 else 'passed','task':args.task,'checks':['local model','cached result','cheaper model','does task require AI','human approval if expensive'],'selected_provider':args.force_provider,'estimated_cost':args.estimated_cost,'billable_approved':False}
    (p/'cost_decisions.json').write_text(json.dumps(decision,indent=2)+'\n'); print(json.dumps(decision,indent=2)); raise SystemExit(0)
if __name__=='__main__': main()
