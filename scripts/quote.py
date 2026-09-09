#!/usr/bin/env python3
"""Create a transparent, non-billable quote manifest from local project inputs."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

def load_yaml_like(path):
    data={}
    if not path.exists(): return data
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or ':' not in line: continue
        k,v=line.split(':',1); v=v.strip().strip('"\'')
        if v.lower() in {'true','false'}: v=v.lower()=='true'
        else:
            try: v=float(v) if '.' in v else int(v)
            except ValueError: pass
        data[k.strip()]=v
    return data

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--out',default='quote_manifest.json'); args=ap.parse_args()
    p=args.project; brief=(p/'brief.md').read_text(encoding='utf-8') if (p/'brief.md').exists() else ''
    cfg=load_yaml_like(p/'project.yaml'); output=cfg.get('output',{}) if isinstance(cfg.get('output'),dict) else {}
    words=len(re.findall(r"\b[\w’'-]+\b",brief)); duration=round(max(30, words/2.4),1)
    manifest={'schema_version':1,'status':'review_required','project_id':cfg.get('project_id',p.name),'interpretation':{'brief_word_count':words,'estimated_duration_seconds':duration,'width':output.get('width',1280),'height':output.get('height',720),'fps':output.get('fps',24),'language':cfg.get('language','en')},'providers':{'research':'local-or-configured','tts':'user-upload-or-configured-provider','vision':'blocked-until-configured','renderer':'ffmpeg'},'estimate':{'billable_credits':None,'currency':'provider-dependent','latency_seconds':None,'basis':'No external provider call made; estimates require configured provider pricing.'},'approval':{'approved':False,'approved_by':None,'approved_at':None},'brief_excerpt':brief[:500]}
    out=p/args.out; out.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':'passed','output':str(out),'requires_approval':True},indent=2))
if __name__=='__main__': main()
