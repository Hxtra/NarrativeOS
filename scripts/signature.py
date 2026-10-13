#!/usr/bin/env python3
"""Signatures: a saved style a reference edit taught, with the moves it uses, when each fires, the pipeline it
drives and the rules notes have taught it. Stored outside the repo (~/NarrativeOS-Signatures/<id>/, or
NARRATIVEOS_SIGNATURES), versioned on every change.

    python scripts/signature.py study REFERENCE.mp4 --id my_style [--label "..."] [--text] [--no-verify]
    python scripts/signature.py list | show ID
    python scripts/signature.py apply ID --project P --clips media/raw.mp4 [--script s.txt] [--force]
    python scripts/signature.py plan ID --project P --voice media/vo.wav [--script s.txt] [--shots N]   (voiceover_broll)
    python scripts/signature.py apply ID --project P --voice media/vo.wav --clips c1.mp4 ... [--plan shot_plan.json] [--music m.mp3]
    python scripts/signature.py remeasure ID --reference REF.mp4 [--grade-from S]
    python scripts/signature.py ship ID --project P [--approved]
    python scripts/signature.py promote ID | reject ID --reason "..." | archive ID
    python scripts/signature.py note ID --project P --text "..."          (Studio records these automatically)
    python scripts/signature.py promote-rule ID --notes N1 N2 --text "..." [--constraint '{"avoid": ["glitch_cut"]}']

Studying a reference measures, it does not guess:
- Style DNA (style_intel.dna): pacing, transitions, colour.
- The effect breakdown (style_intel.breakdown): every visual moment, its closest recipe, its measured layers.
- The transcript (faster-whisper) and its firing moments (talking_head.find_moments).
- Pairing: a visual moment and a speech moment within PAIR_SEC of each other. An effect that repeatedly lands on
  the same kind of moment becomes a move that FIRES on it, with support (how often) and precision (out of how many
  such moments). An effect with no consistent trigger is kept as UNCLASSIFIED with where it sat.
- How tight the reference cuts (the longest pauses it keeps inside a line) and how hard it punches in.
- Verification: each transition move is recreated with its recipe between two synthetic shots, broken down again,
  and compared with the reference moment's measured effects (verified / approximate / failed).

Status honesty: measurements are MEASURED by those tools; pairings, triggers and the camera of a move are INFERRED
and carry their counts. A new Signature is "experimental"; "proven" needs two shipped, approved edits.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]

PAIR_SEC = 0.4                 # a visual moment and a speech moment this close belong together
MIN_SUPPORT = 2                # a move needs at least this many paired occurrences to fire on a trigger
MIN_PRECISION = 0.5            # ... and to fire on at least half of that trigger's occurrences
TRIGGER_PRIORITY = ["NUMBER", "CONTRAST", "LIST", "QUESTION", "CUE", "NAME", "HOOK"]
STATUSES = {"experimental", "proven", "pending", "rejected", "archived"}
SCHEMA = "narrativeos.signature/1.0"


class SignatureError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root() -> Path:
    return Path(os.environ.get("NARRATIVEOS_SIGNATURES") or Path.home() / "NarrativeOS-Signatures").expanduser().resolve()


def sig_dir(sig_id: str) -> Path:
    if not sig_id.replace("_", "").replace("-", "").isalnum():
        raise SignatureError(f"signature id {sig_id!r} must be letters, digits, - or _")
    return root() / sig_id


def load(sig_id: str) -> dict:
    p = sig_dir(sig_id) / "signature.json"
    if not p.is_file():
        raise SignatureError(f"no signature {sig_id!r} in {root()}")
    return json.loads(p.read_text(encoding="utf-8"))


def save(sig: dict, reason: str) -> dict:
    """Write a new version (the old one stays in versions/)."""
    d = sig_dir(sig["id"])
    (d / "versions").mkdir(parents=True, exist_ok=True)
    sig["version"] = int(sig.get("version", 0)) + 1
    sig["updated_at"] = now()
    sig.setdefault("history", []).append({"version": sig["version"], "at": sig["updated_at"], "reason": reason})
    text = json.dumps(sig, indent=2, ensure_ascii=False) + "\n"
    (d / "versions" / f"v{sig['version']:03d}.json").write_text(text, encoding="utf-8")
    (d / "signature.json").write_text(text, encoding="utf-8")
    return sig


def sha(sig: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in sig.items() if k not in ("history", "updated_at")}, sort_keys=True).encode()).hexdigest()[:16]


def list_all() -> list[dict]:
    if not root().is_dir():
        return []
    out = []
    for d in sorted(root().iterdir()):
        if (d / "signature.json").is_file():
            s = json.loads((d / "signature.json").read_text(encoding="utf-8"))
            out.append({k: s.get(k) for k in ("id", "label", "status", "version")} | {"moves": len(s.get("moves", [])), "shipped": len(s.get("shipped", []))})
    return out


# ----------------------------------------------------------------------------------------------- study
def _speech_moments(reference: Path, work: Path) -> tuple[list[dict], list[dict], dict]:
    """Transcript words (reference time) and the firing moments in them."""
    import talking_head as th
    tr = th.transcribe(reference, work / "transcripts")
    lines = th.lines_of(tr["words"], "ref", dict(th.CONFIG))
    words, line_words = [], []
    for ln in lines:
        lw = []
        for w in ln["words"]:
            tw = {"text": w["text"], "t_in": w["start"], "t_out": w["end"], "index": len(words), "segment": 0}
            words.append(tw)
            lw.append(tw)
        line_words.append(lw)
    moments = th.find_moments(words, line_words)
    # Where a line starts is a trigger too: many edits cut or punch at the start of a sentence.
    for lw in line_words[1:]:
        moments.append({"type": "LINE_START", "text": lw[0]["text"], "start": lw[0]["t_in"], "end": lw[0]["t_out"], "word_index": [lw[0]["index"]],
                        "emphasis": [], "status": "MEASURED", "evidence": "first word of a line"})
    return words, moments, tr


def _effect_key(m: dict) -> Optional[dict]:
    """What a breakdown moment does, as a move: a registered transition recipe, or a punch-in (zoom without a cut)."""
    sug = m.get("suggestion") or {}
    types = {e["type"] for e in m.get("events", [])}
    if sug.get("recipe") and sug["recipe"] != "hard_cut":
        return {"key": f"transition:{sug['recipe']}", "does": {"transition": sug["recipe"]}, "why": sug.get("why")}
    if "zoom" in types and "hard_cut" not in types:
        z = next(e for e in m["events"] if e["type"] == "zoom")
        scale = (z.get("evidence") or {}).get("total_scale")
        return {"key": "punch_in", "does": {"punch_in": round(float(scale), 3) if scale else 1.15}, "why": "a scale change without a cut"}
    return None


def _measured_tightness(words: list[dict]) -> Optional[float]:
    """The longest pause the reference keeps inside a line (95th percentile of within-line gaps): how tight it cuts."""
    gaps = sorted(b["t_in"] - a["t_out"] for a, b in zip(words, words[1:]) if 0 < b["t_in"] - a["t_out"] < 0.6)
    return round(gaps[int(0.95 * (len(gaps) - 1))], 3) if len(gaps) >= 5 else None


def _caption_style(bd: dict) -> dict:
    """Caption treatment from measured on-screen text (only when the breakdown read text)."""
    typo = bd.get("typography") or {}
    if typo.get("status") != "MEASURED" or not typo.get("lines"):
        return {"status": "NOT_MEASURED", "reason": "on-screen text was not read (study with --text)"}
    lines = [ln for ln in typo["lines"] if not ln.get("cover_frame")]
    ys = [(ln["box_frac"][1] + ln["box_frac"][3]) / 2 for ln in lines if ln.get("box_frac")]
    heights = [ln["height_frac"] for ln in lines if ln.get("height_frac")]
    words = [len(str(ln.get("text", "")).split()) for ln in lines if ln.get("text")]
    cases = ["upper" if ln.get("uppercase") else "mixed" for ln in lines if "uppercase" in ln]
    params = {}
    if ys:
        y = median(ys)
        params["position"] = "upper" if y < 0.38 else "center" if y < 0.58 else "lower"
    if words:
        params["maxWords"] = max(1, min(5, int(round(median(words)))))
    if cases:
        params["uppercase"] = max(set(cases), key=cases.count) == "upper"
    if heights:
        params["fontScale"] = round(max(0.5, min(2.5, median(heights) / 0.088)), 2)
    return {"status": "MEASURED", "params": params, "lines_read": len(lines)}


def discover_moves(visual: list[dict], speech: list[dict]) -> list[dict]:
    """Pair every visual moment that does something with the speech moment it lands on (within PAIR_SEC). An
    effect that keeps landing on one kind of moment becomes a move that FIRES on it, with its support (how often)
    and precision (out of how many such moments); otherwise it stays UNCLASSIFIED with where it was seen."""
    counts: dict[str, int] = {}
    for sm in speech:
        counts[sm["type"]] = counts.get(sm["type"], 0) + 1
    effects: dict[str, dict] = {}
    for m in visual:
        ek = _effect_key(m)
        if not ek:
            continue
        e = effects.setdefault(ek["key"], {**ek, "occurrences": [], "triggers": {}})
        near = [sm for sm in speech if abs(sm["start"] - m["time"]) <= PAIR_SEC]
        near.sort(key=lambda sm: (TRIGGER_PRIORITY.index(sm["type"]) if sm["type"] in TRIGGER_PRIORITY else 99, abs(sm["start"] - m["time"])))
        trig = near[0] if near else None
        occ = {"t": m["time"], "moment": m["id"], "strip": m.get("strip"), "layers": sorted({e2["type"] for e2 in m["events"]} - {"hard_cut"}),
               "trigger": trig["type"] if trig else None, "said": trig["text"] if trig else None}
        e["occurrences"].append(occ)
        if trig:
            e["triggers"][trig["type"]] = e["triggers"].get(trig["type"], 0) + 1
    moves = []
    for n, (key, e) in enumerate(sorted(effects.items()), 1):
        best = max(e["triggers"].items(), key=lambda kv: (kv[1], -TRIGGER_PRIORITY.index(kv[0]) if kv[0] in TRIGGER_PRIORITY else -99), default=(None, 0))
        trig, support = best
        precision = support / counts[trig] if trig else 0.0
        fires = ({"on": trig, "support": support, "of": counts[trig], "precision": round(precision, 2), "status": "INFERRED"}
                 if trig and support >= MIN_SUPPORT and precision >= MIN_PRECISION else
                 {"on": "UNCLASSIFIED", "seen": len(e["occurrences"]), "status": "INFERRED",
                  "where": [f"{o['t']:.2f}s" + (f" ('{o['said']}', {o['trigger']})" if o["said"] else " (no speech moment)") for o in e["occurrences"]]})
        name = (e["does"].get("transition") or "punch in").replace("_", " ")
        moves.append({"id": f"MV{n:02d}", "name": f"{name} on {fires['on'].lower()}" if fires["on"] != "UNCLASSIFIED" else f"{name} (trigger unclear)",
                      "does": e["does"], "fires": fires, "why_seen": e.get("why"), "evidence": e["occurrences"],
                      "recreation": {"status": "untested"}, "status": "draft"})
    return moves


FACE_MIN_HEIGHT = 0.08        # a face this tall (fraction of the frame height) is someone on camera, not a passer-by
TALKING_HEAD_FACE_SHARE = 0.5  # a speech-led edit with a face in at least this share of its frames is a talking head
SPEECH_LED = 0.35              # speech covers at least this share of the edit


def edit_type(reference: Path, duration: float, coverage: float, work: Path) -> dict:
    """What kind of edit the reference is: talking_head (speech-led, a face on screen), voiceover_broll (speech-led,
    no face on screen) or documentary (not speech-led). Speech coverage and the face share are MEASURED; the kind
    is a rule over them. Without the vision models the face share is NOT_MEASURED and speech alone decides."""
    import talking_head as th
    out = {"speech_coverage": round(coverage, 3), "rule": f"speech >= {SPEECH_LED} and face share >= {TALKING_HEAD_FACE_SHARE} -> talking_head; "
                                                          f"speech >= {SPEECH_LED} -> voiceover_broll; otherwise documentary"}
    if coverage < SPEECH_LED:
        return out | {"kind": "documentary", "faces": {"status": "NOT_NEEDED"}}
    ok, why = th.vision_ready()
    if not ok:
        return out | {"kind": "talking_head", "faces": {"status": "NOT_MEASURED", "reason": why},
                      "warning": "speech alone decided: a voiceover over footage would be called talking_head"}
    import frame_awareness as fa
    a = fa.analyze(reference, 0.0, duration, work / "frames", fps=0.5)
    with_face = [s["t"] for s in a["samples"] if any(f["box"][3] >= FACE_MIN_HEIGHT for f in fa.trusted_faces(s))]
    share = len(with_face) / max(1, len(a["samples"]))
    return out | {"kind": "talking_head" if share >= TALKING_HEAD_FACE_SHARE else "voiceover_broll",
                  "faces": {"status": "MEASURED", "share": round(share, 3), "samples": len(a["samples"]), "fps": 0.5,
                            "min_face_height": FACE_MIN_HEIGHT, "seen_at": [round(t, 1) for t in with_face[:20]]}}


def measure_editing(reference: Path, work: Path, dna: dict, words: list[dict], aspect: Optional[tuple[int, int]] = None,
                    grade_from: float = 0.0) -> dict:
    """What a voiceover pass needs from the reference, all MEASURED: where it cuts against its speech, how its camera
    moves (fractions, push-in and pan rates), and its colour (the grade target)."""
    import grade_match as gm
    import voiceover_broll as vb
    ed = dna.get("editing") or {}
    cuts = ((ed.get("transition_vocabulary") or {}).get("hard_cut") or {}).get("times_sec") or []
    vwords = [{"text": w["text"], "start": w["t_in"], "end": w["t_out"]} for w in words]
    shots_file = work / "dna" / "shots.json"
    sampled = json.loads(shots_file.read_text(encoding="utf-8")).get("sampled", []) if shots_file.is_file() else []
    push = [s["motion"]["zoom_per_sec"] for s in sampled if s.get("motion_class") == "push_in" and s.get("motion")]
    pan = [s["motion"]["pan_px_per_sec"] / 480 for s in sampled if s.get("motion_class") == "pan" and s.get("motion")]
    cm = (dna.get("visual") or {}).get("camera_motion") or {}
    camera = {"status": "MEASURED" if cm.get("fractions") else "NOT_MEASURED", "fractions": cm.get("fractions"), "shots_measured": cm.get("shots_measured"),
              "push_in_zoom_per_sec": round(median(push), 4) if push else None, "pan_frac_per_sec": round(median(pan), 4) if pan else None,
              "basis": "style_intel.visual.camera_motion per sampled shot (pan rate as a fraction of the frame width per second)"}
    return {"placement": vb.cut_placement(cuts, vwords), "camera": camera,
            "grade_target": gm.measure_target(reference, grade_from, None, aspect) | ({"note": f"sampled from {grade_from}s (after the opening text)"} if grade_from else {})}


def study(reference: Path, sig_id: str, label: str = "", with_text: bool = False, verify: bool = True, pipeline_kind: Optional[str] = None) -> dict:
    from style_intel import breakdown as bd_mod
    from style_intel import dna as dna_mod
    from style_intel import profile as profile_mod
    d = sig_dir(sig_id)
    if (d / "signature.json").exists():
        raise SignatureError(f"signature {sig_id!r} exists; study under a new id (signatures are never overwritten)")
    work = d / "reference"
    work.mkdir(parents=True, exist_ok=True)
    dna = dna_mod.analyze(reference, work / "dna", with_speech=True)
    bd = bd_mod.analyze(reference, work / "breakdown", strips=True, with_speech=True, with_text=with_text)
    words, speech, tr = _speech_moments(reference, work)
    src = bd["source"]
    W, H = src.get("width") or 1920, src.get("height") or 1080
    aspect = next((k for k, (w, h) in {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5)}.items() if abs(W / H - w / h) < 0.02), "16:9")
    coverage = (dna.get("speech") or {}).get("speech_coverage") or (sum(w["t_out"] - w["t_in"] for w in words) / max(1.0, src["duration_sec"]))
    etype = edit_type(reference, float(src["duration_sec"]), coverage, work)
    kind = pipeline_kind or etype["kind"]
    extra = measure_editing(reference, work, dna, words)

    moves = discover_moves(bd["moments"], speech)
    profile = profile_mod.build(dna, sig_id, label or sig_id)
    (work / "style_profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    tight = _measured_tightness(words)
    zooms = [float(e["evidence"]["total_scale"]) for m in bd["moments"] for e in m["events"]
             if e["type"] == "zoom" and (e.get("evidence") or {}).get("total_scale")]
    captions = _caption_style(bd)
    sig = {
        "schema": SCHEMA, "id": sig_id, "label": label or sig_id, "status": "experimental", "version": 0, "created_at": now(),
        "reference": {"file": reference.name, "sha256": src.get("sha256"), "duration": src.get("duration_sec"), "size": [W, H],
                      "rights": "reference for analysis only; its footage is never used in an edit"},
        "pipeline": {"kind": kind, "aspect": aspect, "platform": "reels" if aspect == "9:16" else None, "style": "documentary_general",
                     "cut": {**({"max_gap_in_run_sec": max(0.15, min(0.6, tight))} if tight else {}),
                             **({"punch_in_scale": round(max(1.04, min(1.4, median(zooms))), 3)} if zooms else {})},
                     "captions": captions.get("params", {}),
                     **extra,
                     "measured": {"speech_coverage": round(coverage, 3), "edit_type": etype, "tightness_sec": tight, "zooms": len(zooms), "captions": captions,
                                  "pacing": (dna.get("editing") or {}).get("pacing"),
                                  "shot_duration_sec": (dna.get("editing") or {}).get("shot_duration_sec"),
                                  "transition_vocabulary": (dna.get("editing") or {}).get("transition_vocabulary")}},
        "moves": moves, "rules": [], "shipped": [],
        "notes": ["Moves, triggers and the pipeline are INFERRED from measurements of one reference; review the evidence strips.",
                  "The measured StyleProfile is saved in reference/style_profile.json; registering it as a renderer style is a separate decision."],
    }
    sig = save(sig, f"studied {reference.name}")
    if verify:
        sig = verify_moves(sig_id)
    return sig


# ----------------------------------------------------------------------------------------------- verify
def verify_moves(sig_id: str) -> dict:
    """Recreate each transition move between two synthetic shots, break the recreation down, and compare its
    measured effects with the reference moments'. Jaccard similarity of effect types: >= 0.6 verified, > 0
    approximate, 0 failed."""
    import subprocess
    import compile_timeline as ct
    from style_intel import breakdown as bd_mod
    sig = load(sig_id)
    lab = sig_dir(sig_id) / "verify"
    (lab / "media").mkdir(parents=True, exist_ok=True)
    for name, src in (("a", "testsrc2=s=640x360:r=30:d=3"), ("b", "smptehdbars=s=640x360:r=30:d=3")):
        if not (lab / "media" / f"{name}.mp4").is_file():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(lab / "media" / f"{name}.mp4")], check=True)
    (lab / "assets.json").write_text(json.dumps({"assets": [{"asset_id": "a", "local_path": "media/a.mp4", "status": "approved"},
                                                            {"asset_id": "b", "local_path": "media/b.mp4", "status": "approved"}]}))
    for mv in sig["moves"]:
        recipe = mv["does"].get("transition")
        if not recipe:
            mv["recreation"] = {"status": "not_applicable", "reason": "not a transition"}
            continue
        ir = {"ir_version": "3.0", "canvas": {"width": 640, "height": 360, "fps": 30, "sample_rate": 48000}, "style": sig["pipeline"].get("style", "documentary_general"),
              "tracks": [{"id": "v", "kind": "video", "items": [{"id": "A", "asset_id": "a", "timeline_in": 0, "timeline_out": 1.5},
                                                              {"id": "B", "asset_id": "b", "timeline_in": 1.5, "timeline_out": 3.0, "source_in": 0.5,
                                                               "transition_in": {"type": "recipe", "recipe": recipe}}]}]}
        try:
            out = lab / f"{recipe}.mp4"
            ct.compile_timeline(lab, ir, out)
            rec = bd_mod.analyze(out, lab / f"{recipe}_breakdown", strips=False, with_speech=False)
        except Exception as e:  # noqa: BLE001 - a recreation that cannot render is reported as failed
            mv["recreation"] = {"status": "failed", "reason": str(e)[:300]}
            continue
        near = [m for m in rec["moments"] if abs(m["time"] - 1.5) <= 0.5]
        got = sorted({e["type"] for m in near for e in m["events"]} - {"hard_cut", "gradual_transition"})
        want = sorted({t for o in mv["evidence"] for t in o["layers"]} - {"gradual_transition"})
        union = set(got) | set(want)
        sim = len(set(got) & set(want)) / len(union) if union else 1.0
        mv["recreation"] = {"status": "verified" if sim >= 0.6 else "approximate" if sim > 0 else "failed", "similarity": round(sim, 2),
                            "reference_effects": want, "recreated_effects": got, "method": "breakdown of a recreation between two synthetic shots"}
    return save(sig, "verified moves by recreation")


# ----------------------------------------------------------------------------------------------- apply
MIN_PIECE_SEC = 0.5           # a cut made for a move must leave both pieces at least this long


def split_at(items: list[dict], cap_words: list[dict], word: dict, cfg: dict) -> tuple[Optional[dict], str]:
    """Cut the segment holding `word` just before it, so a move that lands on a cut in the reference has a cut here
    too. The cut sits in the pause before the word (at most 0.12 s before it); the new piece takes the other framing,
    so the cut reads. Returns (new item, "") or (None, why not)."""
    k = word["segment"]
    it = items[k]
    prev = next((w for w in reversed(cap_words[:word["index"]]) if w["segment"] == k), None)
    s = round(max(word["t_in"] - 0.12, (prev["t_out"] + word["t_in"]) / 2 if prev else it["timeline_in"]), 3)
    if s - it["timeline_in"] < MIN_PIECE_SEC or it["timeline_out"] - s < MIN_PIECE_SEC:
        return None, f"the word is within {MIN_PIECE_SEC}s of the segment's edge"
    new = copy.deepcopy(it)
    new["id"] = next(f"{it['id']}{c}" for c in "bcdefghij" if all(x["id"] != f"{it['id']}{c}" for x in items))
    new["timeline_in"] = s
    new["source_in"] = round(it.get("source_in", 0.0) + (s - it["timeline_in"]), 3)
    new.pop("transition_in", None)
    if it.get("motion"):
        new.pop("motion")
    else:
        new["motion"] = {"kind": "push_in", "scale_from": cfg["punch_in_scale"], "scale_to": cfg["punch_in_scale"]}
    it["timeline_out"] = s
    items.insert(k + 1, new)
    for w in cap_words:
        if w["segment"] > k or (w["segment"] == k and w["t_in"] >= s):
            w["segment"] += 1
    return new, ""


def fire_moves(moves: list[dict], moments: list[dict], items: list[dict], cap_words: list[dict], cfg: dict) -> tuple[list[dict], set]:
    """Fire a Signature's moves on a cut's moments. A transition goes on the cut nearest the moment (within PAIR_SEC);
    when there is none, the segment is cut just before the moment's first word, as the reference was. A moment too
    close to a segment's edge to cut is reported as skipped, never forced."""
    fired, emphasis = [], set()
    live = [mv for mv in moves if mv.get("status") != "rejected" and mv["fires"].get("on") not in (None, "UNCLASSIFIED")]
    for m in moments:
        for mv in live:
            if mv["fires"]["on"] != m["type"]:
                continue
            does = mv["does"]
            why = f"{mv['name']} fires on {m['type']} (seen {mv['fires'].get('support')}/{mv['fires'].get('of')} in the reference)"
            if "transition" in does:
                cut = next((it for i, it in enumerate(items) if i and abs(it["timeline_in"] - m["start"]) <= PAIR_SEC), None)
                made = ""
                if cut is None:
                    cut, reason = split_at(items, cap_words, cap_words[m["word_index"][0]], cfg)
                    if cut is None:
                        fired.append({"moment": m["type"], "text": m["text"], "at": m["start"], "move": mv["id"], "result": "skipped",
                                      "reason": f"no cut at this moment and none can be made: {reason}"})
                        continue
                    made = " (cut made here)"
                cut["transition_in"] = {"type": "recipe", "recipe": does["transition"], "source": f"signature move {mv['id']}"}
                fired.append({"moment": m["type"], "text": m["text"], "at": m["start"], "move": mv["id"],
                              "result": f"{does['transition']} into {cut['id']}{made}", "why": why})
            elif "punch_in" in does:
                seg = items[cap_words[m["word_index"][0]]["segment"]]
                seg["motion"] = {"kind": "push_in", "scale_from": float(does["punch_in"]), "scale_to": float(does["punch_in"])}
                fired.append({"moment": m["type"], "text": m["text"], "at": m["start"], "move": mv["id"], "result": f"punch-in {does['punch_in']} on {seg['id']}", "why": why})
            elif does.get("caption_emphasis"):
                emphasis.update(m.get("emphasis") or m["word_index"])
                fired.append({"moment": m["type"], "text": m["text"], "at": m["start"], "move": mv["id"], "result": "caption emphasis", "why": why})
    return fired, emphasis


