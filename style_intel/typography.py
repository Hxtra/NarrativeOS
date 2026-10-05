"""On-screen text in a video: what it says, where, how big, what colour, how it animates in and out,
and what effects hit it, with every claim tied to a measurement.

    texts = typography.analyze(video, src)   # used by `python -m style_intel breakdown`

How:
1. OCR (RapidOCR: PaddleOCR's detection and recognition models run locally on onnxruntime) finds text
   boxes on frames sampled at TYPO_DEFAULTS["sample_fps"]. Recognition only runs when a box is new or
   has changed, so a static paragraph is read once, not on every frame.
2. Boxes are linked over time into tracks: one per line of text. Containment also links, so a type-on
   title whose box grows from "MB" to "MY WILDERNESS" stays one track. Start and end are refined to the
   frame by bisection.
3. The first and last second of each track are measured on EVERY frame, inside the text box: how much
   text is there (edge energy), whether the red and blue channels have split, whether the box's bands tear.
4. Rules turn those numbers into animations (type-on, fade, slide, scale, tracking, cut) and effects
   (rgb split, glitch tear). Text, position, size and colour are MEASURED; animations and effects are
   INFERRED from the numbers kept in their evidence. The font family is NOT_MEASURED.

The recognised text is stored in the breakdown (it is needed to say "the title reads X"); Style DNA does
not store it.
"""
from __future__ import annotations

import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np

from .media import frame_at

TYPO_DEFAULTS = {
    "sample_fps": 4.0,            # OCR detection rate; boundaries are then refined to the frame
    "det_long_side": 960,         # detector input cap (the default upscales the short side to 736: 4x slower)
    "min_det_score": 0.6,
    "min_rec_score": 0.6,
    "link_iou": 0.3,              # boxes this overlapping are the same text line ...
    "link_containment": 0.6,      # ... or one this much inside the other (type-on growth)
    "max_gap_samples": 1,         # a line may vanish for one sample (glitch frames) and still be one track
    "reread_every_sec": 1.0,      # ... and at least this often, so a line's text is a vote between real readings
    "reread_settle_sec": 1.0,     # ... and on every sample for this long after the box last changed
    "reread_change": 0.25,        # re-run recognition when a box edge moves by this share of its height (type-on growth),
                                  # not on a pixel of jitter: small static text would otherwise be re-read every sample
    "anim_window_sec": 1.0,       # in/out animations are measured within this of a track's start/end
    "fade_min_frames": 3,         # rising from 20 % to 80 % of the text's edge energy over >= this many frames
    "slide_min_frac": 0.03,       # centre moves this share of the frame during the in/out window
    "scale_min_change": 0.1,      # box height changes this much
    "tracking_min_change": 0.1,   # width per character changes this much at a steady height
    "typeon_min_growth": 1.5,     # character count grows by this factor across >= 2 samples
    "text_rgb_min_px": 1.2,       # red/blue edge displacement inside the text box (box scaled to 320 wide)
    "text_tear_min_px": 6.0,      # band-to-band shift spread inside the text box (box scaled to 320 wide)
    "persistent_share": 0.8,      # on screen for this share of the video: a static overlay, not an animated title
    "block_start_sec": 1.0,       # lines starting this close together and stacked form one text block
    "merge_text_similarity": 0.75,  # two tracks reading this alike, in the same place, are one line that OCR lost for a while
    "merge_gap_sec": 3.0,
    "merge_move_gap_sec": 0.35,   # ... and across a gap this short the line may also have moved (a title sliding up)
    "same_reading": 0.9,          # geometry (slide, scale, tracking) is only compared between samples reading this alike
    "text_fx_over_frame": 2.0,    # an effect is ON THE TEXT only if this much stronger in its box than across the frame
    "cover_max_sec": 0.25,        # text only in the first frames: the export's cover/thumbnail frame
    "region_line_px": 32,         # region checks downscale so the line is about this tall: detection cost follows width
}

ENGINE = None


def engine(cfg: dict):
    """The OCR engine, or None when RapidOCR is not installed (typography is then NOT_MEASURED)."""
    global ENGINE
    if ENGINE is None:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            return None
        ENGINE = RapidOCR(params={"Global.log_level": "critical", "Det.limit_type": "max",
                                  "Det.limit_side_len": cfg["det_long_side"], "Global.min_side_len": 0})
    return ENGINE


def _decode_size(src: dict, long_side: int = 1280) -> tuple[int, int]:
    k = min(1.0, long_side / max(src["width"], src["height"]))
    return int(round(src["width"] * k / 2) * 2), int(round(src["height"] * k / 2) * 2)


