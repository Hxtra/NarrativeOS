#!/usr/bin/env python3
"""Voiceover + footage: a finished voice track and b-roll clips become a cut in a Signature's measured style.

What friends_future's build_draft.py did by hand, as a pipeline (`signature.py plan` / `apply` on a Signature whose
pipeline kind is voiceover_broll):

1. **Words.** The voice is transcribed (talking_head.transcribe: phrase-by-phrase decode, MEASURED times). With a
   script, the script's spelling is put on the heard words (Whisper mishears); script words the model missed get
   times INTERPOLATED between their neighbours, and heard words that are not in the script are dropped. Both are
   reported.
2. **Shots.** Cuts go where the reference cut against its speech (the Signature's measured `placement`: at the onset
   of a sentence, a clause, a pause, or mid-phrase, and how far from that onset). A dynamic programme picks the cut
   points so the shot lengths follow the reference's measured distribution (median, p10, p90). With an opening
   lockup, the first shot holds the whole first sentence, as the reference's did.
3. **Footage.** One clip per shot, in order. Each clip's window skips its first second when it can (fades,
   settling); a clip shorter than its shot is an error, never looped or frozen. When the clip's shape differs from
   the canvas, the crop follows the measured subject (faces, person) when the vision models are installed;
   otherwise it is centred, and the report says so.
4. **Camera.** Each clip's own camera move is MEASURED (style_intel.visual.camera_motion). Push-ins and pans are
   added to static clips only, until the cut has the reference's measured fractions, at the reference's measured
   rates. Never on the lockup shot.
5. **Look.** A per-shot LUT toward the reference's measured colour (grade_match).
6. **Text.** The Signature's caption treatment over the voice's words; the hook sentence in the opening lockup when
   the Signature has one (its layout is OBSERVED, not measured: two blocks, function words small, key words large,
   text colour from the MEASURED brightness behind each block).
7. **Sound.** The voice as narration; music (optional) ducked under it; no sound effects when the reference
   measured none.

Everything is a proposal (`compile.status`), the clips' rights are never invented: a clip without a rights record
in assets.json is registered as simulation_approved with the rights UNVERIFIED.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from statistics import median
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import talking_head as th  # noqa: E402

PHRASE_PAUSE_SEC = 0.25        # a silence this long starts a new phrase even without punctuation
PLACEMENT_WINDOW_SEC = 0.4     # a cut this close to a word onset is "at" that onset
PHRASE_PREFER_SEC = 0.25       # ... and a phrase onset this close wins over a nearer mid-phrase word
DEFAULT_PLACEMENT = {"sentence": 0.6, "clause": 0.25, "pause": 0.1, "mid_phrase": 0.05}  # used only when not measured
DEFAULT_SHOTS = {"median": 4.0, "p10": 2.4, "p90": 5.5}
SKIP_HEAD_SEC = 1.0            # skip a clip's first second when it is long enough (fades, settling)
DEFAULT_PUSH_IN = 1.08         # used only when the reference's push-in rate was not measured
MIN_PUSH_CAP = 1.1             # an added push-in may always reach this, whatever the clip's resolution
LOCKUP = {"base": 0.078, "function": 0.48, "content": 1.0, "key": 1.45, "max_words": 25}
FUNCTION_WORDS = {"a", "an", "the", "and", "or", "but", "so", "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "into", "than",
                  "that", "this", "it", "its", "it's", "is", "are", "was", "were", "be", "been", "will", "would", "can", "could", "do", "does",
                  "you", "your", "you're", "i", "i'm", "we", "we're", "our", "they", "their", "they're", "he", "she", "his", "her", "my", "me",
                  "us", "them", "who", "what", "when", "how", "not", "no", "if", "then", "more", "ever", "just", "all", "have", "has"}


def norm(text: str) -> str:
    """A word as compared between script and transcript: "Twenty-two." and "22" are the same word."""
    parts = re.split(r"[-‐-–]", text.strip(".,!?;:\"'").lower())
    if len(parts) == 2 and all(th._tok(p).isdigit() for p in parts):
        tens, ones = (int(th._tok(p)) for p in parts)
        if tens % 10 == 0 and 0 < ones < 10:
            return str(tens + ones)
    return th._tok(text)


def _pair(a: list[str], b: list[str]) -> list[tuple[Optional[int], Optional[int]]]:
    """Edit-distance pairing of two short word lists (inside a block difflib could not match): substitution costs
    1 - similarity, a skip costs 0.6. Returns (i, j) pairs; None on one side is a skip."""
    INF = math.inf
    n, m = len(a), len(b)
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i < n:
                D[i + 1][j] = min(D[i + 1][j], D[i][j] + 0.6)
            if j < m:
                D[i][j + 1] = min(D[i][j + 1], D[i][j] + 0.6)
            if i < n and j < m:
                D[i + 1][j + 1] = min(D[i + 1][j + 1], D[i][j] + 1 - difflib.SequenceMatcher(a=a[i], b=b[j]).ratio())
    out, i, j = [], n, m
    while i or j:
        if i and j and abs(D[i][j] - (D[i - 1][j - 1] + 1 - difflib.SequenceMatcher(a=a[i - 1], b=b[j - 1]).ratio())) < 1e-9:
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and abs(D[i][j] - (D[i - 1][j] + 0.6)) < 1e-9:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    return out[::-1]


# ----------------------------------------------------------------------------------------------- words
def align_script(heard: list[dict], script_text: str) -> tuple[list[dict], dict]:
    """The script's words at the heard words' times. Returns (words, report)."""
    toks = script_text.split()
    a, b = [norm(w["text"]) for w in heard], [norm(t) for t in toks]
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "replace" and i2 - i1 != j2 - j1:  # pair inside the block: "22. um" heard, "twenty-two." written
            ci, cj = i1, j1
            for i, j in _pair(a[i1:i2], b[j1:j2]):
                di, dj = int(i is not None), int(j is not None)
                ops.append(("replace" if di and dj else "delete" if di else "insert", ci, ci + di, cj, cj + dj))
                ci, cj = ci + di, cj + dj
        else:
            ops.append((tag, i1, i2, j1, j2))
    out, dropped, interpolated, respelled = [], [], [], []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(j2 - j1):
                w = heard[i1 + k]
                out.append({"text": toks[j1 + k], "start": w["start"], "end": w["end"], "status": "MEASURED"})
                if w["text"].strip(".,!?;:\"'").lower() != toks[j1 + k].strip(".,!?;:\"'").lower():
                    respelled.append({"heard": w["text"], "script": toks[j1 + k], "at": w["start"]})
            continue
        if tag in ("delete", "replace"):
            dropped += [{"heard": w["text"], "at": w["start"]} for w in heard[i1:i2]]
        if tag in ("insert", "replace"):
            lo = out[-1]["end"] if out else 0.0
            hi = heard[i2]["start"] if i2 < len(heard) else (heard[-1]["end"] if heard else lo + 0.3 * (j2 - j1))
            if tag == "replace":
                lo, hi = heard[i1]["start"], heard[i2 - 1]["end"]
            step = max(0.0, hi - lo) / (j2 - j1)
            for k in range(j2 - j1):
                out.append({"text": toks[j1 + k], "start": round(lo + k * step, 3), "end": round(lo + (k + 1) * step, 3), "status": "INTERPOLATED"})
                interpolated.append(toks[j1 + k])
    return out, {"script_words": len(toks), "heard_words": len(heard), "respelled": respelled, "interpolated": interpolated,
                 "dropped_not_in_script": dropped}


def voice_words(voice: Path, cache: Path, script_text: Optional[str]) -> tuple[list[dict], dict]:
    tr = th.transcribe(voice, cache)
    heard = [{"text": w["text"], "start": round(w["start"], 3), "end": round(w["end"], 3), "status": "MEASURED"} for w in tr["words"]]
    report = {"model": tr["model"], "timing": tr.get("word_timing"), "heard_words": len(heard)}
    if not script_text:
        return heard, report | {"script": None}
    words, al = align_script(heard, script_text)
    return words, report | {"script": al}


def phrase_kind(words: list[dict], i: int) -> str:
    """What kind of onset word i is: the start of a sentence, a clause, a phrase after a pause, or mid-phrase."""
    if i == 0:
        return "sentence"
    prev = words[i - 1]["text"]
    if re.search(r"[.?!][\"')\]]*$", prev):
        return "sentence"
    if re.search(r"[,;:—-][\"')\]]*$", prev):
        return "clause"
    if words[i]["start"] - words[i - 1]["end"] >= PHRASE_PAUSE_SEC:
        return "pause"
    return "mid_phrase"


def cut_placement(cuts: list[float], words: list[dict]) -> dict:
    """Where a reference cuts against its speech (MEASURED from its cuts and transcript): the share of cuts at the
    onset of a sentence / clause / pause-phrase / mid-phrase word, and how far from that onset."""
    if not cuts or len(words) < 5:
        return {"status": "NOT_MEASURED", "reason": "needs cuts and a transcript"}
    onsets = [(i, w["start"], phrase_kind(words, i)) for i, w in enumerate(words)]
    rank = {"sentence": 0, "clause": 1, "pause": 2, "mid_phrase": 3}
    at, offsets, seen = {k: 0 for k in rank}, [], []
    silent = 0
    for c in cuts:
        near = [o for o in onsets if abs(o[1] - c) <= PLACEMENT_WINDOW_SEC]
        if not near:
            silent += 1
            seen.append({"cut": round(c, 3), "at": None})
            continue
        # A phrase onset wins within PHRASE_PREFER_SEC (about Whisper's word-timing error); beyond it, the nearest onset.
        close = [o for o in near if o[2] != "mid_phrase" and abs(o[1] - c) <= PHRASE_PREFER_SEC]
        i, t, kind = min(close, key=lambda o: (rank[o[2]], abs(o[1] - c))) if close else min(near, key=lambda o: abs(o[1] - c))
        at[kind] += 1
        offsets.append(c - t)
        seen.append({"cut": round(c, 3), "at": kind, "word": words[i]["text"], "offset": round(c - t, 3)})
    n = len(cuts) - silent
    return {"status": "MEASURED", "cuts": len(cuts), "cuts_without_speech": silent,
            "fractions": {k: round(v / n, 3) for k, v in at.items()} if n else {},
            "offset_sec": round(median(offsets), 3) if offsets else 0.0, "evidence": seen}


# ----------------------------------------------------------------------------------------------- shots
def boundaries(words: list[dict], placement: dict) -> list[dict]:
    """Every place a cut could go (before word i), with its kind, its time and its cost (-log of how often the
    reference cut at that kind of place)."""
    fr = placement.get("fractions") if placement.get("status") == "MEASURED" and placement.get("fractions") else DEFAULT_PLACEMENT
    off = float(placement.get("offset_sec") or 0.0) if placement.get("status") == "MEASURED" else 0.0
    out = []
    for i in range(1, len(words)):
        kind = phrase_kind(words, i)
        lo, hi = words[i - 1]["start"] + 0.1, max(words[i - 1]["start"] + 0.1, words[i]["end"] - 0.05)
        t = round(min(hi, max(lo, words[i]["start"] + off)), 3)
        out.append({"before": i, "t": t, "kind": kind, "cost": round(-math.log(max(fr.get(kind, 0.0), 0.02)), 3)})
    return out


def _length_cost(L: float, stats: dict) -> float:
    m, p10, p90 = stats["median"], stats["p10"], stats["p90"]
    sigma = max(0.15, math.log(max(p90, p10 + 1e-3) / max(p10, 1e-3)) / 2.563)
    if L < 0.6 * p10 or L > 2.0 * p90:
        return math.inf
    return (math.log(L / m) / sigma) ** 2


def plan_shots(words: list[dict], total: float, stats: dict, placement: dict, n_shots: Optional[int] = None,
               hook_end_index: Optional[int] = None) -> tuple[list[dict], dict]:
    """Cut points (a dynamic programme): shot lengths close to the reference's measured distribution, cuts at the
    kinds of places the reference cut. hook_end_index: the first cut goes right before this word (the first shot
    holds the hook sentence). Returns (shots, report)."""
    stats = {**DEFAULT_SHOTS, **{k: v for k, v in (stats or {}).items() if k in DEFAULT_SHOTS and v}}
    cands = boundaries(words, placement)
    pts = [{"t": 0.0, "cost": 0.0, "kind": "start", "before": 0}] + cands + [{"t": total, "cost": 0.0, "kind": "end", "before": len(words)}]
    first = None
    if hook_end_index is not None:
        first = next((j for j, p in enumerate(pts) if p.get("before") == hook_end_index), None)
    last = len(pts) - 1

    def solve(K: int) -> tuple[float, list[int]]:
        INF = math.inf
        best = [[INF] * len(pts) for _ in range(K + 1)]
        back = [[-1] * len(pts) for _ in range(K + 1)]
        best[0][0] = 0.0
        for k in range(1, K + 1):
            for j in range(1, len(pts)):
                if k == 1 and first is not None and j != first and not (K == 1 and j == last):
                    continue
                for i in range(j):
                    if best[k - 1][i] == INF:
                        continue
                    L = pts[j]["t"] - pts[i]["t"]
                    lc = 0.0 if (k == 1 and first is not None) else _length_cost(L, stats)
                    if L <= 0.3 or lc == INF:
                        continue
                    c = best[k - 1][i] + lc + pts[j]["cost"]
                    if c < best[k][j]:
                        best[k][j], back[k][j] = c, i
        if best[K][last] == INF:
            return INF, []
        path, j, k = [], last, K
        while k > 0:
            path.append(j)
            j, k = back[k][j], k - 1
        return best[K][last], sorted(path)

    if n_shots:
        cost, path = solve(n_shots)
        tried = {n_shots: cost}
    else:
        tried, path, cost = {}, [], math.inf
        lo, hi = max(1, int(total / (2 * stats["p90"]))), max(2, int(math.ceil(total / (0.6 * stats["p10"]))))
        for K in range(lo, min(hi, 60) + 1):
            c, p = solve(K)
            tried[K] = c
            if c < cost:
                cost, path = c, p
    if not path:
        raise ValueError(f"no cut fits {n_shots or 'any number of'} shots in {total:.1f}s with shot lengths near the reference's "
                         f"(median {stats['median']}s, p10 {stats['p10']}s, p90 {stats['p90']}s)")
    shots, t_prev, i_prev = [], 0.0, 0
    for n, j in enumerate(path, 1):
        p = pts[j]
        ws = words[i_prev:p["before"]]
        shots.append({"shot": n, "in": round(t_prev, 3), "out": round(p["t"], 3), "length": round(p["t"] - t_prev, 3),
                      "says": " ".join(w["text"] for w in ws), "cut_after": p["kind"] if p["kind"] != "end" else None})
        t_prev, i_prev = p["t"], p["before"]
    return shots, {"shots": len(shots), "cost": round(cost, 3), "target_lengths": stats,
                   "placement_used": placement.get("fractions") if placement.get("status") == "MEASURED" else {"DEFAULT": DEFAULT_PLACEMENT},
                   "offset_sec": placement.get("offset_sec", 0.0) if placement.get("status") == "MEASURED" else 0.0,
                   "lengths": [s["length"] for s in shots], "tried": {k: (round(v, 2) if v != math.inf else None) for k, v in tried.items()}}


def hook_end(words: list[dict], max_words: int = LOCKUP["max_words"]) -> Optional[int]:
    """Index of the word after the first sentence (None when it is longer than a lockup can hold)."""
    for i, w in enumerate(words[: max_words + 1]):
        if re.search(r"[.?!][\"')\]]*$", w["text"]):
            return i + 1 if i + 1 < len(words) else None
    return None


# ----------------------------------------------------------------------------------------------- footage
def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-show_entries",
                        "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    s = (d.get("streams") or [{}])[0]
    return {"duration": float(d["format"]["duration"]), "width": s.get("width"), "height": s.get("height")}


def source_window(duration: float, need: float, override: Optional[float] = None) -> float:
    if override is not None:
        if override + need > duration + 1e-3:
            raise ValueError(f"source_in {override}s + {need:.2f}s runs past the clip's end ({duration:.2f}s)")
        return round(override, 3)
    if need > duration + 1e-3:
        raise ValueError(f"the clip is {duration:.2f}s; the shot needs {need:.2f}s (never looped or frozen: pick a longer clip)")
    return round(max(0.0, min(SKIP_HEAD_SEC, duration - need - 0.5)), 3)


def crop_width(src_w: int, src_h: int, W: int, H: int) -> tuple[float, float]:
    """The crop window (fractions of the source) a cover fit to W x H shows."""
    if src_w / src_h > W / H:
        return (src_h * W / H) / src_w, 1.0
    return 1.0, (src_w * H / W) / src_h


def subject_framing(project: Path, path: Path, s: float, L: float, cw: float, ch: float) -> tuple[Optional[dict], str]:
    """Reframe keys that keep the measured subject in the crop, or (None, why a centre crop is used)."""
    if cw >= 0.999 and ch >= 0.999:
        return None, "same shape as the canvas: nothing to crop"
    ok, why = th.vision_ready()
    if not ok:
        return None, f"centre crop: subject NOT_MEASURED ({why})"
    import frame_awareness as fa
    a = fa.analyze(path, s, L, project / "analysis" / "frames", fps=2.0)
    centres = fa.subject_centres(a)
    if len(centres) < max(1, 0.3 * len(a["samples"])):
        return None, f"centre crop: no person or face in {len(a['samples']) - len(centres)}/{len(a['samples'])} sampled frames (MEASURED)"
    keys = fa.camera_keys(centres, cw, ch)
    keys = [[round(max(s, min(s + L, k[0])), 3), k[1], k[2]] for k in keys]
    if keys[0][0] > s:
        keys.insert(0, [s, keys[0][1], keys[0][2]])
    keys.append([round(s + L + 1, 3), keys[-1][1], keys[-1][2]])
    dedup = []
    for k in keys:
        if dedup and abs(dedup[-1][0] - k[0]) < 1e-6:
            dedup[-1] = k
        else:
            dedup.append(k)
    return {"keys": dedup, "basis": f"measured subject in {len(centres)}/{len(a['samples'])} sampled frames"}, "subject kept in the crop"


def clip_motion(path: Path, s: float, L: float) -> dict:
    from style_intel import visual
    m = visual.camera_motion(path, {"start": s, "duration": L})
    return {"class": visual.classify_motion(m), "measured": {k: round(v, 4) for k, v in (m or {}).items() if isinstance(v, float)}}


def spread(cands: list[int], n: int) -> list[int]:
    """n of the candidates, evenly spread (deterministic)."""
    if n <= 0 or not cands:
        return []
    n = min(n, len(cands))
    return sorted({cands[min(len(cands) - 1, int((j + 0.5) * len(cands) / n))] for j in range(n)})


def plan_camera(shots: list[dict], measured: list[str], camera: dict, protect: set) -> dict:
    """Which shots get an added push-in or pan, so the cut's camera fractions match the reference's (MEASURED).
    measured: each clip's own move. Moves are added to static clips only, never to protected shots."""
    fr = (camera or {}).get("fractions") or {}
    K = len(shots)
    want = {"push_in": round(fr.get("push_in", 0) * K), "pan": round(fr.get("pan", 0) * K)}
    have = {k: sum(1 for m in measured if m == k) for k in want}
    static = [i for i, m in enumerate(measured) if m == "static" and i not in protect]
    add_push = spread(static, max(0, want["push_in"] - have["push_in"]))
    rest = [i for i in static if i not in add_push]
    add_pan = spread(rest, max(0, want["pan"] - have["pan"]))
    return {"want": want, "already_in_clips": have, "push_in": add_push, "pan": add_pan}


