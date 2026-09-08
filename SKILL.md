---
name: hermes-video-editor
description: Build and operate an evidence-gated, channel-configurable long-form and short-form video-production workflow for Hermes. Use for structured intake, research, scripts, narration alignment, TTS, semantic asset matching, rights-aware acquisition, graphics, captions, FFmpeg rendering, audio mixing, thumbnails, revision, QA, and optional publishing.
---

# Hermes Video Editor

Build videos as a durable, evidence-gated production graph. Hermes remains the source of truth for intent, cost, claims, assets, rights, timeline lineage, revisions, and release state. FFmpeg is the primary renderer. HyperFrames and external generation providers are adapters, not sources of truth.

## Non-negotiable rules

- Never select media from filenames, search titles, directory order, or keyword overlap alone.
- Never approve a visual without real frame evidence, a verified source interval, provenance, and a rights decision.
- Never spend credits or call a billable provider before a versioned quote and required approval exist.
- Never mark an unimplemented provider stage passed by creating a placeholder artifact. Use `status: blocked` or `status: pending`.
- Never claim semantic matching from technical metadata, one thumbnail, or a model score alone.
- Never publish automatically. Publishing requires an explicit release decision and a provider-specific manifest.
- Keep credentials, browser profiles, cookies, downloaded media, generated media, and machine-specific paths outside the skill package.

## Full production graph

```text
INTAKE → STYLE_LOCK → QUOTE
→ RESEARCH → EVIDENCE_REVIEW → OUTLINE → SCRIPT
→ NARRATION_ALIGNMENT → BEAT_MAP → SHOT_PLAN
→ ASSET_ACQUISITION → ASSET_ANALYSIS → ASSET_APPROVAL
→ GRAPHICS → TTS → CAPTIONS → TIMELINE → AUDIO_MIX
→ THUMBNAIL → PREVIEW_RENDER → TECHNICAL_QA → EDITORIAL_QA
→ TARGETED_REVISION → FINAL_RENDER → DELIVERY_REVIEW → PUBLISH
```

Run one controller step with:

```bash
python scripts/controller.py --project /path/to/project
```

Use `--stage STAGE` only for controlled debugging. The controller persists `state.json`, append-only `events.jsonl`, and `errors.jsonl`. It advances only when dependencies and artifact validators pass.

## Stage contracts

| Stage | Required output | Current implementation rule |
|---|---|---|
| INTAKE | `brief.md`, `project.yaml` | Parses user inputs; does not infer missing settings silently. |
| STYLE_LOCK | `channel_profile.json` | Loads channel identity, pacing, visual, audio, caption, compliance, language, and source policies. |
| QUOTE | `quote_manifest.json` | Records duration, format, providers, model, voice, estimated cost/latency, and approval. No billable generation before approval. |
| RESEARCH | `research.json`, `claim_ledger.json` | Research and citations are required for factual videos. |
| OUTLINE | `outline.json` | Converts research into acts, chapters, and narrative purpose. |
| SCRIPT | `script.json` | Produces narration, visual intent, claims, and source links. |
| NARRATION_ALIGNMENT | `narration_alignment.json` | Maps script text to narration ranges or marks voiceover timing pending. |
| BEAT_MAP | `beat_map.json` | Converts narration into timed beats with pacing and visual purpose. |
| SHOT_PLAN | `shot_specs.json` | Creates structured ShotSpecs; this is planning, not visual approval. |
| ASSET_ACQUISITION | `asset_candidates.json` | Uses browser/API adapters and records provenance, licensing, hashes, and download validation. |
| ASSET_ANALYSIS | `asset_analysis.json` | FFprobe plus at least three real frames per candidate; vision/action analysis is required. |
| ASSET_APPROVAL | `approved_assets.json` | Approves only candidates with frame evidence, rights, interval, and no hard contradiction. |
| GRAPHICS | `graphics_manifest.json` | Records diagrams, maps, icons, templates, and source/license metadata. |
| TTS | `narration.mp3`, `tts_manifest.json` | Provider adapter or user-uploaded voiceover. No fake audio artifact. |
| CAPTIONS | `captions.json`, `captions.ass` | Generates timings from transcript/word alignment; validates coverage and safe area. |
| TIMELINE | `timeline.json` | Canonical multi-track edit plan with stable IDs and lineage. |
| AUDIO_MIX | `audio_mix_manifest.json` | Narration, music, effects, gain, ducking, loudness, and true-peak policy. |
| THUMBNAIL | `thumbnail_manifest.json` | Optional generated/uploaded thumbnail with provenance and human review. |
| PREVIEW_RENDER | `renders/preview.mp4`, `render_manifest.json` | Deterministic render; no encoder-only success claims. |
| TECHNICAL_QA | `qa/technical_qa.json` | FFprobe, stream, duration, frame, captions, loudness, clipping, and checksum checks. |
| EDITORIAL_QA | `qa/editorial_qa.json` | Checks factuality, action relevance, contradictions, pacing, continuity, and captions. |
| TARGETED_REVISION | `qa/revision_report.json` | Applies scoped change requests only to affected artifacts/shots. |
| FINAL_RENDER | `renders/final.mp4` | Renders the approved revision. |
| DELIVERY_REVIEW | `qa/delivery_review.json` | Produces release package and sets `delivery_ready` only if all hard gates pass. |
| PUBLISH | `publish_manifest.json` | Optional and explicitly authorized. Never upload by default. |

