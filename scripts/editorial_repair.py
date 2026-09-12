#!/usr/bin/env python3
"""Convert editorial analysis findings into scoped revision actions."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project; a=json.loads((p/'editorial_analysis.json').read_text()) if (p/'editorial_analysis.json').exists() else {}
 actions=[]
 for flag in a.get('repetition_flags',[]): actions.append({'action_id':f'R{len(actions)+1:03d}','type':'replace_or_diversify','shot_index':flag.get('index'),'reason':flag.get('issue'),'affected_stages':['ASSET_APPROVAL','TIMELINE','TIMELINE_IR','PREVIEW_RENDER']})
 actions += [{'action_id':f'R{len(actions)+1:03d}','type':'review_silence_candidate','shot_id':x.get('shot_id'),'reason':x.get('reason'),'affected_stages':['AUDIO_MIX','TIMELINE']} for x in a.get('silence_candidates',[]) if x.get('recommended')]
 out={'schema_version':1,'status':'passed' if actions else 'passed','revision_required':bool(actions),'actions':actions,'downstream_invalidation':['PREVIEW_RENDER','TECHNICAL_QA','EDITORIAL_QA','FINAL_RENDER'] if actions else []}; (p/'revision_plan.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2))
if __name__=='__main__': main()

