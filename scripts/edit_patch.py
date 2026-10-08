#!/usr/bin/env python3
"""Typed edit patches against the multi-track timeline (IR 3.0): the engine behind "change this part".

A request such as "make this part faster", "remove this shot", "dip to black here" or "music down 3 dB"
becomes a PATCH: a list of typed operations on stable item IDs, built against an exact parent timeline hash.
It is never a free rewrite. Applying a patch gives a new timeline plus a diff that separates

- edited items (the operation targets, and the neighbour a transition change necessarily touches),
- shifted items (only moved in time by a ripple),
- untouched items,

and warns when an edit cuts across something that cannot move with it (a narration item spanning the edit
point). Validation is the compiler's (compile_timeline.validate); a patch that fails it is not applied.

Operations
  set_duration  {item_id, duration, ripple=true}         main-track ripple keeps crossfade overlaps exact
  pace          {from, to, factor}                        every main shot starting in [from, to) x factor
  remove        {item_id, ripple=true}
  set_transition{item_id, type, duration}                 transition INTO a main shot; adjusts the previous shot's out
  set_gain      {item_id|track_id, gain_db|delta_db}
  set_motion    {item_id, kind, scale_from, scale_to}
  set_text      {item_id, text}
  replace_asset {item_id, asset_id, source_in=0}
  move          {item_id, timeline_in}                    non-main items, duration kept
  add           {track_id, item}

The interpreter (`interpret`) turns plain sentences into these operations with explicit rules. When a
reasoning provider is configured (model_provider.py, task propose_edit_patch) it is asked only for what the
rules cannot parse, and its operations go through exactly the same apply-and-validate path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

EPS = 1e-6
MIN_SHOT = 0.6
OPS = {"set_duration", "pace", "remove", "set_transition", "set_gain", "set_motion", "set_text", "replace_asset", "move", "add"}


class PatchError(Exception):
    pass


def timeline_sha(ir: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in ir.items() if k != "compile"}, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def main_track(ir: dict) -> dict | None:
    return next((t for t in ir.get("tracks", []) if t.get("kind") == "video"), None)


def find(ir: dict, item_id: str) -> tuple[dict, dict]:
    for t in ir.get("tracks", []):
        for it in t.get("items", []):
            if it.get("id") == item_id:
                return t, it
    raise PatchError(f"no item {item_id!r} in the timeline")


def _sorted_main(ir: dict) -> list[dict]:
    t = main_track(ir)
    return sorted(t["items"], key=lambda x: float(x["timeline_in"])) if t else []


BEDS = {"music", "ambience"}


def _shift_after(ir: dict, t_point: float, delta: float, skip: set[str], warnings: list[str], prog_end: float | None = None) -> set[str]:
    """Move every non-main item starting at/after t_point by delta; warn about items spanning it.

    A bed (music, ambience) that spans the edit and ends with the programme is trimmed with it when the programme
    gets shorter, so the picture never ends before the sound. Returns the IDs trimmed that way (they are edits)."""
    mt = main_track(ir)
    trimmed: set[str] = set()
    for t in ir.get("tracks", []):
        if t is mt:
            continue
        for it in t.get("items", []):
            if it["id"] in skip:
                continue
            a, b = float(it["timeline_in"]), float(it["timeline_out"])
            if a >= t_point - EPS:
                it["timeline_in"], it["timeline_out"] = round(a + delta, 6), round(b + delta, 6)
            elif b > t_point + EPS and abs(delta) > EPS:
                bed_at_end = t.get("role") in BEDS and prog_end is not None and b >= prog_end - EPS
                if bed_at_end and delta < 0 and b + delta > a + MIN_SHOT:
                    it["timeline_out"] = round(b + delta, 6)
                    trimmed.add(it["id"])
                    warnings.append(f"{it['id']} ({t['role']}) ended with the programme, so it now ends {abs(delta):.2f} s earlier with it")
                elif bed_at_end and delta > 0:
                    warnings.append(f"{it['id']} ({t['role']}) now ends {delta:.2f} s before the picture does; extend or replace it if it should reach the end")
                elif t.get("role") not in BEDS:
                    warnings.append(f"{it['id']} ({t.get('role') or t['kind']}) runs across {t_point:.2f} s and cannot move with the edit: "
                                    f"after that point it is now {abs(delta):.2f} s {'behind' if delta < 0 else 'ahead of'} the picture")
    return trimmed


def _programme_end(ir: dict) -> float:
    return max((float(x["timeline_out"]) for x in _sorted_main(ir)), default=0.0)


def _ripple_main(ir: dict, item: dict, delta: float, warnings: list[str], t_point: float) -> set[str]:
    """Shift every main shot after `item` (in sequence order, so crossfade partners keep their overlap) and every
    other item starting at/after t_point (the edit point on the timeline before the change).
    Returns the IDs of beds trimmed to follow the programme end."""
    prog_end = _programme_end(ir)
    seq = _sorted_main(ir)
    idx = next(i for i, x in enumerate(seq) if x is item)
    for x in seq[idx + 1:]:
        x["timeline_in"] = round(float(x["timeline_in"]) + delta, 6)
        x["timeline_out"] = round(float(x["timeline_out"]) + delta, 6)
        au = x.get("audio") or {}
        for k in ("native_in", "native_out"):
            if k in au:
                au[k] = round(float(au[k]) + delta, 6)
    trimmed = _shift_after(ir, t_point, delta, {item["id"]}, warnings, prog_end)
    if ir.get("duration"):
        ir["duration"] = round(float(ir["duration"]) + delta, 6)
    return trimmed


def _set_duration(ir: dict, item: dict, duration: float, ripple: bool, warnings: list[str]) -> set[str]:
    if duration < MIN_SHOT:
        raise PatchError(f"{item['id']}: {duration:.2f} s is shorter than the {MIN_SHOT} s minimum")
    old_out = float(item["timeline_out"])
    delta = duration - (old_out - float(item["timeline_in"]))
    item["timeline_out"] = round(float(item["timeline_in"]) + duration, 6)
    au = item.get("audio") or {}
    if "native_out" in au:
        au["native_out"] = round(float(au["native_out"]) + delta, 6)
    mt = main_track(ir)
    if ripple and mt and item in mt["items"]:
        return _ripple_main(ir, item, delta, warnings, old_out)
    return set()


def apply_op(ir: dict, op: dict, warnings: list[str]) -> set[str]:
    """Apply one operation in place. Returns the IDs it edits (not mere shifts)."""
    kind = op.get("op")
    if kind not in OPS:
        raise PatchError(f"unknown operation {kind!r}")
    mt = main_track(ir)
    if kind == "set_duration":
        _, it = find(ir, op["item_id"])
        return {it["id"]} | _set_duration(ir, it, float(op["duration"]), op.get("ripple", True), warnings)
    if kind == "pace":
        lo, hi, f = float(op["from"]), float(op["to"]), float(op["factor"])
        if not 0.3 <= f <= 3:
            raise PatchError("pace factor must be within 0.3-3")
        targets = [x for x in _sorted_main(ir) if lo - EPS <= float(x["timeline_in"]) < hi - EPS]
        if not targets:
            raise PatchError(f"no shots start between {lo:.2f} and {hi:.2f} s")
        extra: set[str] = set()
        for x in targets:  # left to right; each ripple moves the later targets too
            length = float(x["timeline_out"]) - float(x["timeline_in"])
            extra |= _set_duration(ir, x, max(MIN_SHOT, round(length * f, 3)), True, warnings)
        return {x["id"] for x in targets} | extra
    if kind == "remove":
        t, it = find(ir, op["item_id"])
        if t is mt and op.get("ripple", True):
            seq = _sorted_main(ir)
            i = seq.index(it)
            length = float(it["timeline_out"]) - float(it["timeline_in"])
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            inherited = it.get("transition_in")
            a0, b0 = float(it["timeline_in"]), float(it["timeline_out"])
            for tr in ir["tracks"]:
                if tr is not mt:
                    for x in tr["items"]:
                        if a0 - EPS <= float(x["timeline_in"]) and float(x["timeline_out"]) <= b0 + EPS:
                            warnings.append(f"{x['id']} ({tr.get('role') or tr['kind']}) sat on the removed shot and stays at its time; "
                                            "move or remove it if it belonged to that shot")
            # Ripple first (while the item is still in the track), then take it out.
            trimmed = _ripple_main(ir, it, -length, warnings, b0)
            t["items"].remove(it)
            edited = {it["id"]} | trimmed
            if nxt is not None:
                prev = seq[i - 1] if i > 0 else None
                overlap = (float(prev["timeline_out"]) - float(nxt["timeline_in"])) if prev else 0.0
                if overlap > EPS:
                    nxt["transition_in"] = {"type": "crossfade", "duration": round(overlap, 6)}
                elif inherited and inherited.get("type", "").startswith("dip"):
                    nxt["transition_in"] = dict(inherited)
                elif (nxt.get("transition_in") or {}).get("type") == "crossfade":
                    nxt.pop("transition_in")
                edited.add(nxt["id"])
            return edited
        t["items"].remove(it)
        return {it["id"]}
    if kind == "set_transition":
        t, it = find(ir, op["item_id"])
        if t is not mt:
            raise PatchError("transitions are set on main-track shots (the transition INTO that shot)")
        seq = _sorted_main(ir)
        i = seq.index(it)
        if i == 0:
            raise PatchError(f"{it['id']} is the first shot; there is nothing to transition from")
        prev = seq[i - 1]
        ttype, dur = op["type"], float(op.get("duration", 0.5))
        if ttype == "recipe" and not op.get("recipe"):
            raise PatchError("a recipe transition needs a recipe id")
        old = it.get("transition_in") or {"type": "cut", "duration": 0}
        old_overlap = float(old.get("duration", 0)) if old.get("type") == "crossfade" else 0.0
        new_overlap = dur if ttype == "crossfade" else 0.0
        prev["timeline_out"] = round(float(prev["timeline_out"]) + new_overlap - old_overlap, 6)
        if ttype == "cut":
            it.pop("transition_in", None)
        elif ttype == "recipe":  # rendered by the Remotion TransitionStack over the straight cut
            it["transition_in"] = {"type": "recipe", "recipe": op["recipe"]}
        else:
            it["transition_in"] = {"type": ttype, "duration": dur}
        return {it["id"], prev["id"]} if new_overlap != old_overlap else {it["id"]}
    if kind == "set_gain":
        if op.get("track_id"):
            t = next((x for x in ir["tracks"] if x["id"] == op["track_id"]), None)
            if not t:
                raise PatchError(f"no track {op['track_id']!r}")
            items = t["items"]
        else:
            items = [find(ir, op["item_id"])[1]]
        for x in items:
            holder = x["audio"] if (x.get("audio") or {}).get("native") else x
            g = float(holder.get("gain_db", 0))
            holder["gain_db"] = round(float(op["gain_db"]) if "gain_db" in op else g + float(op["delta_db"]), 2)
        return {x["id"] for x in items}
    if kind == "set_motion":
        _, it = find(ir, op["item_id"])
        if op["kind"] == "none":
            it.pop("motion", None)
        else:
            it["motion"] = {"kind": op["kind"], "scale_from": float(op.get("scale_from", 1.0)), "scale_to": float(op.get("scale_to", 1.08))}
        return {it["id"]}
    if kind == "set_text":
        _, it = find(ir, op["item_id"])
        if "text" not in it:
            raise PatchError(f"{it['id']} is not a text item")
        it["text"] = str(op["text"])
        return {it["id"]}
    if kind == "replace_asset":
        _, it = find(ir, op["item_id"])
        it["asset_id"] = op["asset_id"]
        it["source_in"] = float(op.get("source_in", 0))
        return {it["id"]}
    if kind == "move":
        t, it = find(ir, op["item_id"])
        if t is mt:
            raise PatchError("main-track shots move by changing durations around them, not by 'move'")
        length = float(it["timeline_out"]) - float(it["timeline_in"])
        it["timeline_in"] = round(float(op["timeline_in"]), 6)
        it["timeline_out"] = round(it["timeline_in"] + length, 6)
        return {it["id"]}
    # add
    t = next((x for x in ir["tracks"] if x["id"] == op["track_id"]), None)
    if not t:
        raise PatchError(f"no track {op['track_id']!r}")
    item = copy.deepcopy(op["item"])
    t["items"].append(item)
    return {item["id"]}


def _items(ir: dict) -> dict[str, dict]:
    return {it["id"]: it for t in ir.get("tracks", []) for it in t.get("items", [])}


def diff(before: dict, after: dict, edited: set[str]) -> dict:
    b, a = _items(before), _items(after)
    out = {"edited": [], "shifted": [], "added": sorted(set(a) - set(b)), "removed": sorted(set(b) - set(a)), "untouched": 0}
    for iid in sorted(set(a) & set(b)):
        x, y = b[iid], a[iid]
        if x == y:
            out["untouched"] += 1
            continue
        changes = {k: {"before": x.get(k), "after": y.get(k)} for k in sorted(set(x) | set(y)) if x.get(k) != y.get(k)}
        timing_only = set(changes) <= {"timeline_in", "timeline_out", "audio"}
        d_in = float(y["timeline_in"]) - float(x["timeline_in"])
        d_out = float(y["timeline_out"]) - float(x["timeline_out"])
        if iid not in edited and timing_only and abs(d_in - d_out) < 1e-4:
            out["shifted"].append({"id": iid, "by": round(d_in, 3)})
        else:
            out["edited"].append({"id": iid, "changes": changes})
    return out


def apply(ir: dict, patch: dict, project: Path | None = None, check: bool = True) -> dict:
    """Apply a patch to a copy of `ir`. Returns {timeline, diff, warnings, validation}."""
    if patch.get("parent_timeline_sha256") and patch["parent_timeline_sha256"] != timeline_sha(ir):
        raise PatchError("the timeline changed since this patch was proposed; propose it again")
    new = copy.deepcopy(ir)
    warnings: list[str] = []
    edited: set[str] = set()
    for op in patch.get("operations", []):
        edited |= apply_op(new, op, warnings)
    d = diff(ir, new, edited)
    unexpected = [e["id"] for e in d["edited"] if e["id"] not in edited]
    if unexpected:
        raise PatchError(f"revision locality violated: {unexpected} changed but no operation targeted them")
    validation = None
    if check and project is not None:
        from compile_timeline import validate
        v = validate(new, project)
        validation = {"errors": v["errors"], "warnings": v["warnings"], "duration": v["duration"]}
    return {"timeline": new, "diff": d, "warnings": warnings, "validation": validation}


# ----------------------------------------------------------------------------------------------- interpreter
_TIME = r"(\d+):(\d{1,2}(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b"


def _times(text: str) -> list[float]:
    out = []
    for m in re.finditer(_TIME, text):
        out.append(int(m.group(1)) * 60 + float(m.group(2)) if m.group(1) else float(m.group(3)))
    return out


def _shot_ref(text: str, ir: dict) -> dict | None:
    seq = _sorted_main(ir)
    ids = {x["id"].lower(): x for x in _items(ir).values()}
    for tok in re.findall(r"[\w-]+", text):
        if tok.lower() in ids and len(tok) > 1:
            return ids[tok.lower()]
    m = re.search(r"\b(?:shot|clip|scene)\s*#?\s*(\d+)\b", text) or re.search(r"#(\d+)\b", text)
    if m and 1 <= int(m.group(1)) <= len(seq):
        return seq[int(m.group(1)) - 1]
    return None


def _item_at(ir: dict, t: float, kind: str = "video") -> dict | None:
    for tr in ir.get("tracks", []):
        if tr.get("kind") == kind:
            for it in tr["items"]:
                if float(it["timeline_in"]) - EPS <= t < float(it["timeline_out"]):
                    return it
    return None


ROLE_WORDS = {"music": "music", "song": "music", "score": "music", "narration": "narration", "voiceover": "narration", "voice": "narration",
              "vo": "narration", "sfx": "sfx", "sound effect": "sfx", "sound effects": "sfx", "ambience": "ambience", "ambient": "ambience"}


# Plain words for the registered VFX recipes, most specific first; only recipes the registry actually has are offered.
RECIPE_WORDS = [
    (r"\bglitch\s*reveal\b", ["glitch_reveal"]), (r"\bglitch\b", ["glitch_cut", "glitch_reveal", "glitch_overlay_cut"]),
    (r"\b(rgb|chromatic|colou?r)\s*(split|aberration|shift)\b", ["rgb_split_hit"]), (r"\b(digital\s*)?tear\b", ["digital_tear"]),
    (r"\b(vhs|static)\b", ["vhs_static_cut"]), (r"\bstutter\b", ["stutter_cut"]),
    (r"\b(cool|cold|blue)\s*(light\s*)?leak\b", ["light_leak_cool"]), (r"\bleak\b.*\bwhip\b|\bwhip\b.*\bleak\b", ["leak_whip"]),
    (r"\blight\s*leak\b|\bleak\b", ["light_leak_warm", "leak_crossfade"]), (r"\bfilm\s*burn\b|\bburn\b", ["film_burn_passage", "film_burn_procedural"]),
    (r"\bfilm\s*damage\b", ["film_damage_dip"]), (r"\blens\s*flare\b|\bflare\b", ["lens_flare_sweep"]),
    (r"\bwhip\s*zoom\b|\bzoom\s*transition\b", ["whip_zoom"]), (r"\bwhip\b.*\bup\b", ["whip_pan_up"]),
    (r"\bwhip\b.*\bright\b", ["whip_pan_right"]), (r"\bwhip\b", ["whip_pan_left"]),
    (r"\bimpact\b|\bpunch\b", ["impact_cut"]), (r"\bshake\b", ["shake_impact"]), (r"\bhalftone\b", ["halftone_reveal"]),
    (r"\bwipe\b.*\bup\b", ["soft_wipe_up"]), (r"\bwipe\b", ["soft_wipe_left"]), (r"\b(projector)\b", ["projector_flicker_cut"]),
    (r"\b(archive|archival|old film)\b.*\bflicker\b|\bflicker\b", ["archive_flicker_cut", "projector_flicker_cut"]),
    (r"\bscratch", ["archive_scratch_cut"]), (r"\bdust\b", ["dust_drift_dissolve"]), (r"\bsnow", ["snowfall_passage"]),
    (r"\b(particle|shimmer|sparkle)", ["particle_shimmer_reveal"]), (r"\bmemory\b|\bdreamy\b", ["memory_fade"]),
    (r"\bblur\s*(dissolve|transition)\b", ["blur_dissolve"]), (r"\bpush[- ]in\s*cut\b", ["push_in_cut"]),
]


def interpret(message: str, ir: dict, selection: dict | None = None, asset_ids: set[str] | None = None,
              recipes: set[str] | None = None) -> dict:
    """Plain words to a patch with explicit rules. Returns {reply, operations, understood}."""
    text = message.strip()
    low = text.lower()
    sel = selection or {}
    target = _shot_ref(low, ir) if not sel.get("item_id") else None
    if sel.get("item_id"):
        try:
            target = find(ir, sel["item_id"])[1]
        except PatchError:
            target = None
    rng = (float(sel["from"]), float(sel["to"])) if sel.get("from") is not None and sel.get("to") is not None else None
    ts = _times(low)
    m = re.search(r"from\s+(" + _TIME + r")\s+(?:to|until|-)\s+(" + _TIME + r")", low)
    if m:
        a, b = _times(m.group(1))[0], _times(m.group(5))[0]
        rng = (min(a, b), max(a, b))
    if target is None and rng is None and "at" in low and ts:
        target = _item_at(ir, ts[0])
    much = bool(re.search(r"\b(much|a lot|way|really|lot)\b", low))
    ops: list[dict] = []
    say = ""

    def need(what="a shot"):
        return {"reply": f"Select {what} on the timeline (or name it, e.g. 'shot 3' or its ID) so I know which part you mean.",
                "operations": [], "understood": False}

    # Captions / titles: change text.
    m = re.search(r"(?:change|set|make|rename)\s+(?:the\s+)?(?:caption|text|title|subtitle)\s+(?:to|say|says|read|reads)\s*[\"“'](.+?)[\"”']", text, re.I)
    if m:
        cap = target if target is not None and "text" in target else None
        if cap is None:
            t = ts[0] if ts else (rng[0] if rng else None)
            cap = _item_at(ir, t, "caption") if t is not None else None
        if cap is None:
            return need("a caption")
        return {"reply": f"Changing caption {cap['id']} from “{cap['text']}” to “{m.group(1)}”.",
                "operations": [{"op": "set_text", "item_id": cap["id"], "text": m.group(1)}], "understood": True}
    # Audio levels.
    role = next((r for w, r in ROLE_WORDS.items() if re.search(rf"\b{w}\b", low)), None)
    up = re.search(r"\b(louder|up|raise|increase|boost|turn up|more)\b", low)
    down = re.search(r"\b(quieter|down|lower|reduce|softer|turn down|less)\b", low)
    if role and (up or down):
        db = re.search(r"(\d+(?:\.\d+)?)\s*db", low)
        delta = float(db.group(1)) if db else (6.0 if much else 3.0)
        delta = -delta if down and not up else delta
        tracks = [t for t in ir.get("tracks", []) if t.get("kind") == "audio" and t.get("role") == role]
        if not tracks:
            return {"reply": f"There is no {role} track in this timeline.", "operations": [], "understood": True}
        for t in tracks:
            ops.append({"op": "set_gain", "track_id": t["id"], "delta_db": delta})
        return {"reply": f"Turning the {role} {'up' if delta > 0 else 'down'} by {abs(delta):g} dB ({', '.join(t['id'] for t in tracks)}).",
                "operations": ops, "understood": True}
    # Recipe transitions into the selected shot (rendered by the Remotion TransitionStack).
    if recipes and re.search(r"\b(transition|into|here|cut|this|between|reveal|use|add|put)\b", low):
        rid = next((c for pat, cands in RECIPE_WORDS if re.search(pat, low) for c in cands if c in recipes), None)
        if rid:
            if target is None or target.get("id") not in {x["id"] for x in _sorted_main(ir)}:
                return need("the shot the transition should lead into")
            return {"reply": f"{rid.replace('_', ' ').capitalize()} into {target['id']}.",
                    "operations": [{"op": "set_transition", "item_id": target["id"], "type": "recipe", "recipe": rid}], "understood": True}
    # Transitions into the selected shot.
    trans = None
    if re.search(r"\b(dip|fade)\s*(to|through)?\s*black\b", low):
        trans = ("dip_black", 0.8)
    elif re.search(r"\b(dip|fade)\s*(to|through)?\s*white\b|\bwhite flash\b|\bflash\b", low):
        trans = ("dip_white", 0.3)
    elif re.search(r"\b(crossfade|cross fade|dissolve|blend into|mix into)\b", low):
        trans = ("crossfade", 0.5)
    elif re.search(r"\b(hard cut|just cut|straight cut|no transition)\b", low):
        trans = ("cut", 0.0)
    if trans:
        if target is None or target.get("id") not in {x["id"] for x in _sorted_main(ir)}:
            return need("the shot the transition should lead into")
        dur = next((t for t in ts if t < 3), trans[1])
        name = {"cut": "Hard cut", "crossfade": "Crossfade", "dip_black": "Dip to black", "dip_white": "White flash"}[trans[0]]
        return {"reply": f"{name} into {target['id']}." if trans[0] == "cut" else f"{name} into {target['id']} over {dur:g} s.",
                "operations": [{"op": "set_transition", "item_id": target["id"], "type": trans[0], "duration": dur}], "understood": True}
    # Remove.
    if re.search(r"\b(remove|delete|cut out|drop|get rid of|take out)\b", low):
        if target is None:
            return need()
        return {"reply": f"Removing {target['id']}; everything after it moves up to close the gap.",
                "operations": [{"op": "remove", "item_id": target["id"]}], "understood": True}
    # Motion.
    if re.search(r"\b(push in|push-in|zoom in|slow zoom|ken burns)\b", low) or re.search(r"\b(pull out|pull-out|zoom out)\b", low) \
            or re.search(r"\b(no motion|static|stop (the )?zoom|no zoom)\b", low):
        if target is None:
            return need()
        if re.search(r"\b(no motion|static|stop (the )?zoom|no zoom)\b", low):
            op = {"op": "set_motion", "item_id": target["id"], "kind": "none"}
            say = f"Holding {target['id']} still (no camera move)."
        elif re.search(r"\b(pull out|pull-out|zoom out)\b", low):
            op = {"op": "set_motion", "item_id": target["id"], "kind": "pull_out", "scale_from": 1.12 if much else 1.08, "scale_to": 1.0}
            say = f"Slow pull-out on {target['id']}."
        else:
            op = {"op": "set_motion", "item_id": target["id"], "kind": "push_in", "scale_from": 1.0, "scale_to": 1.12 if much else 1.08}
            say = f"Slow push-in on {target['id']}."
        return {"reply": say, "operations": [op], "understood": True}
    # Replace with another asset.
    m = re.search(r"\b(?:replace|swap)\b.*?\b(?:with|for)\s+([\w.-]+)", low) or re.search(r"\buse\s+([\w.-]+)\s+(?:here|instead)", low)
    if m:
        if target is None:
            return need()
        want = m.group(1)
        match = next((a for a in sorted(asset_ids or []) if a.lower() == want or a.lower().startswith(want)), None)
        if not match:
            return {"reply": f"I can't find an asset called '{want}'. Pick one from the Assets list (its ID) and try again.", "operations": [], "understood": True}
        return {"reply": f"Replacing the picture in {target['id']} with {match}.",
                "operations": [{"op": "replace_asset", "item_id": target["id"], "asset_id": match}], "understood": True}
    # Explicit durations.
    m = re.search(r"\b(?:make (?:it|this|the shot)|set (?:it|this) to|shorten (?:it|this)? ?to|lengthen (?:it|this)? ?to|trim (?:it|this)? ?to)\s+(" + _TIME + ")", low)
    by = re.search(r"\b(shorter|longer|shorten|lengthen|trim|extend)\b.*?\bby\s+(" + _TIME + ")", low)
    if m or by:
        if target is None:
            return need()
        cur = float(target["timeline_out"]) - float(target["timeline_in"])
        if m:
            new = _times(m.group(1))[0]
        else:
            amt = _times(by.group(2))[0]
            new = cur - amt if by.group(1) in ("shorter", "shorten", "trim") else cur + amt
        return {"reply": f"{target['id']}: {cur:.2f} s → {new:.2f} s; everything after it moves {'up' if new < cur else 'later'} by {abs(new - cur):.2f} s.",
                "operations": [{"op": "set_duration", "item_id": target["id"], "duration": round(new, 3)}], "understood": True}
    # Pace.
    faster = re.search(r"\b(faster|speed (it |this )?up|increase the pace|quicker|tighten|tighter|snappier|more energy|punchier|shorter)\b", low)
    slower = re.search(r"\b(slower|slow (it |this )?down|breathe|hold (it |this )?longer|more time|calmer|longer|let it sit)\b", low)
    if faster or slower:
        factor = (0.65 if much else 0.8) if faster else (1.5 if much else 1.25)
        if rng:
            return {"reply": f"{'Tightening' if faster else 'Loosening'} every shot that starts between {rng[0]:.2f} and {rng[1]:.2f} s "
                             f"to {factor:.0%} of its length; what follows moves to match.",
                    "operations": [{"op": "pace", "from": rng[0], "to": rng[1], "factor": factor}], "understood": True}
        if target is None:
            return need("a shot or a stretch of the timeline")
        cur = float(target["timeline_out"]) - float(target["timeline_in"])
        new = max(MIN_SHOT, round(cur * factor, 3))
        return {"reply": f"{target['id']}: {cur:.2f} s → {new:.2f} s ({'faster' if faster else 'more room to breathe'}).",
                "operations": [{"op": "set_duration", "item_id": target["id"], "duration": new}], "understood": True}
    return {"reply": ("I can't turn that into an edit yet. Try, with a shot or a stretch selected: “make this faster”, “let it breathe”, "
                      "“remove this shot”, “crossfade into this”, “dip to black here”, “push in”, “music down 3 dB”, "
                      "“change the caption to \"…\"”, “make it 2.5 s”, or “replace with <asset id>”."),
            "operations": [], "understood": False}


def propose(ir: dict, message: str, selection: dict | None = None, asset_ids: set[str] | None = None, provider: dict | None = None,
            recipes: set[str] | None = None) -> dict:
    """A patch proposal: rules first; a configured reasoning provider only for what the rules could not parse."""
    r = interpret(message, ir, selection, asset_ids, recipes)
    basis = "rules"
    if not r["understood"] and provider:
        r, basis = ask_provider(ir, message, selection, asset_ids, provider)
    return {"reply": r["reply"], "patch": make_patch(ir, message, selection, r["operations"], basis), "understood": r["understood"]}


def ask_provider(ir: dict, message: str, selection: dict | None, asset_ids: set[str] | None, provider: dict) -> tuple[dict, str]:
    """Ask the configured reasoning provider for operations. Returns (interpretation, basis)."""
    from model_provider import load_reasoning_provider
    identity, call = load_reasoning_provider(provider)
    reply = call("propose_edit_patch", {"request": message, "selection": selection or {}, "timeline": ir,
                                        "allowed_operations": sorted(OPS), "asset_ids": sorted(asset_ids or [])})
    r = {"reply": reply.get("reply", "Proposed by the reasoning provider."), "operations": reply.get("operations", []), "understood": True}
    return r, f"model:{identity['name']}/{identity['model']}"


def make_patch(ir: dict, message: str, selection: dict | None, operations: list[dict], basis: str) -> dict | None:
    """A patch bound to the exact timeline it was proposed against (parent hash), or None when there is nothing to do."""
    if not operations:
        return None
    patch = {"patch_schema": "narrativeos.edit_patch/1.0", "request": message, "selection": selection or {}, "operations": operations,
             "parent_timeline_sha256": timeline_sha(ir), "basis": basis}
    patch["patch_id"] = "P" + hashlib.sha256(json.dumps(patch, sort_keys=True).encode()).hexdigest()[:10]
    return patch


def _label(ir: dict, item_id: str) -> str:
    try:
        _, it = find(ir, item_id)
    except PatchError:
        return item_id
    return f"{item_id} ({it['text']!r})" if "text" in it else item_id


def explain(op: dict, ir: dict) -> str:
    """One operation in plain words, read against the timeline it will be applied to (before the change)."""
    k = op.get("op")
    try:
        if k == "set_duration":
            _, it = find(ir, op["item_id"])
            old = float(it["timeline_out"]) - float(it["timeline_in"])
            return f"{op['item_id']}: {old:.2f} s → {float(op['duration']):.2f} s, later shots ripple to keep the cut tight"
        if k == "pace":
            n = len([x for x in _sorted_main(ir) if float(op["from"]) - EPS <= float(x["timeline_in"]) < float(op["to"]) - EPS])
            pct = round((float(op["factor"]) - 1) * 100)
            return f"{n} shot(s) starting {op['from']:.1f}–{op['to']:.1f} s get {'shorter' if pct < 0 else 'longer'} by {abs(pct)}%"
        if k == "remove":
            return f"remove {_label(ir, op['item_id'])} and close the gap"
        if k == "set_transition":
            _, it = find(ir, op["item_id"])
            old_tr = it.get("transition_in") or {"type": "cut"}
            old = (old_tr.get("recipe") or old_tr["type"]).replace("_", " ")
            if op["type"] == "recipe":
                return f"into {op['item_id']}: {old} → {op['recipe'].replace('_', ' ')} (rendered VFX transition)"
            new = op["type"].replace("_", " ") + (f" {float(op.get('duration', 0.5)):.2f} s" if op["type"] != "cut" else "")
            return f"into {op['item_id']}: {old} → {new}"
        if k == "set_gain":
            who = next((t.get("role") or t["id"] for t in ir["tracks"] if t["id"] == op.get("track_id")), None) or op.get("item_id")
            change = f"{op['delta_db']:+g} dB" if "delta_db" in op else f"set to {op['gain_db']:g} dB"
            return f"{who}: {change}"
        if k == "set_motion":
            if op["kind"] == "none":
                return f"{op['item_id']}: hold the frame still"
            return f"{op['item_id']}: {op['kind'].replace('_', ' ')} {float(op.get('scale_from', 1)):.2f} → {float(op.get('scale_to', 1.08)):.2f}"
        if k == "set_text":
            return f"{_label(ir, op['item_id'])} → {op['text']!r}"
        if k == "replace_asset":
            return f"{op['item_id']}: picture → {op['asset_id']}"
        if k == "move":
            return f"move {op['item_id']} to {float(op['timeline_in']):.2f} s"
        if k == "add":
            return f"add {op['item'].get('id')} on {op['track_id']}"
    except (KeyError, TypeError, ValueError, PatchError):
        pass
    return json.dumps(op, ensure_ascii=False)


def describe(result: dict) -> str:
    d = result["diff"]
    parts = []
    if d["edited"]:
        parts.append(f"{len(d['edited'])} edited ({', '.join(e['id'] for e in d['edited'])})")
    if d["removed"]:
        parts.append(f"removed {', '.join(d['removed'])}")
    if d["added"]:
        parts.append(f"added {', '.join(d['added'])}")
    if d["shifted"]:
        parts.append(f"{len(d['shifted'])} moved in time")
    parts.append(f"{d['untouched']} untouched")
    return "; ".join(parts) + "."
