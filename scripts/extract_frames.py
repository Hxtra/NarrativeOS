#!/usr/bin/env python3
"""Extract timestamped evidence frames from a real media file."""
import argparse, json, shutil, subprocess
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("media",type=Path); ap.add_argument("--out",type=Path,required=True); ap.add_argument("--times",default="1,5,8"); args=ap.parse_args()
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg: raise SystemExit("ffmpeg is required")
    args.out.mkdir(parents=True,exist_ok=True); results=[]
    for i,t in enumerate(x.strip() for x in args.times.split(",")):
        out=args.out/f"frame_{i:02d}_t{t.replace('.','_')}s.png"
        r=subprocess.run([ffmpeg,"-y","-ss",t,"-i",str(args.media),"-frames:v","1","-q:v","2",str(out)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if r.returncode!=0 or not out.is_file(): raise SystemExit(r.stderr[-2000:])
        results.append({"path":str(out),"time_seconds":float(t),"size_bytes":out.stat().st_size})
    print(json.dumps({"media":str(args.media),"frames":results},indent=2))
if __name__=="__main__": main()
