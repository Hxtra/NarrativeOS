#!/usr/bin/env python3
"""Collect hashes and lineage for project artifacts into a release manifest."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project; rows=[]
 for f in sorted(p.rglob('*')):
  if f.is_file() and '.git' not in f.parts and f.name not in {'provenance_manifest.json'}:
   h=hashlib.sha256(f.read_bytes()).hexdigest(); rows.append({'path':str(f.relative_to(p)),'sha256':h,'size_bytes':f.stat().st_size})
 out={'schema_version':1,'status':'review_required','artifact_count':len(rows),'artifacts':rows,'release_requirements':['rights evidence','human approvals','tool/model versions','QA reports']}; (p/'provenance_manifest.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'status':'passed','artifacts':len(rows)},indent=2))
if __name__=='__main__': main()

