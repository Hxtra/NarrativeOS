#!/usr/bin/env python3
"""Evaluate completed visual evidence records; incomplete evidence stays blocked."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--manifest',default='benchmark_manifest.json'); args=ap.parse_args(); p=args.project; q=p/args.manifest
 if not q.exists(): raise SystemExit('benchmark manifest missing')
 data=json.loads(q.read_text()); cases=data.get('cases',[]); metrics={'cases':len(cases),'complete_cases':0,'blocked_cases':0,'top1_accuracy':None,'top3_recall':None,'false_acceptance':None,'wrong_action_acceptance':None,'no_match_block_rate':None}
 for c in cases:
  ok=bool(c.get('decision')) and bool(c.get('evidence_frame_paths')) and c.get('description_source') in {'vision-analysis','verified-human-review'}
  metrics['complete_cases']+=ok; metrics['blocked_cases']+=not ok
 out={'schema_version':1,'status':'passed' if cases and metrics['complete_cases']==len(cases) else 'blocked','no_synthetic_scores':True,'metrics':metrics,'note':'Semantic accuracy metrics remain null until real labeled benchmark cases are executed.'}; (p/'visual_benchmark_report.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2)); raise SystemExit(0 if out['status']=='passed' else 1)
if __name__=='__main__': main()

