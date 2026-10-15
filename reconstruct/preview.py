"""Assemble the remake as far as it is known, and a side-by-side preview against the reference.

Every frame of the remake comes from measurements or rebuilt layers:
- shots and their frames: the measured cuts (reconstruct.cuts), described by the watch pass;
- picture: a rebuilt clip where one exists (rebuild_*/), otherwise a card naming the shot and saying its source
  is not found yet (never the reference's own pixels);
- captions: the watched words at their frames, in the closest installed fonts measured on the clean caption
  (italic serif -> Century Schoolbook Bold Italic, heavy sans -> Franklin Gothic Heavy), with the measured glow;
- audio: the reference's separated stems for now (the music is only partly identified), and said so.
"""
from __future__ import annotations

import glob
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1276, 718
SERIF = r"C:\Windows\Fonts\SCHLBKBI.TTF"   # Century Schoolbook Bold Italic
SANS = r"C:\Windows\Fonts\FRAHV.TTF"
SERIF_SIZE, SANS_SIZE = 47, 54         # sizes that matched the "into this" caption's ink (MEASURED)
CORE_BLUR, HALO_SIGMA, HALO_GAIN = 1.1, 7.0, 0.65
CAPTION_CENTRE_Y = 340                 # "into this" ink box 280-400 (MEASURED)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        alt = {"CENSCBK.TTF": "CENSCBKI.TTF"}.get(Path(path).name)
        return ImageFont.truetype(str(Path(path).with_name(alt)) if alt else "arialbd.ttf", size)


def caption_items(work: Path) -> list[dict]:
    """Watched text items, in frame order (OBSERVED by the watch pass)."""
    items = []
    for f in sorted(glob.glob(str(work / "watch" / "w*_*.json"))):
        r = json.loads(Path(f).read_text(encoding="utf-8"))
        a, b = r["_meta"]["window"]
        for t in r.get("text", []):
            if a <= t["first"] <= b and t.get("words", "").strip():
                items.append(t)
    return sorted(items, key=lambda t: (t["first"], t["last"]))


def style_of(item: dict) -> str:
    s = item.get("style", "").lower()
    if "lower-third" in s or "broadcast" in s:
        return "skip"       # came with the footage, not added by the editor
    return "serif" if ("serif" in s and "sans" not in s) else "sans"