def apply_rules(sig: dict, ir: dict, fired: list[dict]) -> list[dict]:
    """Rules promoted from notes, as constraints on the built timeline. Returns what each rule changed."""
    changes = []
    main = next((t for t in ir["tracks"] if t["kind"] == "video"), {"items": []})
    for rule in sig.get("rules", []):
        c = rule.get("constraint") or {}
        for rid in c.get("avoid", []):
            for it in main["items"]:
                if (it.get("transition_in") or {}).get("recipe") == rid:
                    it.pop("transition_in")
                    changes.append({"rule": rule["id"], "change": f"removed {rid} into {it['id']}"})
        cap = c.get("max_transitions_per_minute")
        if cap is not None:
            recipe_cuts = [it for it in main["items"] if (it.get("transition_in") or {}).get("type") == "recipe"]
            minutes = max(1e-6, max((it["timeline_out"] for it in main["items"]), default=0) / 60)
            allowed = int(cap * minutes)
            for it in recipe_cuts[allowed:]:
                it.pop("transition_in")
                changes.append({"rule": rule["id"], "change": f"removed the transition into {it['id']} (over {cap} per minute)"})
        for k, v in (c.get("captions") or {}).items():
            for t in ir["tracks"]:
                for it in t["items"]:
                    if it.get("template") == "kinetic_captions":
                        it["params"][k] = v
                        changes.append({"rule": rule["id"], "change": f"captions {k} = {v}"})
    return changes