A stage may be `implemented`, `pending`, `blocked`, or `review_required`. The presence of a file alone never proves that its stage passed.

## Visual matching and acquisition

For every `ShotSpec`, acquire independent candidates. For each candidate:

1. Probe the file with FFprobe.
2. Extract multiple frames with `scripts/extract_frames.py`.
3. Analyze the actual frames with a configured vision system.
4. Use temporal/action analysis for action-based shots.
5. Compare subject, action, location, period, mood, composition, continuity, and forbidden meanings.
6. Record exact evidence paths, source interval, provenance, rights, model/version, and decision.
7. Block when no candidate passes.

The matching system should eventually use a cascade: indexed keyframes, multimodal retrieval, action-aware reranking, contradiction detection, and editorial approval. Until that exists, keep `VISUAL_MATCHING` blocked.

Use Hermes browser automation or provider adapters for discovery. Download assets locally, verify magic bytes and decodeability, calculate SHA-256, store the origin page and license evidence, and generate attribution where required. A URL is not a rights decision.

## Voice, captions, audio, and rendering

TTS must be an explicit adapter with provider, model, voice, consent, language, cost, and request metadata. Support user-uploaded narration even when TTS is unavailable. Never create a fake `narration.mp3` to pass a gate.

Caption timing must come from transcript alignment or a user-supplied timing file. Use Whisper/faster-whisper for baseline timing and WhisperX only when word-level alignment is required. Burn ASS/WebVTT captions and inspect sampled frames; FFmpeg exit code is not caption QA.

The timeline must include video, narration, music, effects, captions, graphics, and markers. Implement motion and transitions as explicit filter plans. Use `filter_complex` and re-encode when transitions or motion require it; do not rely on concat stream-copy for effects. Use audio buses, sidechain ducking, loudness normalization, and true-peak checks.

Use `scripts/render_ffmpeg.py` for the current deterministic core. Its current verified path is video-first and must not be described as full audio/motion production until those paths pass real smoke tests.

## Revisions, thumbnails, languages, and publishing

A revision request must resolve to a scoped diff: affected stage, artifact, shot IDs, cost, and expected changes. Re-run only affected downstream stages, then repeat QA.

Store `language` and locale rules in `channel_profile.json`. Keep script, TTS, captions, source citations, and thumbnail text synchronized across languages.

Thumbnail generation, external publishing, voice cloning, avatars, and paid generation require provider-specific consent, provenance, and human/release gates. The skill can prepare a publish manifest; it must not upload automatically.

## Delivery gate

Do not set `delivery_ready: true` unless all approved shots have frame evidence and rights records; claims have sources; narration and captions have complete timing; audio/video streams and loudness pass; captions are visibly rendered; editorial QA finds no material contradictions; provenance and checksums exist; no secrets are packaged; and the release package contains final media, editable timeline, transcript, captions, evaluation report, rights manifest, hashes, tool versions, and approvals.

Read `references/architecture.md` for artifact contracts, `references/vidrush-gap-plan.md` for the implementation roadmap, `references/channel-profile.md` for channel-master configuration, and `references/hyperframes.md` only when testing that optional backend.
