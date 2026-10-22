"""Which visual element follows which sound, how consistently, and at what scale.

The two "made with Claude, music is code" clips use two different strategies: in the TB-303 smoke the particles flow freely
while particular elements answer particular instruments; in the light painting the whole picture pulses. av_sync.py measures
that a picture follows its sound; this module tells the strategies apart.

Audio LAYERS, per frame (from Demucs stems when available, else band splits of the full mix, flagged as such):
  kick (20-120 Hz onsets of the drums), snare (200-3000 Hz), hats (6-16 kHz), bass (onsets of the bass stem), melody (onsets of the
  "other" stem: synths, pads, leads), vocals (onsets of the vocal stem), energy (loudness of the whole mix).
Visual ELEMENTS, per frame: the whole image, 24 grid regions, and 7 colour elements (bright, saturated pixels of one hue: a
cyan ring and magenta smoke are different elements even where they overlap).

For every layer x element:
- lag inside the sync window (av_sync.SYNC_WINDOW) and correlation against circularly shifted copies (p, chance 95 %);
- consistency: the share of the layer's hits that get a visual response at that lag, against random times:
  consistent (>= 60 % and above chance), intermittent (above chance but < 60 %), coincidental (not above chance);
- scale: beat (frame-level), phrase (curves smoothed over one bar) or energy (the element's brightness against the mix's loudness
  over 2 s), each against its own null.
Then a STRATEGY: whole_image, moving_element (one light carries the beat wherever it goes), element_specific, energy_only or none, with the mapping (layer -> element) as evidence.

Uncertainty is reported, not hidden:
- layers that hit together (kick and bass on the same frames) cannot be told apart; such pairs are flagged and the
  mapping is reported for the pair;
- stems leak, and a band split of a full mix mixes instruments;
- a finished video cannot show whether the animation read a note list or analysed the audio afterwards. Only the observed
  relationship is reported.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from style_intel.av_sync import SR, SYNC_WINDOW, _null, _peaks, _xcorr, _z

HUES = {"red": [(0, 8), (172, 180)], "orange": [(8, 20)], "yellow": [(20, 35)], "green": [(35, 80)], "cyan": [(80, 100)],
        "blue": [(100, 130)], "magenta": [(130, 172)]}
GRID = (6, 4)


# ---------------------------------------------------------------- picture
def picture(video: Path, crop=None, width: int = 160) -> dict:
    """One pass for the crop (auto), one pass for features: grid brightness, colour-element brightness, whole-image brightness."""
    import cv2
    cap = cv2.VideoCapture(str(video)); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if crop == "auto":                                          # rows that move, measured on small frames
        k = 160 / W0; prev = None; act = None
        while True:
            ok, f = cap.read()
            if not ok:
                break
            g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (160, int(H0 * k))).astype(np.float32)
            if prev is not None:
                d = np.abs(g - prev).mean(1); act = d if act is None else act + d
            prev = g
        rows = np.where(act > max(act.max() * 0.08, 0.5))[0] if act is not None else []
        y0, y1 = (int(rows.min() / k), int((rows.max() + 1) / k)) if len(rows) else (0, H0)
        crop = (0, y0, W0, y1 - y0)
        cap.release(); cap = cv2.VideoCapture(str(video))
    gy, gx = GRID; grid, hue, whole, hot, huefrac, change, cam, camfit = [], [], [], [], [], [], [], []; prev = None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if crop:
            x, y, w, h = crop; f = f[y:y + h, x:x + w]
        k = width / f.shape[1]; f = cv2.resize(f, (width, max(1, int(f.shape[0] * k))), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV); H, S, V = hsv[..., 0], hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
        g = V; rows, cols = g.shape
        grid.append([g[i * rows // gy:(i + 1) * rows // gy, j * cols // gx:(j + 1) * cols // gx].mean() for i in range(gy) for j in range(gx)])
        vivid = (S > 0.35) & (V > 0.25)
        masks = [vivid & np.any([(H >= a) & (H < b) for a, b in rr], axis=0) for rr in HUES.values()]
        hue.append([float((V * m).mean()) for m in masks]); huefrac.append([float(m.mean()) for m in masks])   # share of the frame
        sp, fit = _camera_step(prev, g) if prev is not None else (0.0, 0.0)
        cam.append(sp); camfit.append(fit)
        whole.append(g.mean()); change.append(float(np.abs(g - prev).mean()) if prev is not None else 0.0); prev = g
        hot.append(float(np.sort(g, axis=None)[-max(1, g.size // 200):].mean()))     # the brightest 0.5 %, wherever it is
    cap.release()
    if not whole:
        raise SystemExit(f"no frames in {video}")
    return {"fps": float(fps), "crop": crop, "n": len(whole), "whole": np.array(whole), "grid": np.array(grid), "hue": np.array(hue),
            "hot": np.array(hot), "huefrac": np.array(huefrac), "change": np.array(change), "camera": np.array(cam), "camera_fit": np.array(camfit)}


def _camera_step(prev: np.ndarray, g: np.ndarray) -> tuple[float, float]:
    """Camera speed between two frames (pixels of the small frame: pan + zoom + roll at the frame edge), from tracked points and a
    RANSAC similarity fit (as style_intel/motion.py), plus the share of points that agree (fit). Inside the crop, so a static text
    band cannot hide the camera."""
    import math
    import cv2
    a8, b8 = (np.clip(prev * 255, 0, 255).astype(np.uint8), np.clip(g * 255, 0, 255).astype(np.uint8))
    pts = cv2.goodFeaturesToTrack(a8, 200, 0.01, 5)
    if pts is None or len(pts) < 10:
        return 0.0, 0.0
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(a8, b8, pts, None, winSize=(15, 15), maxLevel=3)
    good = st.ravel() == 1; p0, p1 = pts[good].reshape(-1, 2), nxt[good].reshape(-1, 2)
    if len(p0) < 10:
        return 0.0, 0.0
    M, inl = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=1.0)
    if M is None:
        return 0.0, 0.0
    h, w = g.shape; c = np.array([w / 2, h / 2]); cc = M[:, :2] @ c + M[:, 2]
    zoom = math.hypot(M[0, 0], M[1, 0]); rot = math.atan2(M[1, 0], M[0, 0])
    return float(math.hypot(*(cc - c)) + abs(math.log(max(zoom, 1e-6))) * w / 2 + abs(rot) * w / 2), float(inl.mean())


def camera(P: dict, A: dict, beats: np.ndarray, fps: float, tempo: float) -> dict:
    """Does the camera move with the music? Its speed against the mix's energy (2 s) and against the rhythm's density per bar,
    and its accelerations against the beat grid. Unreliable when tracked points disagree (smoke, particles): flagged."""
    sp = np.nan_to_num(P["camera"], nan=0.0, posinf=0.0, neginf=0.0)          # a degenerate frame fit gave NaN (MEASURED)
    fit = float(np.median(P["camera_fit"][1:])) if len(sp) > 1 else 0.0
    res = {"median_speed_px": round(float(np.median(sp)), 2), "tracking_agreement": round(fit, 2)}
    if fit < 0.5:
        res["note"] = "tracked points disagree (particles, smoke or fast local motion): the camera estimate is unreliable"
    if np.median(sp) < 0.05:
        res["moving"] = False; return res
    res["moving"] = True
    bar = int(round(4 * 60 / tempo * fps)) if tempo > 0 else int(2 * fps)
    c, c95, p = _scale_test(_smooth(A["energy"], 2 * fps), _smooth(sp, 2 * fps), _rng("cam", "energy"))
    res["speed_vs_energy"] = {"corr": round(c, 3), "chance_95": round(c95, 3), "follows": bool(p <= 0.01 and c > c95)}
    dens = sum(A["layers"].values()) if A["layers"] else A["energy"]
    c, c95, p = _scale_test(_smooth(dens, bar), _smooth(sp, bar), _rng("cam", "phrase"))
    res["speed_vs_rhythm_per_bar"] = {"corr": round(c, 3), "chance_95": round(c95, 3), "follows": bool(p <= 0.01 and c > c95)}
    acc = np.abs(np.diff(_smooth(sp, 3), prepend=sp[0]))
    res["accelerations_on_grid"] = grid_alignment(acc, beats, A["layers"].get("kick"), fps, "camgrid")
    return res


def _rise(x: np.ndarray) -> np.ndarray:
    return np.maximum(np.diff(x, prepend=x[0]), 0)


def elements(P: dict) -> dict[str, dict]:
    """name -> {rise: brightening per frame (flashes, pulses), level: brightness (for energy coupling)}"""
    E = {"whole image": {"rise": _rise(P["whole"]), "level": P["whole"]},
         "brightest spot": {"rise": _rise(P["hot"]), "level": P["hot"]}}     # one moving element (a light point) wherever it goes
    gy, gx = GRID
    for k in range(gy * gx):
        E[f"region r{k // gx}c{k % gx}"] = {"rise": _rise(P["grid"][:, k]), "level": P["grid"][:, k]}
    for i, name in enumerate(HUES):
        lv = P["hue"][:, i]
        if lv.mean() > 0.002:                                  # the colour is actually in the picture
            E[f"{name} element"] = {"rise": _rise(lv), "level": lv}
    return E


# ---------------------------------------------------------------- sound
def _audio(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def _flux(y: np.ndarray, lo: float, hi: float, hop: int, n: int) -> np.ndarray:
    """Onset curve of one frequency band: positive change of log-magnitude, summed over the band, one value per video frame."""
    import librosa
    S = np.log1p(10 * np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))); f = librosa.fft_frequencies(sr=SR, n_fft=2048)
    band = S[(f >= lo) & (f < hi)]
    fl = np.maximum(np.diff(band, axis=1, prepend=band[:, :1]), 0).sum(0)
    return np.pad(fl, (0, max(0, n - len(fl))))[:n]


def _rms(y: np.ndarray, hop: int, n: int) -> np.ndarray:
    """Loudness per video frame. Frames past the end of the audio count as silent: an empty slice gave NaN and poisoned the
    camera-energy test (MEASURED Oct 22 on two clips whose audio ends a frame or two before the picture)."""
    return np.array([np.sqrt(np.mean(s ** 2)) if len(s := y[i * hop:(i + 1) * hop]) else 0.0 for i in range(n)])


def layers(video: Path, n: int, fps: float, work: Path | None, use_stems: bool = True) -> tuple[dict, dict]:
    hop = int(round(SR / fps)); src = "band splits of the full mix"; L = {}
    mix = _audio(video)
    stems = None
    if use_stems and work is not None:
        try:
            from style_intel.departments import stems as demucs
            stems = {k: _audio(v) for k, v in demucs(video, work).items() if k != "no_vocals"}
            src = "Demucs stems (htdemucs)"
        except Exception as e:                                  # demucs missing or failed: say so, fall back
            src = f"band splits of the full mix (stems failed: {type(e).__name__})"
    drums = stems["drums"] if stems else mix
    L["kick"] = _flux(drums, 20, 120, hop, n)
    L["snare"] = _flux(drums, 200, 3000, hop, n)
    L["hats"] = _flux(drums, 6000, 16000, hop, n)
    L["bass"] = _flux(stems["bass"], 30, 400, hop, n) if stems else _flux(mix, 120, 400, hop, n)
    if stems:
        L["melody"] = _flux(stems["other"], 150, 8000, hop, n)
        if _rms(stems["vocals"], hop, n).mean() > 0.1 * _rms(mix, hop, n).mean():
            L["vocals"] = _flux(stems["vocals"], 150, 6000, hop, n)
    energy = _rms(mix, hop, n)
    present = {}
    for k, v in list(L.items()):
        pk = _peaks(v, 1.5)
        if len(pk) < 4 or v.max() <= 0:
            present[k] = f"too few hits ({len(pk)})"; L.pop(k)
        else:
            present[k] = f"{len(pk)} hits"
    return {"layers": L, "energy": energy}, {"source": src, "present": present}


# ---------------------------------------------------------------- relations
def _smooth(x: np.ndarray, w: int) -> np.ndarray:
    w = max(1, int(w)); return np.convolve(x, np.ones(w) / w, mode="same")


def _response(a: np.ndarray, b: np.ndarray, lag: int, rng, n_rand: int = 300) -> dict:
    """Share of the layer's hits followed by a visual response at `lag` (+-1 frame), against the same number of random times."""
    hits = _peaks(a, 1.5); zb = _z(b); n = len(b)
    def rate(ts):
        ts = [t for t in ts if 0 <= t + lag - 1 and t + lag + 1 < n]
        return float(np.mean([zb[t + lag - 1:t + lag + 2].max() > 1.0 for t in ts])) if ts else 0.0
    r = rate(hits)
    rand = [rate(rng.integers(1, n - 2, len(hits))) for _ in range(n_rand)] if len(hits) else [0.0]
    c95 = float(np.percentile(rand, 95))
    kind = "consistent" if r >= 0.6 and r > c95 else "intermittent" if r > c95 else "coincidental"
    return {"hits": int(len(hits)), "responded": round(r, 3), "chance_95": round(c95, 3), "consistency": kind}


