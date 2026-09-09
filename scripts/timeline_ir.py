#!/usr/bin/env python3
"""Validate/export the canonical timeline intermediate representation."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--input',default='timeline.json'); args=ap.parse_args(); p=args.project; data=json.loads((p/args.input).read_text())
    shots=data.get('shots',[]); errors=[]; prev=0.0
    for s in shots:
        if not s.get('shot_id') or not s.get('asset_id') or s.get('status') not in {'approved','simulation_approved'}: errors.append({'shot_id':s.get('shot_id'),'error':'missing approved lineage'})
        if float(s.get('end',0))<=float(s.get('start',0)): errors.append({'shot_id':s.get('shot_id'),'error':'invalid timing'})
        if float(s.get('start',0))<prev: errors.append({'shot_id':s.get('shot_id'),'error':'non-monotonic timing'})
        prev=float(s.get('end',0))
    data['ir_version']='1.0'; data['tracks']=data.get('tracks',{'video':'v_main','narration':'a_narration','music':'a_music','sfx':'a_sfx','captions':'caption_main'}); data['validation']={'status':'passed' if not errors else 'blocked','errors':errors}
    (p/'timeline_ir.json').write_text(json.dumps(data,indent=2)+'\n'); print(json.dumps(data['validation'],indent=2)); raise SystemExit(0 if not errors else 1)
if __name__=='__main__': main()
