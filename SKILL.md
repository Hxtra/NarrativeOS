---
name: hermes-video-editor
description: Build and operate an evidence-gated, channel-configurable long-form video editor for Hermes. Use for script-to-storyboard planning, semantic asset matching, browser-based asset acquisition, deterministic FFmpeg rendering, captions, visual QA, scene revision, and optional HyperFrames experiments.
---

# Hermes Video Editor

Use this skill to build videos from a script without silently substituting irrelevant media. Treat the workflow as a resumable state machine and every render as a compiler of an approved manifest.

## Non-negotiable rules

- Keep FFmpeg as the primary renderer. Treat HyperFrames as optional until a real localhost MP4 + SVG + text composition renders and is visually inspected.
- Never select media from filenames, directory order, search titles, or keyword overlap alone.
- Convert narration into `ShotSpec` records before searching for assets.
- Do not approve a shot without real frame evidence, provenance, rights status, and a verified source interval.
- If no candidate passes, block the shot or use an explicitly labelled fallback; never force a match.
- Never generate factual text inside an image when deterministic editor text can be used.
- Mark a stage complete only when its artifact exists, its schema validates, dependencies pass, and required QA passes.
- Never claim semantic visual matching from technical metadata alone.

## Standard workflow

```text
INTAKE → STYLE_LOCK → RESEARCH → EVIDENCE_REVIEW → OUTLINE → SCRIPT
→ NARRATION_ALIGNMENT → BEAT_MAP → SHOT_PLAN → ASSET_ACQUISITION
→ ASSET_ANALYSIS → ASSET_APPROVAL → GRAPHICS → TIMELINE
→ PREVIEW_RENDER → TECHNICAL_QA → EDITORIAL_QA → TARGETED_REVISION
→ FINAL_RENDER → DELIVERY_REVIEW
```

Run one stage with:

```bash
python scripts/controller.py --project /path/to/project
```

Use `--stage STAGE` only for controlled debugging. The controller writes `state.json`, `events.jsonl`, and `errors.jsonl` and refuses to advance on missing prerequisites.

## Project contract

A project contains:

```text
project.yaml
state.json
channel_profile.json
shot_specs.json
assets.json
timeline.json
renders/
qa/
```

Use JSON schemas in `schemas/`. Use `examples/minimal_project/` as a starting point.

## Asset matching

For each visual beat, create a `ShotSpec` with narration and visual purpose; required subjects, actions, location, period, and mood; forbidden meanings and anachronisms; visual mode; duration; shot type; motion; and fallback options.

For each candidate:

1. Probe it with FFprobe.
2. Extract at least three frames with `scripts/extract_frames.py`.
3. Analyze actual frames with a configured vision system.
4. Record descriptions, evidence paths, usable interval, rights, and decision.
5. Reject contradictions, wrong actions, anachronisms, and unsupported claims.

Without a configured real vision analyzer, leave `VISUAL_MATCHING` blocked.

## Rendering

Use `scripts/render_ffmpeg.py` with a validated `timeline.json`. Each shot must resolve as:

```text
shot_id → approved asset_id → assets.json → verified local_path
```

Supported deterministic motion presets are `static`, `slow_zoom_in`, `slow_zoom_out`, `pan_left`, and `pan_right`. Use explicit `fit_policy` values such as `cover_crop`, `contain`, or `letterbox`. Use hard cuts by default.

Captions must be rendered with ASS or another visibly verified method. A successful FFmpeg exit code is not caption QA. Use `scripts/validate_render.py` to probe streams, duration, frame samples, and caption evidence.

## Browser and HyperFrames

Use Hermes browser automation for candidate discovery, source-page inspection, licensing, downloads, and localhost testing. Download online icons locally, record license and SHA-256, and register them in `assets.json`; do not hotlink unverified production assets.

HyperFrames is optional. Test only with a localhost-served MP4 and SVG. Preserve exact stderr and keep the backend blocked if no output is produced. The FFmpeg path remains valid and primary.

## Channel profiles

Keep channel identity separate from the controller. Store narrative, visual, pacing, audio, music, caption, diagram, forbidden-behavior, and QA rules in `channel_profile.json`. Do not hard-code a specific drawing style into the editor.

## Delivery gate

The project is not ready for delivery unless all approved shots have evidence and rights records; timeline coverage is complete; captions are visible in final frames; audio/video streams and durations pass; editorial QA finds no material contradictions; provenance and checksums are present; no secrets or machine-specific paths are packaged; and `state.json` says `delivery_ready: true`.

Read `references/architecture.md` for artifact contracts and `references/channel-profile.md` for the channel-master pattern. Read `references/hyperframes.md` only when testing that optional backend.
