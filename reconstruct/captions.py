"""On-screen captions read from every frame of the reference (MEASURED), not from the transcript or a watcher.

Measured on ref_6cbda51b: the transcript and the watcher both disagree with the screen. Of 247 spoken words, 43 had no
watched caption; 19 of those were on screen (watcher misses), some were misheard by speech recognition ("ship" on
screen is "chip", "parts" is "parks"), some are written differently ("A hundred million square feet" is
"100,000,000ft²"), and the rest are not captioned at all. So the frames are the only source of truth.

Every frame is read by RapidOCR (local). A line counts as caption text when it is bright, white and unsaturated (the
edit's caption look), so footage text (lower-thirds, signs, tickers) is kept apart and labelled.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

W, H = 1276, 718


def read_all(video: Path, out: Path, every: int = 1) -> list[dict]:
    from rapidocr import RapidOCR
    ocr = RapidOCR(params={"Global.log_level": "critical"})
    raw = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    rows, n = [], 0
    with out.open("w", encoding="utf-8") as fh:
        while True:
            buf = raw.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            if n % every == 0:
                img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
                r = ocr(img)
                lines = []
                for box, txt, score in zip(r.boxes if r.boxes is not None else [], r.txts or [], r.scores or []):
                    b = np.asarray(box)
                    x0, y0 = b.min(0)
                    x1, y1 = b.max(0)
                    crop = img[int(max(0, y0)):int(y1) + 1, int(max(0, x0)):int(x1) + 1].astype(np.float32)
                    bright = crop[crop.mean(axis=2) > 200] if crop.size else np.zeros((0, 3))
                    sat = float((bright.max(axis=1) - bright.min(axis=1)).mean()) if len(bright) else 255.0
                    lines.append({"text": txt, "score": round(float(score), 3), "box": [round(float(v), 1) for v in (x0, y0, x1, y1)],
                                  "white_px": int(len(bright)), "white_sat": round(sat, 1),
                                  "caption_look": bool(len(bright) >= 30 and sat < 40)})
                row = {"frame": n, "lines": lines}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                rows.append(row)
            n += 1
    raw.wait()
    return rows


if __name__ == "__main__":
    import sys
    read_all(Path(sys.argv[1]), Path(sys.argv[2]))


# ----------------------------------------------------------------------------------------------- assembly
import re as _re
from difflib import SequenceMatcher as _SM

BAND = (240, 470)          # caption line centres sit in this vertical band (MEASURED on ref_6cbda51b: 300-380)


def _letters(s: str) -> str:
    return _re.sub(r"[^a-z0-9]", "", s.lower())


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u else 0.0


def respace(text: str, spoken: list[str]) -> str:
    """Put the transcript's word breaks into an OCR reading whose letters are identical to a run of spoken words
    ("hasenough" -> "has enough"). Anything else is left exactly as read (the screen wins over the transcript)."""
    target = _letters(text)
    for i in range(len(spoken)):
        acc = ""
        for j in range(i, min(len(spoken), i + 6)):
            acc += _letters(spoken[j])
            if acc == target:
                words = []
                for w in spoken[i:j + 1]:
                    words.append(_re.sub(r"[^\w'’.,!?²$%-]", "", w))
                # keep the screen's own case and punctuation: rebuild from the reading, letter by letter
                out, k = [], 0
                for w in words:
                    n = len(_letters(w))
                    seg, got = "", 0
                    while k < len(text) and got < n:
                        if _letters(text[k]):
                            got += 1
                        seg += text[k]
                        k += 1
                    while k < len(text) and not _letters(text[k]) and text[k] != " ":
                        seg += text[k]
                        k += 1
                    out.append(seg.strip())
                    while k < len(text) and text[k] == " ":
                        k += 1
                return " ".join(o for o in out if o)
            if len(acc) > len(target):
                break
    return text


def assemble(rows: list[dict], words: list[dict], fps: float) -> list[dict]:
    """Caption runs: consecutive frames showing the same line in the same place. Each run's text is the majority
    reading over its frames (MEASURED), respaced against the transcript where the letters are identical."""
    # 1. caption candidates per frame: in the band, at least two letters
    cand = {}
    for r in rows:
        keep = []
        for ln in r["lines"]:
            x0, y0, x1, y1 = ln["box"]
            cy = (y0 + y1) / 2
            if BAND[0] <= cy <= BAND[1] and len(_letters(ln["text"])) >= 2 and ln["score"] >= 0.6:
                keep.append(ln)
        cand[r["frame"]] = keep
    # 2. track lines across frames into runs
    runs, open_runs = [], []
    for f in sorted(cand):
        nxt = []
        for ln in cand[f]:
            best = None
            for run in open_runs:
                last = run["lines"][-1]
                if f - run["last"] <= 2 and _iou(last["box"], ln["box"]) > 0.35 and _SM(None, _letters(last["text"]), _letters(ln["text"])).ratio() >= 0.7:
                    if best is None or _iou(last["box"], ln["box"]) > _iou(best["lines"][-1]["box"], ln["box"]):
                        best = run
            if best is not None and best not in nxt:
                best["lines"].append(ln)
                best["last"] = f
                nxt.append(best)
            else:
                run = {"first": f, "last": f, "lines": [ln]}
                runs.append(run)
                nxt.append(run)
        open_runs = [r for r in open_runs if f - r["last"] <= 2 and r not in nxt] + nxt
    # 3. majority text, box, transcript support
    out = []
    for run in runs:
        from collections import Counter
        # agreement on letters only: "fab built?" and "fab built." are the same reading of the same caption
        votes = Counter(_letters(ln["text"]) for ln in run["lines"])
        key, n = votes.most_common(1)[0]
        text = Counter(ln["text"].strip() for ln in run["lines"] if _letters(ln["text"]) == key).most_common(1)[0][0]
        frames = run["last"] - run["first"] + 1
        t0, t1 = run["first"] / fps - 1.5, run["last"] / fps + 1.5
        spoken = [w["text"] for w in words if t0 <= w["start"] <= t1]
        support = max((_SM(None, _letters(text), _letters(" ".join(spoken[i:j]))).ratio()
                       for i in range(len(spoken)) for j in range(i + 1, min(len(spoken), i + 6) + 1)), default=0.0)
        boxes = np.array([ln["box"] for ln in run["lines"]])
        x0, y0, x1, y1 = np.median(boxes, axis=0)
        out.append({"text": respace(text, spoken), "read_as": text, "first": run["first"], "last": run["last"], "frames": frames,
                    "agreement": round(n / len(run["lines"]), 2), "box": [round(float(v), 1) for v in (x0, y0, x1, y1)],
                    "transcript_support": round(support, 2), "readings": len(run["lines"])})
    # 4. a caption is transcript-supported, or looks like one: centred, caption-sized, clean text, held 3+ frames.
    #    (The transcript can be wrong, "fab built?" was heard as "boat that"; footage text is off-centre, small,
    #    or full of symbols: x:1178, [5399], TESLA, JOIN US ON OUR JOURNEY.)
    for c in out:
        x0, y0, x1, y1 = c["box"]
        cx, h = (x0 + x1) / 2, y1 - y0
        clean = bool(_re.fullmatch(r"[A-Za-z0-9 ,.'’?!²$%-]+", c["read_as"])) and len(_letters(c["read_as"])) >= 3
        looks = 300 <= cx <= 980 and 45 <= h <= 130 and clean and c["frames"] >= 3 and c["agreement"] >= 0.5
        c["status"] = "CAPTION" if c["transcript_support"] >= 0.6 else ("CAPTION (screen only)" if looks else "REJECTED")
    # 5. a short unsupported reading right next to a caption in the same place is a misread of it ("bu hos")
    caps = sorted([c for c in out if c["status"].startswith("CAPTION")], key=lambda c: c["first"])
    for c in caps:
        if c["transcript_support"] >= 0.6:
            continue
        for d in caps:
            if d is c or d["transcript_support"] < 0.6:
                continue
            near = (0 <= c["first"] - d["last"] <= 2) or (0 <= d["first"] - c["last"] <= 2)
            if near and _iou(c["box"], d["box"]) > 0.5 and _SM(None, _letters(c["read_as"]), _letters(d["read_as"])).ratio() >= 0.5:
                c["status"] = f"MERGED into {d['text']!r}"
                d["first"], d["last"] = min(d["first"], c["first"]), max(d["last"], c["last"])
                break
    return sorted(out, key=lambda c: (c["first"], c["box"][0]))


def uncovered_words(caps: list[dict], words: list[dict], fps: float) -> list[dict]:
    """Spoken words that no caption shows near when they are spoken (+-1.5 s): where to look again."""
    shown = [c for c in caps if c["status"].startswith("CAPTION")]
    out = []
    for w in words:
        lw = _letters(w["text"])
        if not lw:
            continue
        f = w["start"] * fps
        hit = any(c["first"] - 45 <= f <= c["last"] + 45 and lw in _letters(c["text"]) for c in shown)
        if not hit:
            out.append({"text": w["text"], "start": w["start"], "frame": int(round(f))})
    return out


def white_only(img: np.ndarray, min_level: int = 185, max_sat: int = 45) -> np.ndarray:
    """Only the caption colour (white, unsaturated) on black: footage text in colour (the green number grid) and
    the picture behind are removed, so a caption merged into footage text can be read on its own."""
    sat = img.max(axis=2).astype(np.int16) - img.min(axis=2)
    m = (img.min(axis=2) >= min_level) & (sat <= max_sat)
    out = np.zeros_like(img)
    out[m] = 255
    return out


def second_pass(video: Path, misses: list[dict], words: list[dict], fps: float, ocr=None) -> list[dict]:
    """Read white-only frames around each uncovered spoken word; a run of frames whose white text contains the word
    becomes a caption (MEASURED, 'white-only pass')."""
    if ocr is None:
        from rapidocr import RapidOCR
        ocr = RapidOCR(params={"Global.log_level": "critical"})
    found, done = [], set()
    for m in misses:
        if any(f in done for f in range(m["frame"] - 3, m["frame"] + 4)):
            continue
        a = max(0, m["frame"] - 8)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a / fps:.4f}", "-i", str(video), "-frames:v", "48", "-vf", f"scale={W}:{H}",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
        hits = []
        for k in range(0, len(frames), 2):
            r = ocr(white_only(frames[k]))
            for box, txt, score in zip(r.boxes if r.boxes is not None else [], r.txts or [], r.scores or []):
                b = np.asarray(box)
                x0, y0 = b.min(0)
                x1, y1 = b.max(0)
                cy = (y0 + y1) / 2
                if score >= 0.6 and BAND[0] <= cy <= BAND[1] and _letters(m["text"]) in _letters(txt):
                    hits.append((a + k, txt.strip(), [float(x0), float(y0), float(x1), float(y1)]))
        if not hits:
            continue
        from collections import Counter
        text = Counter(h[1] for h in hits).most_common(1)[0][0]
        same = [h for h in hits if h[1] == text]
        t0, t1 = same[0][0] / fps - 1.5, same[-1][0] / fps + 1.5
        spoken = [w["text"] for w in words if t0 <= w["start"] <= t1]
        box = np.median(np.array([h[2] for h in same]), axis=0)
        found.append({"text": respace(text, spoken), "read_as": text, "first": same[0][0], "last": same[-1][0] + 1, "frames": same[-1][0] + 2 - same[0][0],
                      "agreement": round(len(same) / len(hits), 2), "box": [round(float(v), 1) for v in box], "transcript_support": None,
                      "readings": len(hits), "status": "CAPTION (white-only pass)", "for_word": m["text"]})
        done.update(range(same[0][0], same[-1][0] + 2))
    return found
