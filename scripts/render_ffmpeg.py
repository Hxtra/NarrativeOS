#!/usr/bin/env python3
"""Render an approved timeline with FFmpeg; never chooses assets implicitly."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, tempfile
from pathlib import Path

def load(p): return json.loads(p.read_text(encoding="utf-8"))
def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--project",type=Path,required=True); ap.add_argument("--timeline",default="timeline.json"); ap.add_argument("--output",default="renders/preview.mp4"); args=ap.parse_args()
    ffmpeg=shutil.which("ffmpeg"); ffprobe=shutil.which("ffprobe")
    if not ffmpeg or not ffprobe: raise SystemExit("ffmpeg and ffprobe are required")
    p=args.project; tl=load(p/args.timeline); assets=load(p/"assets.json")
    registry={a.get("asset_id"):a for a in assets.get("assets",[])}
    shots=tl.get("shots",[])
    if not shots: raise SystemExit("timeline has no shots")
    out=p/args.output; out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hermes_render_",dir=p) as td:
        parts=[]
        for i,s in enumerate(shots):
            if s.get("status")!="approved": raise SystemExit(f"shot {s.get('shot_id')} is not approved")
            asset=registry.get(s.get("asset_id"));
            if not asset or asset.get("status")!="approved": raise SystemExit(f"asset not approved: {s.get('asset_id')}")
            src=Path(asset.get("local_path","")); src=src if src.is_absolute() else p/src
            if not src.is_file(): raise SystemExit(f"missing asset: {src}")
            dur=float(s["end"])-float(s["start"])
            if dur<=0: raise SystemExit(f"invalid duration for {s.get('shot_id')}")
            size=tl.get("output",{}); w=int(size.get("width",1280)); h=int(size.get("height",720)); fps=int(size.get("fps",24))
            fit=size.get("fit_policy","cover_crop")
            vf=f"scale={w}:{h}:force_original_aspect_ratio={'decrease' if fit=='contain' else 'increase'},crop={w}:{h},setsar=1"
            part=Path(td)/f"part_{i:04d}.mp4"
            ext=src.suffix.lower(); is_image=ext in {".png",".jpg",".jpeg",".webp"}
            cmd=[ffmpeg,"-y"]
            if is_image: cmd += ["-loop","1","-i",str(src),"-t",f"{dur:.3f}"]
            else: cmd += ["-ss",str(float(s.get("source_start",0))),"-i",str(src),"-t",f"{dur:.3f}"]
            cmd += ["-vf",vf,"-r",str(fps),"-an","-c:v","libx264","-pix_fmt","yuv420p","-preset","veryfast","-movflags","+faststart",str(part)]
            r=run(cmd)
            if r.returncode!=0: raise SystemExit(r.stderr[-3000:])
            parts.append(part)
        concat=Path(td)/"concat.txt"; concat.write_text("".join(f"file '{x.as_posix()}'\n" for x in parts),encoding="utf-8")
        r=run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(out)])
        if r.returncode!=0: raise SystemExit(r.stderr[-3000:])
    probe=run([ffprobe,"-v","error","-show_streams","-show_format","-of","json",str(out)])
    if probe.returncode!=0: raise SystemExit(probe.stderr)
    data=json.loads(probe.stdout); save={"status":"passed","output_path":str(out.relative_to(p)),"size_bytes":out.stat().st_size,"ffprobe":data,"motion_policy":"deterministic_fit_with_explicit_motion_field"}
    (p/"renders/render_manifest.json").write_text(json.dumps(save,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(save,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
