# Editing Brain Implementation Audit and Roadmap

## Purpose

This document reconciles the editing research with the actual NarrativeOS checkout. The research documents observed professional editing behavior. The repository currently contains foundational contracts and small heuristic producers, not a complete AI-native editing brain. This distinction is a permanent evidence rule.

## Verified current state

The following line counts and repository state were checked in the current checkout on 2026-09-12:

| Component | Verified current state | Interpretation |
|---|---:|---|
| `scripts/director_brain.py` | 21 lines | Real but simple heuristic producer. It is not a full editorial intelligence engine. |
| `scripts/editorial_analysis.py` | 18 lines | Real but simple timeline inspection and repetition analysis. |
| `scripts/timeline_ir.py` | 17 lines | Real structural validation/export step. It does not implement full event-graph compilation or dependency propagation. |
| `timeline-editor/` | Integrated | Real API/UI package with server-side `EDITORIAL_QA` revision gate and safe media proxy. |
| `references/editing-brain.md` | Present | Research-backed design specification, not an implementation claim. |
| `references/youtube-editorial-study.md` | Present | Directly observed YouTube study and proposed policies, not a validated engine. |

The presence of an artifact, script, or documented policy does not prove that a production-quality capability exists. A capability becomes implemented only after the repository contains executable logic, tests, real inputs, and validation evidence.

## Current architecture gap

The verified architecture is currently closer to:

```text
brief
  ↓
beat_map
  ↓
director_brain
  ├── director_strategy
  ├── emotional_arc
  └── retention_plan

timeline.json
  ↓
editorial_analysis

timeline.json
  ↓
timeline_ir
  ↓
timeline_ir.json
```

The missing layer is the connection between editorial intent and coordinated timeline consequences:

```text
EDITORIAL INTENT
       ↓
  EVENT GRAPH
       ↓
TIMELINE CONSEQUENCES
       ↓
   TIMELINE IR
       ↓
    RENDERER
```

This gap is the most valuable next architectural target because it can be added without replacing the current controller or FFmpeg renderer.

## Important limitation: timing validation is not propagation

The current Timeline IR validation can detect an overlap or non-monotonic sequence. It does not yet reason about downstream consequences.

For example, if:

```text
B001 = 0–5 seconds
B002 = 5–10 seconds
B003 = 10–15 seconds
```

becomes:

```text
B001 = 0–8 seconds
```

validation can report that `B002` now overlaps. It does not yet propagate the three-second change to `B002`, `B003`, captions, audio events, music automation, markers, or downstream dependencies.

Dependency propagation belongs in the Event Graph and retiming layer. It must be implemented and tested before claiming that revision-safe editorial editing exists.

## Permanent evidence-state model

NarrativeOS should keep these states separate:

```text
OBSERVED
   ↓
INFERRED
   ↓
PROPOSED_POLICY
   ↓
IMPLEMENTED
   ↓
VALIDATED
```

A YouTube analysis may produce an observation. An editor-architect may infer a policy. A developer may implement a rule. A test and real render may validate it. These states must never be collapsed into a single “supported” label.

## Staged implementation plan

### Phase 1: Event Graph v0

Implement only three event types:

```text
REVEAL
EMPHASIZE
CUT
```

Each event should include:

- unique event ID;
- narrative purpose;
- trigger;
- beat or claim reference;
- affected shot or object references;
- timing range;
- dependencies;
- visual consequences;
- audio consequences;
- motion consequences;
- downstream consequences;
- provenance;
- validation status.

The initial compiler should produce existing Timeline IR-compatible output. It should not require a new renderer.

Acceptance evidence:

1. Valid Event Graph JSON passes schema validation.
2. Invalid references and unsupported operations are rejected.
3. The compiler emits deterministic output.
4. A real sample project produces a changed timeline artifact.
5. The compiled timeline passes current Timeline IR validation.

### Phase 2: Pacing state

Add:

```text
ORIENT
ACCELERATE
SUSTAIN
SUSPEND
REVEAL
RELEASE
RESET
```

Each beat receives a pacing state and a reason. Pacing state should guide permissible shot-duration ranges and effect intensity without imposing a universal cut frequency.

