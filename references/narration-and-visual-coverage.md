# Narration, Visual Coverage, and Editorial Engine Architecture

## Purpose

This document adds the missing editorial layer identified in the attached review: NarrativeOS must not generate one continuous voice-over and search for one literal clip per sentence. It must plan narration, silence, natural audio, visual coverage, graphics, motion design, and renderer consequences as coordinated editorial decisions.

The design is grounded in the repository’s evidence-gated philosophy. These are architecture requirements and proposed policies until executable code, real media, rendered output, and QA evidence exist.

## 1. Segment-level narration is a core primitive

NarrativeOS should represent narration as a sequence of editorial segments, not one opaque TTS file. A segment may contain narration, natural audio, interview audio, music-only space, a deliberate silence window, or a combination with explicit priority.

```text
BEAT 01
  narration: 0:00–0:08
  visual: archival footage
  music: low ambience

BEAT 02
  narration: none
  visual: real footage
  native_audio: on
  duration: 0:08–0:14

BEAT 03
  narration: 0:14–0:23
  visual: map animation
  sfx: subtle transition

BEAT 04
  narration: none
  visual: interview/news clip
  native_dialogue: on
```

The director must be able to explicitly decide:

- narration required;
- narration not required;
- natural or native audio priority;
- interview or quotation priority;
- music-only passage;
- intentional silence;
- delayed narration entry;
- pause before or after a phrase;
- whether a shot continues underneath multiple sentences.

A missing narration segment is not an error when the plan says that footage, interview, ambience, music, or silence carries the moment.

## 2. `narration_plan.json`

The proposed contract is:

```json
{
  "schema_version": "1.0",
  "project_id": "example",
  "language": "en",
  "voice_profile": "documentary_investigative",
  "segments": [
    {
      "segment_id": "NAR_012",
      "beat_id": "B012",
      "type": "NARRATION",
      "text": "But investigators noticed something unusual.",
      "timing": {
        "target_start": 31.4,
        "target_end": 36.2,
        "pause_before": 0.6,
        "pause_after": 1.2
      },
      "voice_direction": {
        "delivery": "calm_documentary_restrained",
        "emotion": "quiet_suspicion",
        "energy": 0.35,
        "pace": 0.82,
        "emphasis": ["unusual"],
        "pitch_direction": "neutral_low",
        "volume_intent": "intimate",
        "avoid": ["news_anchor", "dramatic_acting", "constant_emphasis", "even_rhythm"]
      },
      "relationships": {
        "visual_coverage_id": "VC_012",
        "music_policy": "duck_under_dialogue",
        "native_audio_policy": "below_dialogue"
      },
      "status": "planned"
    },
    {
      "segment_id": "NAT_013",
      "beat_id": "B013",
      "type": "NATURAL_AUDIO",
      "timing": {"target_start": 36.2, "target_end": 42.0},
      "source_ref": "asset_door_004",
      "reason": "let_original_footage_breathe",
      "native_audio_policy": "priority",
      "narration": "none",
      "status": "planned"
    }
  ]
}
```

Supported segment types should initially include:

```text
NARRATION
NATURAL_AUDIO
INTERVIEW
QUOTE
MUSIC_ONLY
SILENCE
MIXED
```

The system must distinguish `SILENCE` from a missing or failed audio artifact. An intentional silence segment should have a reason and may still contain controlled room tone or natural sound.

## 3. Voice Direction layer

TTS must receive more than plain text. NarrativeOS should generate a voice-direction object that expresses delivery intent while respecting the capabilities of the selected provider.

Direction fields may include:

- delivery mode;
- emotional state;
- energy;
- pace;
- pause before and after;
- emphasis words;
- pitch direction;
- vocal intimacy or distance;
- sentence length preference;
- pronunciation notes;
- words to avoid over-emphasizing;
- provider-specific controls;
- unsupported-control warnings.

The voice-direction layer is not a guarantee that a provider can render every requested nuance. If a provider does not support a control, the request must be recorded as unsupported or approximated, not silently claimed as implemented.

## 4. Voice styles and intra-video variation

A channel profile may define voice styles such as:

