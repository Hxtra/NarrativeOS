#!/usr/bin/env python3
"""Register explicit graphics/icon/thumbnail inputs; never invent source provenance."""
from __future__ import annotations
import argparse,json,shutil,hashlib
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--thumbnail',type=Path); args=ap.parse_args(); p=args.project
    (p/'graphics_manifest.json').write_text(json.dumps({'schema_version':1,'status':'passed','graphics':[],'note':'No graphics supplied; deterministic text overlays remain preferred.'},indent=2)+'\n')
    if args.thumbnail:
        if not args.thumbnail.is_file(): raise SystemExit('thumbnail missing')
        dest=p/'graphics'/args.thumbnail.name; dest.parent.mkdir(exist_ok=True); shutil.copy2(args.thumbnail,dest); h=hashlib.sha256(dest.read_bytes()).hexdigest()
        data={'schema_version':1,'status':'review_required','source':'user-supplied','path':str(dest.relative_to(p)),'sha256':h,'rights_status':'review_required'}
    else: data={'schema_version':1,'status':'review_required','source':'not-generated','note':'Provide a real thumbnail or configure an image provider.'}
    (p/'thumbnail_manifest.json').write_text(json.dumps(data,indent=2)+'\n'); print(json.dumps({'status':'passed','thumbnail':bool(args.thumbnail)},indent=2))
if __name__=='__main__': main()