Acceptance evidence should include a report showing each state transition, its reason, and its resulting timing or operation changes.

### Phase 3: Radio edit

Add `radio_edit.json` as a distinct editorial artifact:

```text
VOICE / INTERVIEW
       ↓
   RADIO EDIT
       ↓
 NARRATIVE BEATS
       ↓
   EVENT GRAPH
       ↓
     PICTURE
```

The radio edit should reference real narration or interview intervals. It should not fabricate alignment if no transcript or audio timing exists.

Acceptance evidence:

- real source audio or explicit user timing exists;
- radio segments are ordered and non-overlapping;
- beat references resolve;
- missing alignment blocks downstream picture compilation.

### Phase 4: Audio-event relationships

Convert isolated audio operations into event responses:

- J-cuts;
- L-cuts;
- ambience bridges;
- SFX triggers;
- music ducking;
- reveal accents;
- silence events.

The system must record source intervals and timeline intervals. It must validate that a referenced audio source exists and that the audio operation is supported by the active renderer.

### Phase 5: Dependency propagation

Implement ripple-safe retiming. When an approved editorial change changes duration, update downstream objects according to explicit track and dependency policies.

Required affected objects include:

- subsequent video clips;
- captions;
- dialogue and music events;
- SFX and ambience bridges;
- graphics and markers;
- event triggers based on time;
- render-plan durations.

The system must preserve a before/after diff and be able to revert an invalid revision byte-for-byte.

### Phase 6: Action and gesture intelligence

Only add `action_markers.json` after real frame-level or audio-level analysis exists. A gesture marker must contain:

- media path;
- frame or time range;
- detector or model metadata;
- observed action label;
- confidence or categorical status;
- validation state;
- link to the editorial decision that uses it.

A guessed timestamp or an LLM-generated label without media evidence must remain blocked.

### Phase 7: Primitive animation and HyperFrames integration

Only after the Event Graph explains why an animation exists should NarrativeOS add primitive animation operations. HyperFrames remains an optional adapter. FFmpeg remains the primary renderer until HyperFrames completes real loader and render validation.

## Proposed Event Graph v0 object

```json
{
  "event_id": "EV_001",
  "type": "REVEAL",
  "status": "proposed",
  "purpose": "introduce_verified_evidence",
  "trigger": {"type": "beat", "beat_id": "B001"},
  "claim_id": "C001",
  "affected_objects": ["SHOT_001"],
  "timing": {"start": 4.0, "duration": 3.0},
  "visual": [{"operation": "video_enter", "asset_id": "asset_001"}],
  "audio": [{"operation": "duck_music", "amount_db": -4.0}],
  "motion": [{"operation": "camera_push", "from_scale": 1.0, "to_scale": 1.04}],
  "dependencies": [],
  "constraints": ["evidence_passed", "rights_verified", "timeline_valid"],
  "provenance": {"source_ids": ["SRC_001"], "decision_reason": "claim evidence reveal"}
}
```

## Recommended next engineering milestone

The next code milestone should be **Event Graph v0 plus deterministic compilation**, not the simultaneous implementation of every research finding. The first vertical slice should demonstrate:

```text
real beat
  ↓
REVEAL event
  ↓
verified shot reference
  ↓
compiled Timeline IR
  ↓
FFmpeg render
  ↓
frame/audio/timing QA
```

The success criterion is not the existence of an event JSON file. The success criterion is an evidenced chain from observed editorial intent to a changed rendered result.

## Final classification

| Capability | Status |
|---|---|
| Research-backed editing principles | Documented |
| Direct YouTube observations | Documented and timestamped |
| Basic director heuristics | Implemented, simple |
| Basic editorial analysis | Implemented, simple |
| Basic Timeline IR validation | Implemented, simple |
| Timeline Editor | Implemented and tested |
| Full Event Graph | Not implemented |
| Dependency propagation | Not implemented |
| Full pacing intelligence | Not implemented |
| Trusted gesture/action markers | Not implemented |
| Primitive animation engine | Not implemented |
| Full AI-native editing architecture | Future |

This classification is intentionally conservative. It prevents the editing research from becoming an unsupported claim about production capability.
