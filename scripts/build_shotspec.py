#!/usr/bin/env python3
"""Build ShotSpecs from beat_map.json or script.json, never from timeline.json."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--out',default='shot_specs.json'); args=ap.parse_args(); p=args.project
    source_path=p/'beat_map.json'
    if source_path.exists(): data=json.loads(source_path.read_text(encoding='utf-8')); source=data.get('beats',[])
    else:
        source_path=p/'script.json'
        if not source_path.exists(): raise SystemExit('Need beat_map.json or script.json')
        data=json.loads(source_path.read_text(encoding='utf-8')); source=data.get('beats',[])
    specs=[]; cursor=0.0
    for i,item in enumerate(source):
        sid=item.get('shot_id') or item.get('beat_id') or f'B{i+1:03d}-S01'; dur=float(item.get('duration_seconds',item.get('duration',max(3.0,min(12.0,len(item.get('narration',item.get('text','')))/12)))))
        start=float(item.get('start',cursor)); end=float(item.get('end',start+dur)); cursor=end
        specs.append({'shot_id':sid,'beat_id':item.get('beat_id',sid),'narration':item.get('narration',item.get('text','')),'visual_purpose':item.get('visual_purpose','Support narration without contradiction.'),'visual_mode':item.get('visual_mode','literal'),'required_subjects':item.get('required_subjects',[]),'required_actions':item.get('required_actions',[]),'required_location':item.get('required_location',''),'required_time_period':item.get('required_time_period',''),'forbidden_meanings':item.get('forbidden_meanings',[]),'duration_seconds':round(end-start,3),'start':start,'end':end,'preferred_shot_type':item.get('preferred_shot_type',''),'fallbacks':item.get('fallbacks',['verified map','document treatment','labelled reconstruction']),'status':'needs_asset_review'})
    out=p/args.out; out.write_text(json.dumps({'schema_version':2,'status':'planning_only','source':source_path.name,'shots':specs},indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':'passed','planning_only':True,'shot_count':len(specs),'output':str(out)},indent=2))
if __name__=='__main__': main()
