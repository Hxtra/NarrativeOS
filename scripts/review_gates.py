#!/usr/bin/env python3
"""Create explicit human-review gate artifacts; never silently approve content."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--approve-quote',action='store_true'); ap.add_argument('--approve-evidence',action='store_true'); args=ap.parse_args(); p=args.project
    q=p/'quote_manifest.json'
    if args.approve_quote:
        if not q.is_file(): raise SystemExit('quote_manifest.json missing')
        data=json.loads(q.read_text()); data['status']='passed'; data['approval']={'approved':True,'approved_by':'explicit-user-review'}; q.write_text(json.dumps(data,indent=2)+'\n')
    if args.approve_evidence:
        (p/'evidence_review.json').write_text(json.dumps({'schema_version':1,'status':'passed','review':'explicit-user-review','research_sources_checked':True},indent=2)+'\n')
    print(json.dumps({'status':'passed','quote_approved':args.approve_quote,'evidence_approved':args.approve_evidence},indent=2))
if __name__=='__main__': main()
