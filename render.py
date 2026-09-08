#!/usr/bin/env python3
"""
render.py — Timeline compiler.

Reads timeline.json and compiles it into a final video via HyperFrames + FFmpeg.
render.py knows NOTHING about the Flannan Isles, the script, the research, or the footage.
It only knows: here is a timeline spec, produce a video.

When HyperFrames is installed: uses npx hyperframes render to compile the HTML compositions.
When HyperFrames is not installed: falls back to direct FFmpeg filtergraph compilation.

This is the deterministic compiler from the VidRush/ViewMax research:
typed timeline IR → one renderer-specific output.
"""
import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

# ---- Paths ----
PROJECT_ROOT = Path(r"C:\Users\openclaw\Desktop\flannan_isles")
TIMELINE_PATH = PROJECT_ROOT / "timeline.json"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
FOOTAGE_DIR = PROJECT_ROOT / "footage"
RENDER_OUTPUT = PROJECT_ROOT / "flannan_isles_edit.mp4"
PREVIEW_OUTPUT = PROJECT_ROOT / "preview.mp4"

FFMPEG = r"C:\Users\openclaw\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
FFPROBE = r"C:\Users\openclaw\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffprobe.exe"


def run(cmd, label="", timeout=600, check=True):
    """Run a command with logging."""
    if label:
        print(f"\n[ {label} ]")
    # Print truncated command
    cmd_str = " ".join(str(c) for c in cmd)
    print(f"  {cmd_str[:300]}{'...' if len(cmd_str) > 300 else ''}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if r.returncode != 0 and check:
        print(f"  STDERR: {r.stderr[:2000]}")
        raise RuntimeError(f"Command failed (rc={r.returncode}): {cmd_str[:200]}")
    return r


def probe(path: Path) -> dict:
    """Probe a media file."""
    r = run([FFPROBE, "-v", "error", "-show_entries",
             "format=duration,size:stream=codec_type,width,height,r_frame_rate,sample_rate,channels",
             "-of", "json", str(path)], label="probe", check=False)
    if r.returncode != 0:
        return {}
    import json
    info = json.loads(r.stdout)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "duration": float(fmt.get("duration", 0)),
        "size_bytes": int(fmt.get("size", 0)),
        "has_video": video.get("codec_type") == "video",
        "has_audio": audio.get("codec_type") == "audio",
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "fps": video.get("r_frame_rate", "0/1"),
        "sample_rate": int(audio.get("sample_rate", 0)),
        "channels": int(audio.get("channels", 0)),
        "video_codec": video.get("codec_name", ""),
        "audio_codec": audio.get("codec_name", ""),
    }


def mb(b):
    return b / (1024 * 1024)


def check_hyperframes_installed() -> bool:
    """Check if HyperFrames is installed locally."""
    hf_bin = PROJECT_ROOT / "node_modules" / ".bin" / "hyperframes"
    if not hf_bin.exists():
        return False
    try:
        r = subprocess.run(["node", str(PROJECT_ROOT / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"), "--version"],
                           capture_output=True, text=True, timeout=15, check=False)
        return r.returncode == 0
    except Exception:
        return False


def render_with_hyperframes(timeline: dict) -> Path:
    """
    Render using HyperFrames: generate HTML composition from timeline,
    then use npx hyperframes render to produce MP4.
    """
    print("\n=== RENDER: HyperFrames path ===")
    print("  Generating composition HTML from timeline...")

    # Generate the composition HTML
    html_path = PROJECT_ROOT / "composition.html"
    generate_composition_html(timeline, html_path)

    # Use HyperFrames CLI directly (node + mjs path, not npx)
    hf_mjs = PROJECT_ROOT / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    render_cmd = [
        "node", str(hf_mjs),
        "render",
        ".",  # project directory
        "-c", str(html_path.relative_to(PROJECT_ROOT)),
        "-o", str(RENDER_OUTPUT),
        "--fps", str(timeline["sequence"]["fps"]),
        "--workers", "1",  # deterministic single-worker
    ]
    run(render_cmd, label="hyperframes render")
    return RENDER_OUTPUT


def generate_composition_html(timeline: dict, out_path: Path):
    """
    Generate a HyperFrames-compatible HTML composition from the timeline.
    This is the "composition" layer — templates + timeline data.
    """
    seq = timeline["sequence"]
    tracks = timeline["tracks"]

    # Build HTML with all tracks as data-*-attributed elements
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width={seq['width']}, height={seq['height']}">
<title>Flannan Isles — Composition</title>
<style>
  /* === Composition base styles === */
  :root {{
    --w: {seq['width']}px;
    --h: {seq['height']}px;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0a0a0f;
    width: var(--w);
    height: var(--h);
    overflow: hidden;
    font-family: "Segoe UI", "Arial", sans-serif;
  }}
  #stage {{
    position: relative;
    width: var(--w);
    height: var(--h);
    background: #0a0a0f;
  }}
  .clip {{
    position: absolute;
    top: 0;
    left: 0;
    width: var(--w);
    height: var(--h);
  }}
  /* Track z-order handled by data-track-index */
