#!/usr/bin/env python3
"""Talking-head core: raw takes in, a tight cut with word-by-word captions out.

    python scripts/talking_head.py --project P --clips media/raw1.mp4 [media/raw2.mp4 ...] [--script script.txt]
        [--aspect 9:16] [--platform reels] [--style documentary_general] [--out timeline_v3.json] [--force]

1. Transcribe every clip with word timings (faster-whisper, cached per file in analysis/transcripts/).
2. Split speech into lines at pauses and sentence ends.
3. Group the attempts at the same line: matched to the script when one is given, otherwise by similarity, with a
   false start (a line abandoned and started again) recognised as the prefix of a later attempt.
4. Score every take and keep the best one per line. Every keep and drop is recorded with its reasons.
5. Cut the kept takes tight: hesitation sounds and immediate word repeats come out, long pauses become jump cuts,
   and alternate segments punch in so the jump cuts read as intentional.
6. Find the firing moments in what is said (hook, numbers, contrasts, lists, questions, spoken cues, names) and fire
   the default moves: emphasis in the captions and a stronger punch-in. Signatures will replace these defaults.
7. Write the IR 3.0 timeline (main track with the clips' own sound, a kinetic-captions graphic) and a report.

Status honesty: transcript words and timings are MEASURED by the model; take choice, lines and moments are INFERRED
from them by the rules here and say so in the report. Nothing is approved: the clips are registered for preview
(simulation_approved) unless --approve-own-footage is given.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from perception import FILLERS  # noqa: E402

CAPTION_BANDS = {"upper": (0.0, 0.38), "center": (0.38, 0.58), "lower": (0.58, 1.0)}  # output-frame height a caption position covers

CONFIG = {
    "line_pause_sec": 0.6,         # a pause this long ends a line when the speaker starts over after it
    "mid_sentence_pause_max_sec": 2.0,  # ... or when it is longer than this, whatever follows
    "sentence_pause_sec": 0.0,     # a sentence end (. ? !) ends a line at any pause: retakes are usually per sentence
    "max_gap_in_run_sec": 0.35,    # inside a kept take, a longer silence becomes a jump cut
    "pad_in_sec": 0.08,            # breathing room before the first word of a segment
    "pad_out_sec": 0.14,           # and after its last word
    "similar_ratio": 0.6,          # attempts at the same line (no script)
    "script_match_ratio": 0.5,     # a line matches a script sentence at least this well
    "group_window": 4,             # how many later lines can be another attempt of this one
    "remove_fillers": True,
    "punch_in_scale": 1.12,        # alternate segments, to hide jump cuts
    "emphasis_scale": 1.2,         # segments holding a number or contrast
}
SHAPES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "fifteen",
                "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion",
                "half", "double", "triple", "percent", "dozen"}
ORDINALS = {"first", "second", "third", "fourth", "fifth", "firstly", "secondly", "thirdly", "finally", "lastly"}
CUES = ["look at this", "watch this", "check this out", "right here", "like this", "track it", "see this", "over here", "this one"]
DISFLUENCY_PROMPT = "Um, uh, so, I mean, like, you know, uh."  # makes Whisper write hesitations instead of dropping them


def norm(t: str) -> str:
    return "".join(c for c in t.lower() if c.isalnum() or c == "'")


# ----------------------------------------------------------------------------------------------- transcription
def _identity(path: Path) -> str:
    st = path.stat()
    return hashlib.sha256(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def _energy_db(path: Path, hop: float = 0.01) -> np.ndarray:
    """RMS level per 10 ms of the clip's audio, in dB (MEASURED)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    k = int(16000 * hop)
    frames = a[: len(a) // k * k].reshape(-1, k) if len(a) >= k else np.zeros((1, k), np.float32)
    return 20 * np.log10(np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)) + 1e-5)


def refine_words(words: list[dict], db: np.ndarray, hop: float = 0.01, min_trim: float = 0.08, min_pause: float = 0.15) -> list[dict]:
    """Whisper puts a pause inside the word next to it, often with the neighbour's tail: "three" after a 0.7 s pause
    was given 0.60-1.66 s, starting at the end of "posted". Trim each word to its own sound: the voiced 10 ms frames
    (a threshold between the clip's noise floor and its speech level), split at silences of min_pause or more, and
    the longest voiced run kept (a neighbour's tail is the short one). Words only shrink, by at least min_trim, and
    keep at least 0.1 s. Model times are kept in model_times."""
    if not len(db) or not words:
        return words
    floor, speech = float(np.percentile(db, 10)), float(np.percentile(db, 95))
    if speech - floor < 12:  # no clear speech/silence contrast (noisy room, music bed): leave the model's times
        return words
    voiced = db >= floor + 0.3 * (speech - floor)
    gap = int(round(min_pause / hop))
    out = []
    for w in words:
        a, b = int(w["start"] / hop), min(len(voiced), int(np.ceil(w["end"] / hop)))
        idx = np.flatnonzero(voiced[a:b])
        start, end = float(w["start"]), float(w["end"])
        if len(idx):
            runs, r0 = [], idx[0]
            for x, y in zip(idx, idx[1:]):
                if y - x > gap:
                    runs.append((r0, x))
                    r0 = y
            runs.append((r0, idx[-1]))
            i0, i1 = max(runs, key=lambda r: r[1] - r[0])
            s2, e2 = float((a + i0) * hop - 0.02), float((a + i1 + 1) * hop + 0.03)
            if s2 - start >= min_trim and end - s2 >= 0.1:
                start = s2
            if end - e2 >= min_trim and e2 - start >= 0.1:
                end = e2
        out.append(w | ({"start": round(start, 3), "end": round(end, 3), "model_times": w.get("model_times", [w["start"], w["end"]])}
                        if (start, end) != (w["start"], w["end"]) else {}))
    return out


