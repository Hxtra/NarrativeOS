#!/usr/bin/env python3
"""Multi-track timeline compiler: one validated timeline in, one FFmpeg render out. No stitching.

    python compile_timeline.py --project P [--timeline timeline_v3.json] [--output renders/preview.mp4] [--preview] [--release]
    python compile_timeline.py --project P --from-shot-timeline timeline.json [--narration narration.mp3] [--music m.mp3] [--captions captions.json]
    python compile_timeline.py --project P --validate-only

The timeline (IR 3.0) is the source of truth:

    {"ir_version": "3.0",
     "canvas": {"width": 1920, "height": 1080, "fps": 30, "sample_rate": 48000},
     "assets": [ ... optional project-produced media (narration) ... ],
     "tracks": [
       {"id": "v_main", "kind": "video", "items": [
          {"id": "S1", "asset_id": "a1", "timeline_in": 0, "timeline_out": 4.25, "source_in": 2.0, "fit": "cover",
           "motion": {"kind": "push_in", "scale_from": 1.0, "scale_to": 1.06},
           "audio": {"native": true, "gain_db": -6, "native_in": 0, "native_out": 4.75}},     # L-cut: sound runs on
          {"id": "S2", "asset_id": "a2", "timeline_in": 3.75, "timeline_out": 8,
           "transition_in": {"type": "crossfade", "duration": 0.5}}]},                         # real overlap
       {"id": "v_fx", "kind": "overlay", "items": [{"id": "leak", "asset_id": "leak1", "timeline_in": 3.5,
          "timeline_out": 4.5, "source_in": 1.0, "blend": "screen", "opacity": 0.8, "fade_in": 0.2, "fade_out": 0.3}]},
       {"id": "a_vo", "kind": "audio", "role": "narration", "items": [...]},
       {"id": "a_music", "kind": "audio", "role": "music", "duck_under": "a_vo",
        "duck": {"threshold": 0.03, "ratio": 8, "attack_ms": 20, "release_ms": 300}, "items": [...]},
       {"id": "a_sfx", "kind": "audio", "role": "sfx", "items": [...]},
       {"id": "cc", "kind": "caption", "style": {"font": "Arial", "size": 0.05}, "items": [
          {"id": "c1", "timeline_in": 0.5, "timeline_out": 2.0, "text": "..."}]}],
     "mix": {"loudnorm": {"I": -16, "TP": -1.5, "LRA": 11}}}

Compilation is a single FFmpeg invocation. Every item is decoded from its own source range, conformed to the
canvas, delayed to its timeline position and composited (video overlay / blend) or mixed (audio buses, music
ducked under narration by sidechain compression, loudness normalised); captions are burned with libass in the
same filtergraph. Main-track transitions are real overlaps: a crossfade is the incoming shot fading in over
the outgoing one; a dip fades both through a colour.

Before anything renders, the timeline is validated: unique IDs, finite monotonic times, every source range
(including transition handles and J/L audio windows) inside the probed asset, main-track overlaps only where a
transition declares them, approved assets only, paths inside the project or an allowed media root, captions
that do not overlap. After rendering, ffprobe must agree with the timeline: size, frame rate, duration within
one frame plus 50 ms, audio present exactly when audio was placed, and audio/video lengths within 80 ms. The
render manifest records the timeline hash, the filtergraph and the FFmpeg version, so a render can be
reproduced and audited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

IR_VERSION = "3.0"
TRACK_KINDS = {"video", "overlay", "audio", "caption"}
AUDIO_ROLES = {"narration", "music", "sfx", "ambience", "dialogue"}
TRANSITIONS = {"cut", "crossfade", "dip_black", "dip_white"}
BLENDS = {"normal", "screen", "add", "multiply"}
MOTIONS = {"none", "push_in", "pull_out"}
FITS = {"cover", "contain"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AV_TOLERANCE = 0.08          # audio vs video stream length
DURATION_TOLERANCE = 0.05    # plus one frame
EPS = 1e-6

# Transition recipes from the Remotion VFX library that FFmpeg can render natively here. Everything else is
# kept as a hard cut and listed as UNRENDERED (it needs the Remotion TransitionStack), never faked.
NATIVE_RECIPES = {
    "hard_cut": ("cut", 0.0), "crossfade_soft": ("crossfade", 0.6), "memory_fade": ("crossfade", 0.8),
    "blur_dissolve": ("crossfade", 0.5), "dip_to_black": ("dip_black", 0.8), "dip_to_white": ("dip_white", 0.6),
    "flash_cut": ("dip_white", 0.2), "exposure_bump": ("dip_white", 0.3),
}
LEGACY_TRANSITIONS = {"cut": ("cut", 0.0), "crossfade": ("crossfade", 0.5), "dissolve": ("crossfade", 0.5),
                      "dip_to_black": ("dip_black", 0.8), "fade_black": ("dip_black", 0.8), "dip_to_white": ("dip_white", 0.6)}


class CompileError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(data) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (json.JSONDecodeError, OSError):
        return default


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ----------------------------------------------------------------------------------------------- assets
def allowed_roots(project: Path) -> list[Path]:
    roots = [project.resolve()]
    for r in os.environ.get("NARRATIVEOS_MEDIA_ROOTS", "").split(os.pathsep):
        if r.strip():
            roots.append(Path(r).expanduser().resolve())
    vfx = os.environ.get("NARRATIVEOS_VFX_LIBRARY") or str(Path.home() / "NarrativeOS-VFX-Library")
    roots.append(Path(vfx).expanduser().resolve())
    return roots


def asset_registry(project: Path, ir: dict) -> dict[str, dict]:
    reg: dict[str, dict] = {}
    for name in ("assets.json", "approved_assets.json"):
        for a in (_load(project / name, {}) or {}).get("assets", []):
            if a.get("asset_id"):
                reg.setdefault(a["asset_id"], {}).update(a)
    for a in ir.get("assets", []):  # project-produced media declared by the timeline itself (narration, etc.)
        if a.get("asset_id"):
            reg.setdefault(a["asset_id"], {}).update(a)
    return reg


def resolve_path(project: Path, asset: dict) -> Path:
    raw = asset.get("local_path") or asset.get("path") or ""
    p = Path(raw)
    p = (p if p.is_absolute() else project / p).resolve()
    if not any(p == r or r in p.parents for r in allowed_roots(project)):
        raise CompileError(f"asset {asset.get('asset_id')}: {p} is outside the project and the allowed media roots")
    return p


def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True)
    if r.returncode:
        raise CompileError(f"ffprobe failed on {path.name}: {r.stderr.strip()[:200]}")
    data = json.loads(r.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    image = path.suffix.lower() in IMAGE_EXT
    dur = None if image else _num((data.get("format") or {}).get("duration"))
    return {"duration": dur, "image": image, "has_video": v is not None, "has_audio": a is not None,
            "width": v.get("width") if v else None, "height": v.get("height") if v else None}


# ----------------------------------------------------------------------------------------------- validation
def validate(ir: dict, project: Path, release: bool = False) -> dict:
    """All invariants, before any render. Returns {errors, warnings, duration, media: {item_id: {...}}}."""
    errors: list[str] = []
    warnings: list[str] = []
    media: dict[str, dict] = {}
    if str(ir.get("ir_version")) != IR_VERSION:
        errors.append(f"ir_version must be {IR_VERSION}")
    c = ir.get("canvas") or {}
    W, H, fps, sr = c.get("width"), c.get("height"), _num(c.get("fps")), c.get("sample_rate", 48000)
    if not (isinstance(W, int) and isinstance(H, int) and W > 0 and H > 0 and W % 2 == 0 and H % 2 == 0):
        errors.append("canvas width/height must be positive even integers")
    if not fps or fps <= 0 or fps > 120:
        errors.append("canvas fps must be in (0, 120]")
    if not isinstance(sr, int) or sr not in (44100, 48000):
        errors.append("canvas sample_rate must be 44100 or 48000")
    frame = 1 / fps if fps else 0.04
    tracks = ir.get("tracks") or []
    if not tracks:
        errors.append("timeline has no tracks")
    reg = asset_registry(project, ir)
    track_ids, item_ids = set(), set()
    end = 0.0
    probes: dict[Path, dict] = {}

    def media_for(item: dict, need: str) -> dict | None:
        aid = item.get("asset_id")
        asset = reg.get(aid)
        if not asset:
            errors.append(f"{item.get('id')}: asset {aid!r} is not in assets.json, approved_assets.json or the timeline's assets")
            return None
        ok_status = {"approved"} if release else {"approved", "simulation_approved"}
        if asset.get("status") not in ok_status:
            errors.append(f"{item.get('id')}: asset {aid} has status {asset.get('status')!r}; needs {' or '.join(sorted(ok_status))}")
        try:
            path = resolve_path(project, asset)
        except CompileError as e:
            errors.append(f"{item.get('id')}: {e}")
            return None
        if not path.is_file():
            errors.append(f"{item.get('id')}: missing file {path}")
            return None
        if path not in probes:
            try:
                probes[path] = probe(path)
            except CompileError as e:
                errors.append(f"{item.get('id')}: {e}")
                return None
        pr = probes[path]
        if need == "video" and not pr["has_video"]:
            errors.append(f"{item.get('id')}: asset {aid} has no picture")
            return None
        if need == "audio" and not pr["has_audio"]:
            errors.append(f"{item.get('id')}: asset {aid} has no audio stream")
            return None
        return {"path": path, **pr}

    def check_range(item_id: str, pr: dict, source_in: float, length: float, what: str) -> None:
        if source_in < -EPS:
            errors.append(f"{item_id}: {what} starts before the source (source_in {source_in:.3f})")
        if pr.get("duration") is not None and source_in + length > pr["duration"] + frame + EPS:
            errors.append(f"{item_id}: {what} needs source {source_in:.3f}-{source_in + length:.3f} s but the asset is {pr['duration']:.3f} s"
                          " (not enough handle for this transition or window)")

    for t in tracks:
        tid, kind = t.get("id"), t.get("kind")
        if not tid or tid in track_ids:
            errors.append(f"track id {tid!r} missing or duplicated")
        track_ids.add(tid)
        if kind not in TRACK_KINDS:
            errors.append(f"track {tid}: kind must be one of {sorted(TRACK_KINDS)}")
            continue
        if kind == "audio" and t.get("role") not in AUDIO_ROLES:
            errors.append(f"track {tid}: audio role must be one of {sorted(AUDIO_ROLES)}")
        items = t.get("items") or []
        for it in items:
            iid = it.get("id")
            if not iid or iid in item_ids:
                errors.append(f"track {tid}: item id {iid!r} missing or duplicated")
            item_ids.add(iid)
            a, b = _num(it.get("timeline_in")), _num(it.get("timeline_out"))
            if a is None or b is None or a < -EPS or b <= a + EPS:
                errors.append(f"{iid}: timeline_in/out must be finite, >= 0 and out > in")
                continue
            end = max(end, b)
            if kind == "caption":
                if not str(it.get("text", "")).strip():
                    errors.append(f"{iid}: caption has no text")
                continue
            src = _num(it.get("source_in", 0)) or 0.0
            for k in ("fade_in", "fade_out"):
                v = _num(it.get(k, 0))
                if v is None or v < 0:
                    errors.append(f"{iid}: {k} must be >= 0")
            if (_num(it.get("fade_in", 0)) or 0) + (_num(it.get("fade_out", 0)) or 0) > (b - a) + EPS:
                errors.append(f"{iid}: fade_in + fade_out longer than the item")
            if kind in ("video", "overlay"):
                m = media_for(it, "video")
                if m:
                    media[iid] = m
                    check_range(iid, m, src, b - a, "picture")
                if it.get("fit", "cover") not in FITS:
                    errors.append(f"{iid}: fit must be one of {sorted(FITS)}")
                mo = it.get("motion") or {}
                if mo.get("kind", "none") not in MOTIONS:
                    errors.append(f"{iid}: motion kind must be one of {sorted(MOTIONS)}")
                elif mo.get("kind", "none") != "none":
                    s0, s1 = _num(mo.get("scale_from", 1.0)), _num(mo.get("scale_to", 1.0))
                    if s0 is None or s1 is None or not (1.0 <= s0 <= 2.0 and 1.0 <= s1 <= 2.0):
                        errors.append(f"{iid}: motion scales must be within 1.0-2.0")
                if kind == "overlay":
                    if it.get("blend", "normal") not in BLENDS:
                        errors.append(f"{iid}: blend must be one of {sorted(BLENDS)}")
                    op = _num(it.get("opacity", 1.0))
                    if op is None or not 0 <= op <= 1:
                        errors.append(f"{iid}: opacity must be 0-1")
                au = it.get("audio") or {}
                if kind == "video" and au.get("native"):
                    if m and not m["has_audio"]:
                        errors.append(f"{iid}: native audio requested but asset {it.get('asset_id')} has no sound")
                    ni, no = _num(au.get("native_in", a)), _num(au.get("native_out", b))
                    if ni is None or no is None or ni < -EPS or no <= ni:
                        errors.append(f"{iid}: native_in/out invalid")
                    elif m:
                        check_range(iid, m, src + (ni - a), no - ni, "native audio (J/L window)")
                        end = max(end, no)
            elif kind == "audio":
                m = media_for(it, "audio")
                if m:
                    media[iid] = m
                    check_range(iid, m, src, b - a, "audio")
                g = _num(it.get("gain_db", 0))
                if g is None or not -60 <= g <= 20:
                    errors.append(f"{iid}: gain_db must be within -60..20")
        # Track-level rules.
        if kind == "video":
            seq = sorted(items, key=lambda x: _num(x.get("timeline_in")) or 0)
            for A, B in zip(seq, seq[1:]):
                a_out, b_in = _num(A.get("timeline_out")), _num(B.get("timeline_in"))
                if a_out is None or b_in is None:
                    continue
                tr = B.get("transition_in") or {"type": "cut", "duration": 0}
                ttype, tdur = tr.get("type", "cut"), _num(tr.get("duration", 0)) or 0.0
                if ttype not in TRANSITIONS:
                    errors.append(f"{B.get('id')}: transition_in type must be one of {sorted(TRANSITIONS)}")
                    continue
                overlap = a_out - b_in
                if ttype == "crossfade":
                    if abs(overlap - tdur) > frame / 2 + EPS or tdur <= 0:
                        errors.append(f"{B.get('id')}: a {tdur:.3f} s crossfade needs exactly {tdur:.3f} s of overlap with {A.get('id')}, found {overlap:.3f} s")
                elif overlap > EPS:
                    errors.append(f"{A.get('id')} and {B.get('id')} overlap by {overlap:.3f} s without a crossfade (unintended overlap)")
                elif overlap < -EPS:
                    warnings.append(f"gap of {-overlap:.3f} s between {A.get('id')} and {B.get('id')} (black)")
                if ttype.startswith("dip") and tdur <= 0:
                    errors.append(f"{B.get('id')}: a dip needs a duration")
            if seq and (_num(seq[0].get("timeline_in")) or 0) > EPS:
                warnings.append(f"track {tid} starts at {_num(seq[0].get('timeline_in')):.3f} s (black before it)")
        if kind == "audio" and t.get("duck_under") and t["duck_under"] not in {x.get("id") for x in tracks if x.get("kind") == "audio"}:
            errors.append(f"track {tid}: duck_under {t['duck_under']!r} is not an audio track")
        if kind == "caption":
            seq = sorted(items, key=lambda x: _num(x.get("timeline_in")) or 0)
            for A, B in zip(seq, seq[1:]):
                if (_num(A.get("timeline_out")) or 0) > (_num(B.get("timeline_in")) or 0) + EPS:
                    errors.append(f"captions {A.get('id')} and {B.get('id')} overlap")
            for it in items:
                longest = max((len(x) for x in str(it.get("text", "")).split("\n")), default=0)
                if longest > 42:
                    warnings.append(f"{it.get('id')}: caption line of {longest} characters (over 42 is hard to read)")
    declared = _num(ir.get("duration"))
    duration = declared if declared else end
    if declared and declared + EPS < end:
        errors.append(f"timeline duration {declared} is shorter than its last item ({end:.3f} s)")
    if duration <= 0:
        errors.append("timeline is empty")
    return {"errors": errors, "warnings": warnings, "duration": round(duration, 6), "media": media}


# ----------------------------------------------------------------------------------------------- filtergraph
def _ass_time(v: float) -> str:
    cs = int(round(v * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_ass(track: dict, W: int, H: int, dest: Path) -> None:
    st = track.get("style") or {}
    size = int(round(H * float(st.get("size", 0.055))))
    margin = int(round(H * float(st.get("margin_v", 0.07))))
    colour = st.get("colour", "&H00FFFFFF")
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
             "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             f"Style: Default,{st.get('font', 'Arial')},{size},{colour},{colour},&H00000000,&H80000000,{-1 if st.get('bold', True) else 0},0,0,0,"
             f"100,100,0,0,1,{max(1, size // 14)},{max(0, size // 28)},2,{int(W * 0.05)},{int(W * 0.05)},{margin},1", "",
             "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for it in sorted(track.get("items", []), key=lambda x: float(x["timeline_in"])):
        text = str(it["text"]).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_ass_time(float(it['timeline_in']))},{_ass_time(float(it['timeline_out']))},Default,,0,0,0,,{text}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fit(fit: str, W: int, H: int) -> str:
    if fit == "contain":
        return f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black"
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"


def _motion(mo: dict, n_frames: int, W: int, H: int, fps: float) -> str:
    kind = mo.get("kind", "none")
    if kind == "none":
        return ""
    s0, s1 = float(mo.get("scale_from", 1.0)), float(mo.get("scale_to", 1.0))
    n = max(1, n_frames - 1)
    return f",zoompan=z='{s0}+({s1}-{s0})*on/{n}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={W}x{H}:fps={fps}"


def build(ir: dict, check: dict, work: Path, scale: float = 1.0) -> tuple[list[str], str, dict]:
    """FFmpeg input arguments and one filtergraph for the whole timeline."""
    c = ir["canvas"]
    W = int(round(c["width"] * scale / 2)) * 2
    H = int(round(c["height"] * scale / 2)) * 2
    fps, sr = float(c["fps"]), int(c.get("sample_rate", 48000))
    total = check["duration"]
    media = check["media"]
    args: list[str] = []
    graph: list[str] = []
    n_in = 0
    info = {"unrendered": [], "inputs": 0}

    def add_input(path: Path, start: float, length: float, image: bool) -> int:
        nonlocal n_in
        if image:
            args.extend(["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{length:.6f}", "-i", str(path)])
        else:
            args.extend(["-ss", f"{max(0.0, start):.6f}", "-t", f"{length:.6f}", "-i", str(path)])
        n_in += 1
        return n_in - 1

    graph.append(f"color=c=black:s={W}x{H}:r={fps:g}:d={total:.6f},format=yuv420p[base]")
    current = "base"
    audio_items: dict[str, list[str]] = {}

    def audio_chain(label_in: str, it: dict, t_in: float, length: float, gain: float, tag: str) -> str:
        fi, fo = float(it.get("fade_in", 0) or 0), float(it.get("fade_out", 0) or 0)
        f = [f"[{label_in}]aresample={sr},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS",
             f"atrim=0:{length:.6f}", f"volume={gain:g}dB"]
        if fi > 0:
            f.append(f"afade=t=in:st=0:d={fi:.6f}")
        if fo > 0:
            f.append(f"afade=t=out:st={max(0.0, length - fo):.6f}:d={fo:.6f}")
        f.append(f"adelay=delays={int(round(t_in * 1000))}:all=1")
        graph.append(",".join(f) + f"[{tag}]")
        return tag

    for t in ir["tracks"]:
        kind = t["kind"]
        if kind == "video":
            seq = sorted(t.get("items", []), key=lambda x: float(x["timeline_in"]))
            for i, it in enumerate(seq):
                m = media[it["id"]]
                a, b = float(it["timeline_in"]), float(it["timeline_out"])
                length = b - a
                k = add_input(m["path"], float(it.get("source_in", 0)), length, m["image"])
                frames = max(1, int(round(length * fps)))
                chain = f"[{k}:v]fps={fps:g},{_fit(it.get('fit', 'cover'), W, H)},setsar=1{_motion(it.get('motion') or {}, frames, W, H, fps)}"
                chain += f",trim=duration={length:.6f},setpts=PTS-STARTPTS,format=yuva420p"
                tr = it.get("transition_in") or {}
                if tr.get("type") == "crossfade":
                    chain += f",fade=t=in:st=0:d={float(tr['duration']):.6f}:alpha=1"
                elif tr.get("type", "").startswith("dip"):
                    colour = "white" if tr["type"] == "dip_white" else "black"
                    chain += f",fade=t=in:st=0:d={float(tr['duration']) / 2:.6f}:color={colour}"
                nxt = seq[i + 1].get("transition_in", {}) if i + 1 < len(seq) else {}
                if nxt.get("type", "").startswith("dip"):
                    colour = "white" if nxt["type"] == "dip_white" else "black"
                    d = float(nxt["duration"]) / 2
                    chain += f",fade=t=out:st={max(0.0, length - d):.6f}:d={d:.6f}:color={colour}"
                chain += f",setpts=PTS+{a:.6f}/TB[v{k}]"
                graph.append(chain)
                graph.append(f"[{current}][v{k}]overlay=eof_action=pass:format=yuv420[c{k}]")
                current = f"c{k}"
                au = it.get("audio") or {}
                if au.get("native") and m["has_audio"]:
                    ni, no = float(au.get("native_in", a)), float(au.get("native_out", b))
                    ka = add_input(m["path"], float(it.get("source_in", 0)) + (ni - a), no - ni, False)
                    tag = audio_chain(f"{ka}:a", {}, ni, no - ni, float(au.get("gain_db", 0)), f"na{ka}")
                    audio_items.setdefault("__native__", []).append(tag)
        elif kind == "overlay":
            for it in sorted(t.get("items", []), key=lambda x: float(x["timeline_in"])):
                m = media[it["id"]]
                a, b = float(it["timeline_in"]), float(it["timeline_out"])
                length = b - a
                k = add_input(m["path"], float(it.get("source_in", 0)), length, m["image"])
                blend, op = it.get("blend", "normal"), float(it.get("opacity", 1.0))
                fi, fo = float(it.get("fade_in", 0) or 0), float(it.get("fade_out", 0) or 0)
                base = f"[{k}:v]fps={fps:g},{_fit(it.get('fit', 'cover'), W, H)},setsar=1,trim=duration={length:.6f},setpts=PTS-STARTPTS"
                if blend == "normal":
                    chain = base + f",format=yuva420p,colorchannelmixer=aa={op:g}"
                    if fi > 0:
                        chain += f",fade=t=in:st=0:d={fi:.6f}:alpha=1"
                    if fo > 0:
                        chain += f",fade=t=out:st={length - fo:.6f}:d={fo:.6f}:alpha=1"
                    graph.append(chain + f",setpts=PTS+{a:.6f}/TB[o{k}]")
                    graph.append(f"[{current}][o{k}]overlay=eof_action=pass:format=yuv420[c{k}]")
                else:
                    # Screen/add are identity over black, multiply over white: pad the layer with that colour for
                    # the whole timeline and fade towards it, then blend in RGB (YUV planes would blend wrongly).
                    neutral = "white" if blend == "multiply" else "black"
                    chain = base + ",format=gbrp"
                    if fi > 0:
                        chain += f",fade=t=in:st=0:d={fi:.6f}:color={neutral}"
                    if fo > 0:
                        chain += f",fade=t=out:st={length - fo:.6f}:d={fo:.6f}:color={neutral}"
                    chain += f",tpad=start_duration={a:.6f}:stop_duration={max(0.0, total - b):.6f}:start_mode=add:stop_mode=add:color={neutral}"
                    graph.append(chain + f",trim=duration={total:.6f},setpts=PTS-STARTPTS[o{k}]")
                    mode = {"screen": "screen", "add": "addition", "multiply": "multiply"}[blend]
                    graph.append(f"[{current}]format=gbrp[b{k}];[b{k}][o{k}]blend=all_mode={mode}:all_opacity={op:g},format=yuv420p[c{k}]")
                current = f"c{k}"
        elif kind == "audio":
            tags = []
            for it in sorted(t.get("items", []), key=lambda x: float(x["timeline_in"])):
                m = media[it["id"]]
                a, b = float(it["timeline_in"]), float(it["timeline_out"])
                k = add_input(m["path"], float(it.get("source_in", 0)), b - a, False)
                tags.append(audio_chain(f"{k}:a", it, a, b - a, float(it.get("gain_db", 0)), f"a{k}"))
            if tags:
                audio_items[t["id"]] = tags
    for t in ir["tracks"]:
        if t["kind"] == "caption" and t.get("items"):
            ass = work / f"{t['id']}.ass"
            write_ass(t, W, H, ass)
            graph.append(f"[{current}]subtitles=filename={ass.name}[cap_{t['id']}]")
            current = f"cap_{t['id']}"
    graph.append(f"[{current}]format=yuv420p,trim=duration={total:.6f}[vout]")

    # Audio buses: one per track (plus native picture sound), music ducked under its key track, then the mix.
    has_audio = bool(audio_items)
    if has_audio:
        buses: dict[str, str] = {}
        for tid, tags in audio_items.items():
            bus = f"bus_{tid.strip('_')}"
            src = "".join(f"[{x}]" for x in tags)
            mix = f"amix=inputs={len(tags)}:duration=longest:normalize=0," if len(tags) > 1 else ""
            graph.append(f"{src}{mix}apad=whole_dur={total:.6f},atrim=0:{total:.6f}[{bus}]")
            buses[tid] = bus
        keys = [t["duck_under"] for t in ir["tracks"] if t["kind"] == "audio" and t.get("duck_under") in buses and t["id"] in buses]
        for key in set(keys):
            n = keys.count(key) + 1
            outs = "".join(f"[{buses[key]}_{j}]" for j in range(n))
            graph.append(f"[{buses[key]}]asplit={n}{outs}")
        used: dict[str, int] = {}
        for t in ir["tracks"]:
            if t["kind"] == "audio" and t.get("duck_under") in buses and t["id"] in buses:
                key = t["duck_under"]
                used[key] = used.get(key, 0) + 1
                d = t.get("duck") or {}
                graph.append(f"[{buses[t['id']]}][{buses[key]}_{used[key]}]sidechaincompress=threshold={float(d.get('threshold', 0.03)):g}:"
                             f"ratio={float(d.get('ratio', 8)):g}:attack={float(d.get('attack_ms', 20)):g}:release={float(d.get('release_ms', 300)):g}"
                             f"[{buses[t['id']]}_ducked]")
                buses[t["id"]] = f"{buses[t['id']]}_ducked"
        for key in set(keys):
            buses[key] = f"{buses[key]}_0"
        ln = (ir.get("mix") or {}).get("loudnorm", {"I": -16, "TP": -1.5, "LRA": 11})
        # A full-length silent bed: adelay can shift a late-starting item's timestamps instead of writing silence,
        # so without it a mix whose first sound starts at 3 s would produce audio that starts at 3 s.
        graph.append(f"anullsrc=r={sr}:cl=stereo,atrim=0:{total:.6f}[bed]")
        src = "[bed]" + "".join(f"[{b}]" for b in buses.values())
        mix = f"amix=inputs={len(buses) + 1}:duration=longest:normalize=0,"
        norm = f"loudnorm=I={ln['I']}:TP={ln['TP']}:LRA={ln['LRA']}," if ln else ""
        graph.append(f"{src}{mix}{norm}aresample={sr},atrim=0:{total:.6f}[aout]")
    info.update(inputs=n_in, has_audio=has_audio, width=W, height=H, fps=fps, sample_rate=sr, duration=total)
    return args, ";\n".join(graph), info


# ----------------------------------------------------------------------------------------------- render
def ffmpeg_version() -> str:
    r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    return r.stdout.splitlines()[0] if r.returncode == 0 and r.stdout else "unknown"


def verify(out: Path, info: dict) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out)], capture_output=True, text=True)
    if r.returncode:
        return {"passed": False, "problems": [f"ffprobe failed: {r.stderr[:200]}"], "ffprobe": {}}
    data = json.loads(r.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    problems = []
    if not v:
        problems.append("no video stream")
    else:
        if (v.get("width"), v.get("height")) != (info["width"], info["height"]):
            problems.append(f"size {v.get('width')}x{v.get('height')}, timeline says {info['width']}x{info['height']}")
        num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
        rate = float(num) / float(den or 1) if float(den or 1) else 0
        if abs(rate - info["fps"]) > 0.01:
            problems.append(f"frame rate {rate:.3f}, timeline says {info['fps']}")
    dur = _num((data.get("format") or {}).get("duration")) or 0
    if abs(dur - info["duration"]) > 1 / info["fps"] + DURATION_TOLERANCE:
        problems.append(f"duration {dur:.3f} s, timeline says {info['duration']:.3f} s")
    if bool(a) != info["has_audio"]:
        problems.append("audio stream " + ("missing" if info["has_audio"] else "present without any audio in the timeline"))
    if v and a:
        vd, ad = _num(v.get("duration")), _num(a.get("duration"))
        if vd is not None and ad is not None and abs(vd - ad) > AV_TOLERANCE:
            problems.append(f"audio {ad:.3f} s vs video {vd:.3f} s differ by more than {AV_TOLERANCE * 1000:.0f} ms")
    return {"passed": not problems, "problems": problems, "duration": dur, "ffprobe": data}


def compile_timeline(project: Path, ir: dict, output: Path, preview: bool = False, release: bool = False, scale: float | None = None) -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise CompileError("ffmpeg and ffprobe are required")
    project = project.resolve()
    check = validate(ir, project, release)
    if check["errors"]:
        raise CompileError("timeline failed validation:\n- " + "\n- ".join(check["errors"]))
    timeline_hash = _sha({k: v for k, v in ir.items() if k != "compile"})
    work = project / "renders" / "compile" / timeline_hash[:16]
    work.mkdir(parents=True, exist_ok=True)
    args, graph, info = build(ir, check, work, scale if scale else (0.5 if preview else 1.0))
    (work / "filtergraph.txt").write_text(graph + "\n", encoding="utf-8")
    output = output if output.is_absolute() else project / output
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.stem + ".partial" + output.suffix)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", *args, "-/filter_complex", "filtergraph.txt", "-map", "[vout]"]
    if info["has_audio"]:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", str(info["sample_rate"])]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast" if preview else "medium", "-crf", "26" if preview else "18", "-pix_fmt", "yuv420p",
            "-r", f"{info['fps']:g}", "-t", f"{info['duration']:.6f}", "-movflags", "+faststart", str(tmp)]
    (work / "command.json").write_text(json.dumps({"cwd": str(work), "argv": cmd}, indent=2) + "\n", encoding="utf-8")
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if r.returncode:
        tmp.unlink(missing_ok=True)
        raise CompileError(f"ffmpeg failed ({r.returncode}): {r.stderr[-3000:]}")
    os.replace(tmp, output)  # atomic: a half-written render never sits at the output path
    ver = verify(output, info)
    unrendered = (ir.get("compile") or {}).get("unrendered", [])
    manifest = {
        "schema_version": 2, "status": "passed" if ver["passed"] else "blocked", "renderer": "compile_timeline.py (single FFmpeg filtergraph)",
        "ir_version": IR_VERSION, "rendered_at": _now(), "mode": "preview" if preview else ("release" if release else "standard"),
        "output_path": str(output.relative_to(project)) if project in output.parents else str(output),
        "output_sha256": _sha(output.read_bytes()), "size_bytes": output.stat().st_size,
        "timeline_sha256": timeline_hash, "filtergraph_sha256": _sha(graph.encode("utf-8")), "compile_dir": str(work.relative_to(project)),
        "ffmpeg": ffmpeg_version(), "canvas": {k: info[k] for k in ("width", "height", "fps", "sample_rate")}, "duration": info["duration"],
        "inputs": info["inputs"], "has_audio": info["has_audio"], "warnings": check["warnings"],
        "unrendered": unrendered, "verification": {k: v for k, v in ver.items() if k != "ffprobe"}, "ffprobe": ver["ffprobe"],
    }
    (project / "renders").mkdir(exist_ok=True)
    (project / "renders" / "render_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not ver["passed"]:
        raise CompileError("render did not match the timeline:\n- " + "\n- ".join(ver["problems"]))
    return manifest


# ----------------------------------------------------------------------------------------------- converter
def from_shot_timeline(tl: dict, project: Path, narration: str | None = None, music: str | None = None,
                       captions: dict | None = None, music_gain_db: float = -14.0) -> dict:
    """Convert a shot timeline (timeline.json, or one compiled from a Director event graph) into IR 3.0."""
    out = tl.get("output", {})
    canvas = {"width": int(out.get("width", 1280)), "height": int(out.get("height", 720)), "fps": float(out.get("fps", 24)), "sample_rate": 48000}
    fit = "contain" if out.get("fit_policy") == "contain_pad" else "cover"
    shots = sorted(tl.get("shots", []), key=lambda s: float(s["start"]))
    markers = tl.get("markers", [])
    unrendered = []
    items = []
    for s in shots:
        it = {"id": s["shot_id"], "asset_id": s["asset_id"], "timeline_in": float(s["start"]), "timeline_out": float(s["end"]),
              "source_in": float(s.get("source_start", 0) or 0), "fit": fit}
        motion = s.get("motion", "static")
        if motion == "slow_zoom_in":
            it["motion"] = {"kind": "push_in", "scale_from": 1.0, "scale_to": 1.08}
        elif motion == "slow_zoom_out":
            it["motion"] = {"kind": "pull_out", "scale_from": 1.08, "scale_to": 1.0}
        if s.get("native_audio_start") is not None or s.get("native_audio_end") is not None or s.get("has_native_audio"):
            if s.get("has_native_audio"):
                it["audio"] = {"native": True, "native_in": float(s.get("native_audio_start", s["start"])),
                               "native_out": float(s.get("native_audio_end", s["end"]))}
        items.append(it)
    by_id = {it["id"]: it for it in items}
    for mk in markers:  # Director MOTION markers override the preset
        if mk.get("type") == "MOTION" and mk.get("motion"):
            for it in items:
                if it["timeline_in"] - EPS <= float(mk["start"]) < it["timeline_out"]:
                    m = mk["motion"]
                    it["motion"] = {"kind": m.get("kind", "push_in"), "scale_from": float(m.get("scale_from", 1.0)), "scale_to": float(m.get("scale_to", 1.06))}
    wanted = []  # (left_id, right_id, kind, duration, source)
    for A, B in zip(shots, shots[1:]):
        kind, dur = LEGACY_TRANSITIONS.get(B.get("transition", "cut"), ("cut", 0.0))
        if kind != "cut":
            wanted.append((A["shot_id"], B["shot_id"], kind, dur, f"shot transition {B.get('transition')}"))
    for mk in markers:
        tr = mk.get("transition") or {}
        if mk.get("type") == "TRANSITION" and tr.get("left_shot_id") in by_id and tr.get("right_shot_id") in by_id:
            recipe = tr.get("recipe")
            if recipe in NATIVE_RECIPES:
                kind, dur = NATIVE_RECIPES[recipe]
                wanted = [w for w in wanted if (w[0], w[1]) != (tr["left_shot_id"], tr["right_shot_id"])]
                if kind != "cut":
                    wanted.append((tr["left_shot_id"], tr["right_shot_id"], kind, dur, f"recipe {recipe}"))
            else:
                unrendered.append({"event_id": mk.get("event_id"), "recipe": recipe, "at": mk.get("start"),
                                   "reason": "not an FFmpeg-native transition; needs the Remotion TransitionStack (kept as a hard cut)"})
    for left, right, kind, dur, why in wanted:
        A, B = by_id[left], by_id[right]
        B["transition_in"] = {"type": kind, "duration": dur, "source": why}
        if kind == "crossfade":
            # Centre the overlap on the cut when both sides have handles; the validator checks the sources.
            half = dur / 2
            if B["source_in"] >= half:
                B["timeline_in"] -= half
                B["source_in"] -= half
                A["timeline_out"] += half
            else:
                A["timeline_out"] += dur
    tracks = [{"id": "v_main", "kind": "video", "items": items}]
    assets = []
    end = max((it["timeline_out"] for it in items), default=0.0)
    if narration:
        assets.append({"asset_id": "narration", "local_path": narration, "status": "approved", "kind": "narration", "rights": "project_produced"})
        dur = probe((project / narration) if not Path(narration).is_absolute() else Path(narration))["duration"] or end
        tracks.append({"id": "a_narration", "kind": "audio", "role": "narration",
                       "items": [{"id": "narration_1", "asset_id": "narration", "timeline_in": 0.0, "timeline_out": min(dur, end) if end else dur}]})
    if music:
        tracks.append({"id": "a_music", "kind": "audio", "role": "music", **({"duck_under": "a_narration"} if narration else {}),
                       "items": [{"id": "music_1", "asset_id": music, "timeline_in": 0.0, "timeline_out": end, "gain_db": music_gain_db,
                                  "fade_in": min(1.0, end / 4), "fade_out": min(2.0, end / 4)}]})
    if captions and captions.get("captions"):
        tracks.append({"id": "captions", "kind": "caption", "items": [
            {"id": f"cap_{i + 1:04d}", "timeline_in": float(c["start"]), "timeline_out": float(c["end"]), "text": c["text"]}
            for i, c in enumerate(captions["captions"])]})
    return {"ir_version": IR_VERSION, "canvas": canvas, "assets": assets, "tracks": tracks, "duration": end or None,
            "compile": {"converted_from": "shot timeline", "unrendered": unrendered}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--timeline", default="timeline_v3.json")
    ap.add_argument("--from-shot-timeline", help="convert this shot timeline (e.g. timeline.json) to IR 3.0 first (writes --timeline)")
    ap.add_argument("--narration")
    ap.add_argument("--music", help="asset_id of an approved music asset")
    ap.add_argument("--captions", help="captions.json (align_captions.py output)")
    ap.add_argument("--output", default="renders/preview.mp4")
    ap.add_argument("--preview", action="store_true", help="half resolution, fast encode")
    ap.add_argument("--release", action="store_true", help="only fully approved assets")
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    p = a.project.resolve()
    try:
        if a.from_shot_timeline:
            caps = _load(p / a.captions) if a.captions else None
            ir = from_shot_timeline(_load(p / a.from_shot_timeline, {}), p, a.narration, a.music, caps)
            (p / a.timeline).write_text(json.dumps(ir, indent=2) + "\n", encoding="utf-8")
        ir = _load(p / a.timeline)
        if ir is None:
            raise CompileError(f"no timeline at {p / a.timeline}")
        if a.validate_only:
            chk = validate(ir, p, a.release)
            print(json.dumps({"status": "blocked" if chk["errors"] else "passed", "errors": chk["errors"], "warnings": chk["warnings"],
                              "duration": chk["duration"]}, indent=2))
            return 1 if chk["errors"] else 0
        m = compile_timeline(p, ir, Path(a.output), a.preview, a.release)
    except CompileError as e:
        print(json.dumps({"status": "blocked", "error": str(e)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({k: m[k] for k in ("status", "output_path", "duration", "has_audio", "inputs", "warnings", "unrendered")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
