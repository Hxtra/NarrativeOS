"""Which font each caption word is set in, and where each word sits (MEASURED by render-and-compare).

The edit mixes two faces inside one caption ("fab" heavy sans + "built?" italic serif). For a caption line, every
assignment of the two faces to its words is rendered (PIL, the same installed fonts EffectCraft uses), scaled so its
ink is as wide as the caption's measured ink, and compared with the white-text mask of the reference frame
(intersection over union, best small shift). The best assignment wins; its margin over the runner-up is the
confidence. Each word's ink box, the font size and the baseline come from the winning render.
"""
from __future__ import annotations

import itertools

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = {"serif": r"C:\Windows\Fonts\SCHLBKBI.TTF", "sans": r"C:\Windows\Fonts\FRAHV.TTF"}
BASE = {"serif": 47.0, "sans": 54.0}      # sizes that matched the "into this" caption together (MEASURED)
GAP = 14                                   # px between words at those sizes (MEASURED on "into this")


def white_mask(img: np.ndarray, box, pad: int = 14, k: int = 17, thr: int = 40) -> tuple[np.ndarray, tuple[int, int]]:
    """Thin, bright, unsaturated strokes: a white top-hat on the minimum channel keeps text strokes and drops broad
    bright areas of the picture (MEASURED: separates captions on bright backgrounds that a plain white test merges)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(img.shape[1], x1 + pad), min(img.shape[0], y1 + pad)
    crop = img[y0:y1, x0:x1]
    g = crop.min(axis=2).astype(np.uint8)
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    sat = crop.max(axis=2).astype(np.int16) - crop.min(axis=2)
    return ((th >= thr) & (g >= 150) & (sat <= 60)).astype(np.uint8), (x0, y0)


def split_words(mask: np.ndarray, n: int) -> list[tuple[int, int]] | None:
    """Column ranges of n words: ink columns split at the n-1 widest gaps."""
    cols = np.where(mask.sum(axis=0) > 0)[0]
    if len(cols) == 0:
        return None
    runs, start = [], cols[0]
    for a, b in zip(cols, cols[1:]):
        if b - a > 1:
            runs.append((start, a))
            start = b
    runs.append((start, cols[-1]))
    if len(runs) < n:
        return None
    gaps = sorted(range(len(runs) - 1), key=lambda i: -(runs[i + 1][0] - runs[i][1]))[: n - 1]
    cut = sorted(gaps)
    out, s = [], runs[0][0]
    for i in cut:
        out.append((s, runs[i][1]))
        s = runs[i + 1][0]
    out.append((s, runs[-1][1]))
    return out


WORD_IOU, WORD_MARGIN = 0.45, 0.08   # a word's face is MEASURED only above both; otherwise UNCERTAIN


def _strip_punct(seg: np.ndarray, word: str) -> tuple[np.ndarray, str]:
    """Compare letters only: drop trailing punctuation from the word and the rightmost small blob from the ink."""
    core = word.rstrip(".,!?;:'\"”’")
    if core == word or not core:
        return seg, word
    n, lab, st, _ = cv2.connectedComponentsWithStats(seg.astype(np.uint8))
    if n > 2:
        right = max(range(1, n), key=lambda i: st[i, cv2.CC_STAT_LEFT])
        if st[right, cv2.CC_STAT_AREA] < 0.12 * seg.sum():
            seg = seg.copy()
            seg[lab == right] = 0
    return seg, core


def word_face(seg: np.ndarray, word: str) -> dict:
    """Score each face on one word: render it, scale to the word's ink width, best small shift, IoU."""
    seg, word = _strip_punct(seg, word)
    ys, xs = np.nonzero(seg)
    seg = seg[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = seg.shape
    scores = {}
    for face in ("serif", "sans"):
        fo = ImageFont.truetype(FONTS[face], 120)
        b = fo.getbbox(word)
        im = Image.new("L", (b[2] - b[0] + 8, b[3] - b[1] + 8), 0)
        ImageDraw.Draw(im).text((4 - b[0], 4 - b[1]), word, font=fo, fill=255)
        a = (np.asarray(im) > 127).astype(np.uint8)
        ya, xa = np.nonzero(a)
        a = a[ya.min():ya.max() + 1, xa.min():xa.max() + 1]
        sc = w / a.shape[1]
        a = (cv2.resize(a * 255, (w, max(1, int(round(a.shape[0] * sc)))), interpolation=cv2.INTER_AREA) > 127).astype(np.uint8)
        best = 0.0
        H = max(a.shape[0], h) + 8
        for dy in range(-4, 5):
            A = np.zeros((H, w), np.uint8)
            B = np.zeros((H, w), np.uint8)
            top = 4 + dy + (h - a.shape[0]) // 2
            if top < 0 or top + a.shape[0] > H:
                continue
            A[top:top + a.shape[0]] = a
            B[4:4 + h] = seg
            best = max(best, (A & B).sum() / max(1, (A | B).sum()))
        scores[face] = (round(float(best), 3), round(float(a.shape[0] / max(1, h)), 2))
    face = max(scores, key=lambda f: scores[f][0])
    other = "sans" if face == "serif" else "serif"
    iou, margin = scores[face][0], round(scores[face][0] - scores[other][0], 3)
    return {"face": face, "iou": iou, "margin": margin, "scores": scores,
            "status": "MEASURED" if iou >= WORD_IOU and margin >= WORD_MARGIN else "UNCERTAIN"}


def render(words: list[str], faces: tuple[str, ...], scale: float) -> tuple[np.ndarray, list[tuple[int, int, int, int]], int]:
    """Binary ink of the line, each word's ink box in line pixels, and the baseline y."""
    fonts = [ImageFont.truetype(FONTS[f], max(6, int(round(BASE[f] * scale)))) for f in faces]
    widths = [fo.getbbox(w, anchor="ls") for fo, w in zip(fonts, words)]
    gap = GAP * scale
    total = sum(b[2] - b[0] for b in widths) + gap * (len(words) - 1)
    asc = max(-b[1] for b in widths) + 4
    desc = max(b[3] for b in widths) + 4
    im = Image.new("L", (int(total + 8), int(asc + desc)), 0)
    d = ImageDraw.Draw(im)
    x, boxes = 4.0, []
    for fo, w, b in zip(fonts, words, widths):
        d.text((x - b[0], asc), w, font=fo, fill=255, anchor="ls")
        boxes.append((int(x), int(asc + b[1]), int(x + b[2] - b[0]), int(asc + b[3])))
        x += (b[2] - b[0]) + gap
    return (np.asarray(im) > 127).astype(np.uint8), boxes, int(asc)


def _ink_box(m: np.ndarray):
    ys, xs = np.nonzero(m)
    return (xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else None


def classify(img: np.ndarray, text: str, box) -> dict:
    """Per-word faces when the words can be separated in the mask (preferred), else the whole-line comparison."""
    words = text.split()
    mask, (ox, oy) = white_mask(img, box)
    segs = split_words(mask, len(words)) if words else None
    if segs and mask.sum() >= 40:
        per = []
        for w, (a, b) in zip(words, segs):
            seg = mask[:, a:b + 1]
            if seg.sum() < 15:
                per = []
                break
            per.append(word_face(seg, w) | {"text": w, "x": [int(ox + a), int(ox + b)]})
        if per:
            iou = float(np.mean([p["iou"] for p in per]))
            ys = np.nonzero(mask)[0]
            return {"status": "MEASURED", "method": "per word", "faces": [p["face"] for p in per], "iou": round(iou, 3),
                    "margin": round(min(p["margin"] for p in per), 3), "words": per,
                    "ink_y": [int(oy + ys.min()), int(oy + ys.max())]}
    return classify_line(img, text, box)


def classify_line(img: np.ndarray, text: str, box) -> dict:
    words = text.split()
    if not words or len(words) > 5:
        return {"status": "NOT_MEASURED", "reason": "no words or more than 5"}
    mask, (ox, oy) = white_mask(img, box)
    ib = _ink_box(mask)
    if ib is None or mask.sum() < 40:
        return {"status": "NOT_MEASURED", "reason": "no white text pixels in the caption box"}
    tw = ib[2] - ib[0] + 1
    target = mask[ib[1]:ib[3] + 1, ib[0]:ib[2] + 1]
    results = []
    for faces in itertools.product(("serif", "sans"), repeat=len(words)):
        ink, wboxes, base = render(words, faces, 1.0)
        rb = _ink_box(ink)
        scale = tw / (rb[2] - rb[0] + 1)
        ink, wboxes, base = render(words, faces, scale)
        rb = _ink_box(ink)
        r = ink[rb[1]:rb[3] + 1, rb[0]:rb[2] + 1]
        best = 0.0
        H = max(r.shape[0], target.shape[0]) + 6
        for dy in range(-3, 4):
            A = np.zeros((H, max(r.shape[1], target.shape[1]) + 2), np.uint8)
            B = np.zeros_like(A)
            A[3 + max(0, dy):3 + max(0, dy) + r.shape[0], :r.shape[1]] = r[:A.shape[0] - 3 - max(0, dy)]
            B[3:3 + target.shape[0], :target.shape[1]] = target
            iou = (A & B).sum() / max(1, (A | B).sum())
            best = max(best, iou)
        results.append((best, faces, scale, wboxes, base, rb))
    results.sort(key=lambda r: -r[0])
    iou, faces, scale, wboxes, base, rb = results[0]
    margin = iou - results[1][0] if len(results) > 1 else iou
    # word boxes and baseline in frame pixels (render ink box aligned to the measured ink box)
    sx, sy = ox + ib[0] - rb[0], oy + ib[1] - rb[1]
    return {"status": "MEASURED", "faces": list(faces), "iou": round(float(iou), 3), "margin": round(float(margin), 3),
            "sizes": [round(BASE[f] * scale, 1) for f in faces], "baseline_y": round(float(sy + base), 1),
            "words": [{"text": w, "face": f, "box": [int(sx + b[0]), int(sy + b[1]), int(sx + b[2]), int(sy + b[3])]}
                      for w, f, b in zip(words, faces, wboxes)]}


MEASURED_IOU = 0.45     # below this the white text could not be separated from the picture: UNCERTAIN


def classify_run(frames: dict, cap: dict, samples: int = 8) -> dict:
    """Per word, its cleanest frame: every frame of the caption is measured and each word keeps the frame where its
    own face was decided with the highest overlap (a word unreadable over one shot can be clean over the next)."""
    span = list(range(cap["first"], cap["last"] + 1))
    results = []
    for f in span:
        if f in frames:
            r = classify(frames[f], cap["text"], cap["box"])
            if r.get("status") == "MEASURED" and r.get("method") == "per word":
                results.append((f, r))
    if not results:
        return classify_run_line(frames, cap, samples)
    n = len(results[0][1]["words"])
    words = []
    for i in range(n):
        f, r = max(((f, r) for f, r in results if len(r["words"]) == n), key=lambda fr: fr[1]["words"][i]["iou"])
        words.append(r["words"][i] | {"frame": f})
    base = max(results, key=lambda fr: fr[1]["iou"])
    return {"status": "MEASURED", "method": "per word", "faces": [w["face"] for w in words], "words": words,
            "iou": round(float(np.mean([w["iou"] for w in words])), 3), "frame": base[0], "ink_y": base[1]["ink_y"]}


def classify_run_line(frames: dict, cap: dict, samples: int = 8) -> dict:
    """The same caption is often held across several shots: measure it on up to `samples` of its frames and keep
    the cleanest (highest overlap). frames: frame number -> RGB image."""
    span = list(range(cap["first"], cap["last"] + 1))
    pick = span if len(span) <= samples else [span[int(i * (len(span) - 1) / (samples - 1))] for i in range(samples)]
    best = None
    for f in pick:
        if f not in frames:
            continue
        r = classify(frames[f], cap["text"], cap["box"])
        if r.get("status") == "MEASURED" and (best is None or r["iou"] > best["iou"]):
            best = r | {"frame": f}
    if best is None:
        return {"status": "NOT_MEASURED", "reason": "no measurable frame"}
    if best["iou"] < MEASURED_IOU:
        best["status"] = "UNCERTAIN"
    return best


def word_layout(word: str, face: str, ink_x: tuple[int, int], ink_y: tuple[int, int]) -> dict:
    """Font size, text origin x and baseline y that put this word's ink exactly at ink_x / ink_y (frame pixels)."""
    core = word
    fo = ImageFont.truetype(FONTS[face], 100)
    l, t, r, b = fo.getbbox(core, anchor="ls")          # ink relative to (origin, baseline) at size 100
    scale = (ink_x[1] - ink_x[0] + 1) / max(1, r - l)
    size = 100 * scale
    return {"text": word, "face": face, "size": round(size, 1), "x": round(ink_x[0] - l * scale, 1), "baseline": round(ink_y[1] - b * scale, 1)}


def face_by_width(word: str, ink_w: float, sizes: dict) -> dict:
    """At the edit's fixed sizes (MEASURED), a word's ink width alone tells its face: the sans is much wider.
    MEASURED when the better face is within 8 % and the other is at least 15 % off; otherwise UNCERTAIN."""
    errs = {}
    for face, size in sizes.items():
        fo = ImageFont.truetype(FONTS[face], max(6, int(round(size))))
        l, t, r, b = fo.getbbox(word.rstrip(".,!?;:'\"”’") or word, anchor="ls")
        errs[face] = abs(np.log(max(1, r - l) / max(1, ink_w)))
    face = min(errs, key=errs.get)
    other = max(errs, key=errs.get)
    ok = errs[face] <= 0.08 and errs[other] >= 0.15
    return {"face": face, "status": "MEASURED (width at fixed size)" if ok else "UNCERTAIN",
            "width_error": {k: round(float(v), 3) for k, v in errs.items()}}


def word_layout_fixed(word: str, face: str, size: float, ink_x: tuple[int, int], ink_bottom: int) -> dict:
    """Origin x and baseline for a word set at a fixed size, its ink centred on the measured ink."""
    fo = ImageFont.truetype(FONTS[face], max(6, int(round(size))))
    l, t, r, b = fo.getbbox(word, anchor="ls")
    cx = (ink_x[0] + ink_x[1]) / 2
    return {"size": size, "x": round(cx - (l + r) / 2, 1), "baseline": round(ink_bottom - b, 1)}
