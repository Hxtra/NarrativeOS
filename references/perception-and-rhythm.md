# Perception & Rhythm Engine

NarrativeOS edits the way a human editor does: it listens to the music,
respects speech, and avoids monotony. The approach is to measure what can be
measured, turn that into editing **proposals**, and have a person review them.
It does not claim human-level musical understanding.

JEV is **not** part of NarrativeOS. It was considered earlier and removed on
2026-09-29 (historical note). The Director is rule-based by default. A
reasoning model can be attached through a provider-agnostic interface, and no
specific model or vendor is assumed.

```
music.wav ─► style_intel.audio.temporal_map ─┐   (events labelled MEASURED / INFERRED; NOT_MEASURED listed)
alignment ─► perception.speech_map ──────────┤
videos ────► perception.visual_map ──────────┤   (cuts + dissolves/burns/dips via style_intel.shots)
style DNA ─► editorial_style.resolve_style ──┤   (allowed transitions = what the reference measurably used)
                                             ▼
                        director_brain.plan_edit  ◄── optional: model_provider (any reasoning model, validated)
                                             ▼
             event_graph.json ─► event_graph.compile_graph ─► timeline.proposed.json (review_required)
                                             └► perception.rhythm_review ─► rhythm_review.json
```

Run it:
`python scripts/director_pipeline.py --timeline T --music M --alignment A --visuals V --profile P [--dna DNA] [--narration N] [--director-provider CFG] --out NEW_DIR`

The output directory must not already exist, and the input timeline is never
modified.

Status meanings:
- **IMPLEMENTED:** code plus tests.
- **PARTIAL:** works with a stated limit.
- **DISABLED:** deliberately switched off.
- **PLANNED:** not built.

## Music map (`style_intel/audio.py::temporal_map`)

| Signal | Basis | Status |
|---|---|---|
| Onsets (spectral flux) | MEASURED | IMPLEMENTED |
| Energy curve (RMS per window) | MEASURED | IMPLEMENTED |
| Beats and one global tempo (librosa tracker) | INFERRED: phase and half/double time are ambiguous | IMPLEMENTED |
| Section candidates (sustained energy contrast) | INFERRED | IMPLEMENTED |
| Phrase candidates (onset nearest a section candidate) | INFERRED; no bar grid | PARTIAL |
| BUILD / IMPACT / BREAKDOWN candidates (energy shapes) | INFERRED; loudness shapes, not song sections or "bass drops" | IMPLEMENTED |
| Kick, snare, hi-hat, downbeat, meter, chorus, vocal entry, instruments, tempo changes, emotion | NOT_MEASURED, each with a reason in `measurements` | PLANNED (needs source separation / trained models) |

- Every event carries `basis`.
- `measurements` lists every feature with MEASURED / INFERRED / NOT_MEASURED
  and the method or reason.
- An onset is never presented as a kick, snare or downbeat.
- Silent audio returns status `silent` and no events.
- All thresholds are in `MUSIC_MAP_DEFAULTS`. Override them with
  `temporal_map(path, config={...})`.

## Rule-based Director (`scripts/director_brain.py::plan_edit`)

A musical event can become any of these actions. **A beat is never
automatically a cut.**

| Action | When | Status |
|---|---|---|
| CUT | An existing cut moves onto a nearby phrase, impact, onset or beat (within `snap_window_sec`, only in `rhythm_mode: phrase_aware`) | IMPLEMENTED |
| REVEAL | Same as CUT, into a shot marked `editorial_intent: reveal`; prefers impacts | IMPLEMENTED |
| HOLD | An explicit hold, or a protected speech pause, stops a cut from moving | IMPLEMENTED |
| ANTICIPATE | Marker before a reveal (`anticipation_sec`); no invented camera move | IMPLEMENTED |
| EMPHASIZE | An impact inside a shot (`accent_action: emphasize`), never inside a protected pause | IMPLEMENTED |
| MOTION | A build covering at least `motion_min_sec` of a shot becomes a push-in (`build_motion: push_in`) | IMPLEMENTED (proposal; render wiring PLANNED) |
| TRANSITION | An impact, breakdown or section change at a cut (`transition_policy: energy`) picks a recipe from `allowed_transitions` only | IMPLEMENTED (proposal; render wiring PLANNED) |
| J_CUT / L_CUT | `audio_overlap` in the style, native audio on both shots, and room in the source | IMPLEMENTED in the timeline IR; the FFmpeg renderer does not play native audio (PLANNED) |

- **Tolerances.** Every one lives in `scripts/editing_config.py`
  (`DIRECTOR_DEFAULTS`, `SPEECH_DEFAULTS`, `RHYTHM_REVIEW_DEFAULTS`). They are
  type-checked, and a bad value raises an error.
- **Outputs.** Everything is `status: proposed`. `compile_graph` always
  produces a `review_required`, unapproved timeline, and `build_timeline.py`
  refuses to overwrite an approved one.
- **Validation.** `event_graph.validate` checks every action:
  - boundaries must be adjacent and in order;
  - a MOTION must lie inside its shot;
  - a TRANSITION must sit exactly on the cut and use a registered recipe that
    the style allows;
  - J/L overlaps must stay within `max_audio_overlap_sec` and need audio on
    both shots.

### Transitions come from measurement, not guesses

`style_intel/shots.py::transition_vocabulary` reports what a video
measurably uses:
- hard cuts;
- dissolves;
- light burns and leaks;
- dips through black;
- flash frames;
- black frames.

Whip, glitch, wipe, zoom and match-cut transitions are listed under
`not_detected`.

Two components reuse it:
- `perception.visual_map` reports it for every analysed video.
- `editorial_style.resolve_style(profile, dna)` sets `allowed_transitions`
  from a full Style DNA through `style_intel.profile.choose_transitions`
  (source `style_dna`). Without a DNA the only allowed transition is
  `hard_cut`; a profile can override that (source `profile`).

## Reasoning models (`scripts/model_provider.py`)

- **Director modes.** `deterministic` is the default.
  `model_assisted` needs a provider config:
  - `command`: runs any program with `{input_file}` and `{output_file}`;
  - `callable`: an in-process SDK wrapper.
- **Validation.** Model proposals go through the same validator. Rejected
  ones are kept in `rejected_model_events` with their errors. Accepted ones
  carry `source: {kind: model, name, model}`.
- **No vendor is built in.** Claude, or any other model, is one config away.

Status: IMPLEMENTED (interface and validation). No provider is configured.

## Speech and rhythm review (`scripts/perception.py`)

| Feature | Status |
|---|---|
| Words and segments from a supplied alignment; invalid timing fails closed | IMPLEMENTED |
| Pauses ≥ `min_pause_sec` preserved, linked to the narration plan's SILENCE reasons | IMPLEMENTED |
| "um" / "uh" fillers and immediate repeats as `trim_candidate`; never auto-cut; "like" / "you know" never flagged | IMPLEMENTED |
| Breaths, false starts, emphasis, speech emotion | PLANNED (NOT_MEASURED) |
| Rhythm review: metronomic shot lengths, ≥ 90% of cuts on beats, repeated camera motion | IMPLEMENTED |
| Shot scale, faces, gaze, screen direction, action matching | PLANNED (needs a vision model) |

## Not claimed

The engine does not provide any of these:
- human-level music understanding;
- automatic final edits;
- rendering of MOTION, TRANSITION or J/L proposals;
- anything that needs a vision model.

Proposals are for review.
