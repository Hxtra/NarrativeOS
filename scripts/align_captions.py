#!/usr/bin/env python3
"""Create captions from explicit timings; audio alignment adapters can be added later."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--timings',type=Path,required=True); args=ap.parse_args(); p=args.project
    data=json.loads(args.timings.read_text(encoding='utf-8')); events=data.get('captions',data if isinstance(data,list) else [])
    if not events: raise SystemExit('timings file has no caption events')
    clean=[]; last=0.0
    for e in events:
        start=float(e['start']); end=float(e['end']); text=str(e['text']).strip()
        if not text or start<last or end<=start: raise SystemExit('invalid caption timing order')
        clean.append({'start':start,'end':end,'text':text}); last=end
    out={'schema_version':1,'status':'passed','source':'explicit-timing-input','alignment_model':data.get('alignment_model','user-or-external-alignment'),'captions':clean}
    (p/'captions.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    from render_captions import ass_time
    lines=['[Script Info]','ScriptType: v4.00+','PlayResX: 1280','PlayResY: 720','[V4+ Styles]','Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding','Style: Default,Arial,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1','[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    for e in clean: lines.append(f"Dialogue: 0,{ass_time(e['start'])},{ass_time(e['end'])},Default,,0,0,0,,{e['text'].replace('{','\\{').replace('}','\\}').replace(chr(10),'\\N')}")
    (p/'captions.ass').write_text('\n'.join(lines)+'\n',encoding='utf-8'); print(json.dumps({'status':'passed','events':len(clean)},indent=2))
if __name__=='__main__': main()
