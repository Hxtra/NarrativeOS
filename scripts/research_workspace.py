#!/usr/bin/env python3
"""Initialize a reusable research workspace; providers remain replaceable adapters."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    root=p/'research'; dirs=['sources','transcripts','documents','extracted','claims','timeline','entities','contradictions','evidence']
    for d in dirs: (root/d).mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':1,'status':'passed','workspace':'research','providers':{'native_rag':{'enabled':False},'notebooklm':{'enabled':False,'adapter_only':True},'other_rag':{'enabled':False}},'policy':'Unified evidence is the source of truth; providers cannot directly approve claims.'}
    (root/'research_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n'); (root/'research_graph.json').write_text(json.dumps({'schema_version':1,'nodes':[],'edges':[]},indent=2)+'\n')
    print(json.dumps({'status':'passed','directories':dirs,'provider_adapters':list(manifest['providers'])},indent=2))
if __name__=='__main__': main()
