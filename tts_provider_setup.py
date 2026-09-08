#!/usr/bin/env python3
"""
tts_openai_setup.py — Configure OpenAI TTS (tts-1-hd) as replacement for edge_tts.

Cost: ~$0.003/1K chars (tts-1-hd) → ~$0.05 per 102.9s narration (~1,500 chars).
ElevenLabs: $22/mo Creator tier (100K chars) — only worth it for frequent production.
"""

import os
from pathlib import Path

env_path = Path.home() / "AppData" / "Local" / "hermes" / ".env"

# Check current .env content
if env_path.exists():
    content = env_path.read_text()
    print("=== Current .env (relevant lines) ===")
    for line in content.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("VOICE_TOOLS_OPENAI_KEY") or line_stripped.startswith("ELEVENLABS_API_KEY") or line_stripped.startswith("STT_OPENAI") or line_stripped.startswith("TTS_"):
            print(f"  {line_stripped}")
    # Check if OPENAI key line exists but is empty
    for line in content.splitlines():
        if "VOICE_TOOLS_OPENAI_KEY" in line:
            parts = line.split("=", 1)
            val = parts[1] if len(parts) > 1 else ""
            if val.strip() == "" or val.strip().startswith("#"):
                print("  [NOTE] VOICE_TOOLS_OPENAI_KEY empty/commented — set to your OpenAI key from https://platform.openai.com/api-keys")

# Show OpenAI TTS pricing for reference narration
narr_chars_approx = 1500  # ~1,500 chars for 102.9s at ~145 wpm
cost_tts_1 = (narr_chars_approx / 1000) * 0.0015
cost_tts_1_hd = (narr_chars_approx / 1000) * 0.003

print(f"\n=== OpenAI TTS Pricing Estimate (Flannan Isles, {narr_chars_approx:,} chars ≈ 102.9s narration) ===")
print(f"  tts-1 (standard):     ${cost_tts_1:.4f} per full narration pass")
print(f"  tts-1-hd (high-def):  ${cost_tts_1_hd:.4f} per full narration pass")
print(f"  ElevenLabs Creator:   $22/mo (100K chars) → only economical for frequent videos")

# Show setup instructions
print(f"\n=== Setup Instructions ===")
print("1. Get OpenAI API key: https://platform.openai.com/api-keys")
print("2. Add to .env:")
print(f"   VOICE_TOOLS_OPENAI_KEY=sk-...your_key...")
print("3. In build_timeline.py, replace edge_tts call with openai.audio.speech.create():")
print("   from openai import OpenAI")
print("   client = OpenAI(api_key=os.getenv('VOICE_TOOLS_OPENAI_KEY'))")
print("   response = client.audio.speech.create(model='tts-1-hd', voice='alloy', input=text)")
print("   response.stream_to_file(output_path)")
print("4. Available OpenAI TTS voices (as of 2026): alloy, echo, fable, onyx, nova, shimmer")
print("   'alloy' = neutral/documentary; 'onyx' = deeper/male; 'nova' = calm/female.")
print("5. For this mystery documentary tone, recommend 'onyx' (deeper male) or 'alloy' (calm measured).")

# Verify openai import works
try:
    from openai import OpenAI
    print(f"\n  [VERIFIED] openai package import works — TTS ready.")
except Exception as e:
    print(f"\n  [WARNING] openai import failed: {e}")
