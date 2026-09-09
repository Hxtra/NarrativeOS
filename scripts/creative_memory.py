#!/usr/bin/env python3
"""Store explicit A/B edit metadata and user preference changes without autonomous preference claims."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--preference',action='append',default=[]); ap.add_argument('--version-a',default=''); ap.add_argument('--version-b',default=''); args=ap.parse_args(); p=args.project
    taste=p/'taste_profile.json'; profile=json.loads(taste.read_text()) if taste.exists() else {'schema_version':1,'preferences':{}}
    for item in args.preference:
        if '=' in item: k,v=item.split('=',1); profile['preferences'][k]=v
    profile['status']='review_required' if not profile['preferences'] else 'passed'; taste.write_text(json.dumps(profile,indent=2)+'\n')
    ab={'schema_version':1,'status':'review_required','variants':[{'id':'A','timeline':args.version_a,'style':'fast/high-SFX'},{'id':'B','timeline':args.version_b,'style':'slow/atmospheric'}],'comparison_metrics':['pacing','visual diversity','caption load','audio design','narrative clarity','human preference']}
    (p/'ab_edit_manifest.json').write_text(json.dumps(ab,indent=2)+'\n'); print(json.dumps({'status':'passed','taste_profile':str(taste),'ab_manifest':'ab_edit_manifest.json'},indent=2))
if __name__=='__main__': main()
