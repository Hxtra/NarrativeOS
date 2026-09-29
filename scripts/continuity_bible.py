#!/usr/bin/env python3
"""Create editable continuity records; unresolved facts remain review-required."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from copy import deepcopy


ENTITY_KINDS = {"person", "location", "object", "environment", "unspecified"}
_PLACE_KINDS = {"location", "environment"}


def normalize_entity(raw: dict, kind: str | None = None) -> dict:
    """One explicit continuity record per recurring person, place, object or environment.

    Older records (``attributes`` / ``reference_images`` / separate ``locations``) are read into this shape.
    """
    entity_id = raw.get("entity_id") or raw.get("location_id")
    if not entity_id:
        raise ValueError("continuity entity needs an entity_id")
    kind = raw.get("kind") or kind or "unspecified"
    if kind not in ENTITY_KINDS:
        raise ValueError(f"entity {entity_id}: kind must be one of {sorted(ENTITY_KINDS)}")
    legacy = deepcopy(raw.get("attributes", {}))
    refs = deepcopy(raw.get("reference_assets", raw.get("reference_images", [])))
    return {
        "entity_id": entity_id,
        "kind": kind,
        "name": raw.get("name"),
        "visual_description": raw.get("visual_description", ""),
        "appearance_constraints": deepcopy(raw.get("appearance_constraints", {} if kind in _PLACE_KINDS else legacy)),
        "environment_constraints": deepcopy(raw.get("environment_constraints", legacy if kind in _PLACE_KINDS else {})),
        "style_constraints": deepcopy(raw.get("style_constraints", {})),
        "reference_assets": refs,
        "approved_reference": raw.get("approved_reference"),
        "generation_history": deepcopy(raw.get("generation_history", [])),
    }


def normalize_bible(bible: dict) -> dict:
    entities = [normalize_entity(e) for e in bible.get("entities", [])]
    entities += [normalize_entity(loc, "location") for loc in bible.get("locations", [])]
    ids = [e["entity_id"] for e in entities]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate continuity entity ids")
    lock = deepcopy(bible.get("style_lock", bible.get("generation_lock", {})))
    return {**{k: deepcopy(v) for k, v in bible.items() if k not in {"entities", "locations", "generation_lock"}},
            "entities": entities, "style_lock": lock}


def resolve_continuity(bible: dict, entity_ids: list[str]) -> dict:
    """Everything a generation request must stay consistent with, resolved from ids alone.

    Returns the full entity records, the production-wide style lock, and the reference assets to send to the
    generator (approved reference first). Unknown ids raise: a new identity or place is never guessed.
    """
    book = normalize_bible(bible or {})
    by_id = {e["entity_id"]: e for e in book["entities"]}
    missing = [i for i in entity_ids if i not in by_id]
    if missing:
        raise ValueError(f"unknown continuity entities {missing}: add them to the bible first")
    selected = [deepcopy(by_id[i]) for i in entity_ids]
    inputs = []
    for entity in selected:
        ordered = sorted(entity["reference_assets"], key=lambda r: r.get("asset_id") != entity["approved_reference"])
        for ref in ordered:
            if all(r["sha256"] != ref.get("sha256") for r in inputs):
                inputs.append({**deepcopy(ref), "entity_id": entity["entity_id"],
                               "role": "approved_reference" if ref.get("asset_id") == entity["approved_reference"] else "reference"})
    return {"entities": selected, "style_lock": deepcopy(book["style_lock"]),
            "generation_lock": deepcopy(book["style_lock"]),  # older name, kept for readers of v1 requests
            "reference_inputs": inputs}


def register_reference(bible: dict, entity_ids: list[str], asset: dict, request_id: str, make_approved: bool = True) -> dict:
    """Record a registered asset as a reference for entities, update their approved reference and history.

    Returns a new, normalized bible; the input is not modified.
    """
    for key in ("asset_id", "sha256", "local_path"):
        if not asset.get(key):
            raise ValueError(f"reference asset needs '{key}'")
    book = normalize_bible(bible)
    by_id = {e["entity_id"]: e for e in book["entities"]}
    missing = [i for i in entity_ids if i not in by_id]
    if missing or not entity_ids:
        raise ValueError(f"unknown or empty continuity entities {missing}")
    for entity in (by_id[i] for i in entity_ids):
        if all(r.get("sha256") != asset["sha256"] for r in entity["reference_assets"]):
            entity["reference_assets"].append(deepcopy(asset))
        if make_approved or not entity["approved_reference"]:
            entity["approved_reference"] = asset["asset_id"]
        entity["generation_history"].append({"request_id": request_id, "asset_id": asset["asset_id"], "sha256": asset["sha256"]})
    book["style_lock"].setdefault("first_reference_sha256", asset["sha256"])
    return book


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); args=ap.parse_args(); p=args.project
    text='\n'.join((p/x).read_text(encoding='utf-8') for x in ('brief.md','script.json') if (p/x).exists())
    names=[]
    for n in re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b',text):
        if n not in {'Create Short','Support The','No External'} and n not in names: names.append(n)
    entities=[{'entity_id':f'E{i+1:03d}','name':n,'attributes':{},'timeline':[],'status':'review_required'} for i,n in enumerate(names)]
    data={'schema_version':1,'status':'review_required','entities':entities,'rules':['Do not show anachronistic objects, places, clothing, logos, dates, or technology without evidence.']}
    (p/'entity_bible.json').write_text(json.dumps(data,indent=2)+'\n')
    (p/'temporal_constraints.json').write_text(json.dumps({'schema_version':1,'status':'review_required','constraints':[],'checks':['date','camera era','clothing','vehicles','architecture','technology','logos','signs']},indent=2)+'\n')
    (p/'geographic_plan.json').write_text(json.dumps({'schema_version':1,'status':'review_required','locations':[],'routes':[],'map_policy':'verify claimed locations before visualizing'},indent=2)+'\n')
    print(json.dumps({'status':'passed','entities':len(entities)},indent=2))
if __name__=='__main__': main()
