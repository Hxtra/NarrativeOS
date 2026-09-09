#!/usr/bin/env python3
"""Create editable continuity records; unresolved facts remain review-required."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    text='\n'.join((p/x).read_text(encoding='utf-8') for x in ('brief.md','script.json') if (p/x).exists())
    names=[]
    for n in re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b',text):
        if n not in {'Create Short','Support The','No External'} and n not in names: names.append(n)
    entities=[{'entity_id':f'E{i+1:03d}','name':n,'attributes':{},'timeline':[],'status':'review_required'} for i,n in enumerate(names)]
    data={'schema_version':1,'status':'review_required','entities':entities,'rules':['Do not show anachronistic objects, places, clothing, logos, dates, or technology without evidence.']}
    (p/'entity_bible.json').write_text(json.dumps(data,indent=2)+'\n')
    (p/'temporal_constraints.json').write_text(json.dumps({'schema_version':1,'status':'review_required','constraints':[],'checks':['date','camera era','clothing','vehicles','architecture','technology','logos','signs']},indent=2)+'\n')
    (p/'geographic_plan.json').write_text(json.dumps({'schema_version':1,'status':'review_required','locations':[],'routes':[],'map_policy':'verify claimed locations before visualizing'},indent=2)+'\n')
    print(json.dumps({'status':'passed','entities':len(entities)},indent=2))
if __name__=='__main__': main()