</style>
</head>
<body>
<div id="stage" data-composition-id="flannan_isles" data-width="{seq['width']}" data-height="{seq['height']}" data-fps="{seq['fps']}">
"""

    # Main video track: each shot as a <video> element with data-*
    v_main = next((t for t in tracks if t["id"] == "v_main"), None)
    if v_main:
        for i, item in enumerate(v_main["items"]):
            # Resolve src from footage_assignments
            src = None
            for fa in timeline.get("footage_assignments", []):
                if fa["asset_id"] == item["asset_id"]:
                    raw = fa["path"]
                    # Convert absolute path → project-relative for HyperFrames
                    try:
                        src = str(Path(raw).resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
                    except ValueError:
                        src = raw
                    break
            if not src:
                # fallback: guess from asset_id
                guess = FOOTAGE_DIR / f"{item['asset_id']}.mp4"
                if guess.exists():
                    src = str(guess.relative_to(PROJECT_ROOT)).replace("\\", "/")
                else:
                    print(f"  WARNING: footage not found for {item['id']} (asset={item['asset_id']})")
                    continue

            dur = item["timeline"]["out_sec"] - item["timeline"]["in_sec"]
            start = item["timeline"]["in_sec"]
            html += f"""
  <video
    class="clip"
    id="{item['id']}"
    data-start="{start}"
    data-duration="{dur}"
    data-track-index="0"
    src="{src}"
    muted
    playsinline
    data-asset-id="{item['asset_id']}"
  ></video>
"""

    # Overlay track: templates
    v_overlay = next((t for t in tracks if t["id"] == "v_overlay"), None)
    if v_overlay:
        for i, item in enumerate(v_overlay["items"]):
            if item.get("type") == "template":
                template_name = item["template"]
                template_path = TEMPLATE_DIR / f"{template_name}.html"

                if template_path.exists():
                    dur = item["timeline"]["out_sec"] - item["timeline"]["in_sec"]
                    start = item["timeline"]["in_sec"]
                    params_json = json.dumps(item.get("params", {}))
                    html += f"""
  <div
    class="clip"
    id="{item['id']}"
    data-start="{start}"
    data-duration="{dur}"
    data-track-index="1"
    data-template="{template_name}"
    data-params='{params_json}'
  ></div>
"""
                else:
                    print(f"  WARNING: template not found: {template_path}")

    # Caption track
    v_captions = next((t for t in tracks if t["id"] == "v_captions"), None)
    if v_captions:
        for i, item in enumerate(v_captions["items"]):
            dur = item["timeline"]["out_sec"] - item["timeline"]["in_sec"]
            start = item["timeline"]["in_sec"]
            # Escape the caption text for HTML attribute
            cap_text_esc = item['text'].replace("'", "\\'")
            cap_style = item.get('style', 'lower_third')
            html += f"""
  <div
    class="clip"
    id="{item['id']}"
    data-start="{start}"
    data-duration="{dur}"
    data-track-index="2"
    data-caption-text="{cap_text_esc}"
    data-caption-style="{cap_style}"
  ></div>
"""

    html += """
</div>

