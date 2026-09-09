#!/usr/bin/env python3
"""Build explicit narration alignment and beat timing from script records."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project; script=json.loads((p/'script.json').read_text())
    beats=script.get('beats',[]); cursor=0.0; aligned=[]; mapped=[]
    for i,b in enumerate(beats):
        text=b.get('narration',''); dur=max(3.0,min(15.0,len(text.split())/2.4)); start=cursor; end=start+dur; bid=b.get('beat_id',f'B{i+1:03d}'); aligned.append({'beat_id':bid,'text':text,'start':start,'end':end,'timing_source':'estimated-from-script; replace with real alignment before release'}); mapped.append({'beat_id':bid,'narration':text,'start':start,'end':end,'duration_seconds':dur,'visual_purpose':b.get('visual_purpose','Support narration without contradiction.'),'required_subjects':b.get('required_subjects',[]),'required_actions':b.get('required_actions',[])}) ; cursor=end
    (p/'narration_alignment.json').write_text(json.dumps({'schema_version':1,'status':'review_required','segments':aligned},indent=2)+'\n')
    (p/'beat_map.json').write_text(json.dumps({'schema_version':1,'status':'review_required','beats':mapped},indent=2)+'\n'); print(json.dumps({'status':'passed','beats':len(mapped),'note':'timing is estimated; replace with audio alignment'},indent=2))
if __name__=='__main__': main()
