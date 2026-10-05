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
from . import typography as typo_mod
from .media import extract_audio, frame_at, probe, sha256
from .profile import known_transitions

# Every threshold lives here; callers override any subset via analyze(config=...).
# Pixel values are on the analysis frame (ANALYSIS_WIDTH wide) unless the name says otherwise.
BREAKDOWN_DEFAULTS = {
    "analysis_long_side": 640,        # frames are measured at this size (long side), so vertical video costs the same
    "motion_long_side": 320,          # global motion, sharpness, holds and glitch bands use this size
    "rgb_split_min_px": 1.5,          # median red-to-blue edge displacement on the motion frame (9 px on a 1080p frame);
                                      # clean footage measured 0.1-0.7, real RGB-split montage frames 3.8-8.1
    "rgb_split_min_coherence": 0.5,   # median displacement vector (or radial part) / median magnitude: a split has a direction
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
    "sound_before_sec": 0.5,          # a moment's sound is the strongest foreground peak in this window
    "sound_after_sec": 0.35,
    "sound_hop": 256,                 # ~11.6 ms at 22.05 kHz
    "sound_mel_bands": 64,
    "sound_background_sec": 3.0,      # each band's background = its rolling median over this long
    "sound_min_excess_db": 6.0,       # mean dB a sound must stick out of the bed, across all bands (a mix's median is ~1.5)
    "sound_band_excess_db": 6.0,      # a band counts as excited above this
    "sound_top_band_hz": 4000.0,
    "sound_top_min_excess_db": 9.0,   # ... or the bands above sound_top_band_hz alone must stick out this far
    "sound_only_min_excess_db": 8.0,  # a sound with no visual event becomes its own moment above this (title SFX, hits)
    "click_max_ms": 120.0,
    "click_min_breadth": 0.3,         # share of bands excited: clicks and hits are broadband, notes are not
    "impact_max_attack_ms": 50.0,     # the frame hop and smoothing alone smear an instant attack over ~35 ms
    "impact_min_decay_ms": 150.0,     # how long the sub-200 Hz excess rings on after the peak
    "whoosh_min_attack_ms": 80.0,
    "whoosh_min_breadth": 0.3,
    "whoosh_active_ms": (200.0, 2500.0),
    "riser_band_hz": 2000.0,          # risers and noise sweeps are measured on energy above this
    "riser_window_sec": 2.5,
    "riser_min_rise_db": 8.0,
    "riser_min_r2": 0.6,
    "riser_min_sec": 1.0,             # the climb itself must last this long
    "riser_min_above_floor_db": 10.0,
    "max_inferred_support": 0.75,     # inferred labels never claim more support than this
}