<script>
  // === HyperFrames composition runtime ===
  // Register timelines for each track
  (function() {
    const stage = document.getElementById('stage');
    window.__timelines = window.__timelines || {};

    // Main video track: play clips at their start times
    const clips = stage.querySelectorAll('video.clip');
    clips.forEach(clip => {
      const startTime = parseFloat(clip.dataset.start) || 0;
      const duration = parseFloat(clip.dataset.duration) || 0;
      clip.addEventListener('loadedmetadata', () => {
        clip.currentTime = startTime;
        clip.play();
      });
    });

    // Overlay track: load templates dynamically
    const overlays = stage.querySelectorAll('[data-template]');
    overlays.forEach(el => {
      const templateName = el.dataset.template;
      const params = JSON.parse(el.dataset.params || '{}');
      const templatePath = 'templates/' + templateName + '.html';

      fetch(templatePath)
        .then(r => r.text())
        .then(html => {
          const temp = document.createElement('div');
          temp.innerHTML = html;
          const content = temp.querySelector('#stage > *');
          if (content) {
            el.appendChild(content);
            // Trigger template's own timeline registration
            const script = temp.querySelector('script');
            if (script) {
              const scriptContent = script.textContent;
              const scriptFunc = new Function('el', 'params', scriptContent);
              scriptFunc(el, params);
            }
          }
        });
    });

    // Register main timeline
    const mainTimeline = gsap ? gsap.timeline({ paused: true }) : null;
    if (mainTimeline) {
      window.__timelines['main'] = mainTimeline;
    }
  })();
