# VidRush/ViewMax Implementation Plan

This reference converts the full research synthesis into an engineering plan. It defines workflow-level equivalence, not undocumented proprietary parity.

## Target architecture

Hermes should be a durable production compiler and evidence system. It should keep typed intent, quote approvals, claims, rights, visual evidence, timeline lineage, deterministic rendering, QA, revisions, and release accountability under its control. External models and generation providers should be replaceable adapters.

Support two profiles over the same artifact contracts:

| Profile | Primary output | Required behavior |
|---|---|---|
| Narrative long-form | Horizontal YouTube/documentary | Brief, quote, research, treatment, narration-led scenes, rights-aware visuals, chapters, multi-track edit, revisions, release package |
| Short-form social/ad | Vertical or platform-specific | Hook, script, product assets, avatar/presenter option, voiceover, b-roll, captions, templates, variants |

## Required durable artifacts

```text
project_brief.json
channel_profile.json
quote_manifest.json
research.json
claim_ledger.json
outline.json
script.json
narration_alignment.json
beat_map.json
shot_specs.json
asset_candidates.json
asset_analysis.json
approved_assets.json
graphics_manifest.json
tts_manifest.json
narration.mp3
captions.json
captions.ass
timeline.json
audio_mix_manifest.json
thumbnail_manifest.json
render_manifest.json
qa/technical_qa.json
qa/editorial_qa.json
qa/revision_report.json
qa/delivery_review.json
publish_manifest.json
run_ledger.jsonl
```

Every artifact needs a schema version, producer, input hashes, creation time, status, and validation result. Media needs a SHA-256 checksum and technical metadata. Provider tasks need request ID, model, cost, status, polling history, result URL, and error classification.

## Visual matching cascade

Do not use filenames, titles, or one image embedding as the approval mechanism.

```text
1. Index assets with sparse keyframes and technical metadata.
2. Retrieve high-recall candidates with text/image/video embeddings.
3. Rerank with denser temporal samples and action signals.
4. Run contradiction-aware entailment: entailed, contradicted, or unknown.
5. Verify the usable source interval and continuity.
6. Apply rights and editorial gates.
7. Approve only with evidence paths and a ShotSpec link.
```

Use a replaceable implementation. A practical progression is OpenCLIP/CLIP4Clip baseline, X-CLIP or InternVideo2 for stronger retrieval, PySlowFast/PyTorchVideo for action signals, and a VLM/API for targeted timestamped verification. Twelve Labs or Gemini can accelerate prototyping; they do not remove the need for provenance and review.

Recommended initial benchmark gates are Recall@50 >= 95%, acceptable@10 >= 80%, critical contradiction safety >= 98%, median interval-boundary error < 1 second, and indexed-query P95 < 2 seconds. These are proposed launch gates, not achieved results.

The benchmark must contain correct, attractive-but-wrong, wrong-action, anachronistic, low-quality, and no-valid-match cases. The no-match case must block rather than invent a match. Report top-1 accuracy, top-3 recall, false acceptance, wrong-action acceptance, anachronism acceptance, blocked-when-no-match, boundary error, and evidence completeness.

## Rights-aware acquisition

Separate discovery, rights evaluation, and transfer. Use source adapters for Pexels, Pixabay, Internet Archive, Europeana, Library of Congress, Openverse, Wikimedia Commons, Iconify, approved map providers, and licensed music sources only after provider terms are checked.

The ingest worker should enforce HTTPS and host policy, redirect and size limits, magic-byte validation, decodeability, SHA-256 storage, cache rules, attribution capture, and source-page provenance. Ambiguous or conflicting rights must route to human review. A search result, CDN URL, archive record, or generated asset is not automatically cleared for publication.

## Timeline and renderer

Use OpenTimelineIO as the canonical editorial interchange and Hermes manifests as the evidence/provenance layer. OTIO is not the renderer. Use FFmpeg for deterministic media compilation and a pinned browser renderer only for HTML/CSS/SVG/WebGL scenes.

The timeline must represent:

```text
video clips
source intervals
transitions
motion presets
captions
narration
music
sound effects
sidechain automation
graphics
markers
chapter boundaries
QA assertions
```

Use chapter-level checkpoints, atomic outputs, and content-addressed intermediate artifacts. Probe every input and output with FFprobe. Use `filter_complex` and re-encode when motion or transitions are required. Use audio buses, sidechain ducking, loudness normalization, true-peak checks, and caption visibility sampling.

## Narration, TTS, and captions

Support both provider-generated TTS and user-uploaded voiceover. Store provider, model, voice, language, consent, request, cost, and checksum metadata. Do not create placeholder audio to pass a stage.

Generate caption timing from the actual narration. Use Whisper or faster-whisper for baseline transcription. Use WhisperX only when word-level alignment or diarization is required. Store transcript segments, word timings where available, confidence, and alignment model metadata. Validate 100% declared speech coverage, timing order, safe-area placement, and sampled visual visibility.