def remeasure(sig_id: str, reference: Path, grade_from: float = 0.0) -> dict:
    """Add the voiceover measurements (edit type with faces, cut placement against speech, camera rates, colour) to
    an existing Signature from its own reference (checked by sha256). Earlier fields stay; the kind changes only
    when the measurement says so, and the old value is kept in the history."""
    sig = load(sig_id)
    ref_sha = hashlib.sha256(reference.read_bytes()).hexdigest()
    if sig["reference"].get("sha256") and sig["reference"]["sha256"] != ref_sha:
        raise SignatureError(f"{reference.name} is not this Signature's reference (sha256 differs)")
    work = sig_dir(sig_id) / "reference"
    dna = json.loads((work / "dna" / "style_dna.json").read_text(encoding="utf-8"))
    words, _, _ = _speech_moments(reference, work)
    pl = sig["pipeline"]
    coverage = pl.get("measured", {}).get("speech_coverage") or 0.0
    etype = edit_type(reference, float(sig["reference"]["duration"]), coverage, work)
    aspect = tuple(int(x) for x in pl.get("aspect", "16:9").split(":"))
    pl.update(measure_editing(reference, work, dna, words, aspect, grade_from))
    pl.setdefault("measured", {})["edit_type"] = etype
    was = pl["kind"]
    pl["kind"] = etype["kind"]
    return save(sig, f"remeasured from the reference: edit type {etype['kind']} (was {was}), cut placement, camera rates, colour")


