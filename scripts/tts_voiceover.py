#!/usr/bin/env python3
"""Register user audio or a configured TTS provider output; never synthesize placeholders."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

def sha256(path):
    h=hashlib.sha256();
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--audio',type=Path); ap.add_argument('--provider'); ap.add_argument('--voice',default=''); ap.add_argument('--language',default='en'); args=ap.parse_args(); p=args.project
    if not args.audio: raise SystemExit('No audio supplied. Pass --audio with user voiceover or implement a configured provider adapter.')
    src=args.audio.resolve()
    if not src.is_file() or src.stat().st_size==0: raise SystemExit('audio file missing or empty')
    out=p/'narration.mp3'; out.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,out)
    manifest={'schema_version':1,'status':'passed','source':'user_upload','provider':args.provider or 'user-upload','voice':args.voice,'language':args.language,'sha256':sha256(out),'consent_record':'user-supplied-audio; verify rights before release'}
    (p/'tts_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':'passed','output':str(out)},indent=2))
if __name__=='__main__': main()
