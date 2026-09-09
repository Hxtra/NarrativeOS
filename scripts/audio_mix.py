#!/usr/bin/env python3
"""Mix real narration and optional music with FFmpeg; no synthetic audio is created."""
from __future__ import annotations
import argparse, json, shutil, subprocess
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--narration',default='narration.mp3'); ap.add_argument('--music',type=Path); ap.add_argument('--output',default='audio/mix.m4a'); args=ap.parse_args(); p=args.project; ff=shutil.which('ffmpeg')
    if not ff: raise SystemExit('ffmpeg required')
    narration=p/args.narration
    if not narration.is_file(): raise SystemExit('narration audio missing')
    out=p/args.output; out.parent.mkdir(parents=True,exist_ok=True)
    if args.music:
        if not args.music.is_file(): raise SystemExit('music file missing')
        cmd=[ff,'-y','-i',str(narration),'-i',str(args.music),'-filter_complex','[1:a]volume=0.18[m];[m][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[duck];[0:a][duck]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-16:TP=-1.5:LRA=11[a]','-map','[a]','-c:a','aac','-b:a','192k',str(out)]
    else: cmd=[ff,'-y','-i',str(narration),'-af','loudnorm=I=-16:TP=-1.5:LRA=11','-c:a','aac','-b:a','192k',str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode: raise SystemExit(r.stderr[-4000:])
    manifest={'schema_version':1,'status':'passed','output':str(out.relative_to(p)),'narration':str(narration.relative_to(p)),'music':str(args.music) if args.music else None,'ducking':bool(args.music),'loudnorm':'I=-16:TP=-1.5:LRA=11'}
    (p/'audio_mix_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8'); print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