DETERMINERS = {"the", "this", "that", "these", "those", "which", "each", "every", "any", "no", "another", "my", "your", "our", "their"}
DIGITS_OF = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                                 "fifteen sixteen seventeen eighteen nineteen twenty".split())}
DIGITS_OF |= {w: str(10 * i) for i, w in enumerate("thirty forty fifty sixty seventy eighty ninety".split(), 3)}


def _tok(text: str) -> str:
    n = norm(text).lstrip("$")
    return DIGITS_OF.get(n, n)


def phrases_of(db: np.ndarray, hop: float = 0.01, min_pause: float = 0.3) -> Optional[list[list[float]]]:
    """Stretches of speech between measured pauses of min_pause or more. None when the audio has no clear
    speech/silence contrast (a noisy room or a music bed), where pauses cannot be measured this way."""
    if not len(db):
        return None
    floor, speech = float(np.percentile(db, 10)), float(np.percentile(db, 95))
    if speech - floor < 12:
        return None
    idx = np.flatnonzero(db >= floor + 0.3 * (speech - floor))
    if not len(idx):
        return None
    runs, r0 = [], idx[0]
    gap = int(round(min_pause / hop))
    for x, y in zip(idx, idx[1:]):
        if y - x > gap:
            runs.append([round(r0 * hop, 3), round((x + 1) * hop, 3)])
            r0 = y
    runs.append([round(r0 * hop, 3), round((idx[-1] + 1) * hop, 3)])
    return runs


def _words_of(segs) -> list[dict]:
    out = []
    for seg in segs:
        for w in seg.words or []:
            text = w.word.strip()
            if text and w.end > w.start:
                out.append({"text": text, "start": round(float(w.start), 3), "end": round(float(w.end), 3), "prob": round(float(w.probability), 3)})
    return out


def align_to_phrases(words: list[dict], phrase_words: list[dict]) -> list[dict]:
    """Times from the per-phrase decode, text from the whole-take decode. Decoding the whole take, the model often
    puts a word that follows a pause before it ("I posted three | videos", when "three" was said after the pause);
    decoded phrase by phrase it cannot cross a pause, but it adds a full stop at every phrase end and the odd stray
    word. So words are matched in order (numbers as digits), matched words take the phrase times, and unmatched
    words keep their own times if they fit between their matched neighbours, else share that interval evenly."""
    a, b = [_tok(w["text"]) for w in words], [_tok(w["text"]) for w in phrase_words]
    out, matched = [dict(w) for w in words], [False] * len(words)
    for blk in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            w, pw = out[blk.a + k], phrase_words[blk.b + k]
            if (pw["start"], pw["end"]) != (w["start"], w["end"]):
                w["model_times"] = [w["start"], w["end"]]
                w["start"], w["end"] = pw["start"], pw["end"]
            matched[blk.a + k] = True
    i = 0
    while i < len(out):
        if matched[i]:
            i += 1
            continue
        j = i
        while j < len(out) and not matched[j]:
            j += 1
        lo = out[i - 1]["end"] if i else 0.0
        hi = out[j]["start"] if j < len(out) else max(lo, max(w["end"] for w in out[i:j]))
        run = out[i:j]
        if not all(lo <= w["start"] and w["end"] <= hi for w in run):
            step = max(hi - lo, 0.1 * len(run)) / len(run)
            for k, w in enumerate(run):
                w["model_times"] = [w["start"], w["end"]]
                w["start"], w["end"] = round(lo + k * step, 3), round(lo + (k + 1) * step, 3)
        i = j
    return out


def transcribe(path: Path, cache_dir: Path, model_size: str = "base") -> dict:
    """Words with times (MEASURED by the model), cached per file content. The take is decoded whole (text and
    punctuation) and phrase by phrase between measured pauses (timing: align_to_phrases); word edges are then
    trimmed to the measured audio (refine_words). Without a clear speech/silence contrast, the whole-take times are
    used and the result says so."""
    cache = cache_dir / f"{path.stem}-{_identity(path)}-{model_size}-p1.json"
    if cache.is_file():
        out = json.loads(cache.read_text(encoding="utf-8"))
    else:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segs, info = model.transcribe(str(path), word_timestamps=True, vad_filter=False, condition_on_previous_text=False,
                                      initial_prompt=DISFLUENCY_PROMPT)
        words = _words_of(segs)
        phrases = phrases_of(_energy_db(path))
        phrase_words = None
        if phrases and len(phrases) > 1:
            clips = [x for a, b in phrases for x in (max(0.0, a - 0.12), b + 0.15)]
            psegs, _ = model.transcribe(str(path), word_timestamps=True, condition_on_previous_text=False, initial_prompt=DISFLUENCY_PROMPT,
                                        clip_timestamps=clips)
            phrase_words = _words_of(psegs)
        out = {"file": path.name, "model": f"faster-whisper {model_size}", "language": info.language, "duration": round(info.duration, 3),
               "words": words, "phrases": phrases, "phrase_words": phrase_words, "status": "MEASURED"}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, indent=1), encoding="utf-8")
    words = align_to_phrases(out["words"], out["phrase_words"]) if out.get("phrase_words") else out["words"]
    timing = ("decoded phrase by phrase between measured pauses; edges trimmed to the measured audio" if out.get("phrase_words")
              else "whole-take decode (no measurable pauses); edges trimmed to the measured audio")
    return {k: v for k, v in out.items() if k != "phrase_words"} | {"words": refine_words(words, _energy_db(path)), "word_timing": timing}


