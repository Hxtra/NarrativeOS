#!/usr/bin/env python3
"""Derive transparent editorial strategy artifacts from a brief and channel profile."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    brief=(p/'brief.md').read_text(encoding='utf-8') if (p/'brief.md').exists() else ''
    low=brief.lower()
    genre='documentary' if any(x in low for x in ('documentary','history','investigation','disappearance')) else 'explainer'
    tone='dark/investigative' if any(x in low for x in ('dark','disappearance','murder','mystery','investigative')) else 'clear/engaging'
    strategy={'schema_version':1,'status':'passed','source':'brief-heuristics','intent':{'genre':genre,'tone':tone,'pacing':'slow-to-escalating' if 'dark' in tone else 'moderate','visual_priority':'real archival footage' if genre=='documentary' else 'literal explanatory visuals','music':'minimal tense' if 'dark' in tone else 'atmospheric','graphics':'investigative' if genre=='documentary' else 'supportive','narration':'serious' if genre=='documentary' else 'conversational','evidence_requirement':'high' if genre=='documentary' else 'medium'},'director_policy':{'ask_for_each_beat':['audience_feeling','audience_understanding','visual_information_needed'],'allow_silence':True,'avoid_effect_stacking':True,'minimum_visual_information':True}}
    beats=json.loads((p/'beat_map.json').read_text()).get('beats',[]) if (p/'beat_map.json').exists() else []
    arc=[]
    for i,b in enumerate(beats):
        t=i/max(1,len(beats)-1); intensity=round(3+6*(1-abs(2*t-1)),2); arc.append({'beat_id':b.get('beat_id',f'B{i+1:03d}'),'intensity':intensity,'function':'hook' if i==0 else ('reveal' if i==len(beats)//2 else 'build'),'silence_after_seconds':0.8 if i and i%4==3 else 0.0})
    retention=[{'time_seconds':round(float(b.get('start',0)),2),'event':'hook' if i==0 else ('new_question' if i%3==0 else 'information')} for i,b in enumerate(beats)]
    for name,data in [('director_strategy.json',strategy),('emotional_arc.json',{'schema_version':1,'status':'passed','points':arc}),('retention_plan.json',{'schema_version':1,'status':'review_required','events':retention,'notes':['Heuristic plan; validate with editorial review.']})]: (p/name).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({'status':'passed','beats':len(beats),'artifacts':['director_strategy.json','emotional_arc.json','retention_plan.json']},indent=2))
if __name__=='__main__': main()
