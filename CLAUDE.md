# NarrativeOS — context for Claude Code sessions

Read this first. It carries over the state of a long claude.ai web conversation
(Sep 15–25, 2026) in which the video-templates work was built. That
conversation ran in a sandbox with no GitHub write access and a restricted
network, so several items were left "blocked by environment" that this PC can
now finish.

## What this repo is

Two skills live here:

| Path | Skill | Role |
|---|---|---|
| `SKILL.md` (root) | `narrativeos-video-editor` | The evidence-gated production graph: controller, stages, research, claims, timeline IR, FFmpeg render, QA. FFmpeg is the primary renderer. |
| `templates/narrativeos-video-templates/` | `narrativeos-video-templates` | A registry of pre-built Remotion components ("pick a template by name, fill the params, render"), a StyleProfile hub, shared motion primitives, and a rights-aware Media Library. |
| `style_intel/` | (Python package, not a skill) | Style Intelligence: measures a reference video's editing language as Style DNA and turns it into a StyleProfile. See `style_intel/README.md`. |

The templates skill is **not yet wired into the controller pipeline.**
`scripts/build_graphics.py` (the GRAPHICS stage) is still a stub that falls
back to deterministic text overlays. Connecting the template registry to that
stage is a deliberate future decision. Do not wire it in silently.

## Direction (decided by the owner, 2026-09-26)

NarrativeOS becomes **its own standalone system**, not a skill inside
another agent framework. The target is VidRush-style output (topic,
script or voiceover in; finished video out) at Envato-template editing
quality. The full vision is in the owner's
`NarrativeOS_Master_Handoff.md`. It is kept outside this public repo
because it contains personal details; ask the owner for it if needed.
The owner's stated long-term pieces:

- **Its own harness and an enforced workflow**, with stages that must be
  followed in order.
- **Specialised agents per job.** A decision agent (JEV), script, editing,
  image generation and video generation agents, and a separate
  **bug-fixing/recovery agent**. When stage N fails, the failure is
  classified and handed to the recovery agent; the script agent never
  debugs.
- **Many styles, including a "Netflix documentary" style.** It exists as
  `premium_documentary`.
- **Reference-style copying.** Give it a video or link and it adapts its
  editing language (pacing, transitions, typography) without breaking the
  system. Later, it should edit any kind of video, not only documentaries.
- **Its own AI-native editor/compositor.** An After Effects-level editor
  that models fully understand, eventually replacing borrowed renderers
  like Remotion.
- **A control skill for external agents** (Claude Code, Codex, Hermes),
  similar to how claude-in-chrome controls Chrome. Keep registries
  JSON-describable so a future `narrativeos` CLI or API can list and apply
  them.
- **An editing knowledge base** built from YouTube editing tutorials and
  real edits (the case library).

**NarrativeOS is general-purpose (decided 2026-09-28).** It is not only a
documentary tool: news, gaming, podcast clips, travel, short-form social and
more are production profiles on the same engine. Documentary is the first
profile. Give it a reference video and it measures the editing language
(`style_intel/`) instead of an LLM guessing at it. The owner asked for the
system only: **do not generate or copy any style yet**. The references tried
so far were not good ones, so `src/styles/generated/` stays empty until the
owner picks a reference.

The current priority is the **VFX/transition library**: 100+ reusable,
layerable transitions. This phase is under way; see "Current state".

Before touching anything under `templates/`, read
`templates/narrativeos-video-templates/SKILL.md`, then its `references/`
(`architecture.md`, `roadmap.md`, `archive-video-hardening.md`) and
`media-library/README.md`.

## The goal (in the owner's words, condensed)

Build a documentary video maker whose motion design and editing reach
**Envato professional-template level**, and that does not produce AI slop.
Specifically:

- **Ready-made templates, not generated per video.** VidRush hires Remotion
  developers to build templates. NarrativeOS does the same, except Claude
  designs and builds every template. No developer will be hired. At render
  time the system picks a template, swaps in the real image or video and
  text, and renders.
- **Templates must differ per documentary style.** DW, true crime, mystery,
  educational and others must not share one recolored title card.
  `StyleProfile.layouts` exists for this, so a style changes structure, not
  just palette.
- **Editing is more than motion design.** J-cuts, L-cuts, SFX choice, when to
  glitch, which transition to use. The decision layer should be built from
  real precedent (a case library), not from an LLM guessing cold.
- **Everything built goes into the skill on GitHub.**

## Working principles established in that conversation (keep them)

- **Evidence over assertion.** A template is not done until a rendered frame
  has been looked at. Typechecking does not count. Audio claims were verified
  with measured dB. A guard was not called working until it had been seen to
  throw.
- **Status honesty.** Use DOCUMENTED, IMPLEMENTED, BLOCKED and VALIDATED. Do
  not turn "metadata is reachable" into "ingestion works". Keep these five
  things separate: provider availability, API availability, metadata
  availability, media-byte availability, and rights verification.
- **Don't invent genre layouts or facts.** Genre-specific StyleProfiles (DW,
  true crime and so on) stay blocked until real evidence exists: case-library
  entries or `.aep` extraction. Pack 4 (statistics, maps, timelines,
  documents) must use real, cited data in its proof renders. No
  plausible-sounding numbers.
