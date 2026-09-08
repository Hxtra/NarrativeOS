#!/usr/bin/env python3
"""Burn deterministic ASS captions onto a rendered video."""
import argparse, json, shutil, subprocess
from pathlib import Path

def ass_time(v):
    v=float(v); h=int(v//3600); m=int((v%3600)//60); s=int(v%60); cs=int(round((v-int(v))*100)); return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--video",type=Path,required=True); ap.add_argument("--captions",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); args=ap.parse_args()
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg: raise SystemExit("ffmpeg is required")
    data=json.loads(args.captions.read_text(encoding="utf-8")); events=data.get("captions",[])
    if not events: raise SystemExit("captions file has no events")
    ass=args.output.with_suffix(".ass"); ass.parent.mkdir(parents=True,exist_ok=True)
    lines=["[Script Info]","ScriptType: v4.00+","PlayResX: 1280","PlayResY: 720","[V4+ Styles]","Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding","Style: Default,Arial,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1","[Events]","Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for e in events:
        text=str(e.get("text","")).replace("{","\\{").replace("}","\\}").replace("\n","\\N")
        lines.append(f"Dialogue: 0,{ass_time(e['start'])},{ass_time(e['end'])},Default,,0,0,0,,{text}")
    ass.write_text("\n".join(lines)+"\n",encoding="utf-8")
    r=subprocess.run([ffmpeg,"-y","-i",str(args.video),"-vf",f"subtitles={ass.as_posix()}","-c:a","copy",str(args.output)],capture_output=True,text=True)
    if r.returncode!=0: raise SystemExit(r.stderr[-4000:])
    print(json.dumps({"status":"passed","output":str(args.output),"ass":str(ass),"events":len(events)},indent=2))
if __name__=="__main__": main()
