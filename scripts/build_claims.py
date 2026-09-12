#!/usr/bin/env python3
"""Create review-required claim records from ingested source excerpts."""
from __future__ import annotations
import argparse,json,re,hashlib
from pathlib import Path

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project; data=json.loads((p/'research/sources.json').read_text()); claims=[]
 for src in data.get('sources',[]):
  lines=[x.strip() for x in src.get('excerpt','').splitlines() if len(x.strip())>30]
  for j,line in enumerate(lines[:10]): claims.append({'claim_id':f'C{len(claims)+1:04d}','fact_key':f'{src["source_id"]}_{j+1}','text':line,'value':line,'source_refs':[src['source_id']],'evidence_span':{'source_id':src['source_id'],'text':line},'verification':'review_required'})
 out={'schema_version':1,'status':'review_required','claims':claims,'source_count':len(data.get('sources',[]))}; (p/'claim_ledger.json').write_text(json.dumps(out,indent=2)+'\n'); (p/'research/claims/claims.json').parent.mkdir(parents=True,exist_ok=True); (p/'research/claims/claims.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'status':'passed','claims':len(claims)},indent=2))
if __name__=='__main__': main()

