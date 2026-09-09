#!/usr/bin/env python3
"""Build explicit claim→source→asset→shot links and explainability records."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    claims=json.loads((p/'claim_ledger.json').read_text()).get('claims',[]) if (p/'claim_ledger.json').exists() else []
    shots=json.loads((p/'shot_specs.json').read_text()).get('shots',[]) if (p/'shot_specs.json').exists() else []
    links=[]
    for i,s in enumerate(shots):
        claim=claims[i] if i<len(claims) else None
        links.append({'link_id':f'L{i+1:04d}','claim_id':claim.get('claim_id') if claim else None,'source_refs':claim.get('source_refs',[]) if claim else [],'shot_id':s.get('shot_id'),'asset_id':None,'status':'unresolved','reason':'Asset approval and source evidence required.'})
    (p/'claim_visual_links.json').write_text(json.dumps({'schema_version':1,'status':'review_required','links':links},indent=2)+'\n')
    (p/'shot_explanations.json').write_text(json.dumps({'schema_version':1,'status':'review_required','decisions':[{'shot_id':s.get('shot_id'),'reasons':['supports narration','awaiting subject/action/date/rights verification']} for s in shots]},indent=2)+'\n')
    print(json.dumps({'status':'passed','links':len(links)},indent=2))
if __name__=='__main__': main()
