#!/usr/bin/env python3
"""Build explicit claim→source→asset→shot links and explainability records.

A claim is only "evidence_supported" when the shot's asset can stand as evidence (media_semantics):
generated media, stock and illustrations are "illustrative_only", whatever they depict.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from media_semantics import can_satisfy_evidence


def build_links(claims: list[dict], shots: list[dict], assets: list[dict]) -> list[dict]:
    by_shot = {a.get("shot_id"): a for a in assets if a.get("shot_id")}
    links = []
    for i, s in enumerate(shots):
        claim = claims[i] if i < len(claims) else None
        asset = by_shot.get(s.get("shot_id"))
        link = {"link_id": f"L{i+1:04d}", "claim_id": claim.get("claim_id") if claim else None,
                "source_refs": claim.get("source_refs", []) if claim else [], "shot_id": s.get("shot_id"),
                "asset_id": asset.get("asset_id") if asset else None, "media_class": asset.get("media_class") if asset else None}
        if asset is None:
            link.update(status="unresolved", reason="Asset approval and source evidence required.")
        else:
            ok, reason = can_satisfy_evidence(asset)
            link.update(status="evidence_supported" if ok else "illustrative_only", reason=reason)
        links.append(link)
    return links


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    load=lambda name,key: json.loads((p/name).read_text()).get(key,[]) if (p/name).exists() else []  # noqa: E731
    claims=load('claim_ledger.json','claims'); shots=load('shot_specs.json','shots'); assets=load('approved_assets.json','assets')
    links=build_links(claims,shots,assets)
    (p/'claim_visual_links.json').write_text(json.dumps({'schema_version':2,'status':'review_required','links':links},indent=2)+'\n')
    (p/'shot_explanations.json').write_text(json.dumps({'schema_version':1,'status':'review_required','decisions':[{'shot_id':s.get('shot_id'),'reasons':['supports narration','awaiting subject/action/date/rights verification']} for s in shots]},indent=2)+'\n')
    print(json.dumps({'status':'passed','links':len(links),'evidence_supported':sum(l['status']=='evidence_supported' for l in links)},indent=2))
if __name__=='__main__': main()
