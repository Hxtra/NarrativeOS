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
- **TRANSITION markers:** converted when the recipe is FFmpeg-native (crossfade, dip, flash family);
- **J/L native-audio splits:** carried over;
- **narration, music (ducked) and captions:** added as tracks.

A crossfade is centred on the cut when the incoming shot has a handle, and otherwise extends the outgoing shot.
Recipes FFmpeg cannot render natively (glitch, whip, leaks and the other Remotion `TransitionStack` recipes)
stay hard cuts and are listed in `compile.unrendered` and the render manifest. They are never faked.

## Status

| Piece | Status |
|---|---|
| Multi-track compile in one FFmpeg pass: crossfade/dip, overlays with blend modes, push-in/pull-out, native audio with J/L windows, per-track audio buses, ducking, SFX placement, loudnorm, burned captions | VALIDATED on synthetic media by measurement (`tests/test_compile_timeline.py`: colours mid-crossfade, the dip, screen arithmetic, 1 kHz music ≥ 6 dB lower under narration, SFX band only at its time, the L-cut tone stopping at its window, caption pixels only at their time, identical decoded frames across two renders). Also rendered with real media: a NASA photo push-in, the 1024×576 / 44.1 kHz documentary clip with its own sound, and a VFX-library light leak screen-blended across the cut. Frames reviewed. |
| Validation and post-render verification | IMPLEMENTED and tested. The real-media run caught a genuine bug: a late-only sound produced a 4 s audio stream on a 7 s video. Now fixed with a silent bed and a regression test. |
| Remotion `TransitionStack` recipes in the final render | NOT YET: listed as unrendered. Next: render recipe segments with Remotion and place them as overlay or main items. |
| Very long timelines | Every item is its own FFmpeg input. Fine for shorts and medium edits; a 25-minute, 300-shot edit should be compiled in chunks (planned). |
