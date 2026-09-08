#!/usr/bin/env python3
"""
render_clean.py — Minimal deterministic compiler.

Stage-tested pipeline:
  T1: one clip, 20s, no audio
  T2: + narration
  T3: + drone
  T4: + 3 clips hard cut
  T5: + 1 crossfade
  T6: + 1 caption
  T7: full 21-clip video with overlays, narration, drone

Source of truth: timeline.json
"""

import json
import subprocess
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT = Path(r"C:\Users\openclaw\Desktop\flannan_isles")
WORK = PROJECT / "render_work"
TIMELINE = PROJECT / "timeline.json"
FOOTAGE = PROJECT / "footage"

FFMPEG = r"C:\Users\openclaw\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
FFPROBE = r"C:\Users\openclaw\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffprobe.exe"
TTS_DIR = Path(r"C:\Users\openclaw\Desktop\flannan_test\work\caps")

WORK.mkdir(exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def run(cmd, label="", check=True):
    print(f"\n[ {label} ]")
    print(f"  CMD: {' '.join(str(c) for c in cmd)[:400]}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    rc = r.returncode
    signed_rc = rc - (1 << 32) if rc >= (1 << 31) else rc
    print(f"  RC: {rc} (signed: {signed_rc})")
    if r.stdout:
        print(f"  STDOUT:\n{r.stdout[:2000]}")
    if r.stderr:
        print(f"  STDERR:\n{r.stderr[:3000]}")
    if rc != 0 and check:
        raise RuntimeError(f"Command failed: rc={rc}")
    return r


def probe(path):
    r = run([FFPROBE, "-v", "error", "-show_entries",
             "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
             "-of", "json", str(path)], label="probe", check=False)
    if r.returncode != 0:
        return {}
    try:
        d = json.loads(r.stdout)
        fmt = d.get("format", {})
        streams = d.get("streams", [])
        result = {
            "duration": float(fmt.get("duration", 0)),
            "size_bytes": int(fmt.get("size", 0)),
            "bit_rate": int(fmt.get("bit_rate", 0)),
            "has_video": any(s.get("codec_type") == "video" for s in streams),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        }
        vs = next((s for s in streams if s.get("codec_type") == "video"), {})
        result.update({
            "width": int(vs.get("width", 0)),
            "height": int(vs.get("height", 0)),
            "fps": vs.get("r_frame_rate", ""),
            "video_codec": vs.get("codec_name", ""),
        })
        aud = next((s for s in streams if s.get("codec_type") == "audio"), {})
        result.update({
            "audio_codec": aud.get("codec_name", ""),
            "sample_rate": int(aud.get("sample_rate", 0)),
            "channels": int(aud.get("channels", 0)),
        })
        return result
    except Exception:
        return {}


def print_probe(label, info):
    print(f"\n=== {label} ===")
    print(f"  Duration:  {info.get('duration', 0):.2f}s")
    print(f"  Size:      {info.get('size_bytes', 0)/1024/1024:.1f} MB")
    print(f"  Video:     {info.get('width', '?')}x{info.get('height', '?')} @ {info.get('fps', '?')} fps ({info.get('video_codec', '?')})")
    print(f"  Audio:     {'yes' if info.get('has_audio') else 'no'} ({info.get('audio_codec', '?')} {info.get('sample_rate', 0)}Hz {info.get('channels', 0)}ch)")


# ── Stage 1: One clip, 20s, no audio ──────────────────────────────────────────
def stage_1():
    print("\n" + "="*60)
    print("STAGE 1: One clip, 20s, no audio")
    print("="*60)
    out = WORK / "s1_onecta.mp4"
    src = FOOTAGE / "clip_00.mp4"
    if not src.exists():
        src = FOOTAGE / "11059181-hd_1366_720_25fps.mp4"
    run([
        FFMPEG, "-y",
        "-stream_loop", "2", "-i", str(src),
        "-t", "20",
        "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,format=yuv420p",
        "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        str(out),
    ], label="stage1")
    info = probe(out)
    print_probe("Stage 1 output", info)
    assert info.get("has_video"), "No video stream"
    assert not info.get("has_audio"), "Unexpected audio"
    assert 19.5 <= info["duration"] <= 21, f"Duration wrong: {info['duration']}"
    return out


# ── Stage 2: Add narration ────────────────────────────────────────────────────
def stage_2(video_in):
    print("\n" + "="*60)
    print("STAGE 2: Add narration")
    print("="*60)
    narr = TTS_DIR / "narr_00_In_1900,_three_lighthouse_keepers_vanished_from_th.wav"
    out = WORK / "s2_narration.mp4"
    run([
        FFMPEG, "-y",
        "-i", str(video_in),
        "-i", str(narr),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out),
    ], label="stage2")
    info = probe(out)
    print_probe("Stage 2 output", info)
    assert info["has_audio"], "No audio stream"
    return out


# ── Stage 3: Add drone ────────────────────────────────────────────────────────
def stage_3(video_in):
    print("\n" + "="*60)
    print("STAGE 3: Add drone music")
    print("="*60)
    drone = WORK / "drone.m4a"
    if not drone.exists():
        run([
            FFMPEG, "-y",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:duration=22:sample_rate=44100",
            "-af", "lowpass=f=180,highpass=f=35,volume=0.18,afade=t=in:d=2,afade=t=out:st=19:d=3",
            "-c:a", "aac", "-b:a", "128k",
            str(drone),
        ], label="synthesize drone")

    out = WORK / "s3_drone.mp4"
    run([
        FFMPEG, "-y",
        "-i", str(video_in),
        "-i", str(drone),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out),
    ], label="stage3")
    info = probe(out)
    print_probe("Stage 3 output", info)
    assert info["has_audio"], "No audio stream"
    return out


