# Perception & Rhythm Engine

This is how NarrativeOS edits the way a human editor does: listening to the
music, respecting speech, and avoiding monotony. There is no "AI decides
everything" model. It measures what can be measured, turns that into
editing proposals, and a person reviews them. **JEV is not used.** The
Director is deterministic code.

```
music.wav ──► temporal_map ──┐
alignment ──► speech_map ────┼──► perception.json ──► plan_edit (Director) ──► event_graph.json
videos ─────► visual_map ────┘                                               └► timeline.proposed.json
profile ────► resolve_style (one editorial intent for every modality)         └► rhythm_review.json
```

Run it:
`python scripts/director_pipeline.py --timeline T --music M --alignment A --visuals V --profile P --out NEW_DIR`

The output directory must not already exist. The input timeline is never
modified.

## Status against the owner's brief

Statuses:
- **IMPLEMENTED:** code plus tests.
- **IR-ONLY:** in the timeline, but not rendered yet.
- **BLOCKED:** waiting on an owner choice.
- **NOT MEASURED:** no reliable detector yet, so it is reported, never guessed.

| Brief item | Status | Where / how |
|---|---|---|
| Remove JEV | IMPLEMENTED | Director is `director_brain.plan_edit`; it refuses a model mode |
| Beats, onsets, tempo | IMPLEMENTED | `style_intel/audio.temporal_map`; librosa. Beat phase and half/double time are ambiguous, and this is flagged |
| Energy curve | IMPLEMENTED | 0.5 s RMS windows |
| Sections / phrases | IMPLEMENTED (candidates) | A ≥ 6 dB sustained energy change; a phrase is an onset near it |
| "Beat is building" / "bass dropped" | IMPLEMENTED (loudness shapes) | BUILD_CANDIDATE (sustained ≥ 6 dB rise over ≥ 4 s), IMPACT_CANDIDATE (≥ 9 dB jump in 0.5 s), BREAKDOWN_CANDIDATE (≥ 9 dB fall that holds). These are loudness shapes, not recognised song sections |
| Kick / snare / hi-hat / chorus / downbeats / meter / tempo changes | NOT MEASURED | Needs source separation or a trained model |
| Cut on the musical moment | IMPLEMENTED | Existing boundaries snap to a nearby impact, phrase, onset or beat (within `snap_window_sec`); reveals prefer impacts |
| Anticipation ("prepare before the beat") | IMPLEMENTED (marker) | ANTICIPATE marker before a reveal. It does not invent a camera move |
| "Don't cut; let the shot hit" | IMPLEMENTED | HOLD for explicit holds and protected pauses; EMPHASIZE for impacts inside a shot (`accent_action: emphasize`) |
| Syncopation / not mechanical | IMPLEMENTED (review) | `rhythm_review`: warns when ≥ 90% of cuts land on beats, or when shot lengths are metronomic |
| J-cut / L-cut | IR-ONLY | `J_CUT` / `L_CUT` events. They need `audio_overlap` in the style, native audio on both shots, and source room for the overlap. The FFmpeg renderer does not play native audio yet |
| Keep meaningful pauses | IMPLEMENTED | Pauses ≥ 0.3 s are preserved, and linked to the narration plan's SILENCE reasons |
| Remove "um", "uh", repeats | IMPLEMENTED (candidates) | SPEECH_FILLER / SPEECH_REPEAT, marked `trim_candidate`. Nothing is removed automatically. "Like" and "you know" are never flagged |
| Breaths, false starts, emphasis, speech emotion | NOT MEASURED | |
| Shot boundaries and camera motion | IMPLEMENTED | Hard cuts plus gradual transitions; ORB+RANSAC motion (`style_intel`) |
| Avoid visual monotony | IMPLEMENTED (motion) | `rhythm_review` flags ≥ 4 shots in a row with the same camera motion |
| Shot scale (wide/close), faces, gaze, direction, action matching, emotion | NOT MEASURED | Needs a vision model; listed in `not_measured` |
| One style across voice, captions, images, music, SFX | IMPLEMENTED | `editorial_style.resolve_style`: one tone/avoid list flows into every modality |
| Image generation when nothing suitable exists online | IMPLEMENTED; provider BLOCKED | `generation.plan_request` routes: conceptual → generate; illustration → stock search first; factual evidence → never generated. `load_adapter` + `command_adapter` run a locally installed model. None is configured yet |
| Imagination-only images skip the search | IMPLEMENTED | `visual_role: conceptual` |
| Same place or person looks the same every time | IMPLEMENTED | The continuity bible supplies attributes and a generation lock, and `register_generated_reference` makes an approved generated image the reference for later requests. `compose_prompt` tells the model to match it |
| Happy-moment image inside a crime video keeps the crime look | IMPLEMENTED | `compose_prompt` always carries the production tone, style and avoid list, whatever the moment |
| Music and SFX generation | IMPLEMENTED; provider BLOCKED | Same request, approval and adapter path; `duration_sec` is passed through |
| AI video generation | DISABLED | Refused by `plan_request`, `execute_request` and `load_adapter` |

## Safety rules the code enforces

- Every Director output is `review_required`. `compile_graph` never
  produces an approved timeline, and `build_timeline.py` refuses to
  overwrite a reviewed or approved one.
- Generation needs all of:
  - a versioned quote that matches the request hash;
  - cost **and** rights approval;
  - verified reference-image bytes;
  - verified output bytes.

  Generated media is `generated_illustration_not_factual_evidence` and can
  never support a factual claim.
- Confidence values are heuristic detector support, not probabilities.

## Adding a real generator

Add an entry to a providers config and pass it to `generation.load_adapter`:

```json
{"image": {"type": "command", "provider": "local-sdxl", "model": "sdxl-1.0",
           "rights_terms": "owner-run local model", "work_dir": "D:/narrativeos-gen",
           "output_ext": ".png", "command": ["python", "gen.py", "--prompt-file", "{prompt_file}",
           "--refs", "{refs_file}", "--out", "{out}"]}}
```

Hosted APIs (OpenAI, FAL, ElevenLabs and others) need their own adapter
type and API keys. None exists yet.

## Next steps

1. Make the renderer play native audio, so J/L-cuts become audible.
2. Add a vision model for shot scale, faces, gaze and action, to feed
   `rhythm_review` and matching.
3. Add source separation (e.g. Demucs) for drum hits and vocal entries, and
   downbeat tracking.
4. Pick and configure an image generator and a music/SFX generator.
