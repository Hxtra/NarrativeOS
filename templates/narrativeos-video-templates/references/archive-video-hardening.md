# ArchiveVideo hardening

Five items, worked through in order, each with real evidence — not just
typed and assumed to work.

## 1. Frame rate — verified Remotion needs no correction, made source fps explicit

Confirmed from Remotion's own documentation (not assumed from memory):
*"Remotion mounts a `<video>` tag and sets `ref.currentTime = frame / fps`
to synchronize with the timeline."* This means video playback speed is
already correct regardless of the source's own encoding rate — a 20fps
source plays back at correct real-world speed inside a 30fps timeline
automatically. That part needed no new code.

What was actually missing: **nobody could tell what a source's real fps
was**, because nothing probed it. `media-library/tools/probe_asset.py`
runs real `ffprobe` at ingestion time (outside Remotion — a React
component can't shell out to ffprobe) and produces facts like:

```
source_fps: 20.0
source_fps_is_common_value: false
real_source_frame_count: 280
has_audio: true
```

on the actual test fixture (see below). `ArchiveVideoParams.technicalProfile`
carries this through explicitly; `showTechnicalDebug: true` renders it
on screen so it's provably plumbed through the pipeline, not just typed
and ignored. Verified: `Proof-ArchiveVideo-RealFootage` shows
`source_fps: 20 (uncommon)` and `real_source_frames: 280` on screen,
matching the probe's real output exactly.

## 2. Audio policy — verified with measured dB, not just "it rendered"

`motion/audioPolicy.ts` — `preserve | mute | duck | replace`, default
`mute` (a deliberate, safe default: old footage can carry useful natural
sound, but silently preserving unknown archival audio by default is its
own silent assumption, same category of mistake as silently assuming a
frame rate).

The real test fixture (`cockatoo_test.mp4`) turned out to measure -91dB
(essentially silent) across its *entire* 14-second source — confirmed by
probing the original file directly, not just the render output. That's
not a bug in the pipeline, it's the source material. To actually verify
the mechanism, a synthetic 440Hz test tone was generated
(`synthetic_test_tone.mp4`, ffmpeg `sine=` filter — self-contained, no
rights ambiguity) and rendered through two policies:

```
preserve:        mean -24.2dB  (close to source's -21.1dB; small delta from AAC re-encode)
duck (to 0.2):   mean -38.2dB
measured delta:  -14.0dB
expected delta:  20*log10(0.2) = -13.98dB
```

Matches to within 0.02dB. `mute` was separately confirmed via `ffprobe`
to produce a video with **no audio stream at all**, not a silent one —
arguably the more correct outcome.

## 3. Watermark — enforced guard, verified to actually throw

`motion/watermarkPolicy.ts` implements no removal — only makes the state
explicit and refuses to proceed on unsafe combinations:

```
status "present" + action "reject"                    -> throws
status "unknown" + action != "manual_review"           -> throws
status "present" + action "preserve"                   -> allowed
status "unknown" + action "manual_review"               -> allowed
status "none"    + action "preserve"                    -> allowed
```

All five cases actually run and verified (not just reasoned about) via a
real test script — the two unsafe combinations threw, the three safe ones
didn't.

## 4. Primitive extraction — useArchiveFlicker

Exposure flicker was bundled inside `useOrganicWeave`'s single
`brightness()` line, forcing anything that wanted flicker to also take
positional jitter. Extracted to `motion/archiveFlicker.ts` as
`useArchiveFlicker(amount, seedPrefix?)` — `useOrganicWeave` now composes
it with its original exact seed prefix (`'weave-f'`) rather than
duplicating the math, and `ArchiveVideo` can request flicker alone via
`flickerAmount` without any positional jitter, which matters for real
video that already moves.

**A verification-methodology correction happened here, worth keeping:**
an initial before/after diff showed a small discrepancy (mean ~2.5/255)
attributed at first to Remotion's bundle cache. A second, unrelated
refactor produced the identical diff magnitude even with that cache
cleared — meaning the cache explanation was too narrow. The actual cause:
this environment's headless Chromium has small (~1%) cross-process image
decode/scaling nondeterminism, unrelated to code logic. The reliable
check is same-session self-consistency (render current code twice in a
row — always 0 diff here) plus direct logical comparison of old vs. new
code, not a before/after diff captured across separate process launches.

## 5. Tested against genuinely different real footage

`test-fixtures/cockatoo_test.mp4` — real moving video, 1280x720, **20fps
(confirmed uncommon)**, real AAC/mp3 audio stream present (if
near-silent), 14s duration. Explicitly marked
`status: engineering_test_fixture_only`, `rights_verified: false` in its
Media Library record — no rights statement exists anywhere in its source
repository for this specific file, unlike its sibling assets which are
individually credited. **Never use this as documentary content, only for
technical QA.** `synthetic_test_tone.mp4` — self-generated, used only to
get an actual audible signal for the audio-policy measurement above.

## What's still not built — named, not glossed over

- **Frame rate:** nothing further needed for playback speed (see #1).
  Not built: any decision logic that *uses* `sourceFpsIsCommonValue`
  (e.g., flagging unusual-fps footage for a human review step before
  it's used) — the fact is surfaced, nothing consumes it yet.
- **Audio:** `replace` mode's code path exists (mounts a separate
  `<Audio>` track, silences the original) but hasn't been rendered and
  verified the way `preserve`/`mute`/`duck` were above.
- **Watermark:** genuinely nothing beyond the explicit-state guard — no
  detection, no removal, by design. `status` still has to come from
  somewhere (asset review at ingestion), which isn't built.
- Frame-rate-driven motion decisions, true watermark detection, and any
  audio normalization beyond simple gain (loudness matching across
  sources, for instance) remain open, real, separate problems.
