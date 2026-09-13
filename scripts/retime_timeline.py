#!/usr/bin/env python3
"""Apply a duration change and propagate it through a Timeline IR artifact."""
from __future__ import annotations
import argparse, copy, json
from pathlib import Path

def shift(value, threshold, delta):
    try: return float(value)+delta if float(value) >= threshold else float(value)
    except (TypeError,ValueError): return value

def retime(data:dict, object_id:str, new_end:float)->dict:
    out=copy.deepcopy(data); target=None
    for shot in out.get("shots",[]):
        if shot.get("shot_id")==object_id: target=shot; break
    if target is None: raise ValueError(f"unknown shot: {object_id}")
    old_end=float(target["end"]); start=float(target["start"]); new_end=float(new_end)
    if new_end <= start: raise ValueError("new_end must be after shot start")
    delta=new_end-old_end; target["end"]=new_end
    for shot in out.get("shots",[]):
        if shot is target: continue
        if float(shot.get("start",0)) >= old_end:
            shot["start"]=shift(shot["start"],old_end,delta); shot["end"]=shift(shot["end"],old_end,delta)
    for key in ("audio_events","graphics_events","caption_events","markers"):
        for item in out.get(key,[]):
            if float(item.get("start",0)) >= old_end:
                item["start"]=shift(item["start"],old_end,delta)
                if "end" in item: item["end"]=shift(item["end"],old_end,delta)
    out.setdefault("retiming_history",[]).append({"object_id":object_id,"old_end":old_end,"new_end":new_end,"delta":delta})
    return out

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--input",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--shot",required=True); ap.add_argument("--new-end",type=float,required=True); args=ap.parse_args()
    try: out=retime(json.loads(args.input.read_text()),args.shot,args.new_end)
    except (ValueError,KeyError) as exc: print(json.dumps({"status":"blocked","error":str(exc)})); return 1
    args.output.write_text(json.dumps(out,indent=2)+"\n"); print(json.dumps({"status":"passed","shot":args.shot,"new_end":args.new_end},indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
