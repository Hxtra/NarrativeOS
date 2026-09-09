#!/usr/bin/env python3
"""Assemble a canonical timeline from approved assets and ShotSpecs."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    specs=json.loads((p/'shot_specs.json').read_text()).get('shots',[]); approved=json.loads((p/'approved_assets.json').read_text()).get('assets',[])
    byshot={x.get('shot_id'):x for x in approved}; shots=[]
    for s in specs:
        a=byshot.get(s.get('shot_id'))
        if not a or a.get('status') not in {'approved','simulation_approved'}: raise SystemExit(f"no approved asset for {s.get('shot_id')}")
        shot_status='simulation_approved' if a.get('status')=='simulation_approved' else 'approved'
        shots.append({'shot_id':s['shot_id'],'asset_id':a['asset_id'],'start':s.get('start',0),'end':s.get('end',s.get('duration_seconds',5)),'source_start':a.get('usable_interval',[0,0])[0],'motion':s.get('motion','static'),'transition':s.get('transition','cut'),'status':shot_status})
    out={'schema_version':2,'status':'passed','output':{'width':1280,'height':720,'fps':24,'fit_policy':'cover_crop'},'tracks':{'video':'v_main','narration':'a_narration','music':'a_music'},'shots':shots}
    (p/'timeline.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'status':'passed','shots':len(shots)},indent=2))
if __name__=='__main__': main()
