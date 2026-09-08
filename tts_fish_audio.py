#!/usr/bin/env python3
"""
tts_fish_audio.py — Fish Audio S2.1 Pro Free via OpenRouter /api/v1/audio/speech.
Model: fish-audio/s2.1-pro (free tier, S2.1 Pro quality).
Required: OPENROUTER_API_KEY in .env (confirmed present: sk-or-...f5fb).

Usage:
  python3 tts_fish_audio.py synth --text "In 1900..." --output demo.mp3
"""
import argparse, os, sys, requests
from pathlib import Path

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
ENDPOINT = "https://openrouter.ai/api/v1/audio/speech"

def synth_text(text: str, output_path: Path, voice: str = "default", speed: float = 1.0):
    if not OPENROUTER_KEY:
        print("ERROR: OPENROUTER_API_KEY not set in .env")
        sys.exit(1)

    print(f"Fish Audio S2.1 Pro synthesis via OpenRouter")
    print(f"  Text length: {len(text)} chars")
    print(f"  Voice: {voice} | Model: fish-audio/s2.1-pro | Speed: {speed}")
    print(f"  Endpoint: {ENDPOINT}")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "fish-audio/s2.1-pro",
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        "speed": speed,
    }

    try:
        response = requests.post(ENDPOINT, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        size = output_path.stat().st_size
        print(f"  SUCCESS: wrote {output_path} ({size:,} bytes, ~{size/1024/1024:.2f} MB)")
        return output_path
    except Exception as e:
        print(f"ERROR: Fish Audio synthesis failed: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"  Response body: {e.response.text[:1000]}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="In 1900, three lighthouse keepers vanished from the Flannan Isles.")
    parser.add_argument("--output", default="C:/Users/openclaw/Desktop/flannan_isles/render_work/fish_tts_demo.mp3")
    parser.add_argument("--voice", default="default")
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()
    synth_text(args.text, Path(args.output), args.voice, args.speed)