def apply(sig_id: str, project: Path, clips: list[Path], script_text: Optional[str] = None, voice: Optional[Path] = None,
          shot_plan: Optional[dict] = None, music: Optional[Path] = None, hook_keys: Optional[set] = None) -> tuple[dict, dict]:
    """Run the Signature's pipeline on raw footage (talking_head) or on a voice plus b-roll clips (voiceover_broll).
    Returns (timeline, report) and pins the project to this version."""
    import talking_head as th
    sig = load(sig_id)
    if sig["status"] in ("rejected", "archived"):
        raise SignatureError(f"signature {sig_id} is {sig['status']}")
    pl = sig["pipeline"]
    if pl["kind"] == "voiceover_broll":
        import voiceover_broll as vb
        if voice is None:
            raise SignatureError(f"{sig_id} drives a voiceover_broll pipeline: give the voice track (--voice) and one clip per shot")
        try:
            ir, report = vb.build(sig, project, voice, clips, script_text, shot_plan, music, hook_keys)
        except ValueError as e:
            raise SignatureError(str(e)) from e
    elif pl["kind"] == "talking_head":
        cfg = {**th.CONFIG, **{k: v for k, v in (pl.get("cut") or {}).items() if k in th.CONFIG}}
        ir, report = th.build(project, clips, script_text, pl.get("aspect", "9:16"), pl.get("platform"), pl.get("style", "documentary_general"), cfg,
                              moves=sig["moves"], caption_params=pl.get("captions") or None)
    else:
        raise SignatureError(f"{sig_id} drives a {pl['kind']} pipeline; only talking_head and voiceover_broll signatures can be applied so far")
    report["rules_applied"] = apply_rules(sig, ir, report["fired"])
    report["signature"] = {"id": sig["id"], "version": sig["version"], "sha": sha(sig), "status": sig["status"]}
    ir.setdefault("compile", {})["signature"] = report["signature"]
    (project / "signature_pin.json").write_text(json.dumps(report["signature"] | {"pinned_at": now()}, indent=2) + "\n", encoding="utf-8")
    return ir, report


