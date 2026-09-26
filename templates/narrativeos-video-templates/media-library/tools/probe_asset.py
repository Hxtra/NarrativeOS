#!/usr/bin/env python3
"""
Real technical probing for video assets entering the Media Library.
Runs outside Remotion entirely — a React component can't shell out to
ffprobe, so this has to happen at ingestion time, upstream of any
ArchiveVideo render. This is the "probe metadata" step in:

    source media -> probe metadata -> normalize/interpret FPS -> ArchiveVideo

Usage: python3 probe_asset.py <path-to-video>
Prints real, ffprobe-derived facts as JSON. Does not guess or default
any of these — if ffprobe can't determine a field, it comes back null,
not a common-value guess like 30fps.
"""
import json
import subprocess
import sys


def probe(path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt",
        "-show_entries", "format=duration",
        "-of", "json",
        path,
    ]
    raw = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(raw)

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    def parse_rate(r):
        if not r or r == "0/0":
            return None
        num, _, den = r.partition("/")
        den = den or "1"
        try:
            return round(float(num) / float(den), 3)
        except (ValueError, ZeroDivisionError):
            return None

    source_fps = parse_rate(video_stream["r_frame_rate"]) if video_stream else None
    duration_sec = float(data["format"]["duration"]) if data.get("format", {}).get("duration") else None

    result = {
        "source_fps": source_fps,
        "source_fps_is_common_value": source_fps in (23.976, 24, 25, 29.97, 30, 50, 59.94, 60) if source_fps else None,
        "width": video_stream.get("width") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "aspect_ratio": round(video_stream["width"] / video_stream["height"], 3) if video_stream else None,
        "duration_sec": duration_sec,
        "real_source_frame_count": round(source_fps * duration_sec) if (source_fps and duration_sec) else None,
        "has_audio": audio_stream is not None,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "video_codec": video_stream.get("codec_name") if video_stream else None,
        "pix_fmt": video_stream.get("pix_fmt") if video_stream else None,
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 probe_asset.py <path-to-video>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(probe(sys.argv[1]), indent=2))