# ----------------------------------------------------------------------------------------------- lines and takes
def _restarts(cur: list[dict], ahead: list[dict]) -> bool:
    """After a pause: is the speaker starting over (a hesitation, or the same words again)?"""
    if not ahead or norm(ahead[0]["text"]) in FILLERS:
        return True
    x = [t for t in (norm(w["text"]) for w in cur) if t and t not in FILLERS]
    if not x:  # only hesitation so far: what follows is a fresh start
        return True
    y = [t for t in (norm(w["text"]) for w in ahead) if t and t not in FILLERS][:len(x)]
    return _ratio(x, y) >= 0.8 or y[:1] == x[:1]


def lines_of(words: list[dict], clip: str, cfg: dict) -> list[dict]:
    """Lines: split at a sentence end, and at a pause of line_pause_sec or more where the speaker starts over (or
    the pause is longer than mid_sentence_pause_max_sec). A pause in the middle of a sentence ("and after ...
    twelve weeks") stays inside its line, so it is never mistaken for a separate attempt; the tight cut removes it."""
    lines, cur = [], []
    for i, w in enumerate(words):
        if cur:
            gap = w["start"] - cur[-1]["end"]
            sentence_end = re.search(r"[.?!]$", cur[-1]["text"]) and gap >= cfg["sentence_pause_sec"]
            pause = gap >= cfg["line_pause_sec"] and (gap > cfg["mid_sentence_pause_max_sec"] or _restarts(cur, words[i:i + 8]))
            if sentence_end or pause:
                lines.append(cur)
                cur = []
        cur.append({**w, "clip": clip})
    if cur:
        lines.append(cur)
    out = []
    for n, ws in enumerate(lines):
        toks = [norm(w["text"]) for w in ws]
        out.append({"id": f"{clip}#{n + 1}", "clip": clip, "words": ws, "start": ws[0]["start"], "end": ws[-1]["end"],
                    "text": " ".join(w["text"] for w in ws), "tokens": [t for t in toks if t], "content": [t for t in toks if t and t not in FILLERS]})
    return out


def _ratio(a: list[str], b: list[str]) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def is_false_start(a: dict, b: dict) -> bool:
    """a was abandoned and b starts the same words again (and goes further)."""
    x, y = a["content"], b["content"]
    return 1 <= len(x) < len(y) and _ratio(x, y[:len(x)]) >= 0.8


def script_lines(text: str) -> list[dict]:
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+|\n+", text) if p.strip()]
    return [{"index": i, "text": p, "content": [t for t in (norm(x) for x in p.split()) if t and t not in FILLERS]} for i, p in enumerate(parts)]


