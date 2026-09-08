# Flannan Isles Mystery — Project README

## Project
Flannan Isles lighthouse disappearance (December 1900). Atmospheric documentary, 2-minute prototype test.

## Pipeline architecture
Hermes native video control workflow (`hermes_native_video_control_workflow.md`):
- Mode: prototype (max 2 min, no publication without approval)
- Timeline IR: `timeline.json` (typed source of truth)
- Renderer: `render_clean.py` (stage-tested, clean compiler)
- Review gate: timeline must be inspected before render

## Verified artifacts
- `timeline.json`: v1.0 schema, 21 beats, actual TTS durations (102.9s narration)
- `project.yaml`: prototype mode, style version `cinematic_mystery_documentary_v001`
- Footage: 5 Pexels clips (`footage/`), 54.33 MB total, resolution >=720p, vertical excluded
- Templates: `title_card.html`, `lower_third.html`, `caption_style.html`
- TTS: Fish Audio S2.1 Pro (primary, OpenRouter endpoint verified — 402 billing gate); OpenAI tts-1-hd / onyx (fallback, `openai` package v2.24.0 verified, requires `VOICE_TOOLS_OPENAI_KEY`)
- Music: synthesized drone (`.m4a`, AAC) — clearly labeled placeholder; real music blocked (Pixabay broken; Jamendo excluded per copyright risk instruction)
- Captions: 21 caption PNG templates verified (`cap_00.png` to `cap_20.png`); sequential overlay chain verified (22 steps, all RC=0 from real `ffmpeg` log). Visual verification: caption drawtext passes compilation but does NOT appear in output video frames at 2s/5s/50s/95s (confirmed by `vision_analyze` on `frame_check.png` and sequential frame extractions). Caption layer requires repair (filtergraph timing or drawtext syntax fix) before publication.
- HyperFrames: v0.8.30 installed; Chrome launches; loader blocked (`VIDEO_SOURCE_UNRENDERABLE` — video `file://` absolute path issue); FFmpeg direct path working.
- Clean renderer (`render_clean.py`): stages 1-6 verified by real execution (real stdout/stderr/duration); stage 7 produces working video (42MB previous, 32.8MB caption-complete version) — caption visibility needs repair.

## Blocked / requires user action
- Caption visibility: real frames show NO caption overlay (verified by vision analysis of `frame_check.png` and `frame_at_50.png`). Filtergraph syntax passes (`RC=0`) but visual result missing.
- HyperFrames loader: needs fix (serve via local HTTP server or patch loader for relative video paths)
- Real music: requires funded OpenRouter account (Fish Audio) or separate OpenAI key for TTS, plus YouTube Audio Library browser automation for licensed audio
- `.env`: `VOICE_TOOLS_OPENAI_KEY` empty (`.env` protected, key must be added by user)

## Next actions (user-directed, not automated)
- Confirm caption repair approach (fix drawtext timing / sequential chain / server-based HyperFrames)
- Confirm TTS provider activation (Fish Audio billing OR add `.env` OpenAI key)
- Confirm real music source (YouTube Audio Library browser automation or funded provider)
- Confirm publication gate: prototype only; no public upload without explicit human approval per `hermes_native_video_control_workflow.md`