- **Primitives vs. editorial treatments.** Primitives return styles and render
  nothing (`useKenBurns`, `containFit`, `useDoubleExposure`,
  `useArchiveFlicker`, `formatAttribution`, `useOrganicWeave`, audio policy,
  watermark guard). Treatments compose primitives. Once a second consumer
  needs inlined logic, extract it into a primitive. Don't let `ArchiveVideo`
  grow into a god-component.
- **Regression checks:** cross-process pixel diffs are noisy (about 1%
  Chromium decode nondeterminism was observed). The reliable check is
  same-session self-consistency (render twice, diff equals 0) plus logical
  comparison of the old and new code.
- **Rights:** never commit licensed or paid assets. That covers Envato and
  MotionElements overlays such as `Leak.mov` and `noise.mov`, and the `.aep`
  files. Never commit media without a verified rights record.
  `cockatoo_test.mp4` is an engineering fixture only and has no rights
  statement. `.gitignore` excludes `*.mp4`/`*.mov` for this reason.
- Media Library pipeline:
  `SEARCHED → CANDIDATE → RIGHTS_VERIFIED → DOWNLOADABLE → BYTE_VERIFIED → REGISTERED`.
  Internet Archive requires a per-item `licenseurl` check. The search filter
  alone is never enough.

## Current state (as of Sep 26, 2026)

**11 editorial components.** These are `title_card` (2 layouts),
`chapter_break`, `credits_roll`, `subscribe_cta`, `media_reveal`,
`speaker_lower_third` (first appearance and returning variants),
`location_stamp`, `interview_frame`, `archive_video` (hardened: probed fps,
audio policy preserve/mute/duck/replace, watermark-state guard) and
`double_exposure_portrait`.

**Other pieces:** 8 shared primitives, 2 StyleProfiles
(`documentary_general`, `documentary_broadcast_grid`), a registry, and
`MultiLayerPlayer` for stacking templates.

**Media Library:**

- 2 byte-backed public-domain NASA images (Eileen Collins portrait, Hubble
  deep field).
- 1 metadata-only Wikimedia record (Alice Paul, 1915). Bytes were never
  fetched.
- 1 Internet Archive record, `ia_1957-10-07_new_moon` (a 1957 Universal
  Newsreel about Sputnik, public domain, 4:3). It stopped at `DOWNLOADABLE`
  only because of the old sandbox.
- 1 engineering fixture.

**Transitions and VFX (added Sep 26, branch `vfx-transition-system`):**

- **Code:** `project/src/vfx/` contains `TransitionStack` (cut types plus
  stackable layers), `OverlayLayer` (peak-aligned footage overlays) and 30
  recipes with editorial meanings.
- **Library:** `vfx-library/` holds the ingest tool, schema and tests.
- **Clips:** the local library lives at `~/NarrativeOS-VFX-Library`
  (`C:\Users\openclaw\NarrativeOS-VFX-Library`), outside the repo. It is
  linked into Remotion as `project/public/vfx`, which is gitignored, by
  running `project/scripts/link_vfx_library.py`. It currently holds the 5
  Urban Slideshow overlays, all confirmed.
- **Not yet ingested:** the owner's 43 downloaded overlays (still on their
  phone) and the History Time Travel particle PNG sequences (need converting
  to alpha video).

**Style Intelligence (added Sep 28, branch `style-intelligence`):**
`python -m style_intel analyze <video> --out <dir>` writes Style DNA. It
measures:
- hard cuts plus gradual transitions (classified as light, dark or dissolve);
- shot lengths, flashes and dips;
- beat sync, with a significance test;
- colour and duotone, grain and camera motion;
- tempo and loudness;
- speech pace (via Whisper).

Typography is not measured yet; it needs OCR, which is the next addition.
`python -m style_intel profile ... --id x` writes a typed StyleProfile that
`STYLE_REGISTRY` loads. It only enables transitions the reference provably
used. Tests: `tests/test_style_intel.py` (synthetic videos with known
answers).

**Verified on this PC (Sep 26):** `npm install` and `tsc --noEmit` pass.
`Proof-TitleCard` and `Proof-ArchiveVideo` render correctly. The grain tiles
were missing from the package, so they are now regenerated by
`project/scripts/make_grain.py` (seeded and deterministic).

## Next steps, in order

0. **Grow the VFX library to 100+ transitions.**
   - Ingest the owner's 43 overlay clips once they are copied over, with
     `vfx-library/tools/vfx_ingest.py`. Review each contact sheet before
     confirming it.
   - Convert and ingest the History Time Travel particles.
   - Add a sound library for the semantic SFX cues.
   - Register overlay-category and variant recipes. Each one must get a
     contact sheet that someone looks at
     (`project/scripts/transition_contact_sheet.mjs`).
1. **Finish the Internet Archive asset end-to-end.** This was the gate the
   owner set before Pack 4. The owner's rule was: "don't move to Pack 4 until
   this IA asset goes all the way through". This PC has normal network
   access, so run `media-library/tools/internet_archive_adapter.py` against
   `1957-10-07_New_Moon`. Take it through BYTE_VERIFIED, run `probe_asset.py`,
   then REGISTERED, then render it through `archive_video`. Do not commit
   the downloaded video itself (it is gitignored). Commit the updated
   metadata record.