MEASUREMENTS = {
    "hard_cut": {"status": "MEASURED", "method": "ffmpeg scdet frame difference"},
    "gradual_transition": {"status": "INFERRED", "method": "colour histograms 0.5 s apart; light / dark / dissolve from the luma path"},
    "flash_frame": {"status": "MEASURED", "method": "luma jump >= 60 that falls back within 4 frames"},
    "dip_to_black": {"status": "MEASURED", "method": ">= 2 frames near black"},
    "frame_hold": {"status": "MEASURED", "method": "consecutive identical frames right after motion"},
    "rgb_split": {"status": "MEASURED", "method": "dense optical flow from the red channel's edges to the blue channel's (uniform, radial or warped splits)"},
    "glitch_tear": {"status": "INFERRED", "method": "horizontal bands displaced by different amounts against the previous frame"},
    "whip_pan": {"status": "INFERRED", "method": "one-axis motion blur (gradient anisotropy) with a sharpness collapse; direction from global motion"},
    "zoom": {"status": "MEASURED", "method": "scale of a similarity transform fitted to ORB matches between consecutive frames"},
    "blur": {"status": "INFERRED", "method": "Laplacian sharpness far below the shot's median, without a direction"},
    "halftone": {"status": "INFERRED", "method": "a 2-D lattice in the whitened image spectrum (two directions plus their sum or difference) made of separate dots"},
    "light_leak": {"status": "INFERRED", "method": "brightness rise with a colour shift over several frames"},
    "exposure_bloom": {"status": "INFERRED", "method": "brightness rise without a colour shift, longer than a flash frame"},
    "sound_onset": {"status": "MEASURED", "method": "strongest foreground peak near each moment: mel bands compared with their own rolling median, so effects over a compressed music bed still show; onset = where it rose above 20 % of that peak"},
    "sound_class": {"status": "INFERRED", "method": "rules on the foreground's envelope and spread: click, impact, whoosh, hit; riser = straight-line climb of energy above 2 kHz"},
    "speech_overlap": {"status": "INFERRED", "method": "faster-whisper speech segments (times only); a sound inside one may be the voice, not an effect"},
    "typography": {"status": "MEASURED", "method": "RapidOCR text detection and recognition on sampled frames, tracked over time; start and end refined to the frame"},
    "text_in": {"status": "MEASURED", "method": "first frame a text line is detected; its animation (type-on, fade, slide, scale, tracking, cut) is INFERRED from per-frame signals"},
    "text_out": {"status": "MEASURED", "method": "first frame a text line is gone; its animation is INFERRED like text_in"},
    "text_effect": {"status": "INFERRED", "method": "red/blue split or band tearing measured inside the text box"},
    "font_family": {"status": "NOT_MEASURED", "reason": "no font identification; size, weight (stroke/height), colour, case and spacing are measured"},
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


def _edges(channel: np.ndarray) -> np.ndarray:
    c = cv2.GaussianBlur(channel.astype(np.float32), (0, 0), 1.0)
    g = cv2.magnitude(cv2.Sobel(c, cv2.CV_32F, 1, 0), cv2.Sobel(c, cv2.CV_32F, 0, 1))
    return cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def channel_misregistration(rgb_small: np.ndarray) -> dict:
    """How far the blue channel's edges sit from the red channel's: dense optical flow between their edge maps.

    Edge maps, not raw channels, so a red object on a green field is not a 'shift'. Flow, not a single
    translation, so radial (lens-style) and warped splits are measured too. Median over the strongest edges."""
    er, eb = _edges(rgb_small[..., 0]), _edges(rgb_small[..., 2])
    flow = cv2.calcOpticalFlowFarneback(er, eb, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    g = np.maximum(er, eb)
    mask = g >= max(8, int(np.percentile(g, 80)))
    if mask.sum() < 50:
        return {"rgb_mag": 0.0, "rgb_dx": 0.0, "rgb_dy": 0.0, "rgb_radial": 0.0}
    fx, fy = flow[..., 0][mask], flow[..., 1][mask]
    h, w = er.shape
    yy, xx = np.mgrid[0:h, 0:w]
    rx, ry = (xx - w / 2)[mask], (yy - h / 2)[mask]
    radial = (fx * rx + fy * ry) / (np.hypot(rx, ry) + 1e-6)
    return {"rgb_mag": float(np.median(np.hypot(fx, fy))), "rgb_dx": float(np.median(fx)), "rgb_dy": float(np.median(fy)),
            "rgb_radial": float(np.median(radial))}


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
        out.update(channel_misregistration(cv2.resize(rgb, self.motion_size, interpolation=cv2.INTER_AREA)))
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
    off = col("rgb_mag")
    for a, b in _runs(off >= cfg["rgb_split_min_px"]):
        p = a + int(np.argmax(off[a : b + 1]))
        scale = 1920 / cfg["motion_long_side"]  # "at_1920": on a 1080p frame (long side 1920), either orientation
        mag, dx, dy, rad = float(off[p]), frames[p]["rgb_dx"], frames[p]["rgb_dy"], frames[p]["rgb_radial"]
        coherent = max(float(np.hypot(dx, dy)), abs(rad)) / max(mag, 1e-6)
        if coherent < cfg["rgb_split_min_coherence"]:
            continue  # edges displaced every which way: flow noise on blur or flare, not an offset channel
        pattern = "uniform" if np.hypot(dx, dy) >= 0.7 * mag else ("radial" if abs(rad) >= 0.5 * mag else "mixed")
        add("rgb_split", a, b, {"max_offset_px_at_1920": round(mag * scale, 1), "dx_px_at_1920": round(dx * scale, 1),
                                "dy_px_at_1920": round(dy * scale, 1), "pattern": pattern,
                                "threshold_px_at_1920": round(cfg["rgb_split_min_px"] * scale, 1)}, p)

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
# Sound effects in an edit sit ON TOP of music that is often compressed flat, so overall loudness barely
# moves when a whoosh or a glitch hits. Each mel band is therefore compared with its own recent background
# (a rolling median): what sticks out of the bed is the foreground, and that is what is found and classified.
def audio_events(path: Path, cfg: dict) -> dict:
    import librosa
    from scipy.ndimage import median_filter

    with tempfile.TemporaryDirectory() as td:
        wav = extract_audio(path, Path(td) / "a.wav", sr=22050)
        y, sr = librosa.load(str(wav), sr=22050, mono=True)
    if len(y) == 0 or float(np.sqrt(np.mean(y ** 2))) < 1e-4:
        return {"status": "silent"}
    hop = cfg["sound_hop"]
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=1024, hop_length=hop, n_mels=cfg["sound_mel_bands"], fmin=40, fmax=sr / 2)
    db = librosa.power_to_db(mel, ref=np.max)
    background = median_filter(db, size=(1, max(3, int(cfg["sound_background_sec"] * sr / hop))), mode="nearest")
    excess = db - background
    freqs = librosa.mel_frequencies(n_mels=cfg["sound_mel_bands"], fmin=40, fmax=sr / 2)
    clipped = np.clip(excess, 0, 24)
    # Mean dB a frame sticks out of the bed, over all bands or over the top bands alone (music leaves the top
    # nearly empty, so clicks and glitches show there first), whichever is stronger.
    top = clipped[freqs >= cfg["sound_top_band_hz"]].mean(axis=0) * cfg["sound_min_excess_db"] / cfg["sound_top_min_excess_db"]
    score = np.convolve(np.maximum(clipped.mean(axis=0), top), np.ones(3) / 3, mode="same")
    high = db[freqs >= cfg["riser_band_hz"]].mean(axis=0)
    return {"status": "measured", "hop_sec": hop / sr, "excess": excess, "score": score, "freqs": freqs, "high_db": high,
            "high_floor_db": float(np.percentile(high, 10)), "score_median": float(np.median(score))}


def classify_sound(audio: dict, p: int, cfg: dict) -> dict:
    """Label the foreground sound peaking at frame p.

    Its envelope is measured on the bands it actually excites (a low boom lives in a few bottom bands;
    averaged over all of them its tail would vanish), and its spread over its whole active span."""
    hop_ms = audio["hop_sec"] * 1000
    ex_all = np.clip(audio["excess"], 0, 24)
    bands = ex_all[:, max(0, p - 2) : p + 3].mean(axis=1) >= cfg["sound_band_excess_db"]
    if not bands.any():
        bands[:] = True
    env = ex_all[bands].mean(axis=0)
    peak = float(env[p])
    start, end = p, p
    while start > 0 and env[start - 1] >= 0.2 * peak:
        start -= 1
    while end < len(env) - 1 and env[end + 1] >= 0.2 * peak:
        end += 1
    attack, decay = (p - start) * hop_ms, (end - p) * hop_ms
    ex = ex_all[:, start : end + 1].sum(axis=1)
    total = max(float(ex.sum()), 1e-6)
    freqs = audio["freqs"]
    low_share = float(ex[freqs < 200].sum() / total)
    high_share = float(ex[freqs >= 4000].sum() / total)
    breadth = float(bands.mean())
    # The low end on its own: an impact is a fast start whose bass rings on after any broadband crack.
    low_env = ex_all[freqs < 200].mean(axis=0) if (freqs < 200).any() else np.zeros_like(env)
    win = low_env[max(0, p - 3) : p + 6]
    lp = max(0, p - 3) + int(np.argmax(win)) if len(win) else p
    low_peak, le = float(low_env[lp]), lp
    while le < len(low_env) - 1 and low_env[le + 1] >= 0.2 * low_peak:
        le += 1
    low_decay = (le - lp) * hop_ms if low_peak >= cfg["sound_band_excess_db"] else 0.0
    f = {"attack_ms": round(attack, 1), "decay_ms": round(decay, 1), "active_ms": round(attack + decay, 1),
         "breadth": round(breadth, 2), "low_share": round(low_share, 2), "high_share": round(high_share, 2),
         "low_peak_excess_db": round(low_peak, 1), "low_decay_ms": round(low_decay, 1)}
    lo, hi = cfg["whoosh_active_ms"]
    if attack <= cfg["impact_max_attack_ms"] and low_decay >= cfg["impact_min_decay_ms"]:
        label = "impact"
    elif attack + decay <= cfg["click_max_ms"] and breadth >= cfg["click_min_breadth"]:
        label = "click"  # a glitch tick, shutter or click: the shape cannot tell them apart
    elif attack >= cfg["whoosh_min_attack_ms"] and breadth >= cfg["whoosh_min_breadth"] and lo <= attack + decay <= hi:
        label = "whoosh"
    elif attack <= cfg["impact_max_attack_ms"] and breadth >= cfg["click_min_breadth"]:
        label = "hit"
    else:
        label = "unclassified"
    return {"class": label, "features": f, "start": start}


def riser_before(audio: dict, t: float, cfg: dict) -> dict | None:
    """A sustained climb of high-band energy (>= riser_band_hz) into t: risers and noise sweeps live up there.

    Only the stretch from the quietest point before t is fitted: a louder tail before it (an impact
    decaying) or a sound simply starting out of silence is not a climb."""
    hop = audio["hop_sec"]
    step = max(1, int(round(0.1 / hop)))
    a, b = max(0, int((t - cfg["riser_window_sec"]) / hop)), int(t / hop)
    curve = audio["high_db"][a:b]
    if len(curve) < 10 * step:
        return None
    db = np.array([curve[i : i + step].mean() for i in range(0, len(curve) - step + 1, step)])
    k = len(db)
    while k > 0 and db[k - 1] >= audio["high_floor_db"] + cfg["riser_min_above_floor_db"]:
        k -= 1
    db = db[k:]
    if len(db) >= 3:
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
        return {"rise_db": round(rise, 1), "slope_db_per_sec": round(float(slope), 1), "r2": round(r2, 2), "duration_sec": round(len(db) * 0.1, 1),
                "band_hz": f">= {cfg['riser_band_hz']:.0f}"}
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
        second_cut = e["type"] == "hard_cut" and moments and any(x["type"] == "hard_cut" for x in moments[-1]["events"])
        if moments and e["start"] <= moments[-1]["_reach"] + merge_sec and not second_cut:  # a fast montage is one moment per cut
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
    if recipe is None and any(k.startswith("text_") for k in by):
        lines = sorted({e["evidence"]["line"] for e in moment["events"] if e["type"].startswith("text_")})
        recipe, why = None, f"a text animation: see On-screen text ({', '.join(lines)})"
    if recipe and recipe not in recipes:
        why = f"{why} (closest recipe '{recipe}' is not registered)"
        recipe = None
    return {"recipe": recipe, "why": why, "cut": cut, "layers": layers}


def attach_sound(moment: dict, audio: dict, cfg: dict) -> dict:
    if audio.get("status") != "measured":
        return {"status": audio.get("status", "not_measured")}
    t, hop, score = moment["time"], audio["hop_sec"], audio["score"]
    out: dict = {"status": "measured", "riser_into_moment": riser_before(audio, t, cfg)}
    a, b = max(0, int((t - cfg["sound_before_sec"]) / hop)), min(len(score), int((t + cfg["sound_after_sec"]) / hop) + 1)
    if b <= a:
        out.update(onset=None, note="no audio at this moment")
        return out
    p = a + int(np.argmax(score[a:b]))
    peak = float(score[p])
    if peak < cfg["sound_min_excess_db"]:
        out.update(onset=None, note=f"nothing stands out of the bed (peak {peak:.1f} dB over the band background)")
        return out
    c = classify_sound(audio, p, cfg)
    start = c["start"]
    out.update(onset={"time": round(start * hop, 3), "peak_time": round(p * hop, 3), "basis": "MEASURED",
                      "offset_from_moment_sec": round(start * hop - t, 3), "excess_db": round(peak, 1)},
               sound_class={"label": c["class"], "basis": "INFERRED", "features": c["features"],
                            "support": round(min(cfg["max_inferred_support"], peak / 24), 2)})
    return out


def add_sound_only_moments(moments: list[dict], audio: dict, speech: list | None, cfg: dict) -> list[dict]:
    """Strong foreground sounds with no visual event nearby (SFX on a text animation, a hit on a held shot)."""
    if audio.get("status") != "measured":
        return moments
    hop, score = audio["hop_sec"], audio["score"]
    taken = [(m["time"] - cfg["sound_before_sec"], m["time"] + cfg["sound_after_sec"]) for m in moments]
    peaks = [i for i in range(1, len(score) - 1) if score[i] >= cfg["sound_only_min_excess_db"] and score[i] >= score[i - 1] and score[i] > score[i + 1]]
    chosen: list[int] = []
    for i in sorted(peaks, key=lambda i: -score[i]):
        t = i * hop
        if any(a <= t <= b for a, b in taken) or any(abs(t - j * hop) < 0.3 for j in chosen):
            continue
        if speech and any(a - 0.1 <= t <= b + 0.1 for a, b in speech):
            continue  # sibilants and plosives live in the same bands; a voice is not an effect
        chosen.append(i)
    extra = []
    for i in chosen:
        m = {"start": round(i * hop, 3), "end": round(i * hop, 3), "time": round(i * hop, 3), "events": [], "sound_only": True,
             "suggestion": {"recipe": None, "why": "a sound with no visual event: place it on the matching text or graphic animation", "cut": "none", "layers": []},
             "review": "UNREVIEWED"}
        m["sound"] = attach_sound(m, audio, cfg)
        extra.append(m)
    merged = sorted(moments + extra, key=lambda m: m["time"])
    ids = {m["id"]: f"M{k:03d}" for k, m in enumerate(merged, 1) if "id" in m}
    for k, m in enumerate(merged, 1):
        m["id"] = f"M{k:03d}"
        note = m["sound"].get("note", "")
        if note.startswith("same sound as "):
            m["sound"]["note"] = "same sound as " + ids.get(note[len("same sound as "):], note[len("same sound as "):])
    return merged


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


def text_events(typo: dict, duration: float, frame_events: list[dict] | None = None, fps: float = 30.0) -> list[dict]:
    """Text lines as moment events: in, out, and effects that hit them.

    An effect measured in a text box that coincides with a cut or a frame-wide effect is the frame's, not the text's."""
    frame_wide = [e for e in (frame_events or []) if e["type"] in ("hard_cut", "rgb_split", "glitch_tear", "flash_frame", "whip_pan", "zoom", "blur")]
    ev = []
    if typo.get("status") != "MEASURED":
        return ev
    for ln in typo["lines"]:
        if ln.get("cover_frame"):
            continue  # the export's thumbnail frame, not part of the edit
        label = {"line": ln["id"], "text": ln["text"]}
        if ln["start"] > 0.05:
            ev.append({"type": "text_in", "basis": "MEASURED", "start": ln["start"], "end": ln["start"], "peak": ln["start"], "frames": 0,
                       "evidence": {**label, "animation": "+".join(ln["in"]["kinds"])}})
        if ln["end"] < duration - 0.05:
            ev.append({"type": "text_out", "basis": "MEASURED", "start": ln["end"], "end": ln["end"], "peak": ln["end"], "frames": 0,
                       "evidence": {**label, "animation": "+".join(ln["out"]["kinds"])}})
        for fx in ln["effects"]:
            if any(e["start"] - 1.5 / fps <= fx["end"] and fx["start"] <= e["end"] + 1.5 / fps for e in frame_wide):
                fx["frame_wide"] = True
                continue
            ev.append({"type": "text_effect", "basis": "INFERRED", "start": fx["start"], "end": fx["end"], "peak": fx["peak"], "frames": fx["frames"],
                       "evidence": {**label, "effect": fx["type"], **fx["evidence"]}})
    return ev


def analyze(video: Path, out_dir: Path, config: dict | None = None, cut_threshold: float = 10.0, strips: bool = True,
            with_speech: bool = True, with_text: bool = False) -> dict:
    cfg = {**BREAKDOWN_DEFAULTS, **(config or {})}
    src = probe(video)
    fps = src["fps"] or 30.0
    if src["duration_sec"] < 1.0:
        raise ValueError(f"{video.name} is {src['duration_sec']:.2f} s long; a breakdown needs at least 1 s of video")
    transitions, cuts = _transition_events(video, fps, src["duration_sec"], cut_threshold)
    frames = measure_frames(video, src, cfg)
    effects = visual_events(frames, fps, cuts, cfg, fit_long_side(src, cfg["motion_long_side"]))
    typo = typo_mod.analyze(video, src) if with_text else {"status": "NOT_MEASURED", "reason": "not run (opt in with --text; it is the slow stage)"}
    moments = group_moments(transitions + effects + text_events(typo, src["duration_sec"], transitions + effects, fps), cfg["moment_merge_sec"])
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
    # One sound belongs to one moment: the one nearest its peak. The others point at it.
    # Overlapping windows can catch slightly different peaks of one sound, so a sound is keyed by where it starts.
    owner: dict[float, dict] = {}
    for m in moments:
        o = m["sound"].get("onset")
        if o and (o["time"] not in owner or abs(m["time"] - o["peak_time"]) < abs(owner[o["time"]]["time"] - owner[o["time"]]["sound"]["onset"]["peak_time"])):
            owner[o["time"]] = m
    for m in moments:
        o = m["sound"].get("onset")
        if o and owner[o["time"]] is not m:
            m["sound"] = {"status": "measured", "onset": None, "riser_into_moment": m["sound"].get("riser_into_moment"),
                          "note": f"same sound as {owner[o['time']]['id']}"}
    moments = add_sound_only_moments(moments, audio, speech, cfg)
    for m in moments:
        if strips:
            review_strip(video, m, fps, out_dir / "strips" / f"{m['id']}.jpg")
            m["strip"] = f"strips/{m['id']}.jpg"
    result = {
        "schema_version": 1,
        "source": {"file": video.name, "sha256": sha256(video), **src},
        "config": {k: list(v) if isinstance(v, tuple) else v for k, v in cfg.items()},
        "measurements": {**MEASUREMENTS, **({} if typo.get("status") == "MEASURED" else
                                            {"typography": {"status": "NOT_MEASURED", "reason": typo.get("reason", "not run")}})},
        "not_measured": [k for k, v in MEASUREMENTS.items() if v["status"] == "NOT_MEASURED" and not (k == "typography")]
                        + (["typography"] if typo.get("status") != "MEASURED" else []),
        "frames_measured": len(frames),
        "typography": typo,
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


def _anim(a: dict) -> str:
    ev = a.get("evidence", {})
    bits = []
    if "chars_per_sec" in ev:
        bits.append(f"{ev['chars_per_sec']} chars/s")
    if "slide_direction" in ev:
        bits.append(f"moving {ev['slide_direction']} {ev['slide_frac']:.0%} of the frame")
    if "edge_scale" in ev:
        bits.append(f"{ev['edge_scale']:.0%} of final size at the edge")
    if "tracking_from" in ev:
        bits.append(f"letter spacing {ev['tracking_from']:.0%} of final")
    if "energy_ramp_frames" in ev and "fade" in a["kinds"]:
        bits.append(f"over {ev['energy_ramp_frames']} frames")
    return "+".join(a["kinds"]) + (f" ({', '.join(bits)})" if bits else "")


def text_report(typo: dict) -> list[str]:
    if typo.get("status") != "MEASURED":
        return ["", "## On-screen text", "", f"Not measured: {typo.get('reason', 'not run')}"]
    by_id = {ln["id"]: ln for ln in typo["lines"]}
    cover = [ln for ln in typo["lines"] if ln.get("cover_frame")]
    out = ["", "## On-screen text", "",
           "Text, position, size and colour are **MEASURED** by OCR. Animations and effects are **INFERRED** from per-frame signals inside the text box. The font family is not identified.", "",
           "| time | text (block) | where, size, colour | in | out | effects on the text | template |", "|---|---|---|---|---|---|---|"]
    if cover:
        out.insert(-2, f"The first {cover[0]['end']:.2f} s is a cover (thumbnail) frame reading: {' / '.join(c['text'] for c in cover)}. It is not part of the edit.")
        out.insert(-2, "")
    for b in typo["blocks"]:
        for i, lid in enumerate(b["lines"]):
            ln = by_id[lid]
            fx = "; ".join(f"{f['type'].replace('_', ' ')} at {_ts(f['peak'])}" for f in ln["effects"] if not f.get("frame_wide")) or "none"
            tmpl = ""
            if i == 0:
                t = b["template"]
                tmpl = (", ".join(f"`{c}`" for c in t["candidates"]) + f": {t['why']}") if t["candidates"] else t["why"]
            style = f"{ln['region'].replace('_', ' ')}, {ln['height_frac']:.1%} of frame height, {ln.get('colour', '?')}"
            if ln.get("uppercase"):
                style += ", uppercase"
            if ln["width_per_char_to_height"] >= 1.0:
                style += ", wide letter spacing"
            if ln.get("stroke_to_height") is not None:
                style += f", stroke {ln['stroke_to_height']:.0%} of height"
            name = f"{ln['text']}" + (f" ({b['id']})" if len(b["lines"]) > 1 else "")
            out.append(f"| {_ts(ln['start'])}–{_ts(ln['end'])} | {name} | {style} | {_anim(ln['in'])} | {_anim(ln['out'])} | {fx} | {tmpl} |")
    return out


def report(result: dict) -> str:
    s = result["source"]
    lines = [f"# Effect breakdown: {s['file']}", "",
             f"{s['duration_sec']:.2f} s, {s['width']}x{s['height']} @ {s['fps'] or '?'} fps. {len(result['moments'])} moments.", "",
             "Every row comes from a detector. **MEASURED** = read from pixels or samples; **INFERRED** = a named effect recognised from those measurements by a stated rule. Look at each row's strip before trusting an INFERRED label.", "",
             "| time | what was detected | recreate in NarrativeOS | sound |", "|---|---|---|---|"]
    for m in result["moments"]:
        what = [] if m["events"] else ["no visual event (sound only; check the strip for text or graphics)"]
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
            sound = f"{c['label']} (INFERRED) starting {_ts(o['time'])} ({o['offset_from_moment_sec']:+.2f} s), {o['excess_db']} dB out of the bed"
            if o.get("during_speech"):
                sound += "; **during speech: may be the voice, not an effect**"
        else:
            sound = snd.get("note", "no distinct sound")
        if snd.get("riser_into_moment"):
            sound += f"; riser into it (+{snd['riser_into_moment']['rise_db']} dB)"
        span = _ts(m["time"]) if m["end"] - m["start"] < 0.1 else f"{_ts(m['start'])}–{_ts(m['end'])}"
        lines.append(f"| {span} | {'<br>'.join(what)} | {rec} | {sound} |")
    lines += text_report(result.get("typography") or {})
    lines += ["", "## Not measured", *[f"- **{k}**: {result['measurements'][k]['reason']}" for k in result["not_measured"]],
              "", "## Equivalent techniques (reference, not findings)",
              *[f"- **{k.replace('_', ' ')}**: {v[1]}" for k, v in TECHNIQUE.items()],
              "", "## Limitations", *[f"- {x}" for x in result["limitations"]], ""]
    return "\n".join(lines)