## Durable orchestration

Start with a Hermes-native controller:

```text
versioned stage registry
append-only event log
materialized state
artifact registry
idempotency keys
atomic writes
human approval gates
bounded retries
crash/replay tests
provider polling records
```

A completed stage must be derivable from its artifacts and validators. A model cannot mark itself complete by writing a status string. LangGraph can later map stages to nodes and human gates to interrupts, but Hermes’s artifact registry remains authoritative. ECC concepts should become local skills, hooks, preflight checks, postflight checks, and specialized profiles.

## Quality and release

Use layered evaluation rather than one score:

| Layer | Examples |
|---|---|
| Technical | FFprobe, codecs, dimensions, duration, frame continuity, stream mapping, checksums |
| Caption/accessibility | Coverage, timing, visibility, safe area, transcript agreement |
| Audio | Loudness, true peak, clipping, narration masking, ducking |
| Visual | Subject, action, location, period, continuity, composition, evidence completeness |
| Editorial | Factuality, claim support, pacing, narrative clarity, contradictions |
| Rights | Provenance, license, attribution, people/brand/music review |
| Operations | Cost, latency, retries, restarts, duplicate callbacks, artifact lineage |

A release package contains final media, editable timeline, transcript, captions, evaluation report, rights/credits manifest, hashes, tool/model versions, and human approvals. Platform publishing is a separate authorized action.

## Phased backlog

### Phase 1: contracts and controller

Add the artifact schemas, full stage registry, quote manifest, event log, run ledger, idempotency keys, and blocked/pending/review-required statuses.

### Phase 2: narration path

Add `RESEARCH`, `OUTLINE`, `SCRIPT`, `NARRATION_ALIGNMENT`, `BEAT_MAP`, `TTS`, and `CAPTIONS`. First support user-uploaded voiceover, then add one TTS provider adapter.

### Phase 3: real acquisition and matching

Add source adapters, rights manifests, content-addressed storage, frame extraction, vision analysis, temporal reranking, contradiction checks, and the held-out benchmark.

### Phase 4: production renderer

Add OTIO export, multi-track timeline compilation, motion presets, transitions, narration muxing, music ducking, loudness, caption verification, chapter rendering, and restartable jobs.

### Phase 5: creative systems

Add diagrams, maps, thumbnail generation, source-linked graphics, multilingual profiles, variants, and scoped conversational revisions.

### Phase 6: operations and publish

Add long-form soak tests, crash recovery, cost and latency ledgers, release packaging, and an optional YouTube publishing adapter behind an explicit authorization gate.

## References

[1]: https://vidrush.ai/ "VidRush official homepage"
[2]: https://docs.vidrush.ai/docs "VidRush official documentation"
[3]: https://www.viewmax.io/ "Viewmax.io official homepage"
[4]: https://www.viewmax.io/mcp "Viewmax.io MCP documentation"
[5]: https://viewmax.studio/docs/api "ViewMax Studio API documentation"
[6]: https://opentimelineio.readthedocs.io/en/latest/ "OpenTimelineIO documentation"
[7]: https://ffmpeg.org/ffmpeg-filters.html "FFmpeg filters documentation"
[8]: https://ffmpeg.org/ffprobe.html "FFprobe documentation"
[9]: https://github.com/mlfoundations/open_clip "OpenCLIP repository"
[10]: https://github.com/xuguohai/X-CLIP "X-CLIP repository"
[11]: https://github.com/OpenGVLab/InternVideo "InternVideo repository"
[12]: https://docs.twelvelabs.io/docs/guides/search "Twelve Labs search documentation"
[13]: https://ai.google.dev/gemini-api/docs/video-understanding "Gemini video understanding documentation"
[14]: https://www.pexels.com/api/documentation/ "Pexels API documentation"
[15]: https://pixabay.com/api/docs/ "Pixabay API documentation"
[16]: https://creativecommons.org/cc-licenses/ "Creative Commons license overview"
[17]: https://operations.osmfoundation.org/policies/tiles/ "OpenStreetMap tile usage policy"
[18]: https://github.com/openai/whisper "Whisper repository"
[19]: https://github.com/m-bain/whisperX "WhisperX repository"
[20]: https://github.com/qdrant/qdrant "Qdrant repository"
[21]: https://docs.langchain.com/oss/python/langgraph/persistence "LangGraph persistence documentation"
[22]: https://temporal.io/blog/idempotency-and-durable-execution "Temporal idempotency guidance"
[23]: https://github.com/affaan-m/everything-claude-code "Everything Claude Code repository"
[24]: https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/kanban-video-orchestrator/references/kanban-setup.md "Hermes Kanban video orchestrator guidance"
[25]: https://www.w3.org/TR/webvtt1/ "W3C WebVTT specification"
[26]: https://tech.ebu.ch/loudness "EBU loudness recommendation"
