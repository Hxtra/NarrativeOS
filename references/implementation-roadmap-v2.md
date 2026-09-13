# NarrativeOS Implementation Roadmap v2

## Executive decision

NarrativeOS should be built in dependency order. The immediate priority is not publishing, thumbnails, a larger UI, many providers, or advanced effects. The priority is the chain that turns editorial intent into a verified render:

```text
STORY
  ↓
EDITORIAL INTENT
  ↓
BEAT
  ↓
VISUAL PURPOSE
  ↓
EVIDENCE
  ↓
EVENT
  ↓
EDITING OPERATION
  ↓
TIMELINE IR
  ↓
RENDER
  ↓
QA
  ↓
REPAIR
```

The current repository has a real but small foundation. It should evolve incrementally rather than be rewritten around unverified assumptions.

## Layered target architecture

```text
Research / claim graph
          ↓
Asset acquisition + rights + provenance
          ↓
Frame / action / evidence verification
          ↓
Editing Brain + pacing state
          ↓
Event Graph
          ↓
NarrativeOS Editorial IR
          ↓
       NLE compiler
      ┌────┼───────────┐
      ↓    ↓           ↓
    MLT HyperFrame  Audio DSP
      └────┼───────────┘
           ↓
         FFmpeg
           ↓
       Preview video
           ↓
  Technical QA + Editorial QA
           ↓
       Repair engine
           ↓
    Final delivery package
```

FFmpeg remains the current verified renderer. MLT is a candidate multitrack editing adapter. HyperFrame is a motion-design adapter. The NarrativeOS Editorial IR remains the source of editorial truth and must not be replaced by provider-specific commands or XML.

## Milestones

| Milestone | Focus | Definition of done |
|---|---|---|
| M1 | Foundation and contracts | Durable state, stage registry, artifact registry, event log, run ledger, idempotent stages, and truthful blocked states. |
| M2 | Story and Director | Claims, story beats, viewer objectives, emotional arc, visual purpose, and director decisions are generated as validated artifacts. |
| M3 | Narration and editorial beats | Segment-level narration plan, voice direction, natural-audio windows, silence windows, interview/quote segments, and real timing or explicit target timing. |
| M4 | Acquisition and provenance | A small set of source adapters enters media with checksums, metadata, rights status, provenance, and content-addressed storage. |
| M5 | Visual understanding | FFprobe, frame extraction, real frame/sequence analysis, claim comparison, rights checks, and approve/reject/block decisions. |
| M6 | Editing Brain and Event Graph | `REVEAL`, `EMPHASIZE`, and `CUT` compile from editorial intent to deterministic timeline consequences. |
| M7 | Multi-track timeline | Video, graphics, narration, native dialogue, music, SFX, ambience, markers, and ripple-safe dependency propagation. |
| M8 | Motion and graphics | Text, evidence cards, maps, timelines, lower thirds, and HyperFrame actions are selected by purpose and rendered through tested adapters. |
| M9 | Audio engine | Dialogue priority, native audio, music, ambience, SFX, Foley, J/L-cuts, ducking, silence, and measurable audio QA. |
| M10 | QA and repair | Technical/editorial QA produces actionable failures; approved repair operations update the graph and rerun affected gates. |
| M11 | Creative memory | Versioned channel recipes, accepted/rejected edit decisions, and human corrections inform future proposals without silently changing policy. |
| M12 | Autonomous production | A full documentary can run through the graph with real media, provenance, narration, visual evidence, render, QA, revision, and delivery. |

## Acquisition scope

Start with a small number of sources rather than many shallow integrations:

```text
Internet Archive
Wikimedia Commons
NASA
NARA
Library of Congress
```

A later phase may add commercial/licensed archives, stock providers, or user-authenticated services. Every provider adapter must return a normalized asset record:

```json
{
  "asset_id": "AST_001",
  "source": {
    "provider": "example",
    "url": "https://example.invalid/asset",
    "collection": "collection-id",
    "title": "source title"
  },
  "event": {},
  "semantic": {},
  "technical": {},
  "provenance": {},
  "rights": {
    "status": "UNKNOWN",
    "verified": false,
    "attribution_required": null,
    "restrictions": []
  },
  "checksum": null,
  "evidence": []
}
```

Allowed rights states:

```text
PUBLIC_DOMAIN
CC_LICENSED
LICENSE_REQUIRED
USER_PROVIDED
UNKNOWN
BLOCKED
```

`UNKNOWN` must never automatically enter a final edit. The system may show it as a candidate, but the compiler must block it until rights evidence exists.

## Visual understanding cascade

The acquisition system must not approve a clip based on the filename, title, or keyword overlap alone:

```text
SHOT SPEC
  ↓
candidate retrieval
  ↓
FFprobe and technical inspection
  ↓
frame extraction
  ↓
frame or sequence vision analysis
  ↓
temporal/action analysis where required
  ↓
claim and evidence comparison
  ↓
rights check
  ↓
APPROVE / REJECT / BLOCK
```

For action-based shots, multiple frames are mandatory. For static subject shots, representative frames may be sufficient when the policy allows it. The evidence manifest must preserve frame paths, timestamps, descriptions, decision reason, and model/tool metadata.

## Renderer decision

The attachment’s MLT recommendation is accepted as a **future adapter evaluation**, not as an immediate replacement. Official MLT documentation confirms a multitrack framework with producers, playlists, multitracks, tractors, filters, and transitions. The repository still needs a real adapter, installation test, media test, deterministic render test, and comparison against FFmpeg.

Remotion may be evaluated for web-native motion graphics and preview compositions. It is not the editorial brain. HyperFrame may execute motion-design events when its loader and output are verified. FFmpeg remains primary until alternatives pass the same render and QA gates.

## What not to build next

Do not prioritize the following before M6–M10 produce a verified vertical slice:

- YouTube publishing;
- a larger UI;
- thumbnails;
- many TTS providers;
- many footage providers;
- advanced 3D effects;
- decorative transition libraries;
- social automation;
- multi-agent complexity.

## First implementation slice

The next implementation should prove one complete chain:

```text
fixture-backed beat
  ↓
viewer objective
  ↓
contextual or evidence coverage decision
  ↓
segment-level narration plan
  ↓
explicit natural-audio or silence window
  ↓
REVEAL or CUT event
  ↓
compiled Timeline IR
  ↓
FFmpeg preview render
  ↓
frame/audio/timing QA
```

This slice must produce real files and real validation output. It should not claim TTS emotion, visual matching, MLT execution, HyperFrame rendering, or rights verification unless those capabilities actually run.

## Final rule

Every new capability must be classified as one of:

```text
DOCUMENTED
IMPLEMENTED
BLOCKED
VALIDATED
```

A research insight becomes part of the editing brain only when it has an executable representation, a test, a real artifact, and a validation result.