# ----------------------------------------------------------------------------------------------- lifecycle and learning
def ship(sig_id: str, project: Path, approved: bool) -> dict:
    sig = load(sig_id)
    tl = project / "timeline_v3.json"
    entry = {"project": project.name, "at": now(), "approved": approved,
             "timeline_sha": hashlib.sha256(tl.read_bytes()).hexdigest()[:16] if tl.is_file() else None}
    sig.setdefault("shipped", []).append(entry)
    return save(sig, f"shipped {project.name}{' (approved)' if approved else ''}")


def set_status(sig_id: str, status: str, reason: str = "") -> dict:
    if status not in STATUSES:
        raise SignatureError(f"status must be one of {sorted(STATUSES)}")
    sig = load(sig_id)
    if status == "proven":
        approved = {s["project"] for s in sig.get("shipped", []) if s.get("approved")}
        if len(approved) < 2:
            raise SignatureError(f"proven needs two shipped, approved edits; {sig_id} has {len(approved)}")
    sig["status"] = status
    return save(sig, f"status -> {status}{': ' + reason if reason else ''}")


def note(sig_id: str, project: str, text: str, patch: Optional[dict] = None) -> dict:
    """A correction made while this Signature was in use (Studio records them). Notes are evidence, not rules."""
    d = sig_dir(sig_id)
    load(sig_id)
    entry = {"id": "N" + hashlib.sha256(f"{project}|{text}|{now()}".encode()).hexdigest()[:8], "project": project, "at": now(), "text": text,
             **({"operations": patch.get("operations")} if patch else {})}
    with (d / "notes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def notes(sig_id: str) -> list[dict]:
    p = sig_dir(sig_id) / "notes.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


def promote_rule(sig_id: str, note_ids: list[str], text: str, constraint: Optional[dict] = None) -> dict:
    """A rule only from notes seen in at least two projects (one video's taste is not yet a rule)."""
    sig = load(sig_id)
    found = [n for n in notes(sig_id) if n["id"] in note_ids]
    if len(found) != len(note_ids):
        raise SignatureError("unknown note id(s)")
    projects = sorted({n["project"] for n in found})
    if len(projects) < 2:
        raise SignatureError(f"a rule needs notes from at least two projects; these come from {projects}")
    rule = {"id": f"R{len(sig.get('rules', [])) + 1:02d}", "text": text, "constraint": constraint or {}, "from_notes": note_ids, "projects": projects, "at": now()}
    sig.setdefault("rules", []).append(rule)
    return save(sig, f"rule {rule['id']}: {text}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("study"); s.add_argument("reference", type=Path); s.add_argument("--id", required=True); s.add_argument("--label", default="")
    s.add_argument("--text", action="store_true"); s.add_argument("--no-verify", action="store_true"); s.add_argument("--kind", choices=["talking_head", "documentary"])
    sub.add_parser("list")
    sh = sub.add_parser("show"); sh.add_argument("id")
    a = sub.add_parser("apply"); a.add_argument("id"); a.add_argument("--project", type=Path, required=True); a.add_argument("--clips", nargs="+", required=True)
    a.add_argument("--script"); a.add_argument("--out", default="timeline_v3.json"); a.add_argument("--force", action="store_true")
    a.add_argument("--voice", help="voiceover_broll: the finished voice track"); a.add_argument("--plan", help="voiceover_broll: a shot plan from `plan`")
    a.add_argument("--music"); a.add_argument("--hook-keys", nargs="*", default=[], help="voiceover_broll: lockup words that cycle faces")
    pn = sub.add_parser("plan"); pn.add_argument("id"); pn.add_argument("--project", type=Path, required=True); pn.add_argument("--voice", required=True)
    pn.add_argument("--script"); pn.add_argument("--shots", type=int); pn.add_argument("--out", default="shot_plan.json"); pn.add_argument("--force", action="store_true")
    rm = sub.add_parser("remeasure"); rm.add_argument("id"); rm.add_argument("--reference", type=Path, required=True)
    rm.add_argument("--grade-from", type=float, default=0.0, help="measure colour from this second on (skip an opening text card)")
    sp = sub.add_parser("ship"); sp.add_argument("id"); sp.add_argument("--project", type=Path, required=True); sp.add_argument("--approved", action="store_true")
    for name in ("promote", "archive"):
        x = sub.add_parser(name); x.add_argument("id")
    r = sub.add_parser("reject"); r.add_argument("id"); r.add_argument("--reason", required=True)
    n = sub.add_parser("note"); n.add_argument("id"); n.add_argument("--project", required=True); n.add_argument("--text", required=True)
    pr = sub.add_parser("promote-rule"); pr.add_argument("id"); pr.add_argument("--notes", nargs="+", required=True); pr.add_argument("--text", required=True)
    pr.add_argument("--constraint", type=json.loads)
    args = ap.parse_args()
    try:
        if args.cmd == "study":
            out = study(args.reference.resolve(), args.id, args.label, args.text, not args.no_verify, args.kind)
            out = {k: out[k] for k in ("id", "status", "version", "pipeline")} | {"moves": [{k: m[k] for k in ("id", "name", "fires", "recreation")} for m in out["moves"]]}
        elif args.cmd == "list":
            out = list_all()
        elif args.cmd == "show":
            out = load(args.id)
        elif args.cmd == "apply":
            project = args.project.resolve()
            dest = project / args.out
            if dest.exists() and not args.force:
                raise SignatureError(f"{dest.name} exists (it may hold edits); use --force or --out another file")
            at = lambda c: (Path(c) if Path(c).is_absolute() else project / c).resolve()  # noqa: E731
            clips = [at(c) for c in args.clips]
            ir, report = apply(args.id, project, clips, at(args.script).read_text(encoding="utf-8") if args.script else None,
                               voice=at(args.voice) if args.voice else None,
                               shot_plan=json.loads(at(args.plan).read_text(encoding="utf-8")) if args.plan else None,
                               music=at(args.music) if args.music else None, hook_keys={k.lower() for k in args.hook_keys})
            if not args.voice:
                import talking_head as th
                th.register_clips(project, clips, approve=False)
            dest.write_text(json.dumps(ir, indent=2) + "\n", encoding="utf-8")
            (project / "analysis").mkdir(exist_ok=True)
            (project / "analysis" / "signature_apply.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            out = {"timeline": dest.name, "signature": report["signature"], "fired": report["fired"], "rules_applied": report["rules_applied"]}
        elif args.cmd == "plan":
            import voiceover_broll as vb
            project = args.project.resolve()
            dest = project / args.out
            if dest.exists() and not args.force:
                raise SignatureError(f"{dest.name} exists; use --force or --out another file")
            sig = load(args.id)
            if sig["pipeline"]["kind"] != "voiceover_broll":
                raise SignatureError(f"{args.id} drives a {sig['pipeline']['kind']} pipeline; plan is for voiceover_broll")
            voice = (Path(args.voice) if Path(args.voice).is_absolute() else project / args.voice).resolve()
            try:
                script = (Path(args.script) if Path(args.script).is_absolute() else project / args.script) if args.script else None
                p = vb.plan(sig, project, voice, script.read_text(encoding="utf-8") if script else None, args.shots)
            except ValueError as e:
                raise SignatureError(str(e)) from e
            dest.write_text(json.dumps(p, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            out = {"plan": dest.name, "shots": [{k: s[k] for k in ("shot", "in", "out", "length", "says")} for s in p["shots"]], "planning": p["planning"]}
        elif args.cmd == "remeasure":
            s = remeasure(args.id, args.reference.resolve(), args.grade_from)
            out = {k: s["pipeline"].get(k) for k in ("kind", "placement", "camera", "grade_target")} | {"edit_type": s["pipeline"]["measured"]["edit_type"], "version": s["version"]}
        elif args.cmd == "ship":
            out = ship(args.id, args.project.resolve(), args.approved)["shipped"][-1]
        elif args.cmd == "promote":
            out = {"status": set_status(args.id, "proven")["status"]}
        elif args.cmd == "archive":
            out = {"status": set_status(args.id, "archived")["status"]}
        elif args.cmd == "reject":
            out = {"status": set_status(args.id, "rejected", args.reason)["status"]}
        elif args.cmd == "note":
            out = note(args.id, args.project, args.text)
        else:
            out = promote_rule(args.id, args.notes, args.text, args.constraint)["rules"][-1]
    except SignatureError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