def group_takes(lines: list[dict], script: Optional[list[dict]], cfg: dict) -> tuple[list[list[dict]], list[dict]]:
    """Attempts at the same line, in order. Returns (groups, off_script lines)."""
    if script:
        by_line: dict[int, list[dict]] = {}
        off = []
        for ln in lines:
            best = max(((_ratio(ln["content"], s["content"]), s["index"]) for s in script), default=(0.0, -1))
            # A false start covers only the beginning of a sentence: match it against that beginning too.
            pre = max(((_ratio(ln["content"], s["content"][:len(ln["content"])]), s["index"]) for s in script if len(ln["content"]) >= 2),
                      default=(0.0, -1))
            score, idx = best if best[0] >= cfg["script_match_ratio"] else (pre if pre[0] >= 0.85 else best)
            if score >= cfg["script_match_ratio"] or (idx == pre[1] and pre[0] >= 0.85):
                ln["script_line"] = idx
                by_line.setdefault(idx, []).append(ln)
            else:
                off.append(ln)
        return [by_line[i] for i in sorted(by_line)], off
    parent = list(range(len(lines)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(lines):
        for j in range(i + 1, min(len(lines), i + 1 + cfg["group_window"])):
            b = lines[j]
            if _ratio(a["content"], b["content"]) >= cfg["similar_ratio"] or is_false_start(a, b):
                parent[find(j)] = find(i)
    groups: dict[int, list[dict]] = {}
    for i, ln in enumerate(lines):
        groups.setdefault(find(i), []).append(ln)
    return list(groups.values()), []


def score_take(take: dict, group: list[dict], ref: Optional[list[str]]) -> dict:
    toks, content, ws = take["tokens"], take["content"], take["words"]
    longest = max(len(t["content"]) for t in group) or 1
    order = group.index(take)
    later = group[order + 1:]
    false_start = any(is_false_start(take, b) for b in later)
    finished = bool(re.search(r"[.?!]$", take["words"][-1]["text"])) and not false_start
    # Against a script, completeness is how much of the scripted line was said. Without one, a take that ends its
    # sentence is complete; only a take cut short is measured against the longest attempt. Between complete takes the
    # later one wins (a line is usually redone to improve it).
    completeness = _ratio(content, ref) if ref else (1.0 if finished else len(content) / longest)
    fillers = sum(1 for t in toks if t in FILLERS)
    repeats = sum(1 for x, y in zip(toks, toks[1:]) if x == y and x not in FILLERS)
    long_pauses = sum(1 for x, y in zip(ws, ws[1:]) if y["start"] - x["end"] >= 0.8)
    prob = sum(w["prob"] for w in ws) / len(ws)
    recency = order / (len(group) - 1) if len(group) > 1 else 1.0
    score = completeness + 0.3 * prob - 0.12 * fillers - 0.08 * repeats - 0.06 * long_pauses + 0.08 * recency - 0.6 * false_start
    return {"score": round(score, 4), "completeness": round(completeness, 3), "fillers": fillers, "repeats": repeats,
            "long_pauses": long_pauses, "confidence": round(prob, 3), "false_start": false_start}


def _why_dropped(s: dict, best: dict) -> str:
    reasons = []
    if s["false_start"]:
        reasons.append("false start: a later take finishes the line")
    if s["completeness"] + 0.05 < best["completeness"]:
        reasons.append(f"less complete ({s['completeness']:.0%} vs {best['completeness']:.0%})")
    if s["fillers"] > best["fillers"]:
        reasons.append(f"more hesitations ({s['fillers']} vs {best['fillers']})")
    if s["repeats"] > best["repeats"]:
        reasons.append(f"stumbles ({s['repeats']} repeated words)")
    if s["confidence"] + 0.05 < best["confidence"]:
        reasons.append("less clearly spoken (lower recognition confidence)")
    return "; ".join(reasons) or "an equally good later take was kept (later takes usually land better)"


def choose_takes(groups: list[list[dict]], script: Optional[list[dict]]) -> list[dict]:
    decisions = []
    for g in groups:
        ref = script[g[0]["script_line"]]["content"] if script and "script_line" in g[0] else None
        scored = [(score_take(t, g, ref), t) for t in g]
        best_s, best = max(scored, key=lambda x: (x[0]["score"], x[1]["start"]))
        takes = []
        for s, t in scored:
            kept = t is best
            takes.append({"take_id": t["id"], "clip": t["clip"], "start": t["start"], "end": t["end"], "text": t["text"], **s,
                          "decision": "kept" if kept else "dropped", "reason": "best take of this line" if kept else _why_dropped(s, best_s)})
        decisions.append({"line": script[g[0]["script_line"]]["text"] if ref is not None else best["text"],
                          "script_line": g[0].get("script_line"), "kept": best, "takes": takes, "status": "INFERRED"})
    if script:
        decisions.sort(key=lambda d: d["script_line"])
    else:
        decisions.sort(key=lambda d: (d["kept"]["clip"], d["kept"]["start"]))
    return decisions


# ----------------------------------------------------------------------------------------------- tight cut
def cut_take(take: dict, clip_duration: float, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Runs of kept words inside a take -> source segments. Returns (segments, removed words)."""
    ws = take["words"]
    removed = []
    keep = []
    for i, w in enumerate(ws):
        t = norm(w["text"])
        if cfg["remove_fillers"] and t in FILLERS:
            removed.append({**w, "why": "hesitation"})
            continue
        nxt = norm(ws[i + 1]["text"]) if i + 1 < len(ws) else None
        if t and t == nxt and ws[i + 1]["start"] - w["end"] < 0.5:
            removed.append({**w, "why": "repeated word"})
            continue
        keep.append(w)
    runs, cur = [], []
    for w in keep:
        if cur and w["start"] - cur[-1]["end"] > cfg["max_gap_in_run_sec"]:
            runs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        runs.append(cur)
    segs = []
    for run in runs:
        # Pads stop at any removed word, so a cut-out "um" never leaks back in through the breathing room.
        lo = max([r["end"] for r in removed if r["end"] <= run[0]["start"]], default=0.0)
        hi = min([r["start"] for r in removed if r["start"] >= run[-1]["end"]], default=clip_duration)
        a = max(lo, run[0]["start"] - cfg["pad_in_sec"], 0.0)
        b = min(hi, run[-1]["end"] + cfg["pad_out_sec"], clip_duration)
        segs.append({"clip": take["clip"], "src_in": round(a, 3), "src_out": round(b, 3), "words": run, "take": take["id"]})
    return segs, removed


def join_segments(segments: list[dict], removed: list[dict]) -> list[dict]:
    """Back-to-back segments of the same clip must not replay audio: where their padded ranges touch or overlap, merge
    them if nothing was cut out between them, otherwise split the shared gap at its midpoint."""
    out: list[dict] = []
    for sg in segments:
        prev = out[-1] if out else None
        if prev and prev["clip"] == sg["clip"] and sg["src_in"] < prev["src_out"] + 0.02 and sg["src_in"] > prev["src_in"]:
            gap_lo, gap_hi = prev["words"][-1]["end"], sg["words"][0]["start"]
            cut_between = any(r["clip"] == sg["clip"] and gap_lo <= r["start"] < gap_hi + 1e-6 for r in removed)
            if not cut_between:
                prev.update(src_out=max(prev["src_out"], sg["src_out"]), words=prev["words"] + sg["words"])
                continue
            mid = round((gap_lo + gap_hi) / 2, 3)
            prev["src_out"], sg = mid, {**sg, "src_in": mid}
        out.append(dict(sg))
    return out


# ----------------------------------------------------------------------------------------------- firing moments
def find_moments(words: list[dict], lines: list[list[dict]]) -> list[dict]:
    """Moments worth an editing move, from what is said. words carry timeline times; lines group them."""
    moments = []

    def add(kind, ws, status, why, emphasis=None):
        moments.append({"type": kind, "text": " ".join(w["text"] for w in ws), "start": ws[0]["t_in"], "end": ws[-1]["t_out"],
                        "word_index": [w["index"] for w in ws], "emphasis": [w["index"] for w in (emphasis or ws)], "status": status,
                        "evidence": why})
    if lines:
        add("HOOK", lines[0][: min(len(lines[0]), 8)], "INFERRED", "first line of the cut")
    for line in lines:
        toks = [norm(w["text"]) for w in line]
        for k, (w, t) in enumerate(zip(line, toks)):
            if t == "one" and (DETERMINERS & set(toks[max(0, k - 2):k]) or toks[k + 1:k + 2] == ["of"]):
                continue  # "the cheap one", "this one", "one of them": a pronoun, not a number
            if re.search(r"\d", w["text"]) or t in NUMBER_WORDS or "%" in w["text"] or "$" in w["text"]:
                add("NUMBER", [w], "MEASURED", "a number in the transcript")
            if t in ORDINALS:
                add("LIST", [w], "MEASURED", "a list marker in the transcript")
        for i, t in enumerate(toks):
            if t in ("or", "versus", "vs") and 0 < i < len(toks) - 1 and len(toks) <= 12:
                add("CONTRAST", [line[i - 1], line[i], line[i + 1]], "INFERRED", f"'{line[i - 1]['text']} {t} {line[i + 1]['text']}'",
                    [line[i - 1], line[i + 1]])
            if t == "not" and i + 1 < len(toks):
                # "not X but Y", "not X, it's Y", "not X, it is Y": the two contrasted words carry the emphasis.
                for j in range(i + 2, min(len(toks), i + 7)):
                    turn = toks[j] in ("but", "its", "it's") or (toks[j] == "is" and toks[j - 1] == "it")
                    if turn and j + 1 < len(toks):
                        add("CONTRAST", line[i:j + 2], "INFERRED", f"'not {line[i + 1]['text']} … {line[j + 1]['text']}'",
                            [line[i + 1], line[j + 1]])
                        break
            if t == "instead" and i + 1 < len(toks) and toks[i + 1] == "of":
                add("CONTRAST", line[i:i + 3], "INFERRED", "'instead of'")
        if line[-1]["text"].endswith("?"):
            add("QUESTION", line, "MEASURED", "the line ends with a question mark")
        joined = " ".join(toks)
        for cue in CUES:
            k = joined.find(cue)
            if k >= 0:
                start = joined[:k].count(" ")
                add("CUE", line[start:start + len(cue.split())], "MEASURED", f"spoken cue '{cue}': needs frame awareness (Phase 3) to act on")
        for i, w in enumerate(line):
            raw = w["text"].strip(".,!?\"'")
            if i > 0 and raw[:1].isupper() and raw not in ("I", "I'm", "I've", "I'll", "I'd") and norm(raw) not in NUMBER_WORDS:
                add("NAME", [w], "INFERRED", "capitalised mid-sentence (a proper noun, as transcribed)")
    return sorted(moments, key=lambda m: (m["start"], m["type"]))


# ----------------------------------------------------------------------------------------------- frame awareness
def vision_ready() -> tuple[bool, str]:
    try:
        import mediapipe  # noqa: F401
        import vision_models
    except ImportError as e:
        return False, f"mediapipe is not installed ({e})"
    missing = [k for k, v in vision_models.status().items() if v["status"] != "ready"]
    return (False, f"vision models missing: {', '.join(missing)} (python scripts/vision_models.py fetch)") if missing else (True, "")


def frame_plan(project: Path, metas: dict, items: list[dict], cap_words: list[dict], moments: list[dict], W: int, H: int) -> dict:
    """Subject-aware framing, caption placement and fingertip anchors from what the pictures show (MEASURED by the
    vision models; the camera path and placements are deterministic rules over those measurements)."""
    import compile_timeline as ct
    import frame_awareness as fa
    cache = project / "analysis" / "vision"
    analyses, plan = {}, {"status": "MEASURED", "reframed": [], "captions_position": "lower", "anchors": [], "faces": {}}
    for aid, meta in metas.items():
        analyses[aid] = fa.analyze(meta["path"], 0.0, meta["duration"], cache)
        sw, sh, _ = fa.probe_size(meta["path"])
        meta["aspect"] = sw / sh
        plan["faces"][aid] = f"{sum(1 for x in analyses[aid]['samples'] if x['faces'])}/{len(analyses[aid]['samples'])} samples"
    A = W / H
    for it in items:
        a = metas[it["asset_id"]]["aspect"]
        cw, ch = min(1.0, A / a), min(1.0, a / A)
        if cw > 0.98 and ch > 0.98:
            continue  # same shape: nothing to reframe
        keys = fa.camera_keys(fa.subject_centres(analyses[it["asset_id"]]), cw, ch)
        L = it["timeline_out"] - it["timeline_in"]
        lo, hi = it["source_in"] - 2.0, it["source_in"] + ct.source_at(it, L, L) + 2.0
        before = [k for k in keys if k[0] <= lo][-1:]
        it["reframe"] = {"keys": before + [k for k in keys if lo < k[0] <= hi] or keys[-1:], "source": "frame_awareness subject track"}
        plan["reframed"].append(it["id"])
    # Captions go where the face is not: measured face centres inside the kept segments, in output coordinates.
    ys = []
    for it in items:
        L = it["timeline_out"] - it["timeline_in"]
        s0, s1 = it["source_in"], it["source_in"] + ct.source_at(it, L, L)
        for smp in analyses[it["asset_id"]]["samples"]:
            if s0 <= smp["t"] < s1 and smp["faces"]:
                x, y, w, h = smp["faces"][0]["box"]
                ys.append(ct.frame_point(it, smp["t"], x + w / 2, y + h / 2, metas[it["asset_id"]]["aspect"], W, H)[1])
    if ys:
        face_y = sorted(ys)[len(ys) // 2]
        plan["face_y"] = round(face_y, 3)
        plan["captions_position"] = "upper" if face_y > 0.55 else "lower"
    # "Track it" and other spoken cues: follow the fingertip the pictures show right after the cue.
    for m in moments:
        if m["type"] != "CUE":
            continue
        w0 = cap_words[m["word_index"][0]]
        it = items[w0["segment"]]
        L = it["timeline_out"] - it["timeline_in"]
        s0, s1 = w0["src_start"], it["source_in"] + ct.source_at(it, L, L)
        pts = []
        for smp in analyses[it["asset_id"]]["samples"]:
            if s0 <= smp["t"] < min(s1, s0 + 3.0) and smp["hands"]:
                hand = min(smp["hands"], key=lambda h: h["index_tip"][1])  # the raised hand
                pts.append({"asset_id": it["asset_id"], "src_t": smp["t"], "x": hand["index_tip"][0], "y": hand["index_tip"][1],
                            "aspect": metas[it["asset_id"]]["aspect"]})
        if len(pts) >= 3:
            plan["anchors"].append({"moment": m["text"], "start": m["start"], "end": min(it["timeline_out"], m["start"] + 3.0), "points": pts})
        else:
            plan.setdefault("unfollowed", []).append({"moment": m["text"], "at": m["start"], "reason": "no hand seen in the 3 s after the cue"})
    return plan


def fire_defaults(moments: list[dict], items: list[dict], cap_words: list[dict], cfg: dict, people, aspect: str) -> tuple[list[dict], set]:
    """The built-in moves, used when no Signature is applied: emphasis and a punch-in on numbers and list markers,
    emphasis on both sides of a contrast."""
    fired, emphasis = [], set()
    for m in moments:
        if m["type"] in ("NUMBER", "LIST"):
            emphasis.update(m["word_index"])
            seg = cap_words[m["word_index"][0]]["segment"]
            items[seg]["motion"] = {"kind": "push_in", "scale_from": cfg["emphasis_scale"], "scale_to": cfg["emphasis_scale"]}
            fired.append({"moment": m["type"], "text": m["text"], "at": m["start"], "move": f"caption emphasis + punch-in {cfg['emphasis_scale']} on {items[seg]['id']}"})
        elif m["type"] == "CONTRAST":
            emphasis.update(m["emphasis"])
            fired.append({"moment": "CONTRAST", "text": m["text"], "at": m["start"], "move": "caption emphasis on both sides of the contrast"})
        elif m["type"] == "NAME" and people and m["text"].strip(".,!?") in people and aspect == "16:9":
            fired.append({"moment": "NAME", "text": m["text"], "at": m["start"], "move": "speaker lower third"})
    return fired, emphasis


# ----------------------------------------------------------------------------------------------- timeline
def caption_position(caption_params: Optional[dict], frame: dict) -> dict:
    """A Signature's caption position never covers the measured face: the face wins, and the conflict is recorded
    in frame["caption_conflict"]."""
    params = dict(caption_params or {})
    if params.get("position") and frame.get("face_y") is not None:
        lo, hi = CAPTION_BANDS.get(params["position"], (0.0, 0.0))
        if lo - 0.1 <= frame["face_y"] <= hi + 0.1:
            frame["caption_conflict"] = {"wanted": params["position"], "used": frame["captions_position"], "face_y": frame["face_y"],
                                         "reason": "the signature's caption position would cover the measured face"}
            params["position"] = frame["captions_position"]
    return params


def _probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s.get("codec_type") == "video"), {})
    num, _, den = (v.get("avg_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {"duration": float(d["format"]["duration"]), "fps": fps, "has_video": bool(v),
            "has_audio": any(s.get("codec_type") == "audio" for s in d["streams"])}


def build(project: Path, clips: list[Path], script_text: Optional[str], aspect: str, platform: Optional[str], style: str,
          cfg: dict, people: Optional[dict] = None, moves: Optional[list[dict]] = None, caption_params: Optional[dict] = None) -> tuple[dict, dict]:
    """(timeline IR, report) for the given raw clips."""
    import remotion_bridge as rb
    cache = project / "analysis" / "transcripts"
    metas, transcripts, lines = {}, {}, []
    for path in clips:
        aid = re.sub(r"[^a-z0-9_]+", "_", path.stem.lower()).strip("_") or "clip"
        metas[aid] = {**_probe(path), "path": path}
        if not metas[aid]["has_audio"]:
            raise SystemExit(f"{path.name} has no sound: a talking-head cut is driven by speech")
        transcripts[aid] = transcribe(path, cache)
        lines += lines_of(transcripts[aid]["words"], aid, cfg)
    script = script_lines(script_text) if script_text else None
    hesitations = [ln for ln in lines if not ln["content"]]
    lines = [ln for ln in lines if ln["content"]]
    groups, off_script = group_takes(lines, script, cfg)
    decisions = choose_takes(groups, script)

    segments, removed = [], []
    for d in decisions:
        segs, rem = cut_take(d["kept"], metas[d["kept"]["clip"]]["duration"], cfg)
        segments += segs
        removed += rem
    segments = join_segments(segments, removed)
    fps = round(metas[next(iter(metas))]["fps"]) or 30
    W, H = SHAPES[aspect]
    t = 0.0
    items, cap_words, timeline_lines = [], [], []
    for n, sg in enumerate(segments):
        length = round(sg["src_out"] - sg["src_in"], 3)
        item = {"id": f"T{n + 1:03d}", "asset_id": sg["clip"], "timeline_in": round(t, 3), "timeline_out": round(t + length, 3),
                "source_in": sg["src_in"], "fit": "cover", "audio": {"native": True}, "take": sg["take"]}
        if n % 2 == 1:  # alternate framing so a jump cut reads as a deliberate punch-in
            item["motion"] = {"kind": "push_in", "scale_from": cfg["punch_in_scale"], "scale_to": cfg["punch_in_scale"]}
        items.append(item)
        for w in sg["words"]:
            w_tl = {"text": w["text"], "t_in": round(t + w["start"] - sg["src_in"], 3), "t_out": round(t + w["end"] - sg["src_in"], 3),
                    "index": len(cap_words), "segment": n, "asset_id": sg["clip"], "src_start": w["start"], "src_end": w["end"]}
            cap_words.append(w_tl)
        t += length
    for take_id in dict.fromkeys(sg["take"] for sg in segments):
        timeline_lines.append([w for w in cap_words if segments[w["segment"]]["take"] == take_id])
    total = round(t, 3)
    moments = find_moments(cap_words, timeline_lines)

    if moves is None:
        fired, emphasis = fire_defaults(moments, items, cap_words, cfg, people, aspect)
    else:  # a Signature's own moves, each with the condition it fires on
        import signature as sig_mod
        fired, emphasis = sig_mod.fire_moves(moves, moments, items, cap_words, cfg)
    vision_ok, vision_why = vision_ready()
    frame = frame_plan(project, metas, items, cap_words, moments, W, H) if vision_ok else {"status": "NOT_MEASURED", "reason": vision_why}
    for a in frame.get("anchors", []):
        fired.append({"moment": "CUE", "text": a["moment"], "at": a["start"], "move": "marker follows the measured fingertip"})
    caption_params = caption_position(caption_params, frame)
    tracks = [{"id": "v_main", "kind": "video", "items": items}]
    remotion_ok = rb.available()[0]
    if remotion_ok:
        # Words keep their source moment: the compiler places them on the timeline at render time, so captions stay
        # in sync after any edit, and a removed take takes its words with it.
        words = [{"text": w["text"], "asset_id": w["asset_id"], "src_start": w["src_start"], "src_end": w["src_end"],
                  **({"emphasis": True} if w["index"] in emphasis else {})} for w in cap_words]
        tracks.append({"id": "captions", "kind": "graphic", "items": [
            {"id": "CAPS", "template": "kinetic_captions", "follow": "main", "timeline_in": 0.0, "timeline_out": total,
             "params": {"words": words, "maxWords": 3, "position": frame.get("captions_position", "lower"), **caption_params}}]})
        if frame.get("anchors"):
            tracks.append({"id": "markers", "kind": "graphic", "items": [
                {"id": f"MK{i + 1}", "template": "anchor_marker", "timeline_in": round(a["start"], 3), "timeline_out": round(a["end"], 3),
                 "params": {"anchors": a["points"]}} for i, a in enumerate(frame["anchors"])]})
    else:  # no Remotion here: plain burned-in lines, said plainly in the report
        caps = []
        for line in timeline_lines:
            for k in range(0, len(line), 4):
                chunk = line[k:k + 4]
                caps.append({"id": f"c{len(caps) + 1:04d}", "timeline_in": chunk[0]["t_in"], "timeline_out": chunk[-1]["t_out"],
                             "text": " ".join(w["text"] for w in chunk)})
        tracks.append({"id": "captions", "kind": "caption", "items": caps})
    ir = {"ir_version": "3.0", "canvas": {"width": W, "height": H, "fps": fps, "sample_rate": 48000, **({"platform": platform} if platform else {})},
          "style": style, "tracks": tracks, "mix": {"loudnorm": {"I": -14, "TP": -1.5, "LRA": 11}},
          "compile": {"made_by": "talking_head.py", "status": "proposal: review the takes and the cut before approval"}}
    raw = sum(m["duration"] for m in metas.values())
    report = {
        "clips": [{"asset_id": k, "file": v["path"].name, "duration": round(v["duration"], 3), "fps": v["fps"]} for k, v in metas.items()],
        "transcription": {k: {"model": v["model"], "language": v["language"], "words": len(v["words"]), "status": "MEASURED"} for k, v in transcripts.items()},
        "script": {"lines": len(script)} if script else None,
        "lines": [{k: d[k] for k in ("line", "script_line", "takes", "status")} for d in decisions],
        "off_script": [{"take_id": ln["id"], "text": ln["text"], "start": ln["start"], "end": ln["end"], "decision": "dropped",
                        "reason": "matches no line of the script"} for ln in off_script]
                      + [{"take_id": ln["id"], "text": ln["text"], "start": ln["start"], "end": ln["end"], "decision": "dropped",
                          "reason": "only hesitation sounds"} for ln in hesitations],
        "cut": {"raw_duration": round(raw, 3), "cut_duration": total, "segments": len(items),
                "removed_words": [{"text": r["text"], "clip": r["clip"], "at": r["start"], "why": r["why"]} for r in removed],
                "captions": "kinetic_captions (Remotion)" if remotion_ok else "plain burned-in lines (Remotion not available)"},
        "moments": moments, "fired": fired,
        "frame": {k: v for k, v in frame.items() if k != "anchors"} | {"anchors": [{k: a[k] for k in ("moment", "start", "end")} | {"points": len(a["points"])}
                                                                              for a in frame.get("anchors", [])]},
        "notes": ["Take choice, lines and moments are INFERRED from the transcript by rules; review them before approving.",
                  "Framing follows the measured subject when the vision models are installed; otherwise it is a centre crop."],
    }
    return ir, report


def register_clips(project: Path, clips: list[Path], approve: bool) -> None:
    p = project / "assets.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"assets": []}
    known = {a.get("asset_id"): a for a in data.get("assets", [])}
    for path in clips:
        aid = re.sub(r"[^a-z0-9_]+", "_", path.stem.lower()).strip("_") or "clip"
        rel = path.resolve().relative_to(project.resolve()).as_posix() if project.resolve() in path.resolve().parents else str(path.resolve())
        entry = known.get(aid) or {"asset_id": aid}
        entry.update(local_path=rel, kind="talking_head_footage", rights="owner_supplied",
                     status="approved" if approve else entry.get("status", "simulation_approved"))
        if aid not in known:
            data.setdefault("assets", []).append(entry)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--clips", nargs="+", required=True, help="raw talking-head clips (paths relative to the project or absolute)")
    ap.add_argument("--script", help="the script the takes should follow (text file); without it, attempts are grouped by similarity")
    ap.add_argument("--aspect", choices=sorted(SHAPES), default="9:16")
    ap.add_argument("--platform", choices=["tiktok", "reels", "shorts", "youtube"], help="keep captions out of this platform's UI")
    ap.add_argument("--style", default="documentary_general")
    ap.add_argument("--out", default="timeline_v3.json")
    ap.add_argument("--force", action="store_true", help="overwrite an existing working timeline")
    ap.add_argument("--approve-own-footage", action="store_true", help="register the clips as approved (they are the owner's)")
    a = ap.parse_args()
    project = a.project.resolve()
    clips = [(Path(c) if Path(c).is_absolute() else project / c).resolve() for c in a.clips]
    for c in clips:
        if not c.is_file():
            raise SystemExit(f"no such clip: {c}")
    out = project / a.out
    if out.exists() and not a.force:
        raise SystemExit(f"{out.name} exists (it may hold edits); use --force or --out another file")
    script = Path(a.script).read_text(encoding="utf-8") if a.script else None
    ir, report = build(project, clips, script, a.aspect, a.platform or ("reels" if a.aspect == "9:16" else None), a.style, dict(CONFIG))
    register_clips(project, clips, a.approve_own_footage)
    out.write_text(json.dumps(ir, indent=2) + "\n", encoding="utf-8")
    (project / "analysis").mkdir(exist_ok=True)
    (project / "analysis" / "talking_head.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    kept = sum(1 for ln in report["lines"] for t in ln["takes"] if t["decision"] == "kept")
    dropped = sum(1 for ln in report["lines"] for t in ln["takes"] if t["decision"] == "dropped") + len(report["off_script"])
    print(json.dumps({"timeline": out.name, "raw_sec": report["cut"]["raw_duration"], "cut_sec": report["cut"]["cut_duration"],
                      "takes_kept": kept, "takes_dropped": dropped, "words_removed": len(report["cut"]["removed_words"]),
                      "moments": len(report["moments"]), "fired": len(report["fired"]), "report": "analysis/talking_head.json"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