def detect(ocr, rgb: np.ndarray, cfg: dict) -> list[tuple[float, float, float, float]]:
    d = ocr(rgb, use_det=True, use_cls=False, use_rec=False)
    if d.boxes is None:
        return []
    out = []
    for box, score in zip(d.boxes, d.scores):
        if score >= cfg["min_det_score"]:
            x0, y0 = box.min(0)
            x1, y1 = box.max(0)
            out.append((float(x0), float(y0), float(x1), float(y1)))
    return out


def read(ocr, rgb: np.ndarray, box, cfg: dict) -> tuple[str, float]:
    h, w = rgb.shape[:2]
    pad = 0.15 * (box[3] - box[1])
    x0, y0 = max(0, int(box[0] - pad)), max(0, int(box[1] - pad))
    x1, y1 = min(w, int(box[2] + pad)), min(h, int(box[3] + pad))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return "", 0.0
    r = ocr(rgb[y0:y1, x0:x1], use_det=False, use_cls=False, use_rec=True)
    if not r.txts:
        return "", 0.0
    return str(r.txts[0]).strip(), float(r.scores[0])


def _iou(a, b) -> tuple[float, float]:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    aa, ab = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(aa + ab - inter, 1e-6), inter / max(min(aa, ab), 1e-6)


def _changed(a, b, frame_w: float, frac: float) -> bool:
    return any(abs(x - y) > max(frac * (a[3] - a[1]), 0.01 * frame_w) for x, y in zip(a, b))


def scan(path: Path, src: dict, cfg: dict, ocr) -> tuple[list[dict], tuple[int, int]]:
    """Text tracks from OCR on sampled frames."""
    fps = src["fps"] or 30.0
    step = max(1, int(round(fps / cfg["sample_fps"])))
    w, h = _decode_size(src)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", f"select='not(mod(n\\,{step}))',scale={w}:{h}",
                             "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = w * h * 3
    tracks: list[dict] = []
    k = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            rgb = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            t = k * step / fps
            boxes = detect(ocr, rgb, cfg)
            live = [tr for tr in tracks if k - tr["last_k"] <= cfg["max_gap_samples"] + 1]
            used: set[int] = set()
            for box in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
                best, best_v = None, 0.0
                for i, tr in enumerate(live):
                    if i in used:
                        continue
                    iou, cont = _iou(box, tr["samples"][-1]["box"])
                    v = max(iou / cfg["link_iou"], cont / cfg["link_containment"])
                    if v >= 1.0 and v > best_v:
                        best, best_v = i, v
                prev = live[best]["samples"][-1] if best is not None else None
                # Re-read when the box changes, and anyway once per reread_every_sec: copied readings would let
                # the first (perhaps glitched) frame of a line win the vote for its text.
                # Text keeps changing for a moment after its box stops growing (a last letter glitching in), so
                # every sample is read until the box has held still for reread_settle_sec.
                changed = prev is None or _changed(box, prev["box"], w, cfg["reread_change"])
                changed_t = round(t, 3) if changed else prev.get("changed_t", prev["t"])
                stale = prev is not None and t - prev.get("read_t", prev["t"]) >= cfg["reread_every_sec"]
                settling = t - changed_t <= cfg["reread_settle_sec"]
                if changed or stale or settling or not prev["text"]:
                    text, score, read_t = *read(ocr, rgb, box, cfg), round(t, 3)
                else:
                    text, score, read_t = prev["text"], prev["score"], prev.get("read_t", prev["t"])
                sample = {"t": round(t, 3), "k": k, "box": box, "text": text, "score": score, "read_t": read_t, "changed_t": changed_t}
                if best is None:
                    tracks.append({"samples": [sample], "last_k": k})
                else:
                    used.add(best)
                    live[best]["samples"].append(sample)
                    live[best]["last_k"] = k
            k += 1
    finally:
        proc.stdout.close()
        proc.wait()
    for tr in tracks:
        tr["step_sec"] = step / fps

    def keep(tr: dict) -> bool:
        good = [s for s in tr["samples"] if s["score"] >= cfg["min_rec_score"] and s["text"]]
        if not good:
            return False
        # One sample is usually OCR noise on a busy or glitching frame; keep it only if it reads cleanly.
        return len(tr["samples"]) >= 2 or any(s["score"] >= 0.9 and len(_alnum(s["text"])) >= 3 for s in good)

    return [tr for tr in tracks if keep(tr)], (w, h)


