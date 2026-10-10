"""Compare a render with its reference: the same measurements on both, every difference as numbers, and a score.

    python -m style_intel compare REFERENCE.mp4 RENDER.mp4 --out DIR [--text] [--ref-cache DIR] [--no-speech]

Both videos go through the same analyzers (Style DNA, per-shot colour, and with --text the on-screen text reader),
so nothing is judged by eye. Each metric carries both values, the difference, a 0-1 similarity and how it was
scored; groups (editing, camera, colour, sound, text) are averaged into an overall score. Metrics that cannot be
measured on one side are listed as NOT_MEASURED and left out of the score, never filled in.

Measurements are cached per video (by sha256) in their folder; --ref-cache points at an existing reference folder
(for a Signature: ~/NarrativeOS-Signatures/<id>/reference), so the reference is not measured twice.

What the score is not: content is never compared (different footage, different words are expected). It measures
the editing language: rhythm, camera, colour and its consistency, loudness and pace, caption treatment.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from statistics import median
from typing import Optional

import numpy as np

SCHEMA = "narrativeos.style_compare/1.0"
GROUP_WEIGHTS = {"editing": 0.25, "camera": 0.1, "colour": 0.25, "sound": 0.15, "text": 0.25}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cuts(dna_dir: Path, dna: dict) -> list[float]:
    shots = dna_dir / "shots.json"
    if shots.is_file():
        s = json.loads(shots.read_text(encoding="utf-8"))
        return sorted(float(c) for c in (s.get("cuts_sec") or s.get("hard_cuts_sec") or []))
    tv = (dna.get("editing") or {}).get("transition_vocabulary") or {}
    return sorted(float(t) for v in tv.values() if isinstance(v, dict) for t in v.get("times_sec", []))


def shot_colours(video: Path, cuts: list[float], duration: float) -> list[dict]:
    """Lab mean of each shot (3 frames in its middle half), the basis of colour consistency (MEASURED)."""
    import cv2
    bounds = [0.0, *[c for c in cuts if 0 < c < duration], duration]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < 0.2:
            continue
        labs = []
        for t in (a + (b - a) * f for f in (0.3, 0.5, 0.7)):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=160:-2",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            if not raw:
                continue
            px = np.frombuffer(raw, np.uint8).reshape(-1, 1, 3).astype(np.float32) / 255.0
            labs.append(cv2.cvtColor(px, cv2.COLOR_RGB2LAB).reshape(-1, 3).mean(0))
        if labs:
            m = np.mean(labs, 0)
            out.append({"start": round(a, 3), "end": round(b, 3), "lab": [round(float(x), 2) for x in m]})
    return out


def measure(video: Path, folder: Path, with_text: bool = False, with_speech: bool = True) -> dict:
    """Everything the comparison needs for one video, cached in folder (reused when the video's sha256 matches)."""
    from style_intel import dna as dna_mod
    folder.mkdir(parents=True, exist_ok=True)
    sha = _sha(video)
    cache = folder / "compare_measure.json"
    if cache.is_file():
        m = json.loads(cache.read_text(encoding="utf-8"))
        if m.get("sha256") == sha and (m.get("typography") or not with_text):
            return m
    dna_file = folder / "dna" / "style_dna.json"
    dna = json.loads(dna_file.read_text(encoding="utf-8")) if dna_file.is_file() else None
    if not dna or (dna.get("source") or {}).get("sha256") != sha:
        dna = dna_mod.analyze(video, folder / "dna", with_speech=with_speech)
    dur = float((dna.get("source") or {}).get("duration_sec") or 0)
    cuts = _cuts(folder / "dna", dna)
    typo = None
    if with_text:
        bd = folder / "breakdown" / "breakdown.json"
        if bd.is_file():
            b = json.loads(bd.read_text(encoding="utf-8"))
            if (b.get("source") or {}).get("sha256") == sha and (b.get("typography") or {}).get("status") == "MEASURED":
                typo = b["typography"]
        if typo is None:
            from style_intel import typography
            typo = typography.analyze(video, dna["source"])
    m = {"file": video.name, "sha256": sha, "duration": dur, "dna": {k: dna.get(k) for k in ("editing", "visual", "audio", "speech", "source")},
         "cuts": cuts, "shots": shot_colours(video, cuts, dur), "typography": typo}
    cache.write_text(json.dumps(m, indent=1, default=str) + "\n", encoding="utf-8")
    return m


# ----------------------------------------------------------------------------------------------- scoring
def _rel(a, b, tol: float) -> Optional[float]:
    """Similarity of two magnitudes: 1 when equal, 0 when they differ by tol (as a fraction of the reference)."""
    if a is None or b is None:
        return None
    a, b = float(a), float(b)
    if a == 0 and b == 0:
        return 1.0
    return max(0.0, 1.0 - abs(a - b) / (max(abs(a), 1e-9) * tol))


def _abs(a, b, tol: float) -> Optional[float]:
    if a is None or b is None:
        return None
    return max(0.0, 1.0 - abs(float(a) - float(b)) / tol)


def _ks(x: list[float], y: list[float]) -> Optional[float]:
    """Kolmogorov-Smirnov distance between two samples (shape of the shot-length distribution)."""
    if len(x) < 2 or len(y) < 2:
        return None
    grid = sorted(set(x) | set(y))
    cx = np.searchsorted(sorted(x), grid, side="right") / len(x)
    cy = np.searchsorted(sorted(y), grid, side="right") / len(y)
    return float(np.max(np.abs(cx - cy)))


def _lengths(m: dict) -> list[float]:
    b = [0.0, *m["cuts"], m["duration"]]
    return [y - x for x, y in zip(b, b[1:]) if y - x > 0.05]


def _text_lines(m: dict) -> list[dict]:
    t = m.get("typography") or {}
    return [ln for ln in (t.get("lines") or []) if not ln.get("cover_frame")] if t.get("status") == "MEASURED" else []


def compare(ref: dict, out: dict) -> dict:
    metrics: list[dict] = []

    def add(group, name, a, b, score, how, unit="", advice=None):
        entry = {"group": group, "metric": name, "reference": a, "render": b, "unit": unit, "how": how}
        if score is None:
            entry |= {"status": "NOT_MEASURED", "score": None}
        else:
            entry |= {"status": "MEASURED", "score": round(score, 3)}
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                entry["difference"] = round(float(b) - float(a), 3)
            if advice and score < 0.8:
                entry["advice"] = advice
        metrics.append(entry)

    re_, oe = ref["dna"].get("editing") or {}, out["dna"].get("editing") or {}
    rl, ol = _lengths(ref), _lengths(out)
    rq = lambda xs, q: round(float(np.quantile(xs, q)), 3) if xs else None  # noqa: E731
    add("editing", "shots per minute", re_.get("cuts_per_minute"), oe.get("cuts_per_minute"), _rel(re_.get("cuts_per_minute"), oe.get("cuts_per_minute"), 0.5),
        "relative difference, 0 at 50 %", "/min", "match the cut rate")
    for label, q in (("median shot length", 0.5), ("short shots (10th percentile)", 0.1), ("long shots (90th percentile)", 0.9)):
        add("editing", label, rq(rl, q), rq(ol, q), _rel(rq(rl, q), rq(ol, q), 0.5), "relative difference, 0 at 50 %", "s", "move shot lengths toward the reference's")
    ks = _ks(rl, ol)
    add("editing", "shot-length distribution", "shape", "shape", None if ks is None else 1 - ks, "1 - Kolmogorov-Smirnov distance between the two sets of shot lengths")
    rv = {k for k, v in (re_.get("transition_vocabulary") or {}).items() if isinstance(v, dict) and v.get("count")}
    ov = {k for k, v in (oe.get("transition_vocabulary") or {}).items() if isinstance(v, dict) and v.get("count")}
    add("editing", "transitions used", sorted(rv), sorted(ov), (len(rv & ov) / len(rv | ov)) if (rv | ov) else 1.0, "Jaccard similarity of transition kinds",
        advice="use only the transition kinds the reference uses")

    rvis, ovis = ref["dna"].get("visual") or {}, out["dna"].get("visual") or {}
    rc, oc = (rvis.get("camera_motion") or {}).get("fractions") or {}, (ovis.get("camera_motion") or {}).get("fractions") or {}
    keys = set(rc) | set(oc)
    add("camera", "camera motion mix", rc, oc, (1 - 0.5 * sum(abs(rc.get(k, 0) - oc.get(k, 0)) for k in keys)) if keys else None,
        "1 - half the L1 distance between motion fractions", advice="match the share of static, push-in and pan shots")

    rs, os_ = np.array([s["lab"] for s in ref["shots"]]), np.array([s["lab"] for s in out["shots"]])
    if len(rs) and len(os_):
        de = float(np.linalg.norm(rs.mean(0) - os_.mean(0)))
        add("colour", "overall colour (Lab mean)", [round(float(x), 1) for x in rs.mean(0)], [round(float(x), 1) for x in os_.mean(0)], max(0.0, 1 - de / 20),
            "Delta-E 76 between the mean Lab of all shots, 0 at 20", advice="grade toward the reference's colour")
        for i, name in ((0, "lightness"), (1, "green-red (a)"), (2, "blue-yellow (b)")):
            r_sd, o_sd = float(rs[:, i].std()), float(os_[:, i].std())
            add("colour", f"shot-to-shot spread of {name}", round(r_sd, 2), round(o_sd, 2),
                min(r_sd, o_sd) / max(r_sd, o_sd) if max(r_sd, o_sd) > 0.5 else 1.0,
                "ratio of the across-shot standard deviations (how much the look jumps between shots)",
                advice="even out the shots (per-shot grade)" if o_sd > r_sd else "the reference varies more between shots")
    else:
        add("colour", "overall colour (Lab mean)", None, None, None, "no shots measured")
    for key, label, tol in (("contrast", "contrast", 0.3), ("saturation", "saturation", 0.3), ("colourfulness", "colourfulness", 0.3), ("grain", "grain", 0.5)):
        add("colour", label, rvis.get(key), ovis.get(key), _rel(rvis.get(key), ovis.get(key), tol), f"relative difference, 0 at {int(tol * 100)} %")

    ra, oa = ref["dna"].get("audio") or {}, out["dna"].get("audio") or {}
    add("sound", "integrated loudness", ra.get("integrated_lufs"), oa.get("integrated_lufs"), _abs(ra.get("integrated_lufs"), oa.get("integrated_lufs"), 6),
        "absolute difference, 0 at 6 LU", "LUFS", "normalise the mix to the reference's loudness")
    add("sound", "loudness range", ra.get("loudness_range_lu"), oa.get("loudness_range_lu"), _abs(ra.get("loudness_range_lu"), oa.get("loudness_range_lu"), 6),
        "absolute difference, 0 at 6 LU", "LU", "compress or open up the mix")
    rsp, osp = ref["dna"].get("speech") or {}, out["dna"].get("speech") or {}
    add("sound", "speech pace", rsp.get("words_per_minute"), osp.get("words_per_minute"), _rel(rsp.get("words_per_minute"), osp.get("words_per_minute"), 0.4),
        "relative difference, 0 at 40 %", "words/min", "tighten pauses or use a faster read")
    add("sound", "speech coverage", rsp.get("speech_coverage"), osp.get("speech_coverage"), _abs(rsp.get("speech_coverage"), osp.get("speech_coverage"), 0.5),
        "absolute difference, 0 at 0.5")

    rt, ot = _text_lines(ref), _text_lines(out)
    if rt and ot:
        def regions(lines):
            c = {}
            for ln in lines:
                c[ln.get("region", "?")] = c.get(ln.get("region", "?"), 0) + 1
            return {k: round(v / len(lines), 3) for k, v in c.items()}
        rr, orr = regions(rt), regions(ot)
        keys = set(rr) | set(orr)
        add("text", "where text sits", rr, orr, 1 - 0.5 * sum(abs(rr.get(k, 0) - orr.get(k, 0)) for k in keys),
            "1 - half the L1 distance between screen-region shares", advice="place text where the reference does")
        rh, oh = median([ln["height_frac"] for ln in rt if ln.get("height_frac")]), median([ln["height_frac"] for ln in ot if ln.get("height_frac")])
        add("text", "text size (median line height)", round(rh, 3), round(oh, 3), _rel(rh, oh, 0.5), "relative difference, 0 at 50 %", "of frame",
            "scale the text toward the reference's size")
        ru, ou = np.mean([bool(ln.get("uppercase")) for ln in rt]), np.mean([bool(ln.get("uppercase")) for ln in ot])
        add("text", "uppercase share", round(float(ru), 3), round(float(ou), 3), 1 - abs(float(ru - ou)), "1 - absolute difference")
        rw, ow = median([len(str(ln.get("text", "")).split()) for ln in rt]), median([len(str(ln.get("text", "")).split()) for ln in ot])
        add("text", "words per line (median)", rw, ow, _rel(rw, ow, 1.0), "relative difference, 0 at 100 %", advice="match how many words show at once")
        luma = lambda c: 0.299 * int(c[1:3], 16) + 0.587 * int(c[3:5], 16) + 0.114 * int(c[5:7], 16)  # noqa: E731
        rcol = [luma(ln["colour"]) for ln in rt if str(ln.get("colour", "")).startswith("#")]
        ocol = [luma(ln["colour"]) for ln in ot if str(ln.get("colour", "")).startswith("#")]
        if rcol and ocol:
            dark_r, dark_o = np.mean([c < 96 for c in rcol]), np.mean([c < 96 for c in ocol])
            add("text", "dark-text share", round(float(dark_r), 3), round(float(dark_o), 3), 1 - abs(float(dark_r - dark_o)), "1 - absolute difference")
        for window, label in ((6.0, "text lines in the opening 6 s"),):
            a_n = sum(1 for ln in rt if ln.get("start", 99) < window)
            b_n = sum(1 for ln in ot if ln.get("start", 99) < window)
            add("text", label, a_n, b_n, _rel(a_n, b_n, 1.0), "relative difference, 0 at 100 %", advice="the opening's text density differs")
        rk = sorted({k for ln in rt for k in ((ln.get("in") or {}).get("kinds") or [])})
        ok = sorted({k for ln in ot for k in ((ln.get("in") or {}).get("kinds") or [])})
        add("text", "text entrance kinds (INFERRED by the reader)", rk, ok, (len(set(rk) & set(ok)) / len(set(rk) | set(ok))) if (rk or ok) else 1.0,
            "Jaccard similarity of the inferred entrance kinds")
    else:
        add("text", "on-screen text", "measured" if rt else "not read", "measured" if ot else "not read", None, "run with --text on both")

    groups = {}
    for g in GROUP_WEIGHTS:
        s = [m["score"] for m in metrics if m["group"] == g and m["score"] is not None]
        groups[g] = round(float(np.mean(s)), 3) if s else None
    scored = {g: s for g, s in groups.items() if s is not None}
    wsum = sum(GROUP_WEIGHTS[g] for g in scored)
    overall = round(sum(GROUP_WEIGHTS[g] * s for g, s in scored.items()) / wsum, 3) if wsum else None
    worst = sorted((m for m in metrics if m["score"] is not None), key=lambda m: m["score"])[:6]
    return {"schema": SCHEMA, "reference": {"file": ref["file"], "sha256": ref["sha256"]}, "render": {"file": out["file"], "sha256": out["sha256"]},
            "overall": overall, "groups": groups, "group_weights": GROUP_WEIGHTS, "metrics": metrics,
            "largest_differences": [{k: m.get(k) for k in ("group", "metric", "reference", "render", "score", "advice")} for m in worst],
            "not_compared": ["content (footage, words) is expected to differ", "font family (not measurable)", "music identity", "per-word typography (not measured yet)"]}


def to_markdown(rep: dict) -> str:
    fmt = lambda v: json.dumps(v) if isinstance(v, (dict, list)) else ("—" if v is None else str(v))  # noqa: E731
    lines = [f"# Style comparison: {rep['render']['file']} vs {rep['reference']['file']}", "",
             f"**Overall similarity: {rep['overall']}** (weighted: " + ", ".join(f"{g} {w:.0%}" for g, w in rep["group_weights"].items()) + ")", "",
             "| Group | Score |", "|---|---|"] + [f"| {g} | {fmt(s)} |" for g, s in rep["groups"].items()]
    lines += ["", "## Largest differences", ""] + [f"- **{m['metric']}** ({m['group']}): reference {fmt(m['reference'])}, render {fmt(m['render'])}, "
                                                    f"score {m['score']}" + (f" — {m['advice']}" if m.get("advice") else "") for m in rep["largest_differences"]]
    lines += ["", "## Every metric", "", "| Group | Metric | Reference | Render | Score | How |", "|---|---|---|---|---|---|"]
    lines += [f"| {m['group']} | {m['metric']} | {fmt(m['reference'])} | {fmt(m['render'])} | {fmt(m['score'])} | {m['how']} |" for m in rep["metrics"]]
    lines += ["", "Not compared: " + "; ".join(rep["not_compared"]) + "."]
    return "\n".join(lines) + "\n"


def run(reference: Path, render: Path, out_dir: Path, with_text: bool = False, ref_cache: Optional[Path] = None, with_speech: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = measure(reference, ref_cache or out_dir / "reference", with_text, with_speech)
    out = measure(render, out_dir / "render", with_text, with_speech)
    rep = compare(ref, out)
    (out_dir / "compare.json").write_text(json.dumps(rep, indent=1, default=str) + "\n", encoding="utf-8")
    (out_dir / "compare.md").write_text(to_markdown(rep), encoding="utf-8")
    return rep
