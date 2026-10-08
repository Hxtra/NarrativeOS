# Multi-track timeline compiler (IR 3.0)

`scripts/compile_timeline.py` turns one validated multi-track timeline into one render in a single FFmpeg
pass. It replaced the old renderer, which encoded every shot separately, concatenated them and laid one
audio file on top. That design could not represent overlaps, transitions, layered audio or J/L cuts: it was
stitching, not editing. `render_ffmpeg.py` keeps its CLI as a thin wrapper over the compiler.

Schema: `schemas/timeline_ir_v3.schema.json` (structure). Semantic rules live in `compile_timeline.validate()`.

## What a timeline can express, and how it renders

| Track kind | Items | Render |
|---|---|---|
| `video` (main) | `timeline_in/out`, `source_in`, `fit` (cover/contain), `motion` (push_in/pull_out with scales), `transition_in` (cut / crossfade / dip_black / dip_white), `audio.native` with its own `native_in/out` window (J/L cuts) | Each item is decoded from its source range, conformed to the canvas, delayed to its timeline time and composited onto a black canvas. A crossfade is a real overlap: the incoming shot's alpha fades in over the outgoing one. A dip fades both shots through a colour. |
| `overlay` | `blend` (normal/screen/add/multiply), `opacity`, `fade_in/out` | Normal: alpha overlay. Screen/add/multiply: the layer is padded with its neutral colour (black, or white for multiply) for the whole timeline and blended in RGB. |
| `audio` | `role` (narration/music/sfx/ambience/dialogue), `gain_db`, `fade_in/out`, track `duck_under` + `duck` settings | One bus per track. A ducked track goes through sidechain compression keyed by the other track. The mix sits on a full-length silent bed, then loudnorm (configurable or off). |
| `caption` | `text`, track `style` (font, size and margin as fractions of the canvas) | ASS subtitles burned with libass in the same filtergraph. |

## Validation before rendering (fails closed)

- `ir_version`, an even-sized canvas, an fps up to 120, and a sample rate of 44.1 or 48 kHz.
- Unique track and item IDs; finite times with out > in.
- Every source range is inside the probed asset, including the extra footage a crossfade needs and the J/L
  native-audio window.
- Main-track overlaps only where a crossfade declares exactly that overlap. Gaps are warnings (black).
- Assets resolve to `assets.json`, `approved_assets.json` or the timeline's own `assets`. Their status must be
  approved; `simulation_approved` is also accepted except in `--release` mode.
- Paths resolve inside the project, `$NARRATIVEOS_MEDIA_ROOTS` or the VFX library. This is the path broker:
  traversal and outside paths are refused.
- Overlay blend and opacity, audio gain within −60..+20 dB, fades no longer than the item, `duck_under` naming a
  real audio track, and captions that do not overlap (lines over 42 characters are warnings).

## Verification after rendering

ffprobe must agree with the timeline:
- size and frame rate;
- duration within one frame plus 50 ms;
- an audio stream exactly when audio was placed;
- audio and video stream lengths within 80 ms.

The render is written to a `.partial` file and renamed only on success. `renders/render_manifest.json`
records the timeline hash, the filtergraph hash, the FFmpeg version, the inputs, warnings, unrendered
transitions and the verification result. `renders/compile/<timeline-hash>/` keeps the exact filtergraph and argv.

## Converting shot timelines

`from_shot_timeline()` (`--from-shot-timeline timeline.json`) converts the existing shot timelines, including
ones compiled from Director event graphs:
- **motion presets:** `slow_zoom_in/out` become push_in/pull_out;
- **MOTION markers:** become motion on the shot they fall in;
- **legacy `transition` fields:** converted to IR transitions;
- **TRANSITION markers:** FFmpeg-native recipes (crossfade, dip, flash family) become native transitions; every
  other registered recipe becomes `{"type": "recipe"}` and is rendered by Remotion;
- **J/L native-audio splits:** carried over;
- **narration, music (ducked) and captions:** added as tracks.

A crossfade is centred on the cut when the incoming shot has a handle, and otherwise extends the outgoing shot.
Only where Remotion cannot run (no node or no `node_modules`) does a non-native recipe stay a hard cut, listed in
`compile.unrendered` and the render manifest. It is never faked.

## Graphics, recipe transitions and finishing (Phase 1 of "graphics into the final cut")

The compiler renders what FFmpeg can't draw with the Remotion project, as short segments, then composites them in
the same single FFmpeg pass (`scripts/remotion_bridge.py` → `project/scripts/render_segments.mjs`):