# ── Stage 4: Three clips hard cut ─────────────────────────────────────────────
def stage_4():
    print("\n" + "="*60)
    print("STAGE 4: Three clips hard cut")
    print("="*60)

    # Normalize three clips to their timeline durations
    clips = []
    for i in range(3):
        src_map = [
            ("11059181-hd_1366_720_25fps.mp4", 0, 4.58),
            ("11230943-hd_1280_720_30fps.mp4", 0, 3.94),
            ("16239001_1280_720_60fps.mp4", 0, 3.91),
        ]
        src_name, src_in, dur = src_map[i]
        src = FOOTAGE / src_name
        out = WORK / f"s4_clip{i}.mp4"
        run([
            FFMPEG, "-y",
            "-ss", str(src_in), "-i", str(src),
            "-t", str(dur),
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
            str(out),
        ], label=f"s4_normalize_clip{i}")
        clips.append(out)

    # Concat demuxer (hard cuts)
    lines = "\n".join(f"file '{c.resolve()}'" for c in clips)
    (WORK / "s4_concat.txt").write_text(lines)
    out = WORK / "s4_hardcut.mp4"
    run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(WORK / "s4_concat.txt"),
        "-c", "copy", str(out),
    ], label="s4_concat")
    info = probe(out)
    print_probe("Stage 4 output", info)
    expected = sum(d for _, _, d in src_map)
    assert abs(info["duration"] - expected) < 0.5, f"Duration mismatch: {info['duration']} vs {expected}"
    return out


# ── Stage 5: One crossfade ────────────────────────────────────────────────────
def stage_5():
    print("\n" + "="*60)
    print("STAGE 5: One crossfade between two clips")
    print("="*60)

    c0 = WORK / "s4_clip0.mp4"
    c1 = WORK / "s4_clip1.mp4"
    d0 = 4.58  # from stage 4
    cf = 0.5
    offset = d0 - cf

    out = WORK / "s5_xfade.mp4"
    run([
        FFMPEG, "-y",
        "-i", str(c0), "-i", str(c1),
        "-filter_complex", f"[0][1]xfade=transition=fade:duration={cf}:offset={offset}[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-an",
        str(out),
    ], label="s5_xfade")
    info = probe(out)
    print_probe("Stage 5 output", info)
    expected = d0 + 3.94 - cf
    assert abs(info["duration"] - expected) < 0.5, f"Duration mismatch: {info['duration']} vs {expected}"
    return out