2. **Pack 4: Evidence & Information.** Start with the evidence/document card,
   built against a real public-domain document. Then build the map flyover,
   the data-viz reveal, the cold-statistic reveal, the timeline bar and the
   redacted stamp. The timeline bar has a visual reference: a Space Race
   1957–1975 style with cyan node dots, yellow year labels and dashed leader
   lines to italic event labels. Every number, date and place must be real
   and cited.
3. **Pack 5: Transitions.** Port the light-leak/film-burn effect as a shared
   primitive (4 variants existed in the earlier one-off Remotion slideshow
   project). Then build glitch/RGB-split (precedent: the "Fast Chromatic"
   master-control rig found in template 1's `.aep`), whip-pan (precedent: the
   Handy Seamless Transitions catalog: Warp Spin, Cam Fgt, Warp Side Roll plus
   directions), match-cut/morph, and a halftone-to-color reveal. Hard cut plus
   sound sting belongs in the case library, not in Remotion.
4. **Pack 6:** quote/testimonial card, per-style kinetic captions, news ticker.
5. **Pack 7:** audio-reactive waveform and beat flash.
6. **Pack 3 remainder:**
   - Parallax/depth reveal. This is blocked on a preprocessing stage:
     segmentation with rembg or SAM, a depth estimate with Depth-Anything v2
     or MiDaS, then layer plates. Never fake parallax from a flat image.
   - A dust/scratch primitive.
   - Watermark detection. Only the explicit-state guard exists today.
7. **Media Library:**
   - Wikimedia byte ingestion. The old sandbox was blocked as "cache-only";
     this PC should reach it.
   - Retest the NASA images API. It returned HTTP 400 in the old sandbox.
   - Automated visual tagging at ingestion.
8. **Editing decision layer:**
   - A case library under `style/case_library/<style>.jsonl`: annotated real
     decisions with style, beat role, intent, operation, timing and source.
   - Measurement tools that extract data from real footage: PySceneDetect
     for cuts, audio/video cross-correlation for J/L-cut offsets, fitting
     easing curves.
   - Citation repair of the Manus research batch (8 sources, 30 cases). One
     DW title was wrong.
9. **`.aep` reverse-engineering:** map the `tdb4` keyframe/easing chunk (124
   bytes per record, layout unknown) to lift real motion curves. Build a
   reusable extractor and write
   `references/aep-template-grammar.md`.
10. **SFX sourcing** against the sound-design spec: glitch ticks, whooshes,
    impacts, forest/water ambience, cinematic swells. Named leads: Rockot "My
    Breakbeats", Analog Glitch, Galactic Swoosh. Recipe for a JFK-style
    archival voice: echo, then normalize to 0 dB.

## Findings from the `.aep` reverse-engineering (the basis of the architecture)

Two purchased templates were studied: *History Time Travel* and *Urban
Slideshow*. Both had these traits:

- **A comp pipeline.** The edit, the look and the final composite live in
  separate chained comps (`01.Edits → 01.DISTORTION → 02.Final`).
- **A central hub.** A "Color" comp controls every color, and the other
  layers read it through expressions. StyleProfile is the code equivalent.
- **Expression-driven toggles.** A checkbox drives opacity between 0 and 100
  instead of turning layer visibility on and off.
- **A shared jitter rig.** A `wiggle()` on one Null, driven by a slider,
  with everything parented to it. `useOrganicWeave` is the code equivalent.
- **Stock overlays blended in Screen mode.** Grain, dust and light leaks are
  stock video overlays composited with Screen blend, not hand-animated.
- **Text slots named `Text_NN` with paired comps.** Lorem Ipsum is not a
  reliable marker for text slots.

## Things that are NOT in this repo

These are on the owner's machine or in the old conversation only:

- The purchased `.aep` templates and their overlay assets. These are licensed
  and must never be committed. See
  `project/public/licensed/urban-slideshow/README.md` for where to place them
  locally.
- The earlier one-off projects: `documentary-slideshow` (Remotion, 14 shots,
  103 s, about 2.1 fps render) and the HyperFrames port (about 1.25 fps; plain
  HTML with GSAP, good `lint`/`snapshot` QA loop).
- The Manus editing-research zip, the AE effect-breakdown document and the
  Lilly's Tech Tips archive-clips tutorial notes (`youtu.be/lLK2JBPC93I`).

## Environment notes (this PC)

- Windows 11, Node 25, Python 3.13 (Pillow, numpy), Git Bash, and the `gh`
  CLI logged in as `Hxtra`. Use `gh` for pushes, and never put tokens in
  remote URLs or files.
- Render a still with:
  `cd templates/narrativeos-video-templates/project && npx remotion still src/index.ts <CompositionId> out.png --frame=N`
- Remotion composition IDs cannot contain underscores. Registry template IDs
  can.
- Rendering is CPU-only and slow. Develop at 1080p with stills, and render
  full videos in chunks.
