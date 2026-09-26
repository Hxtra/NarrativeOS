# Remaining templates

Built so far: `title_card`, `chapter_break`, `credits_roll`, `subscribe_cta`
(all pack `core`). Everything below is not yet built. Organized by pack, in
the priority order they were originally scoped:

## Pack 2 — Speaker & Caption System (P0) — done
`speaker_lower_third` (with real returning-speaker variant), `location_stamp`,
`interview_frame`. Proven together via `MultiLayerPlayer` in
`Proof-InterviewCombined` — pillarboxes a mismatched-aspect-ratio real photo
correctly, location stamp and speaker ID coexist without overlap.

## Pack 3 — Archive & B-Roll (expanded scope, partially done)

**Done:** `archive_video` exists and normalizes aspect ratio (via the
shared `containFit` primitive), grade/grain/vignette (shared style-driven
primitives), and Ken Burns panning (via the shared `useKenBurns`
primitive) — plus real on-screen source attribution pulled from Media
Library metadata. Hardened against frame-rate explicitness, audio policy,
and watermark-state enforcement — see `references/archive-video-hardening.md`
for the full detail with real measured evidence (verified dB math on
audio ducking, a real 20fps/silent-track test fixture, an enforced
watermark guard that's actually been triggered and confirmed to throw).
Tested against the real NASA asset and a real (rights-unverified,
engineering-only) moving-video fixture; a second, genuinely different-
provenance still-image test (the Wikimedia asset) is blocked on bytes,
not architecture — see `media-library/README.md`.

**Media Library milestone since:** Internet Archive Adapter v0 built and
tested (`media-library/tools/internet_archive_adapter.py`) — first
source with a real, working rights-verification pipeline
(SEARCHED → CANDIDATE → RIGHTS_VERIFIED → DOWNLOADABLE → BYTE_VERIFIED →
REGISTERED), confirmed against a real item (a 1957 Universal Newsreels
Sputnik clip, cross-confirmed public domain via two independent
sources). Bytes blocked in this sandbox specifically (network egress
config, not the source) — see `media-library/README.md`'s Internet
Archive section for the precise, tested reason. This item is intended
as the next real ArchiveVideo test once bytes are obtainable — real
1957 newsreel footage, 4:3 aspect ratio, a genuinely different era and
shape than anything tested so far.

**Not done, and don't assume otherwise:**
- Watermark *detection* (only the explicit-state guard exists; `status`
  still has to come from a human/process at ingestion) and any true
  loudness-matching audio normalization across sources (only simple
  gain/duck exists) — see `references/archive-video-hardening.md`.
- `double_exposure` as a real composable primitive — done: see
  `useDoubleExposure` + `double_exposure_portrait`, proven with two
  distinct real Media Library records.
- Parallax / depth push / layered photo reveal — still blocked on the
  segmentation/depth preprocessing step scoped early in this project.
  Don't build a fake parallax from a flat image and call it this.
- Dedicated dust/scratch as its own primitive, distinct from the grain
  overlay, is not built (film grain, vignette, gate-weave jitter, and now
  exposure flicker all already exist as shared primitives).

**Next: Pack 4 — Evidence & Information.** This is where NarrativeOS
moves beyond visual treatment into documentary reasoning — documents,
maps, statistics, timelines, evidence cards, source-backed information.
Not yet started.

## Pack 4 — Evidence & Information (P1, true-crime/investigative/educational-heavy)
- Evidence/document card — zoom + highlight-box + redaction reveal
- Map flyover/location establish
- Data visualization/chart reveal
- Cold statistic/big-number reveal
- Timeline/date progression bar
- Redacted/classified document stamp

## Pack 5 — Transitions (P0 — real templates put most of their engineering here)
- Light leak/film burn — already built in the original documentary-slideshow
  project (4 variants: wipe/flash/vertical/bloom); port into this registry
  as a shared transition primitive rather than per-template code
- Glitch/digital distortion — real precedent confirmed: Template 1's
  "Fast Chromatic" hub-and-expression rig (a master control layer with
  Color/Contrast/Direction sliders, referenced via expressions elsewhere)
- Whip pan/camera move — real precedent confirmed: Template 2 built on
  "Handy Seamless Transitions," a named catalog (Warp Spin, Cam Fgt, Warp
  Side Roll — each with directional variants). Worth deciding whether to
  license that pack's approach/naming convention or build an original
  equivalent catalog.
- Match cut/morph
- Hard cut + sound sting — not visual; this is a timing+SFX recipe and
  belongs in the case-library work, not a Remotion component

## Pack 6 — Typography & Quotes (P1)
- Quote card/testimonial — full-screen kinetic type, no image
- Kinetic caption/subtitle styling per style
- News ticker/breaking banner — news-style specific

## Pack 7 — Audio-Reactive (P2, polish tier)
- Sound-reactive waveform/beat flash

## Infrastructure notes for whoever picks this up

- Style-specific `StyleProfile` entries (DW, true crime, mystery,
  educational, video-essay, nature/wildlife, biography, news) don't exist
  yet — see `architecture.md` for why they shouldn't be guessed.
- The `tdb4` binary keyframe/easing chunk from the `.aep` reverse-engineering
  is still unmapped — see `architecture.md`.