| Style | Direction |
|---|---|
| `INVESTIGATIVE` | calm, controlled, suspicious, restrained |
| `HISTORICAL` | authoritative, reflective, measured |
| `MYSTERY` | intimate, quiet, tense, spacious |
| `EMOTIONAL` | warm, vulnerable, slower, human |
| `BREAKING_EVENT` | urgent but controlled, clear, precise |
| `SCIENTIFIC` | precise, curious, explanatory |
| `REFLECTIVE` | slow, thoughtful, with longer pauses |

The style may change by narrative state. For example:

```text
INTRO       → quiet curiosity
DISCOVERY   → slightly faster, increasing intensity
SHOCK       → short phrase, lower volume, pause
EVIDENCE    → neutral, precise
CONFRONTATION→ firmer, faster
ENDING      → slower, reflective, spacious
```

This should be represented as a beat-level direction change, not as a single global voice prompt.

## 5. Silence and natural-audio windows

Silence and natural audio are editorial actions. The director may explicitly issue decisions such as:

- “Do not talk here; let the footage speak.”
- “Start narration 0.7 seconds after the door closes.”
- “Keep footsteps and room ambience above music.”
- “Leave two seconds after the reveal.”
- “Use the original interview instead of narrator exposition.”

The compiler must preserve these windows when retiming. A silence window may be blocked if it removes necessary comprehension or violates a required narration alignment, but it must not be filled automatically merely because the script contains unused text.

## 6. Visual continuity instead of word matching

NarrativeOS must reject the naive model:

```text
sentence → keyword → clip
```

Narration establishes meaning. Visuals establish a coherent world. A shot may support several sentences and should remain in place when it continues to serve the beat, remains visually alive, and does not contradict the narration.

The director should ask:

> What visual world should the viewer be inside right now?

rather than:

> What image represents every noun in this sentence?

A coverage object should therefore include:

```json
{
  "coverage_id": "VC_012",
  "beat_id": "B012",
  "viewer_objective": "understand_the_scale_of_the_event",
  "mode": "CONTEXTUAL",
  "literal_word_matching": false,
  "visual_subject": "high_altitude_testing_program",
  "preferred_world": [
    "scientists_working",
    "control_rooms",
    "rocket_preparation",
    "launch_facilities",
    "archival_operation_footage"
  ],
  "shot_duration_target": {"min": 3.0, "max": 7.0},
  "continuity_policy": {
    "allow_shot_to_cover_multiple_sentences": true,
    "replace_when": [
      "information_changes",
      "visual_becomes_stale",
      "new_evidence_required",
      "rhythm_requires_cut",
      "narration_requires_specific_visual"
    ]
  }
}
```

## 7. Visual coverage modes

The director should select a coverage mode according to the viewer objective:

| Mode | Use | Example |
|---|---|---|
| `LITERAL` | A specific action or object must be shown. | A door opens at a stated time. |
| `CONTEXTUAL` | Establish the broader subject or world. | Investigators, facilities, documents, interviews. |
| `ATMOSPHERIC` | Establish mood or uncertainty without claiming proof. | Empty hallway, night city, archive texture. |
| `EVIDENCE` | Show the actual source or object supporting the claim. | Dated document, photograph, map, primary footage. |
| `EVENT` | Represent a major historical or public event. | Launches, crowds, facilities, archival events. |
| `REACTION` | Show consequences or human response. | Headlines, broadcasts, crowds, interviews. |

The chosen mode must be visible in the shot plan and carried into evidence and QA. Atmospheric and contextual visuals must not be presented as direct proof of a claim unless separately verified.

## 8. Editorial visual vocabulary

Text overlays and motion graphics belong to the director’s editorial vocabulary, not to a final decorative pass. The director may choose:

- no text;
- informational overlay;
- emphasis text;
- context card;
- evidence text;
- animated typography;
- lower third;
- timeline or location graphic;
- full-screen graphic;
- no text despite available information, to avoid clutter.

The selection must be driven by the viewer objective. Every graphic needs a purpose, content provenance where factual, layout constraints, timing, and safe-zone validation.

## 9. HyperFrame as an available treatment, not an automatic mode

HyperFrame should be available as one of several possible visual treatments. The director should ask whether motion design improves understanding, emphasis, or emotional experience. It should not be triggered merely because a keyword appears or because HyperFrame is installed.

For example, a map animation may be justified when ordinary footage cannot communicate altitude, trajectory, scale, or geographic relationship. A HyperFrame action should include:

