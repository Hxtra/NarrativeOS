#!/usr/bin/env python3
"""Align narration with faster-whisper when installed; never fabricate timings."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--audio',default='narration.mp3'); ap.add_argument('--model',default='small'); args=ap.parse_args(); p=args.project; audio=p/args.audio
 if not audio.is_file(): raise SystemExit('audio missing')
 try:
  from faster_whisper import WhisperModel
 except ImportError:
  out={'schema_version':1,'status':'blocked','reason':'faster-whisper is not installed','audio':str(audio.relative_to(p)),'captions':[]}; (p/'alignment.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2)); raise SystemExit(1)
 model=WhisperModel(args.model,device='auto',compute_type='int8'); segments,info=model.transcribe(str(audio),word_timestamps=True); caps=[]
 for seg in segments:
  words=getattr(seg,'words',None); text=seg.text.strip(); caps.append({'start':seg.start,'end':seg.end,'text':text,'words':[{'start':w.start,'end':w.end,'word':w.word} for w in (words or [])]})
 out={'schema_version':1,'status':'passed','alignment_model':args.model,'language':info.language,'captions':caps}; (p/'alignment.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'status':'passed','segments':len(caps),'language':info.language},indent=2))
if __name__=='__main__': main()