# ── Stage 6: One caption overlay ──────────────────────────────────────────────
def stage_6():
    print("\n" + "="*60)
    print("STAGE 6: One caption overlay")
    print("="*60)

    # Use stage 4 hardcut video as base
    base = WORK / "s4_hardcut.mp4"
    dur = probe(base)["duration"]

    # Generate one caption PNG
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 40)
    text = "The Flannan Isles"
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    bar = Image.new("RGBA", (tw + 60, th + 30), (8, 8, 14, 190))
    img.paste(bar, (60, 600), bar)
    d.text((80, 615), text, font=font, fill=(220, 200, 160, 255))
    cap_img = WORK / "s6_caption.png"
    img.save(cap_img)

    out = WORK / "s6_captioned.mp4"
    run([
        FFMPEG, "-y",
        "-i", str(base),
        "-i", str(cap_img),
        "-filter_complex", f"[0:v][1:v]overlay=0:0:enable='between(t,2,6)'[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-an",
        str(out),
    ], label="s6_overlay")
    info = probe(out)
    print_probe("Stage 6 output", info)
    return out


# ── Stage 7: Full 21-clip video ───────────────────────────────────────────────
def stage_7():
    print("\n" + "="*60)
    print("STAGE 7: Full 21-clip video with overlays, narration, drone")
    print("="*60)

    tl = json.loads(TIMELINE.read_text())
    v_main = next(t for t in tl["tracks"] if t["id"] == "v_main")
    voice = next(t for t in tl["tracks"] if t["id"] == "a_voice")
    overlay = next(t for t in tl["tracks"] if t["id"] == "v_overlay")
    captions = next(t for t in tl["tracks"] if t["id"] == "v_captions")

    # ── 7a: Normalize all 21 clips ──────────────────────────────────────────
    print("\n  --- 7a: Normalize clips ---")
    clip_paths = []
    for i, item in enumerate(v_main["items"]):
        src = None
        for fa in tl.get("footage_assignments", []):
            if fa["asset_id"] == item["asset_id"]:
                src = fa["path"]
                break
        if not src:
            print(f"  WARNING: no source for {item['asset_id']}")
            continue
        dur = item["timeline"]["out_sec"] - item["timeline"]["in_sec"]
        out = WORK / f"c{i:02d}.mp4"
        run([
            FFMPEG, "-y",
            "-ss", str(item["source"]["in_sec"]), "-i", str(src),
            "-t", str(dur),
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            str(out),
        ], label=f"norm clip {i}")
        clip_paths.append(out)

    # ── 7b: Concat demuxer (hard cuts, reliable) ────────────────────────────
    print("\n  --- 7b: Concat demuxer ---")
    lines = "\n".join(f"file '{p.resolve()}'" for p in clip_paths)
    (WORK / "s7_concat.txt").write_text(lines)
    joined = WORK / "s7_joined.mp4"
    run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(WORK / "s7_concat.txt"),
        "-c", "copy", str(joined),
    ], label="s7_concat")
    info_joined = probe(joined)
    print_probe("Joined video", info_joined)

    # ── 7c: Generate overlays ────────────────────────────────────────────────
    print("\n  --- 7c: Generate overlays ---")
    from PIL import Image, ImageDraw, ImageFont
    TTF_B = r"C:\Windows\Fonts\segoeuib.ttf"
    TTF_R = r"C:\Windows\Fonts\segoeui.ttf"

    # Title card (0-3s)
    img = Image.new("RGBA", (1280, 720), (10, 10, 18, 245))
    d = ImageDraw.Draw(img)
    ft = ImageFont.truetype(TTF_B, 84)
    fs = ImageFont.truetype(TTF_R, 30)
    t1, t2 = "The Flannan Isles", "Three Keepers · One Unsolved Mystery"
    b1 = d.textbbox((0, 0), t1, font=ft)
    b2 = d.textbbox((0, 0), t2, font=fs)
    d.text(((1280 - (b1[2]-b1[0])) // 2, 240), t1, font=ft, fill=(220, 200, 160, 255))
    d.text(((1280 - (b2[2]-b2[0])) // 2, 350), t2, font=fs, fill=(180, 180, 190, 255))
    d.rectangle([540, 340, 740, 344], fill=(200, 168, 110, 255))
    img.save(WORK / "ov_title.png")

    # Outro card
    img = Image.new("RGBA", (1280, 720), (10, 10, 18, 245))
    d = ImageDraw.Draw(img)
    t = "A Mystery That Still Haunts the Sea"
    bb = d.textbbox((0, 0), t, font=ft)
    d.text(((1280 - (bb[2]-bb[0])) // 2, 310), t, font=ft, fill=(200, 170, 120, 255))
    d.rectangle([540, 310 + (bb[3]-bb[1]) + 10, 740, 310 + (bb[3]-bb[1]) + 14], fill=(200, 168, 110, 255))
    img.save(WORK / "ov_outro.png")

    # Captions
    cap_imgs = []
    fc = ImageFont.truetype(TTF_B, 38)
    fcs = ImageFont.truetype(TTF_R, 22)
    for i, cap in enumerate(captions["items"]):
        img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        lines = cap["text"].split("\n") if "\n" in cap["text"] else [cap["text"]]
        max_w = 0; total_h = 0; lh = []
        for line in lines:
            bb = d.textbbox((0, 0), line, font=fc if line == lines[-1] else fcs)
            w = bb[2] - bb[0]; h = bb[3] - bb[1]
            max_w = max(max_w, w); lh.append(h); total_h += h
        px, py = 24, 12
        bw = max_w + px * 2 + 16; bh = total_h + py * (len(lines) + 1)
        bx, by = 60, 720 - bh - 100
        bar = Image.new("RGBA", (bw, bh), (8, 8, 14, 190))
        img.paste(bar, (bx, by), bar)
        acc = Image.new("RGBA", (3, max(lh)), (200, 168, 110, 255))
        img.paste(acc, (bx, by), acc)
        x = bx + px + 16; y = by + py
        for li, line in enumerate(lines):
            d.text((x, y), line, font=fc if li == len(lines) - 1 else fcs,
                   fill=(240, 240, 244, 255) if li == len(lines) - 1 else (168, 168, 176, 255))
            y += lh[li] + py
        p = WORK / f"cap_{i:02d}.png"
        img.save(p)
        cap_imgs.append(p)
    print(f"  Generated {len(cap_imgs)} caption PNGs")

    # ── 7d: Build overlay filter graph (title + outro PNGs + drawtext captions) ─
    print("\n  --- 7d: Build overlay filtergraph ---")
    overlay_inputs = []

    # Title card PNG (0-3s) → input index 1
    overlay_inputs.extend(["-i", str(WORK / "ov_title.png")])
    # Outro card PNG (last 4s) → input index 2
    outro_start = info_joined["duration"] - 4.0
    overlay_inputs.extend(["-i", str(WORK / "ov_outro.png")])

    # Build filter chain
    # Input 0 = joined video, 1 = title PNG, 2 = outro PNG
    # Captions use drawtext (no extra inputs)
    fg_parts = []
    fg_parts.append(f"[0:v][1:v]overlay=x=0:y=0:enable='between(t,0,3)'[v1]")
    fg_parts.append(f"[v1][2:v]overlay=x=0:y=0:enable='between(t,{outro_start:.2f},{info_joined['duration']:.2f})'[v2]")

    # Append drawtext captions sequentially
    cur_label = "v2"
    for i, cap in enumerate(captions["items"]):
        t0 = cap["timeline"]["in_sec"]
        t1 = cap["timeline"]["out_sec"]
        text_esc = cap["text"].replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace("[", "\\[").replace("]", "\\]")
        next_label = f"v{i+3}"
        fg_parts.append(
            f"[{cur_label}]drawtext=text='{text_esc}':"
            f"fontfile=/Windows/Fonts/segoeuib.ttf':"
            f"fontsize=38:fontcolor=white:"
            f"box=1:boxcolor=0x08080e@0xbe:boxborderw=24:"
            f"x=60:y=600:"
            f"enable='between(t,{t0:.2f},{t1:.2f})'[{next_label}]"
        )
        cur_label = next_label

    fg_parts.append(f"[{cur_label}]format=yuv420p[vout]")
    overlay_fg = ";".join(fg_parts)

    # ── 7e: Assemble narration WAV ──────────────────────────────────────────
    print("\n  --- 7e: Assemble narration ---")
    narr_wavs = []
    total_narr = 0
    for item in voice["items"]:
        bid = item.get("beat_id", "")
        mp3s = sorted(TTS_DIR.glob(f"narr_*{bid.replace('beat_','')}*.mp3"))
        if mp3s:
            narr_wavs.append(mp3s[0])
            tag = json.loads(subprocess.run([FFPROBE, "-v", "error", "-show_format", "-of", "json", str(mp3s[0])], capture_output=True, text=True).stdout)
            total_narr += float(tag.get("format", {}).get("duration", 0))
        else:
            print(f"  WARNING: no TTS for {bid}")

    wav_list = WORK / "s7_narr_list.txt"
    wav_items = []
    missing_count = 0
    for mp3 in narr_wavs:
        wav = WORK / f"{mp3.stem}.wav"
        if not wav.exists():
            run([FFMPEG, "-y", "-i", str(mp3), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(wav)], label=f"convert {mp3.name}", check=False)
        if wav.exists():
            wav_items.append(str(wav.resolve()))
        else:
            print(f"  WARNING: conversion failed for {mp3.name}")
            missing_count += 1

    if missing_count > 0:
        print(f"  WARNING: {missing_count} narration files missing, rebuilding lookup...")
        # Fallback: find ALL narration MP3s and sort them
        all_mp3s = sorted(TTS_DIR.glob("narr_*.mp3"))
        wav_items = []
        for mp3 in all_mp3s:
            wav = WORK / f"{mp3.stem}.wav"
            if not wav.exists():
                run([FFMPEG, "-y", "-i", str(mp3), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(wav)], label=f"convert {mp3.name}", check=False)
            if wav.exists():
                wav_items.append(str(wav.resolve()))
        print(f"  Fallback found {len(wav_items)} narration WAVs")

    narr_wav = None
    if wav_items:
        wav_list.write_text("\n".join(f"file '{w}'" for w in wav_items))
        narr_wav = WORK / "s7_narration.wav"
        run([
            FFMPEG, "-y", "-f", "concat", "-safe", "0",
            "-i", str(wav_list),
            "-c", "pcm_s16le", str(narr_wav),
        ], label="concat narration")
        print(f"  Narration: {probe(narr_wav)['duration']:.1f}s")
    else:
        print("  WARNING: no narration")

    # ── 7f: Generate drone ───────────────────────────────────────────────────
    print("\n  --- 7f: Generate drone ---")
    total_dur = info_joined["duration"]
    drone = WORK / "s7_drone.m4a"
    run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={int(total_dur)+6}:sample_rate=44100",
        "-af", f"lowpass=f=180,highpass=f=35,volume=0.18,afade=t=in:d=2,afade=t=out:st={int(total_dur)+3}:d=3",
        "-c:a", "aac", "-b:a", "128k",
        str(drone),
    ], label="s7_drone")

    # ── 7g: Mix audio ────────────────────────────────────────────────────────
    print("\n  --- 7g: Mix audio ---")
    audio_mix = WORK / "s7_audio_mix.m4a"
    if narr_wav and narr_wav.exists():
        # Simple volume mix: narration at 1.0, drone at 0.18
        run([
            FFMPEG, "-y",
            "-i", str(narr_wav),
            "-i", str(drone),
            "-filter_complex", "[0:a]volume=1.0[v];[1:a]volume=0.18[m];[v][m]amix=inputs=2:duration=first:normalize=0[out]",
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k",
            str(audio_mix),
        ], label="s7_mix_audio")
    else:
        audio_mix = drone
        print("  Using drone only")

    # ── 7h: Apply overlays + mux audio ───────────────────────────────────────
    print("\n  --- 7h: Overlays + final mux ---")
    final = PROJECT / "flannan_isles_edit.mp4"
    run([
        FFMPEG, "-y",
        "-i", str(joined),
        *overlay_inputs,
        "-filter_complex", overlay_fg,
        "-map", "[vout]",
        "-i", str(audio_mix),
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(final),
    ], label="s7_final")

    info = probe(final)
    print_probe("FINAL OUTPUT", info)
    assert info["has_video"], "No video in final"
    assert info["has_audio"], "No audio in final"
    print(f"\n{'='*60}")
    print(f"RENDER COMPLETE: {final}")
    print(f"{'='*60}")
    return final


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    stages = {
        "1": stage_1,
        "2": lambda: stage_2(stage_1()),
        "3": lambda: stage_3(stage_2(stage_1())),
        "4": stage_4,
        "5": stage_5,
        "6": stage_6,
        "7": stage_7,
        "all": stage_7,
    }
    fn = stages.get(stage)
    if not fn:
        print(f"Unknown stage '{stage}'. Choose: 1-7 or all")
        sys.exit(1)
    try:
        result = fn()
        print(f"\nDone: {result}")
    except Exception as e:
        print(f"\nFAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
