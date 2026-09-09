#!/usr/bin/env python3
"""Create a transparent planning package from a brief; no fabricated web research."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    brief=(p/'brief.md').read_text(encoding='utf-8') if (p/'brief.md').exists() else ''
    if not brief.strip(): raise SystemExit('brief.md is empty')
    paragraphs=[x.strip() for x in re.split(r'\n\s*\n',brief) if x.strip()]
    items=[]
    for i,para in enumerate(paragraphs or [brief]):
        text=re.sub(r'^#+\s*','',para).strip(); items.append({'beat_id':f'B{i+1:03d}','narration':text,'visual_purpose':'Find or create visuals that directly support this narration.','required_subjects':[],'required_actions':[],'source_refs':[]})
    research={'schema_version':1,'status':'review_required','method':'brief-only','sources':[],'notes':['No external research was performed; add citations before factual release.']}
    claims={'schema_version':1,'status':'review_required','claims':[{'claim_id':f'C{i+1:03d}','text':x['narration'],'source_refs':[],'verification':'unverified'} for i,x in enumerate(items)]}
    outline={'schema_version':1,'status':'passed','acts':[{'act_id':'A1','title':'Brief-derived outline','beat_ids':[x['beat_id'] for x in items]}]}
    script={'schema_version':1,'status':'review_required','language':'en','beats':items,'source_policy':'Every factual claim requires a source before release.'}
    for name,data in [('research.json',research),('claim_ledger.json',claims),('outline.json',outline),('script.json',script)]: (p/name).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','beats':len(items),'note':'planning artifacts require factual review'},indent=2))
if __name__=='__main__': main()
