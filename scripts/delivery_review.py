#!/usr/bin/env python3
"""Create a release decision from real artifact presence and QA statuses."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    required=['renders/final.mp4','timeline.json','captions.json','tts_manifest.json','audio_mix_manifest.json']
    missing=[x for x in required if not (p/x).is_file()]
    qa=[]
    for name in ('technical_qa.json','editorial_qa.json'):
        q=p/'qa'/name
        if not q.is_file(): missing.append('qa/'+name)
        elif json.loads(q.read_text()).get('status')!='passed': qa.append(name)
    ready=not missing and not qa
    out={'schema_version':1,'status':'passed' if ready else 'blocked','delivery_ready':ready,'missing_artifacts':missing,'failed_qa':qa,'publish_authorized':False}
    (p/'qa').mkdir(exist_ok=True); (p/'qa/delivery_review.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2)); raise SystemExit(0 if ready else 1)
if __name__=='__main__': main()