def render_caption(words: list[tuple[str, str]]) -> np.ndarray:
    """RGBA full-canvas caption: each (word, style) in its face, centred, white, with the measured glow."""
    fonts = {"serif": _font(SERIF, SERIF_SIZE), "sans": _font(SANS, SANS_SIZE)}
    space = 14
    widths = [fonts[st].getbbox(w)[2] - fonts[st].getbbox(w)[0] for w, st in words]
    total = sum(widths) + space * (len(words) - 1)
    x = (W - total) // 2
    core = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(core)
    for (w, st), wd in zip(words, widths):
        f = fonts[st]
        l, t, r, b = f.getbbox(w)
        d.text((x - l, CAPTION_CENTRE_Y - (t + b) // 2), w, font=f, fill=255)
        x += wd + space
    a = np.asarray(core, np.float32) / 255
    alpha = np.clip(cv2.GaussianBlur(a, (0, 0), CORE_BLUR) + HALO_GAIN * cv2.GaussianBlur(a, (0, 0), HALO_SIGMA), 0, 1)
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = 255
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return out


def caption_track(items: list[dict], frames: int) -> list[list[tuple[str, str]] | None]:
    """Per frame, the words on screen with their faces. A word keeps the face it had when it first appeared."""
    track: list = [None] * frames
    face: dict[str, str] = {}
    for it in items:
        st = style_of(it)
        if st == "skip":
            continue
        ws = it["words"].split()
        new = ws[-1]
        face.setdefault(new.lower(), st)
        line = [(w, face.get(w.lower(), st)) for w in ws]
        for f in range(max(0, it["first"]), min(frames, it["last"] + 1)):
            track[f] = line
    return track


def card(shot: dict, desc: str) -> np.ndarray:
    im = Image.new("RGB", (W, H), (28, 28, 30))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("arial.ttf", 22)
    d.text((24, H - 70), f"{shot['id']}  frames {shot['first']}-{shot['last']}  SOURCE NOT FOUND YET", font=f, fill=(230, 120, 90))
    d.text((24, H - 40), desc[:110], font=f, fill=(170, 170, 170))
    return np.asarray(im, np.float32)


def build(work: Path, ref_video: Path, out: Path, rebuilt: dict[int, Path], rebuilt_has_captions: bool = True) -> dict:
    """rebuilt: first frame -> rebuilt clip (full canvas, starting at that frame). A rebuilt clip that carries its own
    captions (rebuilt_has_captions) gets no second caption from this preview."""
    c = json.loads((work / "cuts.json").read_text(encoding="utf-8"))
    n, fps = c["frames"], c["source"]["fps"]
    shots = c["shots"]
    watched = []
    for f in sorted(glob.glob(str(work / "watch" / "w*_*.json"))):
        r = json.loads(Path(f).read_text(encoding="utf-8"))
        watched += r["shots"]

    def describe(s):
        best = max(watched, key=lambda w: min(w["last"], s["last"]) - max(w["first"], s["first"]), default=None)
        return best["content"] if best and min(best["last"], s["last"]) >= max(best["first"], s["first"]) else "not watched"

    rebuilt_frames: dict[int, np.ndarray] = {}
    for first, clip in rebuilt.items():
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        for k, fr in enumerate(np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)):
            rebuilt_frames[first + k] = fr.astype(np.float32)
    caps = caption_track(caption_items(work), n)
    cache: dict = {}
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", c["source"]["fps_rational"],
                             "-i", "-", "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    status = {"rebuilt_frames": 0, "card_frames": 0, "caption_frames": 0}
    shot_of = {}
    for s in shots:
        for f in range(s["first"], s["last"] + 1):
            shot_of[f] = s
    cards: dict[str, np.ndarray] = {}
    for f in range(n):
        if f in rebuilt_frames:
            img = rebuilt_frames[f].copy()
            status["rebuilt_frames"] += 1
        else:
            s = shot_of[f]
            if s["id"] not in cards:
                cards[s["id"]] = card(s, describe(s))
            img = cards[s["id"]].copy()
            status["card_frames"] += 1
        line = None if (rebuilt_has_captions and f in rebuilt_frames) else caps[f]
        if line:
            key = tuple(line)
            if key not in cache:
                cache[key] = render_caption(line)
            rgba = cache[key].astype(np.float32)
            a = rgba[..., 3:4] / 255
            img = img * (1 - a) + rgba[..., :3] * a
            status["caption_frames"] += 1
        proc.stdin.write(np.clip(img, 0, 255).astype(np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()
    status["frames"] = n
    return status


def side_by_side(ref_video: Path, remake: Path, audio: Path, out: Path) -> None:
    font = "C\\:/Windows/Fonts/arialbd.ttf"
    # Both sides re-timed to frame index / 29.97 so frame N pairs with frame N (two files declaring 2997/100 and
    # 30000/1001 were otherwise merged at 60 fps with one side shifted: MEASURED on preview_v3).
    fc = (f"[0:v]setpts=N/(29.97*TB),scale=960:540,drawtext=fontfile='{font}':text='ORIGINAL':x=16:y=12:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.6[a];"
          f"[1:v]setpts=N/(29.97*TB),scale=960:540,drawtext=fontfile='{font}':text='REMAKE  frame %{{n}}':x=16:y=12:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.6[b];"
          f"[a][b]hstack=2,fps=2997/100[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ref_video), "-i", str(remake), "-i", str(audio), "-filter_complex", fc, "-map", "[v]",
                    "-map", "2:a", "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)], check=True)
