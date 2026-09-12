#!/usr/bin/env python3
"""Ingest explicitly supplied local research files into the persistent workspace."""
from __future__ import annotations
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path

def digest(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--source',type=Path,action='append',required=True); args=ap.parse_args(); p=args.project; root=p/'research'; (root/'sources').mkdir(parents=True,exist_ok=True); records=[]
 for src in args.source:
  src=src.expanduser().resolve()
  if not src.is_file(): raise SystemExit(f'missing source: {src}')
  dest=root/'sources'/src.name; shutil.copy2(src,dest); text=''
  if src.suffix.lower()=='.pdf':
   out=subprocess.run(['pdftotext','-layout',str(dest),'-'],capture_output=True,text=True); text=out.stdout if out.returncode==0 else ''
  else: text=dest.read_text(encoding='utf-8',errors='replace')
  records.append({'source_id':f'SRC_{len(records)+1:04d}','path':str(dest.relative_to(p)),'title':src.stem,'sha256':digest(dest),'excerpt':text[:2000],'format':src.suffix.lower(),'rights_status':'review_required'})
 manifest={'schema_version':1,'status':'review_required','sources':records,'ingest_method':'explicit-local-files'}; (root/'sources.json').write_text(json.dumps(manifest,indent=2)+'\n'); print(json.dumps({'status':'passed','sources':len(records)},indent=2))
if __name__=='__main__': main()