- **Graphic track** (`"kind": "graphic"`): each item names a registry template and its params, e.g.
  `{"template": "speaker_lower_third", "params": {"name": "…", "role": "…"}}`. Project media goes in as
  `{"asset_id": "…"}`, staged under `public/_nos` (gitignored).
  - It renders over transparency (ProRes 4444) at the timeline's size and composites with its alpha, opacity and
    fades.
  - Templates are laid out at 1920×1080, so the canvas must be 16:9.
- **Recipe transitions** (`"transition_in": {"type": "recipe", "recipe": "glitch_reveal"}`) sit on a straight cut.
  1. The compiler cuts both shots' windows (the recipe's `before` and `after`) from their sources with the same
     picture chain as the main track (fit, motion, speed, grade), so the segment matches its neighbours exactly.
  2. It runs them through the TransitionStack and lays the result over the cut.
  3. Where a source has no handle, the nearest frame is held. For recipes that show both shots together (crossfade,
     soft wipe, halftone, whip) this raises a warning.
  4. Windows must fit in their shots and must not overlap.
- **Caching:** segments are cached in `renders/segments/` by a content key: template or recipe, params, both shots'
  descriptions, media identity, grades, size and a hash of the Remotion sources. An unchanged segment is never
  re-rendered. On the demo, the first compile took 65 s (4 segments), the second 13 s.
- **Sound cues:** recipe cues (`whoosh`, `impact`, `glitch_tick`, …) and a graphic's `sfx` list are resolved against
  the local SFX library (`NARRATIVEOS_SFX_LIBRARY`, default `~/NarrativeOS-SFX-Library/sfx_catalog.json`: approved
  sounds with a `cue`). They are placed at the exact frame. Cues without a sound are listed in
  `unresolved_sfx`, never faked.
- **Finishing:**
  - `grade` (timeline-wide, per-item override, `null` to opt out): `lut` (an asset `.cube`), `exposure`,
    `contrast`, `saturation`, `gamma`, `temperature`. Applied to the pictures only; overlays and graphics stay
    ungraded.
  - `speed` (0.1-10; native sound follows via pitch-preserving atempo).
  - `speed_ramp`: points `{t, speed}` over the item; retimed by the exact inverse of the ramp's integral, so each
    output frame shows the source moment the ramp implies. Native sound can't follow a ramp; validation refuses it.
  - `motion_blur` (frame blend, `tmix`).
  - `stabilize`: FFmpeg `deshake`, basic. This FFmpeg build has no vid.stab.
- **Progress:** `compile_timeline(phase=…)` reports `graphics` (segments, cached, done, progress) between `validate`
  and `graph`; the Studio shows it live.

## Status

| Piece | Status |
|---|---|
| Multi-track compile in one FFmpeg pass: crossfade/dip, overlays with blend modes, push-in/pull-out, native audio with J/L windows, per-track audio buses, ducking, SFX placement, loudnorm, burned captions | VALIDATED on synthetic media by measurement (`tests/test_compile_timeline.py`: colours mid-crossfade, the dip, screen arithmetic, 1 kHz music ≥ 6 dB lower under narration, SFX band only at its time, the L-cut tone stopping at its window, caption pixels only at their time, identical decoded frames across two renders). Also rendered with real media: a NASA photo push-in, the 1024×576 / 44.1 kHz documentary clip with its own sound, and a VFX-library light leak screen-blended across the cut. Frames reviewed. |
| Validation and post-render verification | IMPLEMENTED and tested. The real-media run caught a genuine bug: a late-only sound produced a 4 s audio stream on a 7 s video. Now fixed with a silent bed and a regression test. |
| Remotion graphics and `TransitionStack` recipes in the final render | VALIDATED by measurement (`tests/test_final_cut.py`): a flash recipe whitens the cut and nothing outside its window, lower-third text pixels appear only while the graphic is on screen, the recipe's sound cue resolves from an SFX catalogue and its energy sits on the cut, and a recompile reuses every segment. Also rendered on the demo project: a title card, a lower third, a glitch reveal and a warm light leak between real clips. Frames reviewed. |
| Speed, ramps, grade, LUT | VALIDATED by measurement on clips whose brightness encodes source time: 2× shows the right source moment, a ramp matches its exact integral at several times, a LUT swaps red and blue, saturation 0 is neutral grey, items can opt out of the timeline grade. |
| Sound library for recipe cues | BLOCKED on sounds: the mechanism works and is tested with a synthetic catalogue; no real SFX library has been sourced yet, so cues are reported as unresolved. |
| Vertical (9:16) graphics | NOT YET: templates are laid out for 16:9 (Phase 2, talking-head). |
| Very long timelines | Every item is its own FFmpeg input. Fine for shorts and medium edits; a 25-minute, 300-shot edit should be compiled in chunks (planned). |
