#!/usr/bin/env python3
"""Run objective FFprobe QA and create an explicit editorial-review record."""
from __future__ import annotations
import argparse,json,shutil,subprocess
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--video',default='renders/preview.mp4'); args=ap.parse_args(); p=args.project; video=p/args.video; probe=shutil.which('ffprobe')
    if not probe or not video.is_file(): raise SystemExit('ffprobe or video missing')
    r=subprocess.run([probe,'-v','error','-show_streams','-show_format','-of','json',str(video)],capture_output=True,text=True); data=json.loads(r.stdout) if r.returncode==0 else {}
    streams=data.get('streams',[]); ok=r.returncode==0 and any(x.get('codec_type')=='video' for x in streams) and video.stat().st_size>0
    (p/'qa').mkdir(exist_ok=True); (p/'qa/technical_qa.json').write_text(json.dumps({'schema_version':1,'status':'passed' if ok else 'blocked','video':args.video,'has_video':any(x.get('codec_type')=='video' for x in streams),'has_audio':any(x.get('codec_type')=='audio' for x in streams),'ffprobe':data},indent=2)+'\n')
    (p/'qa/editorial_qa.json').write_text(json.dumps({'schema_version':1,'status':'review_required','checks':['visual relevance','action correctness','factuality','pacing','continuity','caption visibility'],'reviewer':None},indent=2)+'\n')
    print(json.dumps({'technical_status':'passed' if ok else 'blocked','editorial_status':'review_required'},indent=2)); raise SystemExit(0 if ok else 1)
if __name__=='__main__': main()
