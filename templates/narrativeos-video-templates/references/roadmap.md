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

## Pack 5 — Transitions & VFX system — foundation done (2026-09-26)

Built as a system, not as per-transition templates. See `SKILL.md` "Transitions & VFX".

**Done:**
- `vfx-library/` ingest tool (ffmpeg peak, blend and tone analysis, contact sheets, schema, tests).
- The owner's 5 Urban Slideshow overlays ingested and confirmed.
- `OverlayLayer`, peak-aligned and verified on real clips.
- `TransitionStack` with 4 cut types and 14 layer kinds.
- 30 recipes with editorial meanings, each reviewed on a contact sheet.
- A `vfx` block on every StyleProfile.
- The `premium_documentary` style (DOCUMENTED).
- `MediaReveal` moved onto `OverlayLayer` (pixel-identical).

**Next:**
- Ingest the owner's 43 downloaded overlay clips once they are copied to the PC, then add overlay-category recipes (`film_burn`, `lens_flare`, `dust` beds, `graphic_elements` accents) and parameter or direction variants toward **100+**.
- Convert the History Time Travel particle PNG sequences into alpha video (ProRes 4444 or VP9 alpha) and ingest them. `OverlayLayer` already passes `transparent` for clips with alpha.
- Build a sound library that the semantic SFX cues resolve against. The first real asset is `Distortion_Power_Zoom_03.mp3` from History Time Travel.
- Match cut / morph: not built. It needs shot analysis (shape or motion matching), not just a layer.
- Luma-key wipe, where the wipe follows B's own brightness. `soft_wipe` is a linear feathered wipe.
- Glitch "Fast Chromatic" master-control rig from template 1's `.aep`: the `rgb_split` + `glitch_slices` layers cover the look, but not yet the single-slider rig.

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
