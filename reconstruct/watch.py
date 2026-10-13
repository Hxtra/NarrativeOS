"""The watch pass: a vision model looks at every frame of a window and says what the editor did (OBSERVED).

Each window (a few seconds) is cut out with its sound, and the absolute frame number is burned into a black bar
under the picture, so the model can name exact frames rather than guess timestamps (a video model samples 1 fps
by default; here it gets every frame). The candidate cuts measured by reconstruct.cuts are given as candidates to
confirm or reject, never as answers. The output follows a fixed schema: shots, transition and effect frames,
layers, text and motion. Every claim is OBSERVED until a re-render containing it matches the reference.

Provider: Gemini (key from GEMINI_API_KEY or ~/.narrativeos/gemini.key). The schema and prompt are
model-agnostic; another provider can fill the same schema.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview"]
WATCH_FPS = 24  # the most frames per second the Gemini API samples; windows are re-timed so it sees every frame

PROMPT = """You are a senior video editor reverse-engineering a finished edit so it can be rebuilt exactly, frame for frame.
The clip is a window of the edit. A black bar under the picture shows the ABSOLUTE frame number (F####) of each frame;
it is not part of the edit. Every frame of the edit is included: the clip is slowed so each edit frame is one frame
of the clip (play speed {speed}), and the sound is slowed to match. Always use the F#### numbers, never clip time.

Measured candidate boundaries in this window (frame numbers where the picture changes a lot): {candidates}.
Some are real cuts; some are effect frames (flash, bloom, glitch, light hit) inside one shot; some cuts may be missing.
Decide each by looking.

Report, in frame numbers from the bar:
1. shots: every shot (a continuous piece of one source picture or one designed card), first and last frame. One-frame
   shots exist in this edit: do not merge them.
2. transitions: what happens between shots and on effect frames: hard cut, white flash, black frame, bloom, glitch,
   whip/motion blur, blended double-exposure frame, invert/negative, zoom blur, light leak, other (describe).
3. for each shot, its layers from back to front: base footage, inset picture (where on screen, a frame/border such as
   a TV set or monitor, a rounded or plain rectangle), collage panels, overlays (grain, glow, vignette, light leak, scan
   lines), and text. For footage: what it shows and its source type (interview, news broadcast with lower-third, archive
   photo, stock video, 3D render, AI-generated still, designed graphic).
4. motion of each layer during the shot: static, slow push-in, fast zoom, pull-out, pan (direction), shake, rotation,
   speed ramp.
5. text: every on-screen word, the frame it appears and the frame it leaves, its style (italic serif, bold sans, giant
   display type behind or in front of the subject, broadcast lower-third that came with the footage), and how it
   animates in (cut on, fade, blur-in, scale, typewriter, slide) and out.
6. colour/look of the shot: grade (warm/cool/neutral, contrast, saturation), black-and-white, inverted, glow, grain.
Cover EVERY frame of the window, from the first F number to the last: the shots must tile the window with no gap.
Be exact and literal. If unsure, say so in "uncertain" instead of guessing."""

SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {"type": "array", "items": {"type": "object", "properties": {
            "first": {"type": "integer"}, "last": {"type": "integer"},
            "content": {"type": "string"}, "source_type": {"type": "string"},
            "layers": {"type": "array", "items": {"type": "object", "properties": {
                "role": {"type": "string", "description": "base | inset | collage_panel | overlay | text | frame_graphic"},
                "description": {"type": "string"}, "position": {"type": "string"},
                "motion": {"type": "string"}}, "required": ["role", "description"]}},
            "look": {"type": "string"}, "uncertain": {"type": "string"}},
            "required": ["first", "last", "content", "layers"]}},
        "transitions": {"type": "array", "items": {"type": "object", "properties": {
            "first": {"type": "integer"}, "last": {"type": "integer"}, "kind": {"type": "string"}, "description": {"type": "string"}},
            "required": ["first", "last", "kind"]}},
        "text": {"type": "array", "items": {"type": "object", "properties": {
            "words": {"type": "string"}, "first": {"type": "integer"}, "last": {"type": "integer"},
            "style": {"type": "string"}, "position": {"type": "string"},
            "animation_in": {"type": "string"}, "animation_out": {"type": "string"}},
            "required": ["words", "first", "last", "style"]}},
        "candidates_rejected": {"type": "array", "items": {"type": "object", "properties": {
            "frame": {"type": "integer"}, "why": {"type": "string"}}, "required": ["frame", "why"]}},
        "notes": {"type": "string"},
    },
    "required": ["shots", "transitions", "text"],
}


def api_key() -> str:
    k = os.environ.get("NARRATIVEOS_GEMINI_KEY") or ""
    f = Path.home() / ".narrativeos" / "gemini.key"
    if not k and f.is_file():
        k = f.read_text(encoding="utf-8").strip()
    return k or os.environ.get("GEMINI_API_KEY", "")


def window_clip(video: Path, first: int, last: int, fps_rational: str, out: Path) -> Path:
    """Frames first..last with sound, the absolute frame number burned into a bar under the picture."""
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    num, den = (int(x) for x in fps_rational.split("/"))
    t0 = first * den / num
    dur = (last - first + 1) * den / num
    font = "C\\:/Windows/Fonts/arialbd.ttf"
    vf = (f"pad=iw:ih+56:0:0:black,drawtext=fontfile='{font}':text='F%{{eif\\:n+{first}\\:d\\:4}}':x=(w-tw)/2:y=h-46:"
          f"fontsize=40:fontcolor=white,setpts=N/({WATCH_FPS}*TB)")
    # Re-timed so every frame is one frame at WATCH_FPS (the API samples at most 24 fps); the sound is slowed to match.
    slow = WATCH_FPS / (num / den)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.4f}", "-i", str(video), "-t", f"{dur:.4f}", "-vf", vf, "-r", str(WATCH_FPS),
                    "-af", f"atempo={slow:.6f}", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "aac", "-b:a", "128k", str(out)], check=True)
    return out


def watch_window(clip: Path, first: int, last: int, candidates: list[int], fps: float, model: str, cache: Path) -> dict:
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key())
    part = types.Part(inline_data=types.Blob(data=clip.read_bytes(), mime_type="video/mp4"), video_metadata=types.VideoMetadata(fps=WATCH_FPS))
    prompt = PROMPT.format(speed=f"{WATCH_FPS / fps:.2f}x", candidates=", ".join(str(c) for c in candidates) or "none")
    t = time.time()
    tried = []
    for m in [model] + [x for x in FALLBACK_MODELS if x != model]:
        try:
            r = client.models.generate_content(model=m, contents=[part, prompt], config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=SCHEMA, temperature=0.1,
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH))
            model = m
            break
        except Exception as e:  # noqa: BLE001 - an overloaded or failing model falls through to the next one
            tried.append(f"{m}: {str(e)[:120]}")
    else:
        raise RuntimeError("every watcher model failed: " + " | ".join(tried))
    out = json.loads(r.text)
    um = r.usage_metadata
    out["_meta"] = {"model": model, "window": [first, last], "seconds": round(time.time() - t, 1), "status": "OBSERVED",
                    "tokens_in": getattr(um, "prompt_token_count", None), "tokens_out": getattr(um, "candidates_token_count", None), "fell_through": tried}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def watch_all(video: Path, work: Path, window: int = 120, model: str = "gemini-3.8-flash", parallel: int = 3) -> list[dict]:
    """Every window of the video, cached per window (a re-run only watches what is missing)."""
    from concurrent.futures import ThreadPoolExecutor
    c = json.loads((work / "cuts.json").read_text(encoding="utf-8"))
    n, fps, rat = c["frames"], c["source"]["fps"], c["source"]["fps_rational"]
    spans = [(a, min(n - 1, a + window - 1)) for a in range(0, n, window)]

    def one(span):
        a, b = span
        clip = window_clip(video, a, b, rat, work / "windows" / f"w{a:05d}_{b:05d}.mp4")
        cands = [x["frame"] for x in c["cuts"] if a <= x["frame"] <= b]
        try:
            r = watch_window(clip, a, b, cands, fps, model, work / "watch" / f"w{a:05d}_{b:05d}.json")
            print(f"window {a}-{b}: {len(r['shots'])} shots, {r['_meta']['model']}, {r['_meta']['seconds']}s", flush=True)
            return r
        except Exception as e:  # noqa: BLE001 - one failed window is reported; a re-run retries it
            print(f"window {a}-{b}: FAILED {str(e)[:200]}", flush=True)
            return None

    with ThreadPoolExecutor(parallel) as ex:
        return list(ex.map(one, spans))


if __name__ == "__main__":
    import sys
    watch_all(Path(sys.argv[1]), Path(sys.argv[2]))
