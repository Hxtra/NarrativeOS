#!/usr/bin/env python3
"""Validate a rendered file with real FFprobe and optional evidence frames."""
import argparse, json, shutil, subprocess
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("video",type=Path); ap.add_argument("--evidence-dir",type=Path); ap.add_argument("--out",type=Path); args=ap.parse_args()
    ffprobe=shutil.which("ffprobe")
    if not ffprobe: raise SystemExit("ffprobe is required")
    if not args.video.is_file(): raise SystemExit("video does not exist")
    r=subprocess.run([ffprobe,"-v","error","-show_streams","-show_format","-of","json",str(args.video)],capture_output=True,text=True)
    if r.returncode!=0: raise SystemExit(r.stderr)
    data=json.loads(r.stdout); streams=data.get("streams",[]); has_v=any(s.get("codec_type")=="video" for s in streams); has_a=any(s.get("codec_type")=="audio" for s in streams)
    frames=sorted(str(x) for x in (args.evidence_dir.glob("*.png") if args.evidence_dir and args.evidence_dir.exists() else []))
    report={"status":"passed" if has_v and args.video.stat().st_size>0 else "blocked","video_exists":True,"size_bytes":args.video.stat().st_size,"has_video":has_v,"has_audio":has_a,"evidence_frames":frames,"ffprobe":data}
    if args.out: args.out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2)); raise SystemExit(0 if report["status"]=="passed" else 1)
if __name__=="__main__": main()
