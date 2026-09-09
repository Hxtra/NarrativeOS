#!/usr/bin/env python3
"""Ingest explicitly supplied local media into the project with provenance and hashes."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

def sha256(path):
    h=hashlib.sha256();
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--manifest',type=Path,required=True); args=ap.parse_args(); p=args.project
    srcdata=json.loads(args.manifest.read_text(encoding='utf-8')); rows=srcdata.get('assets',srcdata if isinstance(srcdata,list) else [])
    assets=[]; candidates=[]
    for i,row in enumerate(rows):
        src=Path(row['local_path']).expanduser().resolve()
        if not src.is_file(): raise SystemExit(f'missing local asset: {src}')
        aid=row.get('asset_id',f'asset_{i+1:04d}'); dest=p/'assets'/f'{aid}{src.suffix.lower()}'; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dest)
        item={'asset_id':aid,'local_path':str(dest.relative_to(p)),'source_url':row.get('source_url','local-file://'+str(src)),'rights_status':row.get('rights_status','review_required'),'license':row.get('license','unspecified'),'sha256':sha256(dest),'status':'candidate','provenance_verified':bool(row.get('source_url'))}
        assets.append(item); candidates.append(item)
    (p/'assets.json').write_text(json.dumps({'schema_version':1,'assets':assets},indent=2)+'\n',encoding='utf-8')
    (p/'asset_candidates.json').write_text(json.dumps({'schema_version':1,'status':'review_required','candidates':candidates,'acquisition_method':'explicit-local-ingest'},indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':'passed','count':len(assets),'rights_review_required':True},indent=2))
if __name__=='__main__': main()
