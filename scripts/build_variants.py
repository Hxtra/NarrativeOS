#!/usr/bin/env python3
"""Create deterministic A/B timeline policy variants without claiming preference wins."""
from __future__ import annotations
import argparse,json,copy
from pathlib import Path

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project; base=json.loads((p/'timeline.json').read_text()); a=copy.deepcopy(base); b=copy.deepcopy(base)
 for s in a.get('shots',[]): s['variant_policy']='fast'; s['caption_policy']='emphasis'; s['sfx_policy']='high'
 for s in b.get('shots',[]): s['variant_policy']='slow'; s['caption_policy']='minimal'; s['sfx_policy']='low'; s['motion']='static'
 a['variant_id']='A_fast_high_sfx'; b['variant_id']='B_slow_atmospheric'; (p/'timeline_variant_A.json').write_text(json.dumps(a,indent=2)+'\n'); (p/'timeline_variant_B.json').write_text(json.dumps(b,indent=2)+'\n'); (p/'variant_comparison.json').write_text(json.dumps({'schema_version':1,'status':'review_required','variants':['A_fast_high_sfx','B_slow_atmospheric'],'metrics':['pacing','visual diversity','caption load','audio design','narrative clarity'],'human_preference_required':True},indent=2)+'\n'); print(json.dumps({'status':'passed','variants':2},indent=2))
if __name__=='__main__': main()

