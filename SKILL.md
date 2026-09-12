---
name: narrativeos-video-editor
description: Build and operate NarrativeOS, an evidence-gated, channel-configurable long-form and short-form video-production workflow for Hermes. Use for structured intake, research, scripts, narration alignment, TTS, semantic asset matching, rights-aware acquisition, graphics, captions, FFmpeg rendering, audio mixing, thumbnails, revision, QA, and optional publishing.
---

# NarrativeOS Video Editor

Build videos as a durable, evidence-gated production graph. NarrativeOS remains the source of truth for intent, cost, claims, assets, rights, timeline lineage, revisions, and release state. FFmpeg is the primary renderer. HyperFrames and external generation providers are adapters, not sources of truth.

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
INTAKE → STYLE_LOCK → DIRECTOR_STRATEGY → QUOTE → RESEARCH_WORKSPACE
→ SOURCE_INGEST → RESEARCH → CLAIM_BUILD → EVIDENCE_REVIEW → CONTRADICTION_REVIEW → OUTLINE → SCRIPT
→ NARRATION_ALIGNMENT → BEAT_MAP → SHOT_PLAN → ASSET_ACQUISITION
→ ASSET_ANALYSIS → VISUAL_BENCHMARK → ASSET_APPROVAL → CONTINUITY_BIBLE → EVIDENCE_LINKING
→ GRAPHICS → TTS → ALIGNMENT → CAPTIONS → TIMELINE → TIMELINE_IR → AUDIO_MIX
→ EDITORIAL_ANALYSIS → EDITORIAL_REPAIR → COST_REVIEW → VARIANT_BUILD → THUMBNAIL → PREVIEW_RENDER
→ TECHNICAL_QA → EDITORIAL_QA → TARGETED_REVISION → FINAL_RENDER
→ DELIVERY_REVIEW → PUBLISH
```

Run one controller step with:

```bash
python scripts/controller.py --project /path/to/project
```

Use `--stage STAGE` only for controlled debugging. The controller persists `state.json`, append-only `events.jsonl`, and `errors.jsonl`. It advances only when dependencies and artifact validators pass.

## NarrativeOS intelligence layer

Use `director_brain.py` for intent detection, director strategy, emotional arcs, retention events, pacing, music intensity, silence opportunities, and effect restraint. Use `continuity_bible.py` for entity, temporal, and geographic memory. Use `evidence_links.py` for claim-to-source-to-asset-to-shot lineage and explainability. Use `editorial_analysis.py` for diversity, shot economy, repetition, silence, and restraint analysis.

Use `research_workspace.py` to initialize persistent research memory and `detect_contradictions.py` to flag conflicting source claims. NotebookLM, native RAG, and other research systems are provider adapters; unified evidence remains the source of truth.

Use `timeline_ir.py` for renderer-independent editorial structure. Use `cost_router.py` before expensive operations. Use `creative_memory.py` for A/B edit metadata and explicit user taste preferences.

Run the integration milestone with:

```bash
python scripts/simulate_documentary.py --project /path/to/simulation
```

The simulation wires research, claims, director strategy, emotional arc,
retention, continuity, ShotSpecs, evidence links, timeline IR, editorial
analysis, and negotiation into `narrative_graph.json`, `negotiation_log.json`,
and `integration_report.json`. It uses structural fixtures and must remain
`production_ready: false` until real media evidence, rights, narration
alignment, and human editorial review are present.

## Producer scripts

The package includes deterministic local producers for quote, brief-derived planning, beat maps, ShotSpecs, review gates, local asset ingest, user voiceover registration, explicit caption timings, timeline assembly, audio mixing, graphics manifests, FFmpeg rendering, QA, and delivery review. It also includes `ingest_sources.py`, `build_claims.py`, `build_provenance.py`, `align_audio.py`, `visual_benchmark.py`, `editorial_repair.py`, and `build_variants.py`. Local source ingestion and hashing are implemented. `align_audio.py` runs faster-whisper when installed and otherwise writes a blocked alignment record. Visual benchmark metrics remain null until real labeled evidence cases exist. Editorial repair creates scoped revision actions. Variant generation creates two deterministic policy manifests but does not claim a human preference win. External web research, provider TTS, vision analysis, thumbnail generation, and publishing remain adapter work or explicit review gates.

## Stage contracts

Each stage has a required artifact map in `scripts/controller.py`. A stage may be `implemented`, `pending`, `blocked`, or `review_required`. The presence of a file alone never proves that its stage passed.

## Visual matching and acquisition

For every `ShotSpec`, acquire independent candidates. Probe media with FFprobe, extract multiple real frames, analyze actual frames with a configured vision system, use temporal/action analysis for action-based shots, record evidence and provenance, and block when no candidate passes. A URL is not a rights decision.

## Voice, captions, audio, and rendering

TTS must be an explicit adapter with provider, model, voice, consent, language, cost, and request metadata. Support user-uploaded narration. Caption timing must come from actual alignment or explicit timing input. The timeline must include video, narration, music, effects, captions, graphics, and markers. Use FFmpeg with explicit motion, transitions, audio buses, ducking, loudness normalization, and QA.

## Delivery gate

Do not set `delivery_ready: true` unless approved shots have evidence and rights records; claims have sources; narration and captions have complete timing; audio/video streams and loudness pass; captions are visibly rendered; editorial QA finds no material contradictions; provenance and checksums exist; no secrets are packaged; and the release package contains final media, editable timeline, transcript, captions, evaluation report, rights manifest, hashes, tool versions, and approvals.

Read `references/architecture.md` for contracts, `references/vidrush-gap-plan.md` for the implementation roadmap, `references/editing-brain.md` for cutting, pacing, sound, music, motion, graphics, captions, platform profiles, event-graph design, and editing QA, `references/youtube-editorial-study.md` for directly observed YouTube editing breakdowns and the user reference analysis, `references/editing-brain-implementation-audit.md` for the verified implemented-versus-proposed classification and staged Event Graph roadmap, and `references/hyperframes.md` only when testing that optional backend.