def region_luma(path: Path, t: float, cx: float, aspect: tuple[int, int], box: tuple[float, float, float, float]) -> float:
    """Mean luma (0-255) of a region of the crop at source time t: what the text will sit on (MEASURED)."""
    import numpy as np
    import grade_match as gm
    rgb = gm.frames(path, t, t + 0.6, 2.0, aspect, cx)[0]
    gray = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    h, w = gray.shape
    x0, y0, x1, y1 = box
    return float(gray[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].mean())


def lockup_params(hook: list[dict], path: Path, t: float, cx: float, aspect: tuple[int, int], keys: set) -> tuple[dict, dict]:
    """The opening lockup for the hook sentence: two blocks (top-left, bottom-right) split at the longest pause near
    the middle; function words small, key words large (OBSERVED layout); text colour from the MEASURED brightness
    behind each block."""
    n = len(hook)
    mid = [i for i in range(max(1, int(0.3 * n)), max(2, int(0.7 * n) + 1)) if 0 < i < n]
    split = max(mid or [max(1, n // 2)], key=lambda i: (round(hook[i]["start"] - hook[i - 1]["end"], 2), -abs(i - n / 2)))
    # A block never ends on a function word: "will" goes with "decide", not after "twenty-two".
    while split > 1 and hook[split - 1]["text"].strip(".,!?;:\"'").lower() in FUNCTION_WORDS:
        split -= 1
    boxes = {"top-left": (0.05, 0.06, 0.62, 0.36), "bottom-right": (0.40, 0.64, 0.95, 0.92)}
    blocks, lumas = [], {}
    t0 = hook[0]["start"]
    for (anchor, box), ws in zip(boxes.items(), (hook[:split], hook[split:])):
        y = region_luma(path, t, cx, aspect, box)
        lumas[anchor] = round(y, 1)
        words = []
        for w in ws:
            bare = w["text"].strip(".,!?;:\"'").lower()
            size = LOCKUP["key"] if bare in keys else LOCKUP["function"] if bare in FUNCTION_WORDS else LOCKUP["content"]
            words.append({"text": bare, "start": round(w["start"] - t0, 3), "size": size, **({"cycle": True} if bare in keys else {})})
        blocks.append({"anchor": anchor, "color": "#111111" if y > 140 else "#ffffff", "maxWidth": 0.6, "words": words})
    return ({"blocks": blocks, "base": LOCKUP["base"]},
            {"split_before": hook[split]["text"], "luma_behind": lumas, "keys": sorted(keys),
             "status": "layout OBSERVED (the reference's opening, frame review); text colour MEASURED (luma behind each block)",
             **({} if keys else {"note": "no key words given (--hook-keys): none cycle faces"})})


# ----------------------------------------------------------------------------------------------- assets
def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(project: Path, p: Path) -> str:
    p = p.resolve()
    return p.relative_to(project.resolve()).as_posix() if project.resolve() in p.parents else str(p)


class Assets:
    """The project's assets.json, merged: an entry already there (same sha256) keeps its id and its rights record."""

    def __init__(self, project: Path):
        self.project = project
        self.path = project / "assets.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {"assets": []}
        self.by_sha = {a["sha256"]: a for a in self.data["assets"] if a.get("sha256")}
        self.added: list[str] = []

    def use(self, p: Path, media_class: str, prefix: str) -> dict:
        h = sha256(p)
        if h in self.by_sha:
            return self.by_sha[h]
        ids = {a["asset_id"] for a in self.data["assets"]}
        base = prefix + (re.sub(r"[^a-z0-9_]+", "_", p.stem.lower()).strip("_") or "media")
        aid = base if base not in ids else next(f"{base}_{k}" for k in range(2, 999) if f"{base}_{k}" not in ids)
        entry = {"asset_id": aid, "local_path": rel(self.project, p), "status": "simulation_approved", "media_class": media_class, "sha256": h,
                 "rights": {"status": "UNVERIFIED", "note": "registered by the voiceover pass; add the rights record before release"}}
        self.data["assets"].append(entry)
        self.by_sha[h] = entry
        self.added.append(aid)
        return entry

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------------------------- build
def plan(sig: dict, project: Path, voice: Path, script_text: Optional[str], n_shots: Optional[int] = None) -> dict:
    """The shot plan for a voice: where the cuts go and what each shot says (for sourcing footage)."""
    pl = sig["pipeline"]
    words, wrep = voice_words(voice, project / "analysis" / "transcripts", script_text)
    total = round(probe(voice)["duration"], 3)
    hook = hook_end(words) if (pl.get("opening") or {}).get("template") == "typographic_lockup" else None
    shots, srep = plan_shots(words, total, pl.get("measured", {}).get("shot_duration_sec") or {}, pl.get("placement") or {}, n_shots, hook)
    return {"voice": rel(project, voice), "duration": total, "signature": {"id": sig["id"], "version": sig["version"]},
            "hook_words": hook, "shots": shots, "planning": srep, "words": wrep}


def build(sig: dict, project: Path, voice: Path, clips: list[Path], script_text: Optional[str], shot_plan: Optional[dict] = None,
          music: Optional[Path] = None, hook_keys: Optional[set] = None) -> tuple[dict, dict]:
    """(timeline IR, report). clips: one per shot, in shot order."""
    import remotion_bridge as rb
    pl = sig["pipeline"]
    W, H = th.SHAPES[pl.get("aspect", "16:9")]
    aspect = tuple(int(x) for x in pl.get("aspect", "16:9").split(":"))
    words, wrep = voice_words(voice, project / "analysis" / "transcripts", script_text)
    total = round(probe(voice)["duration"], 3)
    has_lockup = (pl.get("opening") or {}).get("template") == "typographic_lockup"
    hook = hook_end(words) if has_lockup else None
    if shot_plan:
        shots, srep = shot_plan["shots"], {"from": "shot plan file", "shots": len(shot_plan["shots"])}
        if abs(shots[-1]["out"] - total) > 0.05:
            raise ValueError(f"the shot plan ends at {shots[-1]['out']}s but the voice is {total}s: plan again for this voice")
        if hook is not None and abs(shots[0]["out"] - next(b["t"] for b in boundaries(words, pl.get("placement") or {}) if b["before"] == hook)) > 0.5:
            hook = None  # the plan's first shot does not hold the hook sentence: no lockup
    else:
        shots, srep = plan_shots(words, total, pl.get("measured", {}).get("shot_duration_sec") or {}, pl.get("placement") or {}, len(clips), hook)
    if len(clips) != len(shots):
        raise ValueError(f"{len(shots)} shots need {len(shots)} clips, one per shot in order; got {len(clips)}")

    assets = Assets(project)
    vo = assets.use(voice, "voice", "vo_")
    items, shot_rep, motions = [], [], []
    for sh, clip in zip(shots, clips):
        meta = probe(clip)
        s = source_window(meta["duration"], sh["length"], sh.get("source_in"))
        a = assets.use(clip, "footage", "clip_")
        cw, ch = crop_width(meta["width"], meta["height"], W, H)
        it = {"id": f"S{sh['shot']:02d}", "asset_id": a["asset_id"], "timeline_in": sh["in"], "timeline_out": sh["out"], "source_in": s, "fit": "cover"}
        if sh.get("crop_centre"):
            cx, cy = sh["crop_centre"]
            it["reframe"] = {"keys": [[s, cx, cy], [round(s + sh["length"] + 1, 3), cx, cy]], "basis": "set in the shot plan"}
            framing = "crop centre set in the shot plan"
        else:
            rf, framing = subject_framing(project, clip, s, sh["length"], cw, ch)
            if rf:
                it["reframe"] = rf
        mo = clip_motion(clip, s, sh["length"])
        motions.append(mo["class"])
        items.append(it)
        shot_rep.append({"shot": it["id"], "clip": clip.name, "asset_id": a["asset_id"], "source_in": s, "length": sh["length"], "says": sh.get("says"),
                         "framing": framing, "clip_camera": mo, "_meta": meta, "_crop": (cw, ch)})

    # Camera: added moves only on static clips, toward the reference's measured fractions and rates.
    cam = pl.get("camera") or {}
    protect = {0} if hook is not None else set()
    cplan = plan_camera(shots, motions, cam, protect)
    push_rate = cam.get("push_in_zoom_per_sec")
    pan_rate = cam.get("pan_frac_per_sec")
    for i in cplan["push_in"]:
        L = shots[i]["length"]
        meta, (cw, ch) = shot_rep[i]["_meta"], shot_rep[i]["_crop"]
        # A digital push-in past the clip's spare resolution upscales it: cap at the headroom (at least MIN_PUSH_CAP).
        cap = round(min(1.3, max(MIN_PUSH_CAP, ch * meta["height"] / H, cw * meta["width"] / W)), 3)
        want = 1 + push_rate * L if push_rate else DEFAULT_PUSH_IN
        scale = round(min(cap, max(1.03, want)), 3)
        items[i]["motion"] = {"kind": "push_in", "scale_from": 1.0, "scale_to": scale}
        shot_rep[i]["added_camera"] = (f"push-in to {scale} ({'measured rate' if push_rate else 'default: rate NOT_MEASURED'}"
                                       + (f"; capped from {want:.3f} by the clip's resolution" if want > cap else "") + ")")
    for i in cplan["pan"]:
        cw, ch = shot_rep[i]["_crop"]
        L = shots[i]["length"]
        room = 1 - cw
        if room < 0.02 or not pan_rate:
            shot_rep[i]["added_camera"] = "pan wanted, not added: " + ("no room to pan in this crop" if room < 0.02 else "pan rate NOT_MEASURED")
            continue
        d = min(room, pan_rate * cw * L)
        keys = (items[i].get("reframe") or {}).get("keys")
        cx = keys[0][1] if keys else 0.5
        cx = min(1 - cw / 2 - d / 2, max(cw / 2 + d / 2, cx))
        direction = 1 if (1 - cw / 2 - cx) >= (cx - cw / 2) else -1
        s = items[i]["source_in"]
        items[i]["reframe"] = {"keys": [[s, round(cx - direction * d / 2, 4), 0.5], [round(s + L, 3), round(cx + direction * d / 2, 4), 0.5],
                                        [round(s + L + 1, 3), round(cx + direction * d / 2, 4), 0.5]],
                               "basis": f"pan added at the reference's measured rate ({pan_rate} of the frame per second)"}
        shot_rep[i]["added_camera"] = f"pan {'right' if direction > 0 else 'left'} {d:.3f} of the source width (measured rate)"

    # Look: per-shot LUTs toward the reference's measured colour.
    target = pl.get("grade_target") or {}
    grade_rep = {"status": "NOT_APPLIED", "reason": "the Signature has no measured colour with chroma (signature.py remeasure)"}
    if target.get("chroma") is not None:
        import grade_match as gm
        gshots = [{"id": it["id"], "path": c, "source_in": it["source_in"], "length": sh["length"],
                   "cx": ((it.get("reframe") or {}).get("keys") or [[0, 0.5, 0.5]])[0][1]} for it, c, sh in zip(items, clips, shots)]
        grade_rep = gm.shot_luts(gshots, target, project / "luts", aspect)
        for it in items:
            lut = assets.use(project / "luts" / f"{it['id']}.cube", "lut", "lut_")
            lut.update(status="approved", rights={"status": "RIGHTS_VERIFIED", "basis": "computed by grade_match.py from measurements"})
            it["grade"] = {"lut": lut["asset_id"]}

    # Text.
    tracks = [{"id": "v_main", "kind": "video", "items": items},
              {"id": "a_vo", "kind": "audio", "role": "narration", "items": [{"id": "VO", "asset_id": vo["asset_id"], "timeline_in": 0.0, "timeline_out": total, "source_in": 0.0}]}]
    lock_rep = {"status": "NOT_USED", "reason": "the Signature has no opening lockup" if not has_lockup else "the first sentence is too long for a lockup, or the plan's first shot does not hold it"}
    first_caption = 0
    remotion_ok = rb.available()[0]
    if remotion_ok and hook is not None:
        sh0 = shot_rep[0]
        cx = ((items[0].get("reframe") or {}).get("keys") or [[0, 0.5, 0.5]])[0][1]
        lp, lock_rep = lockup_params(words[:hook], clips[0], items[0]["source_in"] + min(2.0, sh0["length"] / 2), cx, aspect, hook_keys or set())
        tracks.append({"id": "lockup", "kind": "graphic", "items": [{"id": "HOOK", "template": "typographic_lockup", "timeline_in": 0.0,
                                                                     "timeline_out": shots[0]["out"], "params": lp}]})
        first_caption = hook
    caps = pl.get("captions") or {}
    cap_words = [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in words[first_caption:]]
    if remotion_ok:
        tracks.insert(2, {"id": "captions", "kind": "graphic", "items": [{"id": "CAPS", "template": "kinetic_captions", "timeline_in": 0.0, "timeline_out": total,
                                                                          "params": {"words": cap_words, **caps}}]})
    else:
        tracks.insert(2, {"id": "captions", "kind": "caption", "items": [
            {"id": f"c{n + 1:04d}", "timeline_in": w["start"], "timeline_out": w["end"], "text": w["text"]} for n, w in enumerate(cap_words)]})

    # Moves the Signature fires on what is said (transitions on cuts, punch-ins).
    fired = []
    live = [mv for mv in sig.get("moves", []) if mv.get("status") != "rejected" and mv["fires"].get("on") not in (None, "UNCLASSIFIED")]
    if live:
        import signature as sig_mod
        tw = []
        for n, w in enumerate(words):
            seg = next(k for k, sh in enumerate(shots) if w["start"] < sh["out"] or k == len(shots) - 1)
            tw.append({"text": w["text"], "t_in": w["start"], "t_out": w["end"], "index": n, "segment": seg})
        lines, cur = [], []
        for w in tw:
            cur.append(w)
            if re.search(r"[.?!]$", w["text"]):
                lines.append(cur)
                cur = []
        if cur:
            lines.append(cur)
        cfg = {**th.CONFIG, **{k: v for k, v in (pl.get("cut") or {}).items() if k in th.CONFIG}}
        fired, _ = sig_mod.fire_moves(live, th.find_moments(tw, lines), items, tw, cfg)

    # Sound.
    sound = pl.get("sound") or {}
    sfx_rep = ("none: the reference has no measurable sound effects" if sound.get("sfx_events") == 0
               else "none: sound effects are not placed by this pass yet")
    if music:
        m = assets.use(music, "music", "music_")
        tracks.append({"id": "a_music", "kind": "audio", "role": "music", "duck_under": "a_vo",
                       "duck": {"threshold": 0.03, "ratio": 6, "attack_ms": 30, "release_ms": 400},
                       "items": [{"id": "MUSIC", "asset_id": m["asset_id"], "timeline_in": 0.0, "timeline_out": total, "source_in": 0.0,
                                  "gain_db": -14, "fade_in": 0.3, "fade_out": 1.2}]})
    assets.save()

    ir = {"ir_version": "3.0", "canvas": {"width": W, "height": H, "fps": 30, "sample_rate": 48000, **({"platform": pl["platform"]} if pl.get("platform") else {})},
          "style": pl.get("style", "documentary_general"), "tracks": tracks, "mix": {"loudnorm": {"I": -14, "TP": -1.5, "LRA": 11}},
          "compile": {"made_by": "voiceover_broll.py", "status": "proposal: review the shots, framing and text before approval"}}
    for r in shot_rep:
        r.pop("_meta")
        r.pop("_crop")
    report = {"words": wrep, "shots": shot_rep, "planning": srep, "camera": cplan | {"rates": {"push_in_zoom_per_sec": push_rate, "pan_frac_per_sec": pan_rate}},
              "grade": {k: v for k, v in grade_rep.items() if k != "shots"} if isinstance(grade_rep, dict) else grade_rep,
              "lockup": lock_rep, "captions": {"words": len(cap_words), "params": caps, "renderer": "kinetic_captions" if remotion_ok else "plain burned-in words"},
              "fired": fired, "sound": {"sfx": sfx_rep, "music": music.name if music else None},
              "assets_added": assets.added,
              "notes": ["Shot boundaries, camera moves and the lockup are rules over measurements; the lockup's layout is OBSERVED, not measured.",
                        "Clips registered here have UNVERIFIED rights until a rights record is added to assets.json.",
                        "Check every clip by eye: real footage, not AI-generated, and the subject in frame after the crop."]}
    return ir, report
