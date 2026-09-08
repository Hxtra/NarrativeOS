#!/usr/bin/env python3
"""
tts_openai_provider.py — Replace edge_tts with OpenAI TTS (tts-1-hd, onyx voice).

Usage: set VOICE_TOOLS_OPENAI_KEY in .env, then:
  python3 tts_openai_provider.py synth --text "Sample narration line." --output test.mp3

Supported voices (OpenAI 2026): alloy, echo, fable, onyx, nova, shimmer
For Flannan Isles documentary tone: onyx (deeper male, calm measured) or alloy (neutral documentary).
"""

import argparse, os, sys
from pathlib import Path

# Use the interpreter that actually has openai installed (python / 3.11 path)
# This script will import openai from the active interpreter

def synth_text(text: str, output_path: Path, voice: str = "onyx", model: str = "tts-1-hd"):
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not found. Install with: pip install openai")
        sys.exit(1)

    api_key = os.getenv("VOICE_TOOLS_OPENAI_KEY")
    if not api_key:
        # Try direct OPENAI_API_KEY fallback
        api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: VOICE_TOOLS_OPENAI_KEY or OPENAI_API_KEY not set in environment/.env")
        print("Get key at: https://platform.openai.com/api-keys")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Synthesizing with OpenAI TTS: model={model}, voice={voice}, chars={len(text)} -> {output_path}")
    try:
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
        )
        response.stream_to_file(str(output_path))
        size_bytes = output_path.stat().st_size
        print(f"  SUCCESS: wrote {output_path} ({size_bytes:,} bytes, ~{size_bytes/1024/1024:.2f} MB)")
        return output_path
    except Exception as e:
        print(f"ERROR: OpenAI TTS synthesis failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="In 1900, three lighthouse keepers vanished from the Flannan Isles.")
    parser.add_argument("--output", default="/c/Users/openclaw/Desktop/flannan_isles/render_work/openai_tts_demo.mp3")
    parser.add_argument("--voice", default="onyx")
    parser.add_argument("--model", default="tts-1-hd")
    args = parser.parse_args()
    synth_text(args.text, Path(args.output), args.voice, args.model)
