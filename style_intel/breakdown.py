"""Effect breakdown: every transition, effect and synced sound in a video, with timestamps and evidence.

    python -m style_intel breakdown <video> --out <dir>

The question this answers is the one usually handed to a multimodal model
("list every transition, effect and sound, with timestamps, and tell me how to
recreate it"). Here every event comes from a detector that leaves numbers
behind, so it can be audited and re-run:

- MEASURED: read directly from pixels or samples (a cut, a frame hold, a
  red-vs-blue channel offset, an onset time).
- INFERRED: a named effect recognised from measured signals by a stated rule
  (a "whip pan" is strong one-axis motion blur plus a sharpness collapse; a
  "whoosh" is a slow-attack noisy swell). Rules and thresholds are in
  BREAKDOWN_DEFAULTS; the numbers behind each label are in its `evidence`.
- NOT_MEASURED: listed with the reason, never guessed (typography, speed ramps,
  the identity of a sound such as "bird call").

Events that happen together become one *moment*: a cut plus its layers, which is
how NarrativeOS's TransitionStack builds a transition. Each moment gets the
closest registered recipe, a layer stack with measured parameters, the synced
sound, and a strip of frames around it for review. Nothing here is reviewed
until a person (or a vision model through scripts/model_provider.py) has looked
at the strips: every moment starts as `review: UNREVIEWED`.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from . import shots as shots_mod
from . import speech as speech_mod
from .media import extract_audio, frame_at, probe, sha256
from .profile import known_transitions

# Every threshold lives here; callers override any subset via analyze(config=...).
# Pixel values are on the analysis frame (ANALYSIS_WIDTH wide) unless the name says otherwise.
BREAKDOWN_DEFAULTS = {
    "analysis_long_side": 640,        # frames are measured at this size (long side), so vertical video costs the same
    "motion_long_side": 320,          # global motion, sharpness, holds and glitch bands use this size
    "rgb_split_min_px": 1.5,          # red-vs-blue channel offset (~4.5 px on a 1080p frame); lenses stay well under 1
    "rgb_split_min_response": 0.05,   # phase-correlation peak strength; lower = no reliable shift
    "rgb_split_min_texture": 6.0,     # channel std; flat frames have no edges to align
    "glitch_bands": 8,
    "glitch_min_spread_px": 6.0,      # band-to-band horizontal displacement spread (motion frame)
    "glitch_min_band_response": 0.08,
    "glitch_min_good_bands": 5,       # fewer reliable bands = a cut or a blank frame, not a tear
    "glitch_max_residual": 0.6,       # a band's shift must explain the change: shifted error <= 60 % of unshifted
                                      # (periodic textures such as piano keys give false shifts one period apart)
    "glitch_max_frames": 10,          # tearing is brief; a long run of spread is parallax
    "whip_min_anisotropy": 0.8,       # |ln(horizontal / vertical gradient energy)|
    "whip_max_sharpness_ratio": 0.55, # sharpness vs the same shot's median
    "whip_min_travel": 0.1,           # summed global shift as a fraction of the frame (RGB split and zooms also soften)
    "zoom_min_scale_step": 0.02,      # per-frame scale change (2 %/frame = 60 %/s; Ken Burns is ~0.5 %/s)
    "zoom_min_frames": 2,
    "blur_max_sharpness_ratio": 0.35,
    "blur_min_frames": 3,
    "min_texture_ratio": 0.35,        # whip/blur need edges: frame gradient vs the video's median (blank cards have none)
    "halftone_min_peak": 10.0,        # whitened spectral peak in a second direction (>= 30 degrees from the strongest)
    "halftone_min_lattice": 4.0,      # ... AND a peak at the sum or difference of the two: a 2-D dot lattice.
                                      # Tested: dot grids 5-32 px scored 5.2-29; photos and piano keys <= 2.6
    "halftone_min_dot_ratio": 0.02,   # separate dots found / lattice cells expected: a halftone is made of dots,
                                      # a rendered tiling (a drawn keyboard: ~40 keys vs ~7000 cells) is not
    "halftone_min_frames": 3,
    "leak_min_luma_rise": 12.0,
    "leak_min_chroma_shift": 6.0,     # mean(R) - mean(B) change; sign gives warm / cool
    "leak_min_frames": 5,
    "leak_max_frames": 75,            # 2.5 s; a longer bright stretch is a shot, not a leak
    "leak_baseline_frames": (20, 8),  # baseline = median luma from 20 to 8 frames before
    "hold_max_diff": 0.4,             # mean abs difference (0-255) that counts as the same frame
    "hold_min_motion_before": 2.0,    # the frames before must move, or it is just a still shot
    "hold_min_repeats": 2,            # 1 repeat is pulldown (24p in 30p); 2+ is a deliberate hold
    "moment_merge_sec": 0.3,          # events closer than this are one moment
    "sound_before_sec": 0.5,          # a moment's sound is the loudest peak in this window
    "sound_after_sec": 0.35,
    "click_max_ms": 120.0,
    "impact_max_attack_ms": 50.0,     # the 512-sample RMS window alone smears an instant attack over ~25 ms
    "impact_min_low_ratio": 0.25,     # energy below 150 Hz at the peak
    "impact_min_decay_ms": 150.0,
    "whoosh_min_attack_ms": 80.0,
    "whoosh_min_band_flatness": 0.2,  # flatness inside the occupied band: noise ~0.5, tones and chords far lower
    "whoosh_min_bandwidth_hz": 1000.0,
    "whoosh_active_ms": (200.0, 2500.0),
    "riser_window_sec": 2.5,
    "riser_min_rise_db": 8.0,
    "riser_min_r2": 0.6,
    "riser_min_sec": 1.0,             # the climb itself must last this long
    "sound_min_prominence_db": 10.0,  # a moment's sound must stand this far above the floor and the level just before
    "max_inferred_support": 0.75,     # inferred labels never claim more support than this
}

MEASUREMENTS = {
    "hard_cut": {"status": "MEASURED", "method": "ffmpeg scdet frame difference"},
    "gradual_transition": {"status": "INFERRED", "method": "colour histograms 0.5 s apart; light / dark / dissolve from the luma path"},
    "flash_frame": {"status": "MEASURED", "method": "luma jump >= 60 that falls back within 4 frames"},
    "dip_to_black": {"status": "MEASURED", "method": ">= 2 frames near black"},
    "frame_hold": {"status": "MEASURED", "method": "consecutive identical frames right after motion"},
    "rgb_split": {"status": "MEASURED", "method": "phase correlation of the red channel against the blue channel"},
    "glitch_tear": {"status": "INFERRED", "method": "horizontal bands displaced by different amounts against the previous frame"},
    "whip_pan": {"status": "INFERRED", "method": "one-axis motion blur (gradient anisotropy) with a sharpness collapse; direction from global motion"},
    "zoom": {"status": "MEASURED", "method": "scale of a similarity transform fitted to ORB matches between consecutive frames"},
    "blur": {"status": "INFERRED", "method": "Laplacian sharpness far below the shot's median, without a direction"},
    "halftone": {"status": "INFERRED", "method": "a 2-D lattice in the whitened image spectrum (two directions plus their sum or difference) made of separate dots"},
    "light_leak": {"status": "INFERRED", "method": "brightness rise with a colour shift over several frames"},
    "exposure_bloom": {"status": "INFERRED", "method": "brightness rise without a colour shift, longer than a flash frame"},
    "sound_onset": {"status": "MEASURED", "method": "loudest RMS peak near each moment standing >= 10 dB above the floor and the level before; onset = where it rose within 20 dB of that peak"},
    "sound_class": {"status": "INFERRED", "method": "envelope and spectrum rules: click, impact, whoosh, hit, riser (see evidence)"},
    "speech_overlap": {"status": "INFERRED", "method": "faster-whisper speech segments (times only); a sound inside one may be the voice, not an effect"},
    "typography": {"status": "NOT_MEASURED", "reason": "no OCR or text detector yet"},
    "speed_ramp": {"status": "NOT_MEASURED", "reason": "needs optical-flow speed tracking within a shot"},
    "sound_identity": {"status": "NOT_MEASURED", "reason": "no sound-event classifier: 'bird', 'water' or 'shutter' cannot be told apart from 'click' or 'noise'"},
    "music_vs_sfx": {"status": "NOT_MEASURED", "reason": "no source separation; onsets in a music bed can be notes, not effects"},
    "plugin_or_ae_effect": {"status": "NOT_MEASURED", "reason": "a rendered video does not record which tool made a look; recreation advice is a reference, not a finding"},
    "grade_and_grain": {"status": "MEASURED", "method": "per shot, by `python -m style_intel analyze` (not repeated here)"},
}

# Recreating an event: the NarrativeOS layer, plus the usual equivalent elsewhere (REFERENCE, not a finding).
TECHNIQUE = {
    "rgb_split": ("rgb_split layer (px from the measurement)", "split channels and offset red/blue (AE: shift channels or a channel-offset plugin)"),
    "glitch_tear": ("glitch_slices layer, or a glitch overlay clip", "horizontal slice displacement (AE: Displacement Map / Turbulent Displace / sliced masks)"),
    "whip_pan": ("whip_pan layer in the measured direction", "fast position move with directional blur (AE: CC Force Motion Blur or Directional Blur)"),
    "zoom": ("zoom_punch layer (scale from the measurement)", "fast scale animation with motion blur"),
    "blur": ("blur layer / blur_dissolve", "Gaussian/camera-lens blur on the cut"),
    "halftone": ("halftone cut type", "halftone / color halftone effect revealing into the image"),
    "light_leak": ("light_leak overlay (Screen blend) in the measured tone", "light-leak footage on Screen/Add with animated opacity"),
    "exposure_bloom": ("flash layer with a slow release / exposure_bump", "exposure or glow ramp"),
    "flash_frame": ("flash layer (white, 1-2 frames)", "1-2 frame white solid or exposure spike"),
    "dip_to_black": ("dip layer", "fade through black"),
    "frame_hold": ("stutter layer (holdFrames from the measurement)", "freeze frames / hold keyframes"),
}


def _runs(mask: np.ndarray, max_gap: int = 1) -> list[tuple[int, int]]:
    """Inclusive (start, end) index runs of True, bridging gaps up to max_gap frames."""
    idx = np.flatnonzero(mask)
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][1] <= max_gap + 1:
            out[-1][1] = int(i)
        else:
            out.append([int(i), int(i)])
    return [(a, b) for a, b in out]


class _FrameMeter:
    """Per-frame measurements, streamed so long videos never sit in memory."""

    def __init__(self, cfg: dict, size: tuple[int, int], motion_size: tuple[int, int]):
        self.cfg = cfg
        w, h = size
        mw, mh = motion_size
        self.motion_size = motion_size
        self.win = cv2.createHanningWindow((w, h), cv2.CV_32F)
        self.mwin = cv2.createHanningWindow((mw, mh), cv2.CV_32F)
        bh = mh // cfg["glitch_bands"]
        self.band_rows = [(i * bh, (i + 1) * bh) for i in range(cfg["glitch_bands"])]
        self.bwin = cv2.createHanningWindow((mw, bh), cv2.CV_32F)
        # Whitening for the halftone test: each spectrum bin is compared with its radius's mean.
        fy = np.fft.fftshift(np.fft.fftfreq(h))[:, None] * 2
        fx = np.fft.fftshift(np.fft.fftfreq(w))[None, :] * 2
        r = np.sqrt(fx ** 2 + fy ** 2)
        self.rbin = np.minimum((r * 64).astype(int), 90)
        self.annulus = (r >= 0.05) & (r <= 0.95)  # dots up to ~40 px on the analysis frame
        self.radius = r
        self.angle = np.degrees(np.arctan2(fy, fx)) % 180
        self.orb = cv2.ORB_create(800)
        self.prev = None  # (gray_small_float, keypoints, descriptors)

    def measure(self, rgb: np.ndarray) -> dict:
        cfg = self.cfg
        f = rgb.astype(np.float32)
        r, b = f[..., 0], f[..., 2]
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        out = {
            "y": float(gray.mean()),
            "warm": float(r.mean() - b.mean()),
            "y_left": float(gray[:, : w // 2].mean()), "y_right": float(gray[:, w // 2 :].mean()),
            "y_top": float(gray[: h // 2].mean()), "y_bottom": float(gray[h // 2 :].mean()),
        }
        # RGB split: where is the red channel relative to the blue one?
        if r.std() >= cfg["rgb_split_min_texture"] and b.std() >= cfg["rgb_split_min_texture"]:
            (dx, dy), resp = cv2.phaseCorrelate(b, r, self.win)
            out.update(rgb_dx=float(dx), rgb_dy=float(dy), rgb_resp=float(resp))
        else:
            out.update(rgb_dx=0.0, rgb_dy=0.0, rgb_resp=0.0)
        # Halftone: an isolated peak in the whitened spectrum.
        spec = np.abs(np.fft.fftshift(np.fft.fft2((gray.astype(np.float32) - gray.mean()) * self.win)))
        radial = np.bincount(self.rbin.ravel(), spec.ravel()) / np.maximum(np.bincount(self.rbin.ravel()), 1)
        white = spec / np.maximum(radial[self.rbin], 1e-6)
        # A dot grid peaks in two directions at once; a motion blur's ripples or stripes peak in one.
        # So the score is the strongest peak at least 30 degrees away from the strongest one.
        ring = np.where(self.annulus, white, 0.0)
        k1 = np.unravel_index(int(np.argmax(ring)), ring.shape)
        off = np.abs(self.angle - self.angle[k1])
        second = np.where(np.minimum(off, 180 - off) >= 30, ring, 0.0)
        k2 = np.unravel_index(int(np.argmax(second)), second.shape)
        out["halftone_peak"] = float(second[k2])
        # A lattice also peaks at v1 + v2 or v1 - v2; stripes and one-off textures do not.
        cy, cx = h // 2, w // 2
        near = cv2.dilate(white.astype(np.float32), np.ones((3, 3), np.uint8))  # tolerate one-bin rounding
        lattice = 0.0
        for sign in (1, -1):
            # The DFT is periodic: a sum beyond Nyquist aliases back in, so wrap instead of dropping it.
            qy, qx = (k1[0] + sign * (k2[0] - cy)) % h, (k1[1] + sign * (k2[1] - cx)) % w
            lattice = max(lattice, float(near[qy, qx]))
        out["halftone_lattice"] = lattice
        out["halftone_dot_ratio"] = 0.0
        if lattice >= cfg["halftone_min_lattice"]:
            # Count separate dots (dark on light and light on dark) against the cells the lattice period implies.
            period = 2.0 / max(min(float(self.radius[k1]), float(self.radius[k2])), 1e-6)  # the lower one is nearer the fundamental
            cells = (w / period) * (h / period)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            dots = max(cv2.connectedComponents(binary)[0], cv2.connectedComponents(255 - binary)[0]) - 1
            out["halftone_dot_ratio"] = float(dots / max(cells, 1.0))

        small = cv2.resize(gray, self.motion_size, interpolation=cv2.INTER_AREA)
        sf = small.astype(np.float32)
        lap = cv2.Laplacian(sf, cv2.CV_32F)
        gx = cv2.Sobel(sf, cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(sf, cv2.CV_32F, 0, 1)
        out["sharp"] = float(lap.var())
        out["texture"] = float(np.mean(np.abs(gx)) + np.mean(np.abs(gy)))
        out["aniso"] = float(np.log((np.mean(gx ** 2) + 1e-3) / (np.mean(gy ** 2) + 1e-3)))
        kp, des = self.orb.detectAndCompute(small, None)
        out.update(diff=None, scale=None, gdx=None, gdy=None, band_spread=None, good_bands=0)
        if self.prev is not None:
            psf, pkp, pdes = self.prev
            out["diff"] = float(np.abs(sf - psf).mean())
            (pdx, pdy), presp = cv2.phaseCorrelate(psf, sf, self.mwin)
            out.update(gdx=float(pdx), gdy=float(pdy), gresp=float(presp))
            if des is not None and pdes is not None and len(kp) >= 30 and len(pkp) >= 30:
                pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(pdes, des, k=2)
                good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
                if len(good) >= 20:
                    pa = np.float32([pkp[m.queryIdx].pt for m in good])
                    pb = np.float32([kp[m.trainIdx].pt for m in good])
                    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0)
                    if M is not None and inl.mean() >= 0.4:
                        out["scale"] = float(np.hypot(M[0, 0], M[1, 0]))
            shifts = []
            for a, z in self.band_rows:
                (bdx, _), bresp = cv2.phaseCorrelate(psf[a:z], sf[a:z], self.bwin)
                if bresp < cfg["glitch_min_band_response"]:
                    continue
                k = int(round(bdx))
                if abs(k) >= 2 and 2 * (abs(k) + 2) >= sf.shape[1] - 8:
                    continue  # a shift this large leaves nothing to compare: unverifiable
                if abs(k) >= 2:
                    # Keep a shift only if moving the old band by it actually explains the new one.
                    m = abs(k) + 2
                    e0 = float(np.abs(psf[a:z, m:-m] - sf[a:z, m:-m]).mean())
                    e1 = float(np.abs(np.roll(psf[a:z], k, axis=1)[:, m:-m] - sf[a:z, m:-m]).mean())
                    if e0 < 1.0 or e1 > cfg["glitch_max_residual"] * e0:
                        continue
                shifts.append(bdx)
            out["good_bands"] = len(shifts)
            if len(shifts) >= cfg["glitch_min_good_bands"]:
                out["band_spread"] = float(max(shifts) - min(shifts))
        self.prev = (sf, kp, des)
        return out


def fit_long_side(src: dict, long_side: int) -> tuple[int, int]:
    k = long_side / max(src["width"], src["height"])
    return int(round(src["width"] * k / 2) * 2), int(round(src["height"] * k / 2) * 2)


def measure_frames(path: Path, src: dict, cfg: dict) -> list[dict]:
    w, h = fit_long_side(src, cfg["analysis_long_side"])
    mw, mh = fit_long_side(src, cfg["motion_long_side"])
    mh -= mh % cfg["glitch_bands"]
    meter = _FrameMeter(cfg, (w, h), (mw, mh))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            stdout=subprocess.PIPE)
    size = w * h * 3
    frames = []
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            frames.append(meter.measure(np.frombuffer(buf, np.uint8).reshape(h, w, 3)))
    finally:
        proc.stdout.close()
        proc.wait()
    return frames


def _shot_index(n: int, fps: float, cuts: list[float]) -> np.ndarray:
    idx = np.zeros(n, int)
    for c in cuts:
        idx[int(round(c * fps)):] += 1
    return idx


def visual_events(frames: list[dict], fps: float, cuts: list[float], cfg: dict, motion_size: tuple[int, int] = (320, 180)) -> list[dict]:
    """Effect events from the per-frame measurements (cuts, flashes, dips and gradual transitions come from shots.py)."""
    n = len(frames)
    col = lambda k, d=0.0: np.array([fr[k] if fr.get(k) is not None else d for fr in frames], float)  # noqa: E731
    shot = _shot_index(n, fps, cuts)
    events: list[dict] = []
    T = lambda i: round(i / fps, 3)  # noqa: E731

    def add(kind, a, b, evidence, peak=None):
        events.append({"type": kind, "basis": MEASUREMENTS[kind]["status"], "start": T(a), "end": T(b + 1),
                       "peak": T(peak if peak is not None else a), "frames": b - a + 1, "evidence": evidence})

    # RGB split
    off = np.hypot(col("rgb_dx"), col("rgb_dy"))
    resp = col("rgb_resp")
    for a, b in _runs((off >= cfg["rgb_split_min_px"]) & (resp >= cfg["rgb_split_min_response"])):
        p = a + int(np.argmax(off[a : b + 1]))
        scale = 1920 / cfg["analysis_long_side"]  # "at_1920": on a 1080p frame (long side 1920), either orientation
        add("rgb_split", a, b, {"max_offset_px_at_1920": round(float(off[p]) * scale, 1),
                                "dx_px_at_1920": round(frames[p]["rgb_dx"] * scale, 1), "dy_px_at_1920": round(frames[p]["rgb_dy"] * scale, 1),
                                "phase_response": round(float(resp[p]), 3), "threshold_px_at_1920": round(cfg["rgb_split_min_px"] * scale, 1)}, p)

    # Sharpness relative to the shot's own median (a soft shot is not a blur effect).
    sharp = col("sharp")
    ratio = np.ones(n)
    for s in np.unique(shot):
        m = shot == s
        med = float(np.median(sharp[m])) if m.any() else 0.0
        if med > 1e-3:
            ratio[m] = sharp[m] / med
    aniso = col("aniso")
    texture = col("texture")
    textured = texture >= cfg["min_texture_ratio"] * float(np.median(texture))

    taken = np.zeros(n, bool)
    # Zoom: fast scale change between consecutive frames.
    scale = col("scale", 1.0)
    for a, b in _runs(np.abs(scale - 1) >= cfg["zoom_min_scale_step"], max_gap=0):
        if b - a + 1 < cfg["zoom_min_frames"]:
            continue
        total = float(np.prod(scale[a : b + 1]))
        add("zoom", a, b, {"direction": "in" if total > 1 else "out", "total_scale": round(total, 3),
                           "max_step_per_frame": round(float(np.max(np.abs(scale[a : b + 1] - 1))), 3)}, a + int(np.argmax(np.abs(scale[a : b + 1] - 1))))
        taken[a : b + 1] = True

    # Whip pan: one-axis blur and a sharpness collapse.
    whip_mask = (ratio <= cfg["whip_max_sharpness_ratio"]) & (np.abs(aniso) >= cfg["whip_min_anisotropy"]) & ~taken & textured
    for a, b in _runs(whip_mask):
        if b - a + 1 < 2:
            continue
        horizontal = float(np.mean(aniso[a : b + 1])) < 0  # weak horizontal gradients = blurred along x
        lo, hi = max(0, a - 1), min(n - 1, b + 1)
        shift = float(np.nansum([frames[i]["gdx" if horizontal else "gdy"] or 0.0 for i in range(lo, hi + 1)]))
        if abs(shift) < cfg["whip_min_travel"] * motion_size[0 if horizontal else 1]:
            continue
        direction = ("left" if shift < 0 else "right") if horizontal else ("up" if shift < 0 else "down")
        p = a + int(np.argmin(ratio[a : b + 1]))
        add("whip_pan", a, b, {"axis": "x" if horizontal else "y", "direction": direction, "summed_shift_px_motion_frame": round(shift, 1),
                               "min_sharpness_ratio": round(float(ratio[p]), 3), "anisotropy": round(float(aniso[p]), 2)}, p)
    for e in events:
        if e["type"] == "whip_pan":
            taken[int(round(e["start"] * fps)) : int(round(e["end"] * fps))] = True

    # Blur without a direction.
    for a, b in _runs((ratio <= cfg["blur_max_sharpness_ratio"]) & ~taken & (np.abs(aniso) < cfg["whip_min_anisotropy"]) & textured):
        if b - a + 1 >= cfg["blur_min_frames"]:
            p = a + int(np.argmin(ratio[a : b + 1]))
            add("blur", a, b, {"min_sharpness_ratio": round(float(ratio[p]), 3)}, p)

    # Glitch tearing: bands moving by different amounts. Skip whips (their bands blur unevenly).
    spread = col("band_spread")
    # Across a cut the previous frame is another shot, so band displacement there means nothing.
    boundary = np.zeros(n, bool)
    for i in np.flatnonzero(np.diff(shot)) + 1:
        boundary[max(0, i - 1) : i + 2] = True
    # Entering and leaving a tear both displace bands; frames in between match each other. One event.
    for a, b in _runs((spread >= cfg["glitch_min_spread_px"]) & ~taken & ~boundary, max_gap=cfg["glitch_max_frames"] // 2):
        if b - a + 1 <= cfg["glitch_max_frames"]:
            p = a + int(np.argmax(spread[a : b + 1]))
            add("glitch_tear", a, b, {"max_band_spread_px_at_320": round(float(spread[p]), 1), "reliable_bands": frames[p]["good_bands"],
                                      "threshold_px_at_320": cfg["glitch_min_spread_px"]}, p)

    # Halftone
    ht, lat, dots = col("halftone_peak"), col("halftone_lattice"), col("halftone_dot_ratio")
    is_ht = (ht >= cfg["halftone_min_peak"]) & (lat >= cfg["halftone_min_lattice"]) & (dots >= cfg["halftone_min_dot_ratio"])
    for a, b in _runs(is_ht, max_gap=2):
        if b - a + 1 >= cfg["halftone_min_frames"]:
            p = a + int(np.argmax(lat[a : b + 1]))
            add("halftone", a, b, {"second_direction_peak": round(float(ht[p]), 1), "lattice_peak": round(float(lat[p]), 1), "dot_ratio": round(float(dots[p]), 2),
                                   "threshold": cfg["halftone_min_lattice"]}, p)

    # Light leaks and blooms: brightness rise against the frames just before.
    y, warm = col("y"), col("warm")
    far, near = cfg["leak_baseline_frames"]
    base_y, base_w = np.full(n, np.nan), np.full(n, np.nan)
    for i in range(far, n):
        base_y[i] = np.median(y[i - far : i - near])
        base_w[i] = np.median(warm[i - far : i - near])
    rise = np.nan_to_num(y - base_y)
    shift = np.nan_to_num(warm - base_w)
    cut_idx = [int(round(c * fps)) for c in cuts]
    near_cut = lambda i: any(abs(i - c) <= 2 for c in cut_idx)  # noqa: E731
    for a, b in _runs(rise >= cfg["leak_min_luma_rise"]):
        if not cfg["leak_min_frames"] <= b - a + 1 <= cfg["leak_max_frames"]:
            continue  # shorter is a flash frame (shots.py reports those); longer is a brighter shot
        if near_cut(a) and any(a + 2 < c <= b + 5 for c in cut_idx):
            continue  # starts on a cut and the next cut ends it: a brighter shot (or an insert), not light over one
        p = a + int(np.argmax(rise[a : b + 1]))
        # A leak is a bump: brighter than the picture on BOTH sides, so a cut to a brighter shot is not one.
        pre = slice(max(0, a - far), max(1, a - near))
        post = slice(min(n - 1, b + near), min(n, b + far))
        sides_y = [float(np.median(y[sl])) for sl in (pre, post) if sl.stop > sl.start]
        sides_w = [float(np.median(warm[sl])) for sl in (pre, post) if sl.stop > sl.start]
        if not sides_y:
            continue
        dy, dw = float(y[p] - max(sides_y)), float(warm[p] - np.mean(sides_w))
        if dy < cfg["leak_min_luma_rise"]:
            continue
        bl = frames[a - 1] if a else frames[a]
        lr = (frames[p]["y_left"] - bl["y_left"]) - (frames[p]["y_right"] - bl["y_right"])
        tb = (frames[p]["y_top"] - bl["y_top"]) - (frames[p]["y_bottom"] - bl["y_bottom"])
        side = None
        if max(abs(lr), abs(tb)) >= 0.3 * dy:
            side = ("left" if lr > 0 else "right") if abs(lr) >= abs(tb) else ("top" if tb > 0 else "bottom")
        evidence = {"luma_rise": round(dy, 1), "chroma_shift_r_minus_b": round(dw, 1), "brightest_side": side}
        if abs(dw) >= cfg["leak_min_chroma_shift"]:
            add("light_leak", a, b, {**evidence, "tone": "warm" if dw > 0 else "cool"}, p)
        else:
            add("exposure_bloom", a, b, evidence, p)

    # Frame holds: identical frames right after motion (one repeat is pulldown, not a hold).
    diff = col("diff", 99.0)
    shot_start = {int(sh): int(np.flatnonzero(shot == sh)[0]) for sh in np.unique(shot)}
    for a, b in _runs(diff <= cfg["hold_max_diff"], max_gap=0):
        repeats = b - a + 1
        # Motion before the hold must be inside the same shot: the cut itself is not motion,
        # and a still image after a cut is a still shot, not a freeze.
        before = diff[max(shot_start[int(shot[a])] + 1, a - 3) : a]
        if repeats >= cfg["hold_min_repeats"] and len(before) >= 2 and float(np.mean(before)) >= cfg["hold_min_motion_before"]:
            add("frame_hold", a - 1, b, {"held_frames": repeats + 1, "motion_before": round(float(np.mean(before)), 2)}, a - 1)
    return events


# --------------------------------------------------------------------------------------------- audio
def audio_events(path: Path, cfg: dict) -> dict:
    import librosa

    with tempfile.TemporaryDirectory() as td:
        wav = extract_audio(path, Path(td) / "a.wav", sr=22050)
        y, sr = librosa.load(str(wav), sr=22050, mono=True)
    if len(y) == 0 or float(np.sqrt(np.mean(y ** 2))) < 1e-4:
        return {"status": "silent", "y": None}
    hop = 128
    env = librosa.feature.rms(y=y, frame_length=512, hop_length=hop)[0]
    env_db = 20 * np.log10(env + 1e-9)
    return {"status": "measured", "y": y, "sr": sr, "env_db": env_db, "env_t": np.arange(len(env)) * hop / sr,
            "floor_db": float(np.percentile(env_db, 10))}


def classify_sound(y: np.ndarray, sr: int, t: float, cfg: dict) -> dict:
    """Envelope and spectrum of the sound at an onset, and the rule-based label they give."""
    import librosa

    hop = 128
    a0 = max(0, int((t - 0.4) * sr))
    seg = y[a0 : int((t + 1.6) * sr)]
    if len(seg) < 2048:
        return {"class": "unclassified", "features": {}}
    env = librosa.feature.rms(y=seg, frame_length=512, hop_length=hop)[0]
    tt = np.arange(len(env)) * hop / sr + a0 / sr
    look = (tt >= t - 0.05) & (tt <= t + 0.4)
    if not look.any():
        return {"class": "unclassified", "features": {}}
    p = int(np.flatnonzero(look)[np.argmax(env[look])])
    peak = float(env[p])
    floor = 0.1 * peak  # -20 dB
    s = p
    while s > 0 and env[s - 1] >= floor:
        s -= 1
    e = p
    while e < len(env) - 1 and env[e + 1] >= floor:
        e += 1
    ms = hop / sr * 1000
    attack, decay = (p - s) * ms, (e - p) * ms
    active = seg[s * hop : (e + 1) * hop + 512]
    pk = seg[max(0, p * hop - int(0.03 * sr)) : p * hop + int(0.2 * sr)]
    spec = np.abs(np.fft.rfft(pk * np.hanning(len(pk)))) ** 2 if len(pk) > 64 else np.ones(2)
    freqs = np.fft.rfftfreq(len(pk), 1 / sr) if len(pk) > 64 else np.array([0.0, 1.0])
    low_ratio = float(spec[freqs < 150].sum() / max(spec.sum(), 1e-12))
    flat, bandwidth = 0.0, 0.0
    if len(active) >= 512:
        pw = np.abs(np.fft.rfft(active * np.hanning(len(active)))) ** 2
        fa = np.fft.rfftfreq(len(active), 1 / sr)
        cum = np.cumsum(pw) / max(pw.sum(), 1e-12)
        lo_i, hi_i = int(np.searchsorted(cum, 0.05)), int(np.searchsorted(cum, 0.95))
        band = pw[lo_i : hi_i + 1] + 1e-20
        flat = float(np.exp(np.mean(np.log(band))) / np.mean(band))
        bandwidth = float(fa[min(hi_i, len(fa) - 1)] - fa[lo_i])
    cent = float(np.mean(librosa.feature.spectral_centroid(y=pk, sr=sr, n_fft=512, hop_length=hop))) if len(pk) >= 512 else 0.0
    f = {"attack_ms": round(attack, 1), "decay_ms": round(decay, 1), "active_ms": round(attack + decay, 1),
         "low_band_ratio": round(low_ratio, 3), "band_flatness": round(flat, 3), "bandwidth_hz": round(bandwidth), "centroid_hz": round(cent)}
    lo, hi = cfg["whoosh_active_ms"]
    if attack + decay <= cfg["click_max_ms"]:
        label = "click"  # a glitch tick, shutter or click: the envelope cannot tell them apart
    elif attack <= cfg["impact_max_attack_ms"] and low_ratio >= cfg["impact_min_low_ratio"] and decay >= cfg["impact_min_decay_ms"]:
        label = "impact"
    elif (attack >= cfg["whoosh_min_attack_ms"] and flat >= cfg["whoosh_min_band_flatness"]
          and bandwidth >= cfg["whoosh_min_bandwidth_hz"] and lo <= attack + decay <= hi):
        label = "whoosh"
    elif attack <= cfg["impact_max_attack_ms"]:
        label = "hit"
    else:
        label = "unclassified"
    return {"class": label, "features": f}


def riser_before(y: np.ndarray, sr: int, t: float, cfg: dict, floor_db: float) -> dict | None:
    """A sustained loudness climb into t (a riser or swell), from 0.1 s RMS steps.

    Only the stretch that is audibly above the floor right up to t is fitted: a sound that simply
    starts out of silence is one big step, not a riser."""
    w = cfg["riser_window_sec"]
    a = int(max(0.0, t - w) * sr)
    seg = y[a : int(t * sr)]
    step = int(0.1 * sr)
    if len(seg) < 10 * step:
        return None
    db = np.array([20 * np.log10(np.sqrt(np.mean(seg[i : i + step] ** 2)) + 1e-9) for i in range(0, len(seg) - step + 1, step)])
    k = len(db)
    while k > 0 and db[k - 1] >= floor_db + cfg["sound_min_prominence_db"]:
        k -= 1
    db = db[k:]
    if len(db) >= 3:  # start at the quietest point: a louder tail before it (an impact decaying) is not part of the climb
        smooth = np.convolve(db, np.ones(3) / 3, mode="same")
        db = db[int(np.argmin(smooth[:-1])) :]
    if len(db) * 0.1 < cfg["riser_min_sec"]:
        return None
    x = np.arange(len(db)) * 0.1
    slope, icept = np.polyfit(x, db, 1)
    fit = slope * x + icept
    r2 = 1 - float(np.sum((db - fit) ** 2) / max(np.sum((db - db.mean()) ** 2), 1e-9))
    rise = float(fit[-1] - fit[0])
    if rise >= cfg["riser_min_rise_db"] and r2 >= cfg["riser_min_r2"]:
        return {"rise_db": round(rise, 1), "slope_db_per_sec": round(float(slope), 1), "r2": round(r2, 2), "duration_sec": round(len(db) * 0.1, 1)}
    return None


# --------------------------------------------------------------------------------------------- moments
def _transition_events(path: Path, fps: float, duration: float, cut_threshold: float) -> tuple[list[dict], list[float]]:
    track, raw = shots_mod.frame_track(path, cut_threshold)
    cuts = shots_mod.merge_cuts(raw, duration)
    gradual = shots_mod.gradual_transitions(path, fps, cuts)
    kinds = shots_mod.classify_gradual(track, gradual)
    flashes, dips = shots_mod.flashes_and_dips(track)
    ev = [{"type": "hard_cut", "basis": "MEASURED", "start": round(c, 3), "end": round(c, 3), "peak": round(c, 3), "frames": 0, "evidence": {"scdet_threshold": cut_threshold}} for c in cuts]
    ev += [{"type": "gradual_transition", "basis": "INFERRED", "start": round(g - 0.4, 3), "end": round(g + 0.4, 3), "peak": round(g, 3), "frames": 0,
            "evidence": {"kind": k, "window_sec": shots_mod.GRADUAL_WINDOW_SEC}} for g, k in zip(gradual, kinds)]
    ev += [{"type": "flash_frame", "basis": "MEASURED", "start": round(t, 3), "end": round(t + 2 / fps, 3), "peak": round(t, 3), "frames": 0, "evidence": {}} for t in flashes]
    ev += [{"type": "dip_to_black", "basis": "MEASURED", "start": round(t, 3), "end": round(t + 2 / fps, 3), "peak": round(t, 3), "frames": 0, "evidence": {}} for t in dips]
    return ev, cuts


def group_moments(events: list[dict], merge_sec: float) -> list[dict]:
    """Events close together become one moment. Long events (a 3 s hold, a slow leak) join the moment
    they start in but do not stretch it, or every event in a video would chain into one."""
    moments: list[dict] = []
    for e in sorted(events, key=lambda e: e["start"]):
        reach = e["end"] if e["end"] - e["start"] <= 1.0 else e["start"]
        if moments and e["start"] <= moments[-1]["_reach"] + merge_sec:
            m = moments[-1]
            m["events"].append(e)
            m["end"] = max(m["end"], e["end"])
            m["_reach"] = max(m["_reach"], reach)
        else:
            moments.append({"start": e["start"], "end": e["end"], "_reach": reach, "events": [e]})
    for m in moments:
        m.pop("_reach")
    for i, m in enumerate(moments, 1):
        m["id"] = f"M{i:03d}"
        cut = next((e for e in m["events"] if e["type"] == "hard_cut"), None)
        lead = cut or max(m["events"], key=lambda e: e["frames"])
        m["time"] = lead["peak"]
    return moments


def suggest(moment: dict, recipes: set[str], fps: float) -> dict:
    """Closest registered recipe, plus a TransitionStack-style layer stack with measured parameters."""
    by = {}
    for e in moment["events"]:
        by.setdefault(e["type"], e)
    layers = []
    env = lambda e: {"attack": max(1, int(round((moment["time"] - e["start"]) * fps))), "release": max(1, int(round((e["end"] - moment["time"]) * fps)))}  # noqa: E731
    if "rgb_split" in by:
        e = by["rgb_split"]
        layers.append({"kind": "rgb_split", "px": e["evidence"]["max_offset_px_at_1920"], **env(e)})
    if "glitch_tear" in by:
        e = by["glitch_tear"]
        layers.append({"kind": "glitch_slices", "maxOffsetPx": round(e["evidence"]["max_band_spread_px_at_320"] * 6), **env(e)})
    if "whip_pan" in by:
        e = by["whip_pan"]
        layers.append({"kind": "whip_pan", "direction": e["evidence"]["direction"] or "right", **env(e)})
    if "zoom" in by:
        e = by["zoom"]
        layers.append({"kind": "zoom_punch", "scale": e["evidence"]["total_scale"], **env(e)})
    if "blur" in by:
        layers.append({"kind": "blur", **env(by["blur"])})
    if "frame_hold" in by:
        e = by["frame_hold"]
        layers.append({"kind": "stutter", "holdFrames": e["evidence"]["held_frames"], **env(e)})
    if "light_leak" in by:
        e = by["light_leak"]
        layers.append({"kind": "overlay", "select": {"category": "light_leak", "tone": e["evidence"]["tone"]}, **env(e)})
    if "flash_frame" in by or "exposure_bloom" in by:
        e = by.get("flash_frame") or by["exposure_bloom"]
        layers.append({"kind": "flash", "color": "#fff", **env(e)})
    if "dip_to_black" in by:
        layers.append({"kind": "dip", "color": "#000", **env(by["dip_to_black"])})
    gradual = by.get("gradual_transition", {}).get("evidence", {}).get("kind")
    cut = "hard" if "hard_cut" in by else ("crossfade" if gradual == "dissolve" else "gradual" if gradual else "none")

    whip_dir = by.get("whip_pan", {}).get("evidence", {}).get("direction")
    leak_tone = by.get("light_leak", {}).get("evidence", {}).get("tone", "warm")
    order = [
        ("halftone", "halftone_reveal", "a regular dot grid resolving into the picture"),
        ("glitch_tear+rgb_split", "glitch_cut", "displaced bands with channel separation"),
        ("glitch_tear", "digital_tear", "displaced horizontal bands"),
        ("whip_pan+light_leak", "leak_whip", "a whip pan carrying a light leak"),
        ("whip_pan", f"whip_pan_{whip_dir}" if whip_dir in ("left", "right", "up") else "whip_pan_right", "one-axis motion blur across the cut"),
        ("zoom", "whip_zoom", "a fast scale change through the cut"),
        ("rgb_split", "rgb_split_hit", "red/blue channels pulled apart"),
        ("frame_hold", "stutter_cut", "frames held after motion"),
        ("light_leak+gradual_transition", "leak_crossfade", "a coloured light rise during a gradual change"),
        ("light_leak", "light_leak_cool" if leak_tone == "cool" else "light_leak_warm", f"a {leak_tone} light rise"),
        ("flash_frame", "flash_cut", "a white flash on the cut"),
        ("exposure_bloom", "exposure_bump", "a brightness bloom without a colour shift"),
        ("blur", "blur_dissolve", "the picture loses focus through the change"),
        ("dip_to_black", "dip_to_black", "frames go to black"),
    ]
    recipe, why = None, None
    for need, rid, reason in order:
        if all(k in by for k in need.split("+")):
            recipe, why = rid, reason
            break
    if recipe is None:
        recipe, why = {"dissolve": ("crossfade_soft", "a plain dissolve"), "light": ("film_burn_passage", "a change through bright light"),
                       "dark": ("dip_to_black", "a change through black")}.get(gradual, ("hard_cut", "a clean cut") if cut == "hard" else (None, None))
    if recipe and recipe not in recipes:
        why = f"{why} (closest recipe '{recipe}' is not registered)"
        recipe = None
    return {"recipe": recipe, "why": why, "cut": cut, "layers": layers}


def attach_sound(moment: dict, audio: dict, cfg: dict) -> dict:
    if audio.get("status") != "measured":
        return {"status": audio.get("status", "not_measured")}
    t = moment["time"]
    env, et, floor = audio["env_db"], audio["env_t"], audio["floor_db"]
    out: dict = {"status": "measured", "riser_into_moment": riser_before(audio["y"], audio["sr"], t, cfg, floor)}
    win = np.flatnonzero((et >= t - cfg["sound_before_sec"]) & (et <= t + cfg["sound_after_sec"]))
    pre = env[(et >= t - cfg["sound_before_sec"] - 0.5) & (et < t - cfg["sound_before_sec"])]
    if not len(win):
        out.update(onset=None, note="no audio at this moment")
        return out
    p = int(win[np.argmax(env[win])])
    prominence = float(env[p] - max(floor, float(np.median(pre)) if len(pre) else floor))
    if prominence < cfg["sound_min_prominence_db"]:
        out.update(onset=None, note=f"no distinct sound (loudest peak {prominence:.1f} dB above what came before)")
        return out
    s0 = p
    while s0 > 0 and env[s0 - 1] >= env[p] - 20:
        s0 -= 1
    c = classify_sound(audio["y"], audio["sr"], float(et[p]) - 0.02, cfg)
    out.update(onset={"time": round(float(et[s0]), 3), "peak_time": round(float(et[p]), 3), "basis": "MEASURED",
                      "offset_from_moment_sec": round(float(et[s0]) - t, 3), "peak_dbfs": round(float(env[p]), 1), "prominence_db": round(prominence, 1)},
               sound_class={"label": c["class"], "basis": "INFERRED", "features": c["features"],
                            "support": round(min(cfg["max_inferred_support"], prominence / 40), 2)})
    return out


def review_strip(path: Path, moment: dict, fps: float, dest: Path) -> None:
    offsets = [-6, -2, 0, 2, 6]
    tiles = []
    for k in offsets:
        try:
            tiles.append(frame_at(path, max(0.0, moment["time"] + k / fps), 256))
        except (ValueError, subprocess.CalledProcessError):
            continue
    if tiles:
        h = min(t.shape[0] for t in tiles)
        cv2.imwrite(str(dest), cv2.cvtColor(np.hstack([t[:h] for t in tiles]), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])


def analyze(video: Path, out_dir: Path, config: dict | None = None, cut_threshold: float = 10.0, strips: bool = True,
            with_speech: bool = True) -> dict:
    cfg = {**BREAKDOWN_DEFAULTS, **(config or {})}
    src = probe(video)
    fps = src["fps"] or 30.0
    if src["duration_sec"] < 1.0:
        raise ValueError(f"{video.name} is {src['duration_sec']:.2f} s long; a breakdown needs at least 1 s of video")
    transitions, cuts = _transition_events(video, fps, src["duration_sec"], cut_threshold)
    frames = measure_frames(video, src, cfg)
    effects = visual_events(frames, fps, cuts, cfg, fit_long_side(src, cfg["motion_long_side"]))
    moments = group_moments(transitions + effects, cfg["moment_merge_sec"])
    audio = audio_events(video, cfg) if src["has_audio"] else {"status": "no_audio_track"}
    speech = speech_mod.spans(video) if with_speech and audio.get("status") == "measured" else None
    recipes = known_transitions()
    out_dir.mkdir(parents=True, exist_ok=True)
    if strips:
        (out_dir / "strips").mkdir(exist_ok=True)
    for m in moments:
        m["suggestion"] = suggest(m, recipes, fps)
        m["sound"] = attach_sound(m, audio, cfg)
        onset = m["sound"].get("onset")
        if onset and speech is not None:
            onset["during_speech"] = any(a - 0.1 <= onset["peak_time"] <= b + 0.1 for a, b in speech)
        m["review"] = "UNREVIEWED"
        if strips:
            review_strip(video, m, fps, out_dir / "strips" / f"{m['id']}.jpg")
            m["strip"] = f"strips/{m['id']}.jpg"
    result = {
        "schema_version": 1,
        "source": {"file": video.name, "sha256": sha256(video), **src},
        "config": {k: list(v) if isinstance(v, tuple) else v for k, v in cfg.items()},
        "measurements": MEASUREMENTS,
        "not_measured": [k for k, v in MEASUREMENTS.items() if v["status"] == "NOT_MEASURED"],
        "frames_measured": len(frames),
        "speech_check": "not_run" if speech is None else {"segments": len(speech), "speech_sec": round(sum(b - a for a, b in speech), 1)},
        "moments": moments,
        "limitations": [
            "Effect labels are INFERRED from the measured numbers in each event's evidence; check the review strip before relying on one.",
            "Sound labels describe the envelope (click, impact, whoosh, hit, riser), not what made the sound; in a music bed the nearest onset may be a note.",
            "Recipes are the closest registered NarrativeOS transition, not a claim about how the original was made.",
        ],
    }
    (out_dir / "breakdown.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (out_dir / "breakdown.md").write_text(report(result), encoding="utf-8")
    return result


def _ts(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def report(result: dict) -> str:
    s = result["source"]
    lines = [f"# Effect breakdown: {s['file']}", "",
             f"{s['duration_sec']:.2f} s, {s['width']}x{s['height']} @ {s['fps'] or '?'} fps. {len(result['moments'])} moments.", "",
             "Every row comes from a detector. **MEASURED** = read from pixels or samples; **INFERRED** = a named effect recognised from those measurements by a stated rule. Look at each row's strip before trusting an INFERRED label.", "",
             "| time | what was detected | recreate in NarrativeOS | sound |", "|---|---|---|---|"]
    for m in result["moments"]:
        what = []
        for e in m["events"]:
            ev = ", ".join(f"{k} {v}" for k, v in e["evidence"].items() if v is not None and k not in ("scdet_threshold", "threshold", "threshold_px_at_1920", "threshold_px_at_320", "window_sec"))
            what.append(f"{e['type'].replace('_', ' ')} ({e['basis']}{'; ' + ev if ev else ''})")
        sug = m["suggestion"]
        rec = f"`{sug['recipe']}`: {sug['why']}" if sug["recipe"] else (sug["why"] or "no matching recipe")
        tech = [TECHNIQUE[e["type"]][0] for e in m["events"] if e["type"] in TECHNIQUE]
        if tech:
            rec += "<br>layers: " + "; ".join(dict.fromkeys(tech))
        snd = m["sound"]
        if snd.get("status") != "measured":
            sound = snd.get("status", "")
        elif snd.get("onset"):
            o, c = snd["onset"], snd["sound_class"]
            sound = f"{c['label']} (INFERRED) starting {_ts(o['time'])} ({o['offset_from_moment_sec']:+.2f} s), {o['prominence_db']} dB above what came before"
            if o.get("during_speech"):
                sound += "; **during speech: may be the voice, not an effect**"
        else:
            sound = snd.get("note", "no distinct sound")
        if snd.get("riser_into_moment"):
            sound += f"; riser into it (+{snd['riser_into_moment']['rise_db']} dB)"
        span = _ts(m["time"]) if m["end"] - m["start"] < 0.1 else f"{_ts(m['start'])}–{_ts(m['end'])}"
        lines.append(f"| {span} | {'<br>'.join(what)} | {rec} | {sound} |")
    lines += ["", "## Not measured", *[f"- **{k}**: {result['measurements'][k]['reason']}" for k in result["not_measured"]],
              "", "## Equivalent techniques (reference, not findings)",
              *[f"- **{k.replace('_', ' ')}**: {v[1]}" for k, v in TECHNIQUE.items()],
              "", "## Limitations", *[f"- {x}" for x in result["limitations"]], ""]
    return "\n".join(lines)