def _reading(samples: list[dict], cfg: dict) -> str:
    """A line's text: the most frequent full-length reading (glitch variants and partial type-on reads lose)."""
    read = [x for x in samples if x.get("read_t", x["t"]) == x["t"]] or samples  # real readings only, not copies
    good = [x for x in read if x["text"] and x["score"] >= cfg["min_rec_score"]] or read
    longest = max(len(_alnum(x["text"])) for x in good)
    full = [x for x in good if len(_alnum(x["text"])) >= 0.8 * longest]
    counts: dict[str, list[float]] = {}
    for x in full:
        counts.setdefault(x["text"], []).append(x["score"])
    return max(counts, key=lambda t: (len(counts[t]), max(counts[t])))


def merge_tracks(tracks: list[dict], cfg: dict) -> list[dict]:
    """Join tracks of one line that OCR lost for a while (bright frames, montages) or that moved after a short gap."""
    tracks = sorted(tracks, key=lambda tr: tr["samples"][0]["t"])
    merged: list[dict] = []
    for tr in tracks:
        text = _reading(tr["samples"], cfg)
        b = tr["samples"][0]["box"]
        target = None
        for m in reversed(merged):
            gap = tr["samples"][0]["t"] - m["samples"][-1]["t"]
            # A small overlap is allowed too: OCR sometimes starts a second track of a line it has not yet lost.
            if gap <= -1.0 or gap > cfg["merge_gap_sec"] or similar(text, m["text"]) < cfg["merge_text_similarity"]:
                continue
            mb = m["samples"][-1]["box"]
            lh = max(b[3] - b[1], mb[3] - mb[1])
            ratio = (b[3] - b[1]) / max(1e-6, mb[3] - mb[1])
            dy = abs((b[1] + b[3]) / 2 - (mb[1] + mb[3]) / 2)
            in_place = dy <= lh and 0.6 <= ratio <= 1.6
            if in_place or gap <= cfg["merge_move_gap_sec"]:
                target = m
                break
        if target is None:
            merged.append({**tr, "text": text})
        else:
            target["samples"].extend(tr["samples"])
            target["text"] = _reading(target["samples"], cfg)
    return merged


def detect_region(ocr, rgb: np.ndarray, box, cfg: dict, width_margin: float = 1.0, height_margin: float = 0.6) -> list[tuple]:
    """Detection near one line only: its row band, its width plus `width_margin` widths either side, downscaled so
    the line is about region_line_px tall. Boxes come back in frame coordinates."""
    h, w = rgb.shape[:2]
    bh, bw = box[3] - box[1], box[2] - box[0]
    x0, x1 = max(0, int(box[0] - width_margin * bw)), min(w, int(box[2] + width_margin * bw))
    y0, y1 = max(0, int(box[1] - height_margin * bh)), min(h, int(box[3] + height_margin * bh))
    crop = rgb[y0:y1, x0:x1]
    if crop.shape[0] < 8 or crop.shape[1] < 8:
        return []
    k = min(1.0, cfg["region_line_px"] / max(1.0, bh))
    if k < 1.0:
        crop = cv2.resize(crop, (max(8, int(crop.shape[1] * k)), max(8, int(crop.shape[0] * k))), interpolation=cv2.INTER_AREA)
    return [(d[0] / k + x0, d[1] / k + y0, d[2] / k + x0, d[3] / k + y0) for d in detect(ocr, crop, cfg)]


def _present_in(ocr, rgb: np.ndarray, box, cfg: dict) -> bool:
    """Is this line on screen in this frame? Detection runs near the box only, not on the whole frame."""
    found = detect_region(ocr, rgb, box, cfg, width_margin=0.5, height_margin=1.0)
    return any(_iou(b, box)[1] >= cfg["link_containment"] or _iou(b, box)[0] >= cfg["link_iou"] for b in found)


def refine(ocr, path: Path, src: dict, tr: dict, size: tuple[int, int], cfg: dict) -> tuple[float, float]:
    """Frame-accurate first and last frame of a track, by bisection between samples."""
    fps = src["fps"] or 30.0
    first, last = tr["samples"][0], tr["samples"][-1]
    step = int(round(tr["step_sec"] * fps))

    def bisect(lo: int, hi: int, box, appearing: bool) -> int:
        # lo: frame where the state is "before", hi: frame where it is "after". The gap is decoded once.
        frames = _decode_window(path, lo / fps, (hi + 1) / fps, size)
        a, b = 0, min(hi - lo, len(frames) - 1)
        while b - a > 1:
            mid = (a + b) // 2
            if _present_in(ocr, frames[mid], box, cfg) == appearing:
                b = mid
            else:
                a = mid
        return lo + b

    f0 = first["k"] * step
    start = bisect(f0 - step, f0, first["box"], True) / fps if f0 > 0 else 0.0
    f1 = last["k"] * step
    total = int(src["duration_sec"] * fps)
    end = (bisect(f1, min(total, f1 + step), last["box"], False) / fps) if f1 + step < total else src["duration_sec"]
    return round(start, 3), round(end, 3)


