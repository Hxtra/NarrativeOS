#!/usr/bin/env python3
"""
render_captions_only.py — Apply caption overlays as separate sequential pass.
Reads s7_joined.mp4 + 21 caption PNGs → produces video with captions.
This avoids the 23-input filtergraph limit that crashes FFmpeg.
"""
import subprocess, sys
from pathlib import Path

WORK = Path(r"C:\Users\openclaw\Desktop\flannan_isles\render_work")
FFMPEG = r"C:\Users\openclaw\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"

joined = WORK / "s7_joined.mp4"
output = WORK / "s7_with_all_captions.mp4"

timeline = __import__("json").load(open("timeline.json"))
caps = [i for i in timeline["tracks"] if i["id"] == "v_captions"][0]["items"]

current = joined
for i, cap in enumerate(caps):
    png = WORK / f"cap_{i:02d}.png"
    out = WORK / f"cap_step_{i:02d}.mp4"
    t0 = cap["timeline"]["in_sec"]
    t1 = cap["timeline"]["out_sec"]
    text_esc = cap["text"].replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace("[", "\\[").replace("]", "\\]")
    # Simple overlay with fixed lower-third position
    cmd = [
        FFMPEG, "-y",
        "-i", str(current),
        "-i", str(png),
        "-filter_complex", f"[0:v][1:v]overlay=x=0:y=620:enable='between(t,{t0:.2f},{t1:.2f})'[v]",
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-c:a", "copy",
        "-shortest",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    rc = result.returncode
    signed_rc = rc - (1 << 32) if rc >= (1 << 31) else rc
    print(f"Caption {i:02d} ({t0:.1f}-{t1:.1f}s): RC={rc} (signed={signed_rc})")
    if rc != 0:
        print(f"  ERROR text: {cap['text'][:60]}...")
        print(f"  Filter: between(t,{t0},{t1})")
        # Print last error line
        err_lines = result.stderr.split("\n")
        for line in err_lines[-8:]:
            print(f"    {line}")
    current = out

# Copy final caption step to output name
subprocess.run(["cp", str(current), str(output)], capture_output=True)
print(f"Caption overlay complete: {output}")
print(f"Steps completed: {len(caps)} caption overlays applied sequentially")
