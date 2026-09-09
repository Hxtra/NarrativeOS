#!/usr/bin/env python3
"""Analyze timeline restraint and diversity without inventing quality scores."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    tl=json.loads((p/'timeline.json').read_text()).get('shots',[]) if (p/'timeline.json').exists() else []
    types=[]; motions=[]; effects=[]
    for s in tl:
        types.append(s.get('visual_type','unknown')); motions.append(s.get('motion','static')); effects.append(s.get('transition','cut'))
    repeats=[]
    for i in range(1,len(types)):
        if types[i]==types[i-1] and types[i]!='unknown': repeats.append({'index':i,'issue':'repeated_visual_type'})
    report={'schema_version':1,'status':'review_required','shot_count':len(tl),'visual_type_counts':{x:types.count(x) for x in set(types)},'motion_counts':{x:motions.count(x) for x in set(motions)},'transition_counts':{x:effects.count(x) for x in set(effects)},'repetition_flags':repeats,'restraint_rules':['Prefer minimum visual information.','Permit black screen, still image, text, or silence when editorially justified.','Do not stack zoom, whoosh, shake, glitch, flash, transition, and bass hit by default.'],'silence_candidates':[{'shot_id':s.get('shot_id'),'recommended':False,'reason':'Requires director review'} for s in tl]}
    (p/'editorial_analysis.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps({'status':'passed','shots':len(tl),'repetition_flags':len(repeats)},indent=2))
if __name__=='__main__': main()