def _decode_window(path: Path, t0: float, t1: float, size: tuple[int, int]) -> list[np.ndarray]:
    w, h = size
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{max(0.04, t1 - t0):.3f}", "-i", str(path), "-an",
                          "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    n = len(raw) // (w * h * 3)
    return [np.frombuffer(raw[i * w * h * 3 : (i + 1) * w * h * 3], np.uint8).reshape(h, w, 3) for i in range(n)]


def _crop(rgb: np.ndarray, box, pad: float = 0.2) -> np.ndarray:
    h, w = rgb.shape[:2]
    p = pad * (box[3] - box[1])
    return rgb[max(0, int(box[1] - p)) : min(h, int(box[3] + p)), max(0, int(box[0] - p)) : min(w, int(box[2] + p))]


def _norm320(img: np.ndarray) -> np.ndarray:
    k = 320 / max(1, img.shape[1])
    return cv2.resize(img, (320, max(8, int(img.shape[0] * k))), interpolation=cv2.INTER_AREA)


def _band_box(ocr, rgb: np.ndarray, box, cfg: dict):
    """Where the line is in this frame: detection in the line's neighbourhood only, merged into one box."""
    # Only detections on this line's own row: stacked lines above and below are other lines, not this one growing.
    found = [d for d in detect_region(ocr, rgb, box, cfg)
             if min(d[3], box[3]) - max(d[1], box[1]) >= 0.5 * min(d[3] - d[1], box[3] - box[1])]
    if not found:
        return None
    return (min(d[0] for d in found), min(d[1] for d in found), max(d[2] for d in found), max(d[3] for d in found))


