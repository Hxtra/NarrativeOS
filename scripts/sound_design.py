"""Sound-design reasoning: for every moment of a film, decide sound, silence or nothing, and say why.

The owner's point (Oct 20): NarrativeOS does not need more sound effects, it needs to know why a sound belongs at a moment.
Four steps, each written down:
1. OBSERVE: picture events (the film's events.json), the shot plan (a brief: which world/place each shot is, which moments are
   reveals, peaks or turning points), the narration (cues, word times, pauses).
2. REASON: rules taken from MEASURED reference mixes (skills/narrativeos-sound-design/SKILL.md). Every proposal cites its rule,
   its evidence and a confidence. A rule with weak evidence says so.
3. SELECT or CREATE: real recordings for real-world sounds (paper, wood, water, wind), designed sounds (hits, booms, swells,
   ticks) from the library, or silence. If no library file fits, the proposal says what to find or synthesise.
4. PLACE and MIX: keep designed hits off stressed words, keep the density as sparse as the references, and write a plan for
   scripts/sound_mix.py.

  python scripts/sound_design.py BRIEF.json [--out proposals.json] [--plan sound_plan.json]

BRIEF.json:
{"events": "film/events.json", "cues": "film/cues.json", "words": "film/words.json", "voice_start": 2.0,
 "shots": {"globe": {"world": "space", "place": null}, "wellTop": {"world": "syene", "place": "well"}, ...},
 "moments": [{"event": "shrinks", "purpose": "turning_point"}, {"event": "ring", "purpose": "reveal", "word": "earth"},
             {"shot": "beta2", "purpose": "placed_silence"}],
 "library": "media/rights.json", "place_sounds": {"well": ["drip", "water"]}, "bookend": "desert"}
Shots with "home": true (the narrator's desk) do not make world jumps.
Purposes: reveal, turning_point, peak, placed_silence, list_beat, bookend.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# The rules, each with the measured evidence behind it (SOUND_NOTES.md; skills/narrativeos-sound-design/SKILL.md).
RULES = {
    "world_jump": {"evidence": "Fern: 9 of 16 checked low booms land on a cut into a new place or state", "confidence": 0.7},
    "same_world_cut": {"evidence": "Fern and Veritasium: most cuts carry no effect; effects are sparse", "confidence": 0.7},
    "place": {"evidence": "Fern: sparse foley tells where we are (cattle in an Indian street, rain in English cold)", "confidence": 0.6},
    "hand_action": {"evidence": "a visible hand action (writing, a brush) gets its real sound, quietly; Fern's desk scenes", "confidence": 0.5},
    "physical_change": {"evidence": "the physical moment of the story gets a real recorded sound (real recordings beat synthesis for "
                                    "wood, paper, water: the owner rejected synthesised foley, Oct 18)", "confidence": 0.7},
    "turning_point": {"evidence": "a low hit marks a change of state (Fern's booms on state changes)", "confidence": 0.6},
    "reveal": {"evidence": "the reveal gets a low hit with a music change (Veritasium's peak: the cue changes with the reveal)", "confidence": 0.6},
    "light_transition": {"evidence": "a light bloom carrying a cut gets a swell (the sound carries the cut as the light does)", "confidence": 0.4},
    "list_beat": {"evidence": "WEAK: soft ticks on cuts that land on listed nouns; Claude's choice in the Eratosthenes film, not measured in a reference", "confidence": 0.3},
    "pause": {"evidence": "a deliberate pause is left empty: Fern's placed silences; filling a pause with a whoosh removes the tension", "confidence": 0.8},
    "placed_silence": {"evidence": "Fern stops the music right before its darkest moment; the room stays (no digital silence)", "confidence": 0.7},
    "bookend": {"evidence": "Veritasium opens and closes on the same birdsong", "confidence": 0.6},
    "brand": {"evidence": "the channel mark gets one short tonal sound (a convention, not measured)", "confidence": 0.4},
}
DESIGNED_MIN_GAP = 4.0      # s between designed hits (the references are sparse; Fern's booms are minutes apart outside montages)
REL_DB = {"boom": 12, "hit": 14, "swell": 20, "creak": 18, "foley": 22, "ambience": 30, "tick": 20, "chime": 18}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def observe(brief: dict, base: Path) -> dict:
    ev = load(base / brief["events"]); E = ev["ev"] if isinstance(ev, dict) else ev
    pre = brief.get("voice_start", 0.0)
    cues = load(base / brief["cues"])["cues"] if brief.get("cues") else []
    words = load(base / brief["words"]) if brief.get("words") else []
    lines = [(c["t0"] + pre, c["t1"] + pre, c.get("text", "")) for c in cues]
    pauses = [(a[1], b[0]) for a, b in zip(lines, lines[1:]) if b[0] - a[1] >= 0.6]          # deliberate gaps between lines
    speech = [(w["t0"] + pre, w["t1"] + pre, w["w"]) for w in words]
    cuts = sorted([e for e in E if e["type"] == "cut"], key=lambda e: e["t"])
    return {"events": sorted(E, key=lambda e: e["t"]), "cuts": cuts, "lines": lines, "pauses": pauses, "speech": speech,
            "duration": ev.get("dur") if isinstance(ev, dict) else None}


def _speaking(t: float, speech: list) -> tuple | None:
    return next((w for w in speech if w[0] - 0.05 <= t <= w[1] + 0.05), None)


def reason(obs: dict, brief: dict) -> list[dict]:
    shots = brief.get("shots", {}); P = []
    moments = brief.get("moments", [])
    by_event = {m["event"]: m for m in moments if "event" in m}
    by_shot = {m["shot"]: m for m in moments if "shot" in m}
    def add(t, decision, rule, what, sound_class, role=None, **kw):
        P.append({"t": round(t, 3), "decision": decision, "rule": rule, "what": what, "class": sound_class, "role": role,
                  "evidence": RULES[rule]["evidence"], "confidence": RULES[rule]["confidence"], **kw})
    prev = brief.get("first_shot") or next(iter(shots), None)      # the film opens on a shot that no cut event names
    first_place = {}
    for c in obs["cuts"]:
        cur = shots.get(c["shot"], {}); pw = shots.get(prev, {}).get("world") if prev else None
        m = by_shot.get(c["shot"])
        if m and m["purpose"] == "placed_silence":
            add(c["t"], "silence", "placed_silence", f"music out at '{c['shot']}', room tone stays", "silence", role="silence")
        elif m and m["purpose"] == "list_beat":
            add(c["t"], "sound", "list_beat", f"cut on a listed noun ({c['shot']})", "designed", role="tick")
        elif pw is not None and cur.get("world") and cur.get("world") != pw and not cur.get("home") and not shots.get(prev, {}).get("home"):
            # the evidence is P(cut into a new world | boom), not P(boom | new-world cut): cuts to and from the narrator's home base
            # (the desk) are routine, and the density limit below keeps the rest sparse
            add(c["t"], "sound", "world_jump", f"cut from the {pw} world into the {cur['world']} world", "designed", role="boom", peak_on="cut")
        else:
            add(c["t"], "nothing", "same_world_cut", f"cut within the {cur.get('world', '?')} world", None)
        place = cur.get("place")
        if place and place not in first_place:
            first_place[place] = c["t"]
            add(c["t"], "sound", "place", f"we arrive at the {place}: its ambience", "real", role="ambience", place=place)
        prev = c["shot"]
    kinds = {"pen": ("hand_action", "real", "foley", "ink being written"), "brush": ("hand_action", "real", "foley", "a brush stroke"),
             "strike": ("hand_action", "real", "foley", "a pen strike-through"), "bend": ("physical_change", "real", "creak", "the board bends"),
             "bloom": ("light_transition", "designed", "swell", "sunlight blooms and carries the cut")}
    for e in obs["events"]:
        m = by_event.get(e["type"])
        if m and m["purpose"] in ("turning_point", "reveal", "peak"):
            rule = "reveal" if m["purpose"] in ("reveal", "peak") else "turning_point"
            t = e["t"]
            if m.get("word"):                                    # land on the word that names it
                w = next((s for s in obs["speech"] if s[0] >= e["t"] - 0.5 and s[2].lower().strip(".,!?").startswith(m["word"])), None)
                t = w[0] if w else t
            add(t, "sound", rule, f"{m['purpose'].replace('_', ' ')}: {e['type']}", "designed", role="boom" if rule == "reveal" else "hit", peak_on=m.get("word") or e["type"])
        elif e["type"] in kinds:
            rule, cls, role, what = kinds[e["type"]]
            add(e["t"], "sound", rule, what, cls, role=role)
    for p in P:                                                  # one sound per transition: a boom on the cut already carries it
        if p["role"] == "swell" and any(q["role"] == "boom" and q["decision"] == "sound" and 0 <= q["t"] - p["t"] <= 1.0 for q in P):
            p["decision"] = "dropped"; p["dropped_because"] = "a boom within 1 s carries this transition (one sound per transition)"
    for a, b in obs["pauses"]:                                   # pauses stay empty unless the picture itself does something there
        inside = [p for p in P if a < p["t"] < b and p["decision"] == "sound" and p["class"] == "designed"]
        add(a, "nothing", "pause", f"a {b - a:.1f} s pause after a line is left empty" + (f" (except {len(inside)} picture event(s) inside it)" if inside else ""), None, until=round(b, 3))
    if brief.get("bookend"):
        add(0.0, "sound", "bookend", f"the film opens on {brief['bookend']}", "real", role="ambience", place=brief["bookend"])
        if obs["duration"]:
            add(obs["duration"] - 6.0, "sound", "bookend", f"and closes on the same {brief['bookend']}", "real", role="ambience", place=brief["bookend"])
    for c in obs["cuts"]:
        if c["shot"] == brief.get("brand_shot", "logo"):
            add(c["t"] + 1.0, "sound", "brand", "the channel mark", "designed", role="chime")
    return sorted(P, key=lambda p: p["t"])


def constrain(P: list[dict], obs: dict) -> list[dict]:
    """Sparse like the references, and never on top of a stressed word.
    - Designed hits (boom, hit) closer than DESIGNED_MIN_GAP: the more confident one stays, the other is dropped (reason recorded).
    - A hit that is not meant to land ON a word, but falls on one, moves into the gap within 150 ms, or is lowered 4 dB."""
    hits = [p for p in P if p["decision"] == "sound" and p["class"] == "designed" and p["role"] in ("boom", "hit")]
    for p in sorted(hits, key=lambda p: -p["confidence"]):                  # most confident first claim their place
        if p["decision"] != "sound":
            continue
        for q in hits:
            if q is not p and q["decision"] == "sound" and abs(q["t"] - p["t"]) < DESIGNED_MIN_GAP and q["confidence"] <= p["confidence"]:
                q["decision"] = "dropped"; q["dropped_because"] = f"within {DESIGNED_MIN_GAP} s of a more confident hit at {p['t']} s (references are sparse)"
    for p in hits:
        if p["decision"] != "sound" or p.get("peak_on"):
            continue
        w = _speaking(p["t"], obs["speech"])
        if w:
            gap = min((abs(p["t"] - w[0]), w[0]), (abs(p["t"] - w[1]), w[1]))
            if gap[0] <= 0.15:
                p["t"] = round(gap[1], 3); p["moved"] = "into the gap next to the word"
            else:
                p["level_adjust_db"] = -4; p["note"] = f"under the word '{w[2]}': 4 dB lower"
    return P


def select(P: list[dict], library: list[dict], place_terms: dict | None = None) -> None:
    """Pick a checked library file for each sound by role (rights.json records with used/rejected status). Real-world sounds
    must come from recordings; designed sounds may be synthesised later. If nothing fits, say what to find."""
    place_terms = place_terms or {}
    usable = [r for r in library if r.get("kind") == "sfx" and not r.get("rejected_reason")]
    role_map = {"boom": ["boom"], "hit": ["hit", "boom"], "swell": ["swell"], "creak": ["creak"], "foley": ["pen", "brush", "scribble"],
                "ambience": ["wind", "drip"], "tick": ["tick"], "chime": ["chime"]}
    for p in P:
        if p["decision"] != "sound":
            continue
        cands = [r for r in usable if r.get("role") in role_map.get(p["role"], [])]
        if p["role"] == "ambience" and p.get("place"):
            terms = place_terms.get(p["place"], str(p["place"]).lower().split())
            cands = [r for r in cands if any(k in r["title"].lower() for k in terms)]
        if p["role"] == "foley":
            want = {"ink being written": "pen", "a brush stroke": "brush", "a pen strike-through": "pen"}.get(p["what"], "pen")
            cands = [r for r in cands if r.get("role") == want] or cands
        if cands:
            p["file"] = cands[0]["file"]; p["source"] = cands[0].get("title")
        else:
            p["file"] = None
            p["todo"] = ("find a real recording of " if p["class"] == "real" else "find or synthesise a designed ") + p["role"]
        p["rel_db"] = REL_DB.get(p["role"], 20) - p.get("level_adjust_db", 0)        # 4 dB lower = 4 dB further under the voice


def table(P: list[dict]) -> str:
    rows = ["| t (s) | decision | what | why (rule) | evidence | confidence | sound |", "|---|---|---|---|---|---|---|"]
    for p in P:
        snd = p.get("source") or p.get("todo") or ("" if p["decision"] != "sound" else "?")
        why = p["rule"] + (f"; {p['dropped_because']}" if p.get("dropped_because") else "") + (f"; {p['moved']}" if p.get("moved") else "") + (f"; {p['note']}" if p.get("note") else "")
        rows.append(f"| {p['t']:.2f} | {p['decision']} | {p['what']} | {why} | {p['evidence']} | {p['confidence']} | {snd} |")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief"); ap.add_argument("--out"); ap.add_argument("--table")
    a = ap.parse_args()
    bp = Path(a.brief).resolve(); base = bp.parent; brief = load(bp)
    obs = observe(brief, base)
    P = constrain(reason(obs, brief), obs)
    lib = load(base / brief["library"])["records"] if brief.get("library") else []
    select(P, lib, brief.get("place_sounds"))
    out = Path(a.out) if a.out else base / "sound_proposals.json"
    out.write_text(json.dumps(P, indent=1), encoding="utf-8")
    md = table(P)
    (Path(a.table) if a.table else base / "SOUND_PROPOSALS.md").write_text("# Sound proposals\n\n" + md + "\n", encoding="utf-8")
    n = {k: sum(p["decision"] == k for p in P) for k in ("sound", "silence", "nothing", "dropped")}
    print(json.dumps(n), "->", out)


if __name__ == "__main__":
    main()