def _scale_test(a: np.ndarray, b: np.ndarray, rng, n_null: int = 120) -> tuple[float, float, float]:
    """Correlation at lag 0 of two (already smoothed) curves, its chance 95 % from circular shifts, and p."""
    za, zb = _z(a), _z(b); c = float(np.mean(za * zb)); n = len(a)
    null = np.array([float(np.mean(za * np.roll(zb, int(rng.integers(n // 8, n - n // 8))))) for _ in range(n_null)])
    return c, float(np.percentile(null, 95)), float((null >= c).mean())


def _rng(*names) -> np.random.Generator:
    """A fixed random stream per test, so adding an element never changes another test's result (MEASURED Oct 20: with one
    shared stream, adding the brightest-spot element flipped the TB-303 clip's verdict)."""
    import zlib
    return np.random.default_rng(zlib.crc32("|".join(names).encode()))


def relate(A: dict, E: dict, fps: float, tempo: float) -> list[dict]:
    lo, hi = SYNC_WINDOW; out = []
    bar = int(round(4 * 60 / tempo * fps)) if tempo > 0 else int(2 * fps)
    for la, a in A["layers"].items():
        for name, e in E.items():
            rng = _rng(la, name)
            L, c, _ = _xcorr(a, e["rise"], hi, lo)
            null = _null(a, e["rise"], hi, rng, 100 if name.startswith("region") else 200, lo)
            p = float((null >= c).mean()); c95 = float(np.percentile(null, 95))
            beat = p <= 0.01 and c > c95
            rel = {"layer": la, "element": name, "lag_frames": L, "lag_ms": round(1000 * L / fps), "corr": round(c, 3),
                   "chance_95": round(c95, 3), "p": round(p, 3), "beat_level": bool(beat)}
            if beat:
                rel.update(_response(a, e["rise"], L, rng))
            pc, p95, pp = _scale_test(_smooth(a, bar), _smooth(e["rise"], bar), rng)
            rel["phrase_level"] = bool(pp <= 0.01 and pc > p95); rel["phrase_corr"] = round(pc, 3)
            out.append(rel)
    ec = {}
    for name, e in E.items():                                       # energy: element brightness against the mix's loudness, 2 s
        rng = _rng("energy", name)
        c, c95, p = _scale_test(_smooth(A["energy"], 2 * fps), _smooth(e["level"], 2 * fps), rng)
        ec[name] = {"corr": round(c, 3), "chance_95": round(c95, 3), "p": round(p, 3), "energy_level": bool(p <= 0.01 and c > c95)}
    for r in out:
        r["energy_level"] = ec[r["element"]]["energy_level"]
    return out, ec


def ambiguous_pairs(A: dict, thr: float = 0.5) -> list[dict]:
    """Layers whose hits coincide (|r| >= thr at lag 0): a picture following one also follows the other."""
    ks = list(A["layers"]); out = []
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            r = float(np.corrcoef(A["layers"][ks[i]], A["layers"][ks[j]])[0, 1])
            if r >= thr:
                out.append({"layers": [ks[i], ks[j]], "corr": round(r, 2)})
    return out


def _rest_without(P: dict, hue_index: int) -> np.ndarray:
    """Brightness of the image with one colour element's pixels taken out."""
    frac = P["huefrac"][:, hue_index]
    return (P["whole"] - P["hue"][:, hue_index]) / np.maximum(1 - frac, 1e-3)


def strategy(rels: list[dict], ec: dict, A: dict, P: dict, n_regions: int) -> dict:
    """Decided by evidence, not by counting regions (counting flipped the verdict between 11 and 13 of 24, MEASURED Oct 20):
    1. for the strongest layer: take its best colour element OUT of the image; if the rest no longer follows, that element
       carries the sync (element_specific). A big bright element lifts the whole-image average on its own.
    2. if the brightest spot (a moving light) is the strongest follower: moving_element;
    3. if the whole image follows and the following is spread over at least half the picture: whole_image;
    4. otherwise: element_specific (a part of the picture), or energy_only / none."""
    beat = [r for r in rels if r["beat_level"] and r.get("consistency") in ("consistent", "intermittent")]
    mapping = {}
    for r in sorted(beat, key=lambda r: -r["corr"]):                  # per layer: the clearest named element first
        if r["element"] != "whole image" and not r["element"].startswith("region"):
            mapping.setdefault(r["layer"], r)
    for r in sorted(beat, key=lambda r: -r["corr"]):
        if r["element"].startswith("region"):
            mapping.setdefault(r["layer"], r)
    res = {"mapping": {k: {"element": v["element"], "lag_ms": v["lag_ms"], "corr": v["corr"], "consistency": v["consistency"],
                           "responded": v["responded"], "chance_95": v["chance_95"], "phrase_level": v["phrase_level"]} for k, v in mapping.items()}}
    if not beat:
        if any(v["energy_level"] for v in ec.values()):
            return {**res, "strategy": "energy_only", "why": "brightness rides the music's loudness over seconds, but no element answers individual hits"}
        return {**res, "strategy": "none", "why": "no element follows the sound better than chance at the beat, phrase or energy scale"}
    top = max(beat, key=lambda r: r["corr"]); layer = top["layer"]
    of_layer = [r for r in rels if r["layer"] == layer]
    regs = [r for r in of_layer if r["element"].startswith("region")]
    best_reg = max([r["corr"] for r in regs] or [0])
    spread = sum(r["beat_level"] and r["corr"] >= 0.5 * best_reg for r in regs) / n_regions if best_reg > 0 else 0.0
    whole = next((r for r in of_layer if r["element"] == "whole image"), None)
    spot = next((r for r in of_layer if r["element"] == "brightest spot"), None)
    colours = [r for r in of_layer if r["element"].endswith(" element") and r["beat_level"]]
    ev = {"strongest_layer": layer, "spread": round(spread, 2), "whole_image_corr": whole["corr"] if whole else None}
    border = []                                                        # verdicts near a threshold are flagged, not forced
    if colours:
        col = max(colours, key=lambda r: r["corr"]); hix = list(HUES).index(col["element"].split()[0])
        rest = _rise(_rest_without(P, hix)); lo, hi = SYNC_WINDOW
        _, c, _ = _xcorr(A["layers"][layer], rest, hi, lo)
        null = _null(A["layers"][layer], rest, hi, _rng("rest", layer, col["element"]), 200, lo)
        follows = bool((null >= c).mean() <= 0.01 and c > np.percentile(null, 95))
        ratio = col["corr"] / max(c, 1e-6)
        ev.update({"element": col["element"], "element_corr": col["corr"], "rest_without_element_corr": round(c, 3), "rest_follows": follows,
                   "element_vs_rest": round(ratio, 2)})
        if not follows:
            return {**res, "strategy": "element_specific", "evidence": ev, "borderline": border,
                    "why": f"{layer} drives the {col['element']} (r={col['corr']}); with that colour taken out, the rest of the image no longer follows (r={round(c, 3)})"}
        if ratio >= 1.2:                                               # the element leads; its light spills onto the rest
            if ratio < 1.35:
                border.append(f"element vs rest {ratio:.2f} (element-led from 1.2; whole-image below)")
            return {**res, "strategy": "element_led_with_spill", "evidence": ev, "borderline": border,
                    "why": f"{layer} drives the {col['element']} (r={col['corr']}); the rest of the image follows more weakly (r={round(c, 3)}), "
                           f"as the element's light or glow spreads"}
    if spot and spot["beat_level"] and spot["corr"] >= best_reg and (not whole or spot["corr"] > whole["corr"]):
        return {**res, "strategy": "moving_element", "evidence": ev, "borderline": border,
                "why": f"one bright moving element carries {layer} wherever it goes (r={spot['corr']}); regions follow only while it passes"}
    if 0.4 <= spread <= 0.6:
        border.append(f"spread {spread:.2f} (whole image from 0.5)")
    if whole and whole["beat_level"] and spread >= 0.5:
        return {**res, "strategy": "whole_image", "evidence": ev, "borderline": border,
                "why": f"the image as a whole follows {layer} (r={whole['corr']}), spread over {round(100 * spread)}% of the picture"}
    where = max(regs, key=lambda r: r["corr"])["element"] if regs else "?"
    return {**res, "strategy": "regional", "evidence": ev, "borderline": border,
            "why": f"{layer} is followed in one part of the picture (around {where}; {round(100 * spread)}% of regions), not by a colour element or the whole image"}


def grid_alignment(change: np.ndarray, beats: np.ndarray, kick: np.ndarray | None, fps: float, seed: str = "grid") -> dict:
    """Do the picture's big changes (cuts, new shapes, camera jumps) land on the musical grid? For each big change, its phase
    within the beat and within an assumed 4/4 bar (the bar start is the beat position with the most kick). Phase concentration is
    measured as the Rayleigh vector length against the same number of random times. A picture can follow the music through
    WHEN things happen even when its brightness does not pulse."""
    ev = _peaks(change, 2.0)
    if len(beats) < 4 or len(ev) < 4:
        return {"events": int(len(ev)), "note": "too few beats or picture events to test"}
    beats = np.asarray(beats, float); period = float(np.median(np.diff(beats)))
    offset = 0
    if kick is not None:
        sums = [kick[beats[k::4].astype(int).clip(0, len(kick) - 1)].sum() for k in range(4)]; offset = int(np.argmax(sums))
    def phases(ts, unit):
        out = []
        for t in ts:
            if unit == "beat":
                i = np.searchsorted(beats, t) - 1
                if 0 <= i < len(beats) - 1:
                    out.append((t - beats[i]) / (beats[i + 1] - beats[i]))
            else:
                bars = beats[offset::4]; i = np.searchsorted(bars, t) - 1
                if 0 <= i < len(bars) - 1:
                    out.append((t - bars[i]) / (bars[i + 1] - bars[i]))
        return np.array(out)
    def R(ph):
        return float(np.abs(np.mean(np.exp(2j * np.pi * ph)))) if len(ph) else 0.0
    rng = _rng(seed); res = {"events": int(len(ev)), "beat_period_ms": round(1000 * period / fps)}
    lo_t, hi_t = int(beats[0]), int(beats[-1])
    for unit in ("beat", "bar"):
        ph = phases(ev, unit); r = R(ph)
        null = [R(phases(rng.integers(lo_t, hi_t, len(ev)), unit)) for _ in range(500)]
        mean_ph = float(np.angle(np.mean(np.exp(2j * np.pi * ph))) / (2 * np.pi)) if len(ph) else 0.0
        span = period if unit == "beat" else 4 * period
        near = float(np.mean((ph < 0.1) | (ph > 0.9))) if len(ph) else 0.0
        c95 = float(np.percentile(null, 95))
        res[unit] = {"locked": bool(r > c95), "R": round(r, 3), "chance_95": round(c95, 3),
                     "low_confidence": bool(len(ev) < 12 or 0.9 * c95 <= r <= 1.15 * c95),
                     "mean_offset_ms": round(1000 * mean_ph * span / fps), "share_within_10pct": round(near, 2)}
    return res


def analyze(video: Path, out: Path, crop=None, use_stems: bool = True, tempo: float | None = None) -> dict:
    import librosa
    out.mkdir(parents=True, exist_ok=True)
    P = picture(video, crop); n, fps = P["n"], P["fps"]
    A, meta = layers(video, n, fps, out, use_stems)
    mix = _audio(video); hop = int(round(SR / fps))
    t, beats = librosa.beat.beat_track(y=mix, sr=SR, hop_length=hop)
    tempo = tempo or float(np.atleast_1d(t)[0])
    E = elements(P)
    rels, ec = relate(A, E, fps, tempo)
    S = strategy(rels, ec, A, P, GRID[0] * GRID[1])
    G = grid_alignment(P["change"], beats, A["layers"].get("kick"), fps)
    CAM = camera(P, A, beats, fps, tempo)
    amb = ambiguous_pairs(A)
    unc = [f"layers from {meta['source']}"]
    for a in amb:
        unc.append(f"{a['layers'][0]} and {a['layers'][1]} hit together (r={a['corr']}): an element following one also follows the other; the mapping names the stronger, not proven the cause")
    unc.append("how the sync was made (a shared note list, or audio analysed after rendering) cannot be seen in the finished video")
    return {"crop": P["crop"], "fps": fps, "frames": n, "tempo_bpm": round(tempo, 1), "layers": meta["present"],
            "strategy": S, "grid": G, "camera": CAM, "energy": {k: v for k, v in ec.items() if v["energy_level"]},
            "relations": sorted([r for r in rels if r["beat_level"]], key=lambda r: -r["corr"])[:40], "uncertainty": unc}


def summary(r: dict) -> str:
    s = r["strategy"]
    lines = [f"STRATEGY: {s['strategy']}: {s['why']}", f"  evidence: {s.get('evidence', {})}"]
    if s.get("borderline"):
        lines.append(f"  BORDERLINE: {'; '.join(s['borderline'])}")
    g = r.get("grid", {})
    for u in ("beat", "bar"):
        if u in g:
            x = g[u]; lines.append(f"  big picture changes on the {u}: {'LOCKED' if x['locked'] else 'not locked'} (R={x['R']}, chance {x['chance_95']}; "
                                   f"{x['share_within_10pct']:.0%} within 10% of the {u}, mean offset {x['mean_offset_ms']:+d} ms; {g['events']} changes)"
                                   + ("  [LOW CONFIDENCE: few changes or near chance]" if x.get("low_confidence") else ""))
    cm = r.get("camera", {})
    if cm:
        if not cm.get("moving", False):
            lines.append(f"  camera: still (median {cm['median_speed_px']} px/frame)")
        else:
            e, b = cm["speed_vs_energy"], cm["speed_vs_rhythm_per_bar"]; acc = cm["accelerations_on_grid"].get("beat", {})
            lines.append(f"  camera: speed {'FOLLOWS' if e['follows'] else 'does not follow'} the energy (r={e['corr']}, chance {e['chance_95']}); "
                         f"{'FOLLOWS' if b['follows'] else 'does not follow'} the rhythm per bar (r={b['corr']}); accelerations "
                         f"{'LOCKED' if acc.get('locked') else 'not locked'} to the beat (R={acc.get('R')}, chance {acc.get('chance_95')}"
                         f"{', LOW CONFIDENCE' if acc.get('low_confidence') else ''})"
                         + (f"  [{cm['note']}]" if cm.get("note") else ""))
    lines.append(f"layers: {r['layers']}  tempo {r['tempo_bpm']} BPM")
    for k, v in s["mapping"].items():
        lines.append(f"  {k:7s} -> {v['element']:18s} {v['lag_ms']:+4d} ms  r={v['corr']:.3f}  {v['consistency']} "
                     f"({v['responded']:.0%} of hits answered, chance {v['chance_95']:.0%}){'  + follows phrases' if v['phrase_level'] else ''}")
    if r["energy"]:
        lines.append("  energy: " + ", ".join(f"{k} r={v['corr']}" for k, v in list(r["energy"].items())[:5]))
    lines += ["  uncertain: " + u for u in r["uncertainty"]]
    return "\n".join(lines)