def edge_box(ocr, signals: list[dict], frames: list[np.ndarray], box, cfg: dict, entering: bool):
    """The line's box at the first frame it is legible (entering) or the last (leaving): half its final edge energy.
    One detection per window, where the motion of a slide or scale is still visible."""
    if not signals:
        return None
    e = np.array([x["energy"] for x in signals])
    order = range(len(e)) if entering else range(len(e) - 1, -1, -1)
    seq = e if entering else e[::-1]
    base, plateau = float(seq[:3].min()), float(np.median(seq[len(seq) // 2 :]))
    if plateau - base <= 1.0:
        return None
    for i in order:
        if e[i] >= base + 0.5 * (plateau - base):
            return _band_box(ocr, frames[i], box, cfg)
    return None


def window_signals(path: Path, t0: float, t1: float, box, size: tuple[int, int], fps: float) -> tuple[list[dict], list[np.ndarray]]:
    """Per frame inside the text box: edge energy (how much text shows), red/blue split, band tear.
    The decoded frames come back too, so the edge frame's box can be measured without decoding again."""
    from .breakdown import channel_misregistration

    out, prev = [], None
    decoded = _decode_window(path, t0, t1, size)
    for i, rgb in enumerate(decoded):
        crop = _norm320(_crop(rgb, box))
        g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
        energy = float(cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)).mean())
        rgbm = channel_misregistration(crop)
        # The whole frame is only measured when the text box shows a split, to tell the two apart.
        frame_rgb = channel_misregistration(_norm320(rgb))["rgb_mag"] if rgbm["rgb_mag"] >= 1.0 else 0.0
        tear, box_shift = 0.0, 0.0
        if prev is not None and prev.shape == g.shape and g.shape[0] >= 16:
            (gdx, gdy), _ = cv2.phaseCorrelate(prev, g, cv2.createHanningWindow((g.shape[1], g.shape[0]), cv2.CV_32F))
            box_shift = float(np.hypot(gdx, gdy))
            shifts = []
            bands = 4
            bh = g.shape[0] // bands
            win = cv2.createHanningWindow((g.shape[1], bh), cv2.CV_32F)
            for j in range(bands):
                a, z = j * bh, (j + 1) * bh
                (dx, _), resp = cv2.phaseCorrelate(prev[a:z], g[a:z], win)
                k = int(round(dx))
                if resp < 0.1 or abs(k) >= g.shape[1] // 3:
                    continue
                if abs(k) >= 2:
                    m = abs(k) + 2
                    e0 = float(np.abs(prev[a:z, m:-m] - g[a:z, m:-m]).mean())
                    e1 = float(np.abs(np.roll(prev[a:z], k, axis=1)[:, m:-m] - g[a:z, m:-m]).mean())
                    if e0 < 1.0 or e1 > 0.6 * e0:
                        continue
                shifts.append(dx)
            if len(shifts) >= 3:
                tear = float(max(shifts) - min(shifts))
        out.append({"t": round(t0 + i / fps, 3), "energy": energy, "rgb": rgbm["rgb_mag"], "frame_rgb": frame_rgb,
                    "rgb_coherent": max(float(np.hypot(rgbm["rgb_dx"], rgbm["rgb_dy"])), abs(rgbm["rgb_radial"])) / max(rgbm["rgb_mag"], 1e-6),
                    "tear": tear, "box_shift": box_shift})
        prev = g
    return out, decoded


def _alnum(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", s)


def animation(samples: list[dict], signals: list[dict], frame: tuple[int, int], cfg: dict, entering: bool,
              text: str = "", ref_box=None, first_box=None) -> dict:
    """How a line comes in (entering) or goes out, from OCR samples and per-frame signals in the window.

    Type-on/off comes from the character count growing. Slide, scale and tracking compare the box at the
    edge of the window with the settled box, using only samples that read the line's full text: while the
    text itself is changing, its box changes too, and that is not motion."""
    kinds, ev = [], {}
    seq = samples if entering else samples[::-1]  # always read from the edge inward
    if len(seq) >= 2:
        lens = [len(_alnum(x["text"])) for x in seq]
        # Typing reveals the START of the line first; text sliding or wiping in from the left reveals its END first.
        full_t = _alnum(text).upper()
        partial = [_alnum(x["text"]).upper() for x in seq if 0 < len(_alnum(x["text"])) < len(full_t)]
        prefix = sum(SequenceMatcher(None, q, full_t[: len(q)]).ratio() >= SequenceMatcher(None, q, full_t[-len(q):]).ratio() for q in partial)
        if partial:
            ev["partial_readings"] = "prefixes" if prefix * 2 >= len(partial) else "suffixes"
        if (lens[0] > 0 and lens[-1] >= cfg["typeon_min_growth"] * lens[0] and all(b2 >= a2 for a2, b2 in zip(lens, lens[1:]))
                and ev.get("partial_readings", "prefixes") == "prefixes"):
            dt = abs(seq[-1]["t"] - seq[0]["t"]) or 1e-6
            kinds.append("type_on" if entering else "type_off")
            ev["characters"] = [lens[0], lens[-1]]
            ev["chars_per_sec"] = round((lens[-1] - lens[0]) / dt, 1)
    same = [x["box"] for x in seq if text and similar(x["text"], text) >= cfg["same_reading"]]
    edge_boxes = [first_box] if first_box is not None else same
    dense = first_box is not None
    if edge_boxes and ref_box is not None and "type_on" not in kinds and "type_off" not in kinds:
        b0, b1 = edge_boxes[0], ref_box
        W, H = frame
        # Text entering from off-screen is clipped at the frame edge: measure the edge that is still free.
        if b0[0] <= 0.01 * W and b0[2] < 0.99 * W:
            dx = (b1[2] - b0[2]) / W
        elif b0[2] >= 0.99 * W and b0[0] > 0.01 * W:
            dx = (b1[0] - b0[0]) / W
        else:
            dx = ((b1[0] + b1[2]) - (b0[0] + b0[2])) / 2 / W
        if b0[1] <= 0.01 * H and b0[3] < 0.99 * H:
            dy = (b1[3] - b0[3]) / H
        elif b0[3] >= 0.99 * H and b0[1] > 0.01 * H:
            dy = (b1[1] - b0[1]) / H
        else:
            dy = ((b1[1] + b1[3]) - (b0[1] + b0[3])) / 2 / H
        h0, h1 = b0[3] - b0[1], b1[3] - b1[1]
        ev["geometry_from"] = "detection at the first legible frame" if dense else "OCR samples"
        if max(abs(dx), abs(dy)) >= cfg["slide_min_frac"] and abs(h1 - h0) <= cfg["scale_min_change"] * h1:
            mx, my = (dx, dy) if entering else (-dx, -dy)
            kinds.append("slide")
            ev["slide_direction"] = ("right" if mx > 0 else "left") if abs(mx) >= abs(my) else ("down" if my > 0 else "up")
            ev["slide_frac"] = round(max(abs(dx), abs(dy)), 3)
        if abs(h1 - h0) >= cfg["scale_min_change"] * max(h0, h1):
            kinds.append("scale")
            ev["edge_scale"] = round(h0 / h1, 2)  # size at the start (in) or end (out) relative to the settled size
    if same and ref_box is not None and "type_on" not in kinds and "type_off" not in kinds:
        b0, b1 = same[0], ref_box
        h0, h1 = b0[3] - b0[1], b1[3] - b1[1]
        n = len(_alnum(text))
        if n >= 3 and abs(h1 - h0) <= 0.05 * h1:
            wpc0, wpc1 = (b0[2] - b0[0]) / n, (b1[2] - b1[0]) / n
            if abs(wpc1 - wpc0) >= cfg["tracking_min_change"] * wpc1:
                kinds.append("tracking")
                ev["tracking_from"] = round(wpc0 / wpc1, 2)
    if signals:
        e = np.array([s["energy"] for s in signals])
        seqe = e if entering else e[::-1]
        plateau = float(np.median(seqe[len(seqe) // 2 :])) if len(seqe) >= 4 else float(seqe.max())
        base = float(seqe[:3].min())
        span = plateau - base
        if span > 1.0:
            lo = int(np.argmax(seqe >= base + 0.2 * span))
            hi = int(np.argmax(seqe >= base + 0.8 * span))
            ramp = max(0, hi - lo)
            ev["energy_ramp_frames"] = ramp
            if ramp >= cfg["fade_min_frames"] and "type_on" not in kinds and "type_off" not in kinds:
                kinds.append("fade")
    if not kinds:
        kinds.append("cut")
    return {"kinds": kinds, "basis": "INFERRED", "evidence": ev}


def effects(signals: list[dict], cfg: dict) -> list[dict]:
    """RGB split or band tearing inside the text box. A tear needs the text fully there in both frames compared:
    the frame where a line cuts in or out differs from the last one everywhere, which is not a tear."""
    out = []
    if signals:
        top = max(x["energy"] for x in signals)
        for prev, cur in zip([None] + signals[:-1], signals):
            # ... and the box as a whole must hold still: a sliding line shifts its text bands against the background.
            if prev is None or min(prev["energy"], cur["energy"]) < 0.6 * top or cur.get("box_shift", 0.0) >= 2.0:
                cur["tear"] = 0.0
    for kind, key, thr in (("rgb_split", "rgb", cfg["text_rgb_min_px"]), ("glitch_tear", "tear", cfg["text_tear_min_px"])):
        # On the text, not the whole frame: a frame-wide RGB split also splits the text, but that is the frame's effect.
        hits = [x for x in signals if x[key] >= thr and (key != "rgb" or (x["rgb_coherent"] >= 0.5 and x["rgb"] >= cfg["text_fx_over_frame"] * x["frame_rgb"]))]
        if hits:
            peak = max(hits, key=lambda s: s[key])
            out.append({"type": kind, "basis": "INFERRED", "start": hits[0]["t"], "end": hits[-1]["t"], "peak": peak["t"],
                        "frames": len(hits), "evidence": {f"max_{key}_px_at_320": round(peak[key], 1), "threshold": thr}})
    return out


def _style(path: Path, t: float, box, size: tuple[int, int]) -> dict:
    """Colour and stroke weight of the text, from the frame where it is fully shown."""
    rgb = cv2.resize(frame_at(path, t, None), size, interpolation=cv2.INTER_AREA)
    crop = _crop(rgb, box, 0.0)
    if crop.size == 0:
        return {}
    g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    border = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]])
    bg = float(np.median(border))
    _, mask = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Text is the class that differs from the border (background).
    if abs(float(g[mask > 0].mean() if (mask > 0).any() else bg) - bg) < abs(float(g[mask == 0].mean() if (mask == 0).any() else bg) - bg):
        mask = 255 - mask
    if not (mask > 0).any():
        return {}
    col = np.median(crop[mask > 0], axis=0).astype(int)
    stroke = float(cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 3).max() * 2) / max(1.0, box[3] - box[1])
    out = {"colour": "#{:02x}{:02x}{:02x}".format(*col), "contrast": round(abs(float(np.median(g[mask > 0])) - bg), 1)}
    if stroke <= 0.5:  # thicker than half the line means the mask caught background, not letters
        out["stroke_to_height"] = round(stroke, 3)
    return out


def _region(cx: float, cy: float) -> str:
    v = "top" if cy < 1 / 3 else ("middle" if cy < 2 / 3 else "bottom")
    hz = "left" if cx < 0.38 else ("center" if cx < 0.62 else "right")
    return f"{v}_{hz}"


def known_templates() -> set[str]:
    root = Path(__file__).parents[1] / "templates/narrativeos-video-templates/project/src/templates"
    ids = set()
    for f in root.glob("*.tsx"):
        ids.update(re.findall(r"registerTemplate<\w+>\(\{\s*id: '([a-z0-9_]+)'", f.read_text(encoding="utf-8")))
    return ids


def template_for(block: dict, templates: set[str]) -> dict:
    """Closest registered text template for a block, from where it sits and how big it is (a candidate, not a finding)."""
    region, h = block["region"], block["height_frac"]
    if block["persistent"]:
        cand, why = None, "static overlay text for the whole video"
    elif region.startswith("bottom") and h < 0.08:
        cand, why = ["speaker_lower_third", "location_stamp"], "small text in the lower third"
    elif region.startswith("middle") and h >= 0.05:
        cand, why = ["title_card", "chapter_break"], "large text in the middle of the frame"
    elif region.startswith("top"):
        cand, why = ["location_stamp"], "small text near the top"
    else:
        cand, why = ["title_card"], "on-screen title"
    if cand:
        cand = [c for c in cand if c in templates] or None
    return {"candidates": cand, "why": why, "basis": "INFERRED"}


def analyze(path: Path, src: dict, config: dict | None = None) -> dict:
    cfg = {**TYPO_DEFAULTS, **(config or {})}
    ocr = engine(cfg)
    if ocr is None:
        return {"status": "NOT_MEASURED", "reason": "RapidOCR is not installed (pip install rapidocr; see requirements.txt)"}
    import time

    fps = src["fps"] or 30.0
    timing = {}
    t0 = time.time()
    raw, size = scan(path, src, cfg, ocr)
    timing["scan"] = round(time.time() - t0, 1)
    scanned = len(raw)
    raw = merge_tracks(raw, cfg)
    t0 = time.time()
    W, H = size
    templates = known_templates()
    lines = []
    for tr in sorted(raw, key=lambda tr: tr["samples"][0]["t"]):
        tr["samples"].sort(key=lambda x: x["t"])
        text = tr["text"]
        full = max((x for x in tr["samples"] if x["text"] == text), key=lambda x: x["score"])
        start, end = refine(ocr, path, src, tr, size, cfg)
        if len(_alnum(text)) < 2 and end - start < 1.0:
            continue  # a stray letter: a fragment of spaced-out text or OCR noise
        cover = start <= 0.0 and end <= cfg["cover_max_sec"]
        box = full["box"]
        cx, cy = (box[0] + box[2]) / 2 / W, (box[1] + box[3]) / 2 / H
        persistent = (end - start) >= cfg["persistent_share"] * src["duration_sec"]
        if cover:
            lines.append({"id": f"T{len(lines) + 1:03d}", "cover_frame": True, "text": text, "text_basis": "MEASURED (OCR)", "start": start, "end": end,
                          "basis": "MEASURED", "persistent": False, "effects": [], "in": {"kinds": ["cover_frame"], "evidence": {}},
                          "out": {"kinds": ["cover_frame"], "evidence": {}}, "region": "", "height_frac": 0.0, "box_frac": [0, 0, 0, 0],
                          "width_per_char_to_height": 0.0})
            continue
        win = cfg["anim_window_sec"]
        in_s = [x for x in tr["samples"] if x["t"] <= start + win]
        out_s = [x for x in tr["samples"] if x["t"] >= end - win]
        settled = [x for x in tr["samples"] if similar(x["text"], text) >= cfg["same_reading"]] or [full]
        ref_box = tuple(float(np.median([x["box"][i] for x in settled])) for i in range(4))
        sig_in, fr_in = window_signals(path, start - 0.2, min(end, start + win), box, size, fps) if not persistent or start > 0.1 else ([], [])
        sig_out, fr_out = window_signals(path, max(start, end - win), end + 0.2, box, size, fps) if not persistent or end < src["duration_sec"] - 0.1 else ([], [])
        box_in, box_out = edge_box(ocr, sig_in, fr_in, box, cfg, True), edge_box(ocr, sig_out, fr_out, box, cfg, False)
        del fr_in, fr_out
        line = {
            "id": f"T{len(lines) + 1:03d}",
            "cover_frame": cover,
            "text": text, "text_basis": "MEASURED (OCR)", "ocr_score": round(full["score"], 3),
            "readings": [s["text"] for s in tr["samples"]][:40],
            "start": start, "end": end, "basis": "MEASURED",
            "box_frac": [round(box[0] / W, 3), round(box[1] / H, 3), round(box[2] / W, 3), round(box[3] / H, 3)],
            "region": _region(cx, cy), "height_frac": round((box[3] - box[1]) / H, 3),
            "uppercase": bool(_alnum(text)) and _alnum(text).upper() == _alnum(text),
            "width_per_char_to_height": round((box[2] - box[0]) / max(1, len(text.replace(" ", ""))) / max(1.0, box[3] - box[1]), 2),
            "persistent": persistent,
            # Colour from the settled middle of the line, not a sample caught mid-fade.
            **_style(path, min(settled, key=lambda x: abs(x["t"] - (start + end) / 2))["t"], box, size),
            "in": animation(in_s, sig_in, size, cfg, True, text, ref_box, box_in) if not (persistent and start <= 0.1) else {"kinds": ["present_from_start"], "basis": "MEASURED", "evidence": {}},
            "out": animation(out_s, sig_out, size, cfg, False, text, ref_box, box_out) if not (persistent and end >= src["duration_sec"] - 0.1) else {"kinds": ["present_to_end"], "basis": "MEASURED", "evidence": {}},
            "effects": effects(sig_in + sig_out, cfg),
        }
        lines.append(line)
    timing["per_line_analysis"] = round(time.time() - t0, 1)
    lines = drop_fragments(lines)
    blocks = group_blocks(lines, cfg)
    for b in blocks:
        b["template"] = template_for(b, templates)
    return {"status": "MEASURED", "engine": "RapidOCR (PaddleOCR models, onnxruntime)", "config": cfg, "lines": lines, "blocks": blocks,
            "timing_sec": timing, "tracks_scanned": scanned, "tracks_after_merge": len(raw),
            "not_measured": {"font_family": "no font identification", "kerning_detail": "letter spacing is a width-per-character ratio only"}}


def _contained(part: str, whole: str) -> float:
    """How well `part` matches somewhere inside `whole` (best window of the same length)."""
    a, b = _alnum(part).upper(), _alnum(whole).upper()
    if not a or len(a) > len(b):
        return 0.0
    return max(SequenceMatcher(None, a, b[i : i + len(a)]).ratio() for i in range(len(b) - len(a) + 1))


def drop_fragments(lines: list[dict]) -> list[dict]:
    """A line that reads as a piece of another line on screen at the same time, on the same row, is OCR reading
    part of that line on a hard frame (glitch, flash), not a line of its own."""
    keep = []
    for ln in lines:
        frag = any(
            o is not ln and not o.get("cover_frame") and not ln.get("cover_frame")
            and len(_alnum(o["text"])) > len(_alnum(ln["text"]))
            and o["start"] <= ln["start"] and ln["end"] <= o["end"]
            and min(o["box_frac"][3], ln["box_frac"][3]) - max(o["box_frac"][1], ln["box_frac"][1]) > 0
            and _contained(ln["text"], o["text"]) >= 0.8
            for o in lines)
        if not frag:
            keep.append(ln)
    for i, ln in enumerate(keep, 1):
        ln["id"] = f"T{i:03d}"
    return keep


def group_blocks(lines: list[dict], cfg: dict) -> list[dict]:
    """Lines that start together and are stacked form one block (a title with its subtitle, a credit stack)."""
    blocks: list[dict] = []
    for ln in sorted((x for x in lines if not x.get("cover_frame")), key=lambda x: (x["start"], x["box_frac"][1])):
        hit = None
        for b in blocks:
            if b["persistent"] != ln["persistent"] or abs(ln["start"] - b["start"]) > cfg["block_start_sec"]:
                continue
            lh = max(b["height_frac"], ln["height_frac"])
            gap = max(0.0, ln["box_frac"][1] - b["box_frac"][3], b["box_frac"][1] - ln["box_frac"][3])
            overlap_x = min(ln["box_frac"][2], b["box_frac"][2]) - max(ln["box_frac"][0], b["box_frac"][0])
            if gap <= 1.5 * lh and overlap_x > 0:
                hit = b
                break
        if hit is None:
            blocks.append({"lines": [ln["id"]], "start": ln["start"], "end": ln["end"], "box_frac": list(ln["box_frac"]),
                           "height_frac": ln["height_frac"], "persistent": ln["persistent"]})
        else:
            hit["lines"].append(ln["id"])
            hit["end"] = max(hit["end"], ln["end"])
            hit["box_frac"] = [min(hit["box_frac"][0], ln["box_frac"][0]), min(hit["box_frac"][1], ln["box_frac"][1]),
                               max(hit["box_frac"][2], ln["box_frac"][2]), max(hit["box_frac"][3], ln["box_frac"][3])]
            hit["height_frac"] = max(hit["height_frac"], ln["height_frac"])
    for i, b in enumerate(blocks, 1):
        b["id"] = f"B{i:03d}"
        cx, cy = (b["box_frac"][0] + b["box_frac"][2]) / 2, (b["box_frac"][1] + b["box_frac"][3]) / 2
        b["region"] = _region(cx, cy)
    return blocks


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _alnum(a).upper(), _alnum(b).upper()).ratio()
