#!/usr/bin/env python3
"""Detect exact-key conflicts in supplied source claim records; no silent source selection."""
from __future__ import annotations
import argparse,json
from collections import defaultdict
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--claims',default='research/claims/claims.json'); args=ap.parse_args(); p=args.project; q=p/args.claims
    rows=json.loads(q.read_text()).get('claims',[]) if q.exists() else []
    groups=defaultdict(list)
    for r in rows: groups[r.get('fact_key',r.get('claim_id'))].append(r)
    conflicts=[]
    for key,vals in groups.items():
        normalized={str(v.get('value','')).strip().lower() for v in vals}
        if len(normalized)>1: conflicts.append({'fact_key':key,'values':vals,'status':'conflict_detected','action':'human_review_or_further_research'})
    out={'schema_version':1,'status':'passed' if not conflicts else 'review_required','conflicts':conflicts,'source_count':len(rows)}
    (p/'research/contradictions/contradictions.json').parent.mkdir(parents=True,exist_ok=True); (p/'research/contradictions/contradictions.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2)); raise SystemExit(0 if not conflicts else 1)
if __name__=='__main__': main()
