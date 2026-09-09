#!/usr/bin/env python3
"""Run a deterministic NarrativeOS integration simulation.

The simulation exercises artifact wiring and negotiation using fictional, locally
created evidence. It is explicitly not proof of real visual matching or rights.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def write(p, data): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def run(script, project, *extra):
    r=subprocess.run([sys.executable,str(ROOT/'scripts'/script),'--project',str(project),*extra],capture_output=True,text=True)
    if r.returncode: raise SystemExit(f'{script} failed:\n{r.stdout}\n{r.stderr}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project; p.mkdir(parents=True,exist_ok=True)
    (p/'brief.md').write_text('# The Lantern Coast\n\nCreate a short fictional documentary about a lighthouse keeper who maintained a lantern during a winter storm. Use a restrained, atmospheric, evidence-aware style.\n',encoding='utf-8')
    (p/'project.yaml').write_text('schema_version: 2\nproject_id: lantern_coast_simulation\nmode: simulation\n',encoding='utf-8')
    write(p/'channel_profile.json',{'schema_version':1,'channel_id':'simulation-documentary','language':'en','pacing':'restrained','music':'atmospheric','compliance':{'source_policy':'simulation-only'}})
    run('quote.py',p); run('review_gates.py',p,'--approve-quote')
    run('generate_script.py',p)
    claims=[{'claim_id':'C001','fact_key':'lantern_action','value':'keeper maintained lantern','source_refs':['SIM_SOURCE_001'],'verification':'simulation'}]
    write(p/'claim_ledger.json',{'schema_version':1,'status':'passed','claims':claims})
    write(p/'research.json',{'schema_version':1,'status':'passed','mode':'simulation','sources':[{'source_id':'SIM_SOURCE_001','title':'Fictional public-domain simulation source','rights_status':'public-domain-simulation'}]})
    run('build_beat_map.py',p); run('director_brain.py',p); run('continuity_bible.py',p); run('build_shotspec.py',p)
    # Simulation assets are structural fixtures, not semantic visual-match evidence.
    shots=json.loads((p/'shot_specs.json').read_text())['shots']; candidates=[]; approved=[]
    for i,s in enumerate(shots):
        aid=f'sim_asset_{i+1:03d}'; candidates.append({'candidate_id':aid,'shot_id':s['shot_id'],'source_path':f'simulation://{aid}','decision':'simulation_candidate','evidence_frame_paths':[], 'vision_descriptions':[], 'comparison':{'mode':'simulation','not_production_evidence':True}}); approved.append({'shot_id':s['shot_id'],'asset_id':aid,'status':'simulation_approved','rights_status':'public-domain-simulation','evidence_frame_paths':[],'usable_interval':[0,float(s.get('duration_seconds',5))]})
    write(p/'asset_candidates.json',{'schema_version':1,'status':'simulation','candidates':candidates})
    write(p/'asset_analysis.json',{'schema_version':1,'status':'simulation','analysis_mode':'structural-only','note':'No real vision analyzer executed.'})
    write(p/'approved_assets.json',{'schema_version':1,'status':'simulation','assets':approved})
    run('evidence_links.py',p); run('build_graphics.py',p); run('build_timeline.py',p)
    timeline=json.loads((p/'timeline.json').read_text());
    # The negotiation layer resolves competing editorial objectives explicitly.
    arc=json.loads((p/'emotional_arc.json').read_text()).get('points',[])
    negotiations=[]
    cursor=0.0
    for i,s in enumerate(timeline.get('shots',[])):
        intensity=arc[i].get('intensity',5) if i<len(arc) else 5
        requested=3.0 if intensity>=7 else 5.0
        chosen=max(requested,4.0) if intensity<7 else requested
        negotiations.append({'shot_id':s['shot_id'],'director_intensity':intensity,'retention_requested_seconds':requested,'chosen_duration_seconds':chosen,'decision':'protect emotional hold' if chosen>requested else 'honor retention beat','reason':'Director arc and retention plan negotiated before rendering.'})
        s['start']=cursor; s['end']=cursor+chosen; cursor=s['end']; s['motion']='static' if intensity<6 else 'slow_zoom_in'; s['status']='simulation_approved'
    timeline['shots']=timeline.get('shots',[]); timeline['status']='simulation'; write(p/'timeline.json',timeline)
    write(p/'negotiation_log.json',{'schema_version':1,'status':'simulation','decisions':negotiations})
    run('timeline_ir.py',p)
    write(p/'audio_events.json',{'schema_version':1,'status':'simulation','events':[{'event_id':'A001','type':'narration','start':0,'end':float(timeline['shots'][-1]['end']) if timeline.get('shots') else 0,'duck_music_db':-8},{'event_id':'A002','type':'silence','start':0.8,'duration':0.8,'reason':'emotional hold'}],'policy':'Audio events follow director arc and shot purpose.'})
    run('editorial_analysis.py',p)
    run('cost_router.py',p,'--task','simulation-documentary','--estimated-cost','0')
    write(p/'qa_plan.json',{'schema_version':1,'status':'simulation','checks':['technical streams','caption coverage','loudness','visual evidence','factuality','continuity','rights','cost/latency'],'release_gate':'blocked until real evidence and human review'})
    graph_nodes=['brief','research','director_strategy','claim_ledger','emotional_arc','retention_plan','continuity','shot_specs','assets','evidence_links','timeline_ir','audio_events','editorial_analysis','qa_plan']
    edges=[['brief','research'],['research','director_strategy'],['research','claim_ledger'],['director_strategy','emotional_arc'],['emotional_arc','retention_plan'],['claim_ledger','evidence_links'],['emotional_arc','shot_specs'],['continuity','shot_specs'],['shot_specs','assets'],['assets','evidence_links'],['evidence_links','timeline_ir'],['timeline_ir','audio_events'],['audio_events','editorial_analysis'],['editorial_analysis','qa_plan']]
    write(p/'narrative_graph.json',{'schema_version':1,'status':'simulation','nodes':graph_nodes,'edges':[{'from':a,'to':b} for a,b in edges]})
    report={'schema_version':1,'status':'simulation_complete','production_ready':False,'reason':'Simulation used structural fixtures and no real vision, rights, TTS, or editorial human review.','artifacts_checked':['research.json','claim_ledger.json','director_strategy.json','emotional_arc.json','retention_plan.json','narration_alignment.json','beat_map.json','shot_specs.json','asset_candidates.json','claim_visual_links.json','timeline_ir.json','audio_events.json','editorial_analysis.json','qa_plan.json','negotiation_log.json','narrative_graph.json'],'negotiations':len(negotiations),'unresolved_production_gates':['real asset acquisition','real frame-level vision evidence','real narration alignment','human editorial review']}
    write(p/'integration_report.json',report); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