- editorial purpose;
- viewer objective;
- source data or geometry;
- timing;
- style profile;
- expected output asset;
- renderer capability status;
- QA evidence.

If the HyperFrame loader or renderer is blocked, the event should remain blocked or route to a verified alternative. It must not be marked complete because a composition file exists.

## 10. Timeline architecture and renderer boundaries

NarrativeOS should own the editorial representation. FFmpeg should remain the primary verified low-level renderer for the current repository. HyperFrame should be a motion-design adapter. A future MLT adapter is technically promising, but must be evaluated and tested before replacing the current renderer.

The conceptual architecture is:

```text
Director Brain
      ↓
NarrativeOS Editorial/Event IR
      ↓
  ┌───────────────┬─────────────────┬─────────────┐
  ↓               ↓                 ↓
FFmpeg          MLT adapter       HyperFrame
  ↓               ↓                 ↓
  └───────────────┴─────────────────┴─────────────┘
                      ↓
               Compositing / delivery
```

The timeline should contain at least:

```text
Video tracks
Graphics track
Narration track
Native/dialogue track
Music track
SFX/Foley/ambience tracks
Markers and evidence references
```

The renderer should consume this IR rather than receiving a sequence of ad hoc commands from the AI.

## 11. MLT assessment

The attachment’s MLT recommendation is technically plausible and is supported by official MLT documentation. MLT describes itself as an open-source framework for authoring, managing, and running multitrack audio/video compositions. Its XML model includes producers, playlists, multitracks, tractors, filters, and transitions, which are closer to NLE timeline concepts than issuing isolated FFmpeg commands.

MLT should therefore be treated as a **candidate timeline/render adapter**, not as an immediate replacement. Before adoption, NarrativeOS needs:

1. an adapter mapping from NarrativeOS Timeline IR to MLT XML or API objects;
2. real media tests for multiple tracks, transitions, filters, keyframes, and audio mixing;
3. deterministic output and render reproducibility checks;
4. platform installation and portability tests;
5. a comparison against the current FFmpeg renderer;
6. explicit handling for evidence overlays, captions, native audio, and HyperFrame assets;
7. a rollback path if an MLT render fails.

The Timeline IR must remain renderer-neutral so NarrativeOS is not locked into MLT.

Remotion is a separate candidate for web-native motion graphics and data-driven compositions. Its official model combines React components with frame-based video metadata and renderable compositions. It may be useful for graphics or a browser-based preview adapter, but it should not replace the evidence and event layers.

## 12. Updated execution order

The new vertical slice should be:

```text
real research claim or fictional public-domain brief
       ↓
beat with viewer objective
       ↓
narration plan segment
       ↓
voice direction or explicit natural-audio window
       ↓
visual coverage mode
       ↓
editorial event
       ↓
Timeline IR
       ↓
FFmpeg render
       ↓
frame/audio/timing QA
```

The first implementation should not attempt full TTS acting, MLT integration, HyperFrame rendering, and semantic visual coverage at once. The minimum useful slice is a real or fixture-backed `narration_plan.json`, one explicit silence/natural-audio window, one contextual coverage decision, one Event Graph event, and a rendered output whose changed timing is verified.

## 13. Acceptance gates

A narration and visual-coverage capability is not complete until:

- segments are generated from a real script or approved fixture;
- narration and non-narration windows are explicit;
- timing is tied to real audio or clearly marked as target timing;
- voice direction records provider support and unsupported controls;
- coverage mode is recorded per beat;
- visuals can span multiple sentences when continuity allows;
- literal word matching is not used as the sole relevance proof;
- graphics and HyperFrame actions have editorial purposes;
- native audio and silence survive compilation;
- the renderer produces real audio/video output;
- frame, audio, timing, caption, evidence, and rights QA artifacts exist;
- missing providers or blocked renderers remain visibly blocked.

## Sources

[1]: https://www.mltframework.org/ "Official MLT Multimedia Framework"

[2]: https://www.mltframework.org/docs/mltxml/ "Official MLT XML Documentation"

[3]: https://www.remotion.dev/docs/the-fundamentals "Official Remotion Fundamentals"

[4]: https://github.com/mltframework/mlt "MLT Framework GitHub Repository"