</script>
</body>
</html>
"""

    out_path.write_text(html)
    print(f"  Composition HTML written: {out_path}")


def render_with_ffmpeg(timeline: dict) -> Path:
    """
    Fallback: compile timeline directly to FFmpeg filtergraph.
    This is the "deterministic compiler" path when HyperFrames isn't available.
    """
    print("\n=== RENDER: FFmpeg direct path (HyperFrames not installed) ===")

    seq = timeline["sequence"]
    tracks = timeline["tracks"]
    total_dur = seq["duration_sec"]

    # Build a complex filtergraph
    # We need: main video track, overlay track, caption track, audio mix

    # Strategy:
    # 1. Prepare each video clip as a normalized intermediate
    # 2. Concatenate main video track
    # 3. Overlay templates as generated PNG sequences or HTML-rendered frames
    # 4. Burn captions as drawtext
    # 5. Mix audio: TTS narration + synthesized drone

    # For this MVP, we do:
    # - Concatenate all main video clips with crossfade transitions
    # - Overlay: generate title card, lower-thirds, and outro as PNG frames, overlay with enable timers
    # - Captions: drawtext filter for each caption event
    # - Audio: mix narration + drone

    # Step 1: Prepare normalized clips
    print("  Step 1: Normalizing video clips...")
    work_dir = PROJECT_ROOT / "render_work"
    work_dir.mkdir(exist_ok=True)

    v_main = next((t for t in tracks if t["id"] == "v_main"), None)
    normalized = []

    if v_main:
        for i, item in enumerate(v_main["items"]):
            src_path = None
            # Find source
            for fa in timeline.get("footage_assignments", []):
                if fa["asset_id"] == item["asset_id"]:
                    src_path = Path(fa["path"])
                    break
            if not src_path or not src_path.exists():
                print(f"  WARNING: skipping {item['id']} — source not found")
                continue

            out_name = f"clip_{i:02d}.mp4"
            out_path = work_dir / out_name

            # Normalize: scale to 1280x720, 24fps, yuv420p, trim to TIMELINE duration
            src_in = item["source"]["in_sec"]
            src_out = item["source"]["out_sec"]
            timeline_dur = item["timeline"]["out_sec"] - item["timeline"]["in_sec"]
            trim_dur = timeline_dur

            run([
                FFMPEG, "-y",
                "-ss", str(src_in), "-i", str(src_path),
                "-t", str(trim_dur),
                "-vf", f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,format=yuv420p",
                "-an",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                str(out_path),
            ], label=f"normalize clip {i}: {item['id']}")

            normalized.append((out_path, item))
            print(f"    -> {out_name}: {probe(out_path).get('duration', 0):.1f}s")

    # Step 2: Crossfade concatenate main clips
    print("  Step 2: Composing main video track with crossfades...")
    if len(normalized) >= 2:
        # Use xfade filter for transitions
        input_args = []
        filter_parts = []
        for i, (path, item) in enumerate(normalized):
            input_args.extend(["-i", str(path)])

        # Build xfade chain with cumulative offsets
        prev_label = "0"
        cumulative_dur = 0.0
        cf_dur = 1.0  # crossfade duration in seconds — must match timeline overlap
        for i in range(1, len(normalized)):
            clip_dur = normalized[i-1][1]["timeline"]["out_sec"] - normalized[i-1][1]["timeline"]["in_sec"]
            cumulative_dur += clip_dur
            offset = cumulative_dur - cf_dur * (i - 1) - cf_dur
            filter_parts.append(
                f"[{prev_label}][{i}]xfade=transition=fade:duration={cf_dur}:offset={offset:.3f}[{prev_label}_xf];"
            )
            prev_label = f"{prev_label}_xf"

        # Add format
        filter_parts.append(f"[{prev_label}]format=yuv420p[vout]")

        filter_graph = "".join(filter_parts)
        main_video = work_dir / "main_video.mp4"

        cmd = [FFMPEG, "-y"] + input_args + [
            "-filter_complex", filter_graph,
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-an",
            str(main_video),
        ]
        run(cmd, label="xfade concatenate")
    else:
        # Single clip or no clips
        if normalized:
            main_video = normalized[0][0]
        else:
            # Generate a black placeholder
            main_video = work_dir / "black.mp4"
            run([
                FFMPEG, "-y",
                "-f", "lavfi", "-i", f"color=black:size=1280x720:duration={total_dur}:rate=24",
                "-c:v", "libx264", "-preset", "ultrafast",
                str(main_video),
            ], label="generate black placeholder")
        print("  (single clip or no clips — using as-is)")

    main_info = probe(main_video)
    main_dur = main_info.get("duration", total_dur)
    print(f"  Main video: {main_dur:.1f}s")

    # Step 3: Generate overlay images (title, lower-thirds, outro)
    print("  Step 3: Generating overlay images...")
    from PIL import Image, ImageDraw, ImageFont

    TTF_SEGOE = r"C:\Windows\Fonts\segoeui.ttf"
    TTF_SEGOE_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"

    title_img = work_dir / "title.png"
    outro_img = work_dir / "outro.png"

    # Title card
    img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_title = ImageFont.truetype(TTF_SEGOE_BOLD, 96)
    font_sub = ImageFont.truetype(TTF_SEGOE, 36)

    title_text = "The Flannan Isles"
    sub_text = "Three Keepers — One Unsolved Mystery"

    tb = draw.textbbox((0, 0), title_text, font=font_title)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    tx = (1280 - tw) // 2
    ty = (720 - th) // 2 - 40

    # Semi-transparent background
    overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 140))
    img.paste(overlay, (0, 0), overlay)

    draw.text((tx, ty), title_text, font=font_title, fill=(232, 232, 236, 255))
    sb = draw.textbbox((0, 0), sub_text, font=font_sub)
    sw, sh = sb[2] - sb[0], sb[3] - sb[1]
    draw.text(((1280 - sw) // 2, ty + th + 20), sub_text, font=font_sub, fill=(144, 144, 152, 255))
    img.save(title_img)

    # Outro card
    img2 = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw2 = ImageDraw.Draw(img2)
    overlay2 = Image.new("RGBA", (1280, 720), (0, 0, 0, 160))
    img2.paste(overlay2, (0, 0), overlay2)
    outro_text = "The sea keeps its secrets."
    ob = draw2.textbbox((0, 0), outro_text, font=font_title)
    ow, oh = ob[2] - ob[0], ob[3] - ob[1]
    draw2.text(((1280 - ow) // 2, (720 - oh) // 2), outro_text, font=font_title, fill=(200, 200, 208, 255))
    img2.save(outro_img)

    # Generate lower-third frames for each beat
    print("  Step 3b: Generating lower-third frames...")
    caption_track = next((t for t in tracks if t["id"] == "v_captions"), None)

    # Step 4: Build caption/drawtext filters
    print("  Step 4: Building caption filters...")

    # For captions, we'll use drawtext with enable timers
    # Build a text file for drawtext or individual overlays

    # Step 5: Assemble narration audio from TTS files
    print("  Step 5: Assembling narration from TTS...")
    narration_wav = work_dir / "narration_full.wav"
    if not narration_wav.exists():
        voice_track = next((t for t in tracks if t["id"] == "a_voice"), None)
        if voice_track:
            # Collect all TTS MP3s in timeline order
            tts_mp3s = []
            for item in voice_track["items"]:
                audio_path = item.get("audio_path", "")
                if audio_path and Path(audio_path).exists():
                    tts_mp3s.append(Path(audio_path))
                else:
                    # Try to find by beat_id in caps dir
                    bid = item.get("beat_id", "")
                    caps = PROJECT_ROOT.parent / "flannan_test" / "work" / "caps"
                    found = list(caps.glob(f"narr_*{bid.replace('beat_', '')}*.mp3")) if caps.exists() else []
                    if found:
                        tts_mp3s.append(found[0])
                    else:
                        print(f"    WARNING: no TTS file for {bid}")

            if tts_mp3s:
                # Convert each MP3 -> mono WAV, then concatenate
                wav_list = work_dir / "tts_wav_list.txt"
                with open(wav_list, "w") as f:
                    for mp3 in tts_mp3s:
                        wav = work_dir / f"{mp3.stem}.wav"
                        if not wav.exists():
                            run([
                                FFMPEG, "-y", "-i", str(mp3),
                                "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
                                str(wav)
                            ], label=f"convert {mp3.name} -> WAV", check=False)
                        f.write(f"file '{wav.resolve()}'\n")

                run([
                    FFMPEG, "-y", "-f", "concat", "-safe", "0",
                    "-i", str(wav_list),
                    "-c", "pcm_s16le", str(narration_wav)
                ], label="concatenate narration")
                print(f"    Narration: {probe(narration_wav).get('duration', 0):.1f}s")
            else:
                print("    WARNING: no TTS files found for narration")
                narration_wav = None
        else:
            print("    WARNING: no voice track in timeline")
            narration_wav = None
    else:
        print(f"    [SKIP] narration WAV exists: {narration_wav}")

    # Step 6: Generate drone audio
    print("  Step 6: Generating placeholder drone (real music TBD)...")
    drone_path = work_dir / "drone.m4a"
    if not drone_path.exists():
        drone_dur = int(total_dur) + 6
        run([
            FFMPEG, "-y",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={drone_dur}:sample_rate=44100",
            "-af", "lowpass=f=180,highpass=f=35,volume=0.07,afade=t=in:d=2,afade=t=out:st=" + str(drone_dur - 3) + ":d=3",
            "-c:a", "aac", "-b:a", "128k",
            str(drone_path),
        ], label="synthesize drone")

    # Step 7: Mix audio (narration + drone with ducking)
    print("  Step 7: Mixing audio...")
    audio_mix = work_dir / "audio_mix.m4a"
    if narration_wav and narration_wav.exists():
        run([
            FFMPEG, "-y",
            "-i", str(narration_wav),
            "-i", str(drone_path),
            "-filter_complex",
            "[0:a]volume=1.0[voice];"
            "[1:a]volume=0.25,sidechaincompress=threshold=-30:ratio=5:attack=20:release=250[music];"
            "[voice][music]amix=inputs=2:duration=first:normalize=0[out]",
            "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k",
            str(audio_mix),
        ], label="mix narration + drone")
    else:
        # No narration — just use drone
        audio_mix = drone_path
        print("    [WARNING] No narration, using drone only")

    # Step 8: Mux video + audio
    print("  Step 8: Final mux...")
    final_video = work_dir / "final_composed.mp4"
    run([
        FFMPEG, "-y",
        "-i", str(final_video),
        "-i", str(audio_mix),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        str(final_video),
    ], label="mux video + audio")

    # Build the overlay filter chain
    # Inputs: main video, title PNG, outro PNG, caption PNGs
    inputs = ["-i", str(main_video), "-i", str(title_img), "-i", str(outro_img)]

    # Caption PNGs
    cap_images = []
    if caption_track:
        for i, cap_item in enumerate(caption_track["items"]):
            cap_img = work_dir / f"cap_{i:02d}.png"
            # Generate caption image
            cap_img_pil = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
            cap_draw = ImageDraw.Draw(cap_img_pil)

            text = cap_item["text"]
            lines = text.split("\n")
            font = ImageFont.truetype(TTF_SEGOE_BOLD, 40)
            font_sub = ImageFont.truetype(TTF_SEGOE, 24)

            # Build lower-third bar
            max_w = 0
            total_h = 0
            line_heights = []

            for li, line in enumerate(lines):
                bb = cap_draw.textbbox((0, 0), line, font=font if li == len(lines)-1 else font_sub)
                w = bb[2] - bb[0]
                h = bb[3] - bb[1]
                max_w = max(max_w, w)
                line_heights.append(h)
                total_h += h

            pad_x, pad_y = 24, 12
            bar_w = max_w + pad_x * 2
            bar_h = total_h + pad_y * (len(lines) + 1)
            bar_x = 60
            bar_y = 720 - bar_h - 100

            bar = Image.new("RGBA", (bar_w, bar_h), (8, 8, 14, 190))
            cap_img_pil.paste(bar, (bar_x, bar_y), bar)

            # Accent line
            accent = Image.new("RGBA", (3, max(line_heights)), (200, 168, 110, 255))
            cap_img_pil.paste(accent, (bar_x, bar_y), accent)

            # Text
            x = bar_x + pad_x + 16
            y = bar_y + pad_y
            for li, line in enumerate(lines):
                cap_draw.text((x, y), line,
                             font=font if li == len(lines)-1 else font_sub,
                             fill=(240, 240, 244, 255) if li == len(lines)-1 else (168, 168, 176, 255))
                y += line_heights[li] + pad_y

            cap_img_pil.save(cap_img)
            cap_images.append(cap_img)
            inputs.extend(["-i", str(cap_img)])

    # Build overlay filter
    vf_parts = []
    prev = "0:v:0"

    # Title overlay (first 3 seconds)
    vf_parts.append(f"[{prev}][1:v]scale=1280:720,format=yuva420p[title];")
    vf_parts.append(f"[{prev}][title]overlay=x=0:y=0:enable='between(t,0,3)'[v1];")

    # Outro overlay (last 4 seconds)
    outro_start = main_dur - 4.0
    vf_parts.append(f"[{prev}][2:v]scale=1280:720,format=yuva420p[outro];")
    vf_parts.append(f"[{prev}][outro]overlay=x=0:y=0:enable='between(t,{outro_start},{main_dur})'[v2];")

    # Caption overlays
    prev_label = "v2"
    for i, cap_img in enumerate(cap_images):
        cap_item = caption_track["items"][i]
        cap_start = cap_item["timeline"]["in_sec"]
        cap_end = cap_item["timeline"]["out_sec"]
        img_idx = 3 + i  # input index
        vf_parts.append(f"[{prev_label}][{img_idx}:v]scale=1280:720,format=yuva420p[c{i}];")
        vf_parts.append(f"[{prev_label}][c{i}]overlay=x=0:y=0:enable='between(t,{cap_start},{cap_end})'[v{i+3}];")
        prev_label = f"v{i+3}"

    vf_parts.append(f"[{prev_label}]format=yuv420p[vout]")
    filter_graph = "".join(vf_parts)

    video_with_overlays = work_dir / "video_with_overlays.mp4"
    cmd = [FFMPEG, "-y"] + inputs + [
        "-filter_complex", filter_graph,
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-an",
        str(video_with_overlays),
    ]
    run(cmd, label="apply overlays")

    # Step 6: Assemble narration audio from TTS files
    print("  Step 6: Assembling narration from TTS...")
    narration_wav = work_dir / "narration_full.wav"
    if not narration_wav.exists():
        voice_track = next((t for t in tracks if t["id"] == "a_voice"), None)
        if voice_track:
            # Collect all TTS MP3s in timeline order
            tts_mp3s = []
            for item in voice_track["items"]:
                audio_path = item.get("audio_path", "")
                if audio_path and Path(audio_path).exists():
                    tts_mp3s.append(Path(audio_path))
                else:
                    # Try to find by beat_id in caps dir
                    bid = item.get("beat_id", "")
                    caps = PROJECT_ROOT.parent / "flannan_test" / "work" / "caps"
                    found = list(caps.glob(f"narr_*{bid.replace('beat_', '')}*.mp3")) if caps.exists() else []
                    if found:
                        tts_mp3s.append(found[0])
                    else:
                        print(f"    WARNING: no TTS file for {bid}")

            if tts_mp3s:
                # Convert each MP3 -> mono WAV, then concatenate
                wav_list = work_dir / "tts_wav_list.txt"
                with open(wav_list, "w") as f:
                    for mp3 in tts_mp3s:
                        wav = work_dir / f"{mp3.stem}.wav"
                        if not wav.exists():
                            run([
                                FFMPEG, "-y", "-i", str(mp3),
                                "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
                                str(wav)
                            ], label=f"convert {mp3.name} -> WAV", check=False)
                        f.write(f"file '{wav.resolve()}'\n")

                run([
                    FFMPEG, "-y", "-f", "concat", "-safe", "0",
                    "-i", str(wav_list),
                    "-c", "pcm_s16le", str(narration_wav)
                ], label="concatenate narration")
                print(f"    Narration: {probe(narration_wav).get('duration', 0):.1f}s")
            else:
                print("    WARNING: no TTS files found for narration")
                narration_wav = None
        else:
            print("    WARNING: no voice track in timeline")
            narration_wav = None
    else:
        print(f"    [SKIP] narration WAV exists: {narration_wav}")

    # Step 7: Generate placeholder drone (real music TBD)
    print("  Step 7: Generating placeholder drone (real music TBD)...")
    drone_path = work_dir / "drone.m4a"
    if not drone_path.exists():
        drone_dur = int(total_dur) + 6
        run([
            FFMPEG, "-y",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={drone_dur}:sample_rate=44100",
            "-af", f"lowpass=f=180,highpass=f=35,volume=0.07,afade=t=in:d=2,afade=t=out:st={drone_dur - 3}:d=3",
            "-c:a", "aac", "-b:a", "128k",
            str(drone_path),
        ], label="synthesize drone")

    # Step 8: Mix audio (narration + drone with ducking)
    print("  Step 8: Mixing audio...")
    audio_mix = work_dir / "audio_mix.m4a"
    if narration_wav and narration_wav.exists():
        run([
            FFMPEG, "-y",
            "-i", str(narration_wav),
            "-i", str(drone_path),
            "-filter_complex",
            "[0:a]volume=1.0[voice];"
            "[1:a]volume=0.25,sidechaincompress=threshold=-30:ratio=5:attack=20:release=250[music];"
            "[voice][music]amix=inputs=2:duration=first:normalize=0[out]",
            "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k",
            str(audio_mix),
        ], label="mix narration + drone")
    else:
        audio_mix = drone_path
        print("    [WARNING] No narration, using drone only")

    # Step 9: Mux video + audio
    print("  Step 9: Final mux...")
    final_out = PROJECT_ROOT / "flannan_isles_edit.mp4"
    run([
        FFMPEG, "-y",
        "-i", str(video_with_overlays),
        "-i", str(audio_mix),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        str(final_out),
    ], label="final mux")

    return final_out


def main():
    import json

    print("=" * 60)
    print("render.py — Timeline Compiler")
    print("=" * 60)

    # Load timeline
    if not TIMELINE_PATH.exists():
        print(f"ERROR: {TIMELINE_PATH} not found. Run build_timeline.py first.")
        return 1

    timeline = json.loads(TIMELINE_PATH.read_text())
    print(f"\nLoaded timeline: {TIMELINE_PATH}")
    print(f"  Schema: {timeline['schema_version']}")
    print(f"  Duration: {timeline['total_duration_sec']:.1f}s "
          f"({timeline['total_duration_sec']/60:.1f} min)")
    print(f"  Tracks: {len(timeline['tracks'])}")

    # Check HyperFrames availability
    hf_available = False  # FFmpeg direct path forced
    print(f"\n  HyperFrames installed: {hf_available}")

    # Render
    if hf_available:
        try:
            output = render_with_hyperframes(timeline)
        except Exception as e:
            print(f"\n[FALLBACK] HyperFrames failed: {e}")
            print("  Falling back to FFmpeg direct render...")
            output = render_with_ffmpeg(timeline)
    else:
        output = render_with_ffmpeg(timeline)

    # Validate output
    info = probe(output)
    if info:
        print(f"\n=== RENDER COMPLETE ===")
        print(f"  Output: {output}")
        print(f"  Duration: {info['duration']:.1f}s")
        print(f"  Size: {mb(info['size_bytes']):.2f} MB")
        print(f"  Video: {info.get('width','?')}x{info.get('height','?')}, "
              f"{info.get('video_codec','?')}")
        if info.get('has_audio'):
            print(f"  Audio: {info.get('audio_codec','?')}, "
                  f"{info.get('sample_rate','?')}Hz, "
                  f"{info.get('channels','?')}ch")
    else:
        print(f"\nWARNING: Could not probe output: {output}")
        return 1

    # Write render manifest
    render_manifest = {
        "timeline_hash": hashlib.sha256(TIMELINE_PATH.read_bytes()).hexdigest()[:16],
        "output_path": str(output),
        "output_hash": hashlib.sha256(output.read_bytes()).hexdigest()[:16],
        "output_duration": info.get("duration", 0),
        "output_size_mb": mb(info.get("size_bytes", 0)),
        "hyperframes_available": hf_available,
        "rendered_at": __import__('datetime').datetime.now().isoformat(),
    }
    manifest_path = PROJECT_ROOT / "render_manifest.json"
    manifest_path.write_text(json.dumps(render_manifest, indent=2))
    print(f"\n  Render manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
