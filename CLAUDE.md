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
- **Specialised agents per job.** Script, editing, image generation and
  music/SFX generation agents, and a separate **bug-fixing/recovery agent**.
  When stage N fails, the failure is classified and handed to the recovery
  agent; the script agent never debugs.
- **Model-agnostic reasoning.** The architecture is: reasoning/Director
  model provider → model abstraction (`scripts/model_provider.py`) →
  Director (`scripts/director_brain.py`). The Director is rule-based by
  default. A reasoning model can be attached (`mode: model_assisted`) to
  propose extra events, which pass the same validators as rule output. No
  model or vendor is assumed. *(Historical: an earlier design used a model
  called JEV as the decision agent; the owner removed it on 2026-09-29.)*
- **AI-generated video stays disabled** by a capability flag until the owner
  turns it on. Image, music, SFX and voice generation go through the job
  state machine in `scripts/generation.py`, and only after a quote plus cost
  and rights gates.
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
  stackable layers), `OverlayLayer` (peak-aligned footage overlays) and 40
  recipes with editorial meanings (10 overlay-footage recipes added Oct 3).
- **Library:** `vfx-library/` holds the ingest tool, schema and tests.
- **Clips:** the local library lives at `~/NarrativeOS-VFX-Library`
  (`C:\Users\openclaw\NarrativeOS-VFX-Library`), outside the repo. It is
  linked into Remotion as `project/public/vfx`, which is gitignored, by
  running `project/scripts/link_vfx_library.py`. It holds 35 confirmed
  clips: the 5 Urban Slideshow overlays plus 30 of the owner's 43 downloads
  (ingested Oct 3, branch `vfx-library-43-overlays`).
  - Rights come from the downloader's per-file records, matched by sha256
    (`ingest --provenance`): 38 Pixabay, 5 CC BY 3.0.
  - Four CC BY light leaks need on-screen credit (`vfx_ingest.py credits`).
  - 13 clips were rejected with reasons: green/blue screen, live-action
    footage, full-frame backgrounds and inserts. They were then deleted by
    the owner's decision (`purge-rejected`); `purged.json` keeps their
    checksums so re-ingest skips them. The table is in `vfx-library/README.md`.
  - The peak search now keeps 0.5 s from clip edges. A white tail frame had
    made one glitch clip's overlay end exactly on the cut.
- **Not yet ingested:** the History Time Travel particle PNG sequences (need
  converting to alpha video).

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

**Effect breakdown (Oct 3, branch `effect-breakdown`).** This is the
feature from the owner's Manus thread: give it a video and get every
transition, effect and synced sound, with timestamps, as recreation
instructions. Manus's own audit showed that only its cut points were
measured; everything else was a model's guess.
`python -m style_intel breakdown <video> --out <dir>` measures instead:
- **Visual events:** cuts, flashes, dips, gradual transitions, frame holds,
  RGB split, zoom, whip pan, blur, glitch tear, halftone, light leak and
  bloom.
- **Sound at each moment:** onset and peak are MEASURED; the class (click,
  impact, whoosh, hit, riser) is INFERRED from envelope and spectrum. Sounds
  that overlap Whisper speech are flagged.
- **Labels:** every event is MEASURED or INFERRED, with its evidence numbers.
  Typography, speed ramps and sound identity are NOT_MEASURED.
- **Moments:** events are grouped into moments (cut plus layers). Each maps to
  the closest registered recipe, with a measured layer stack and a review
  strip; every moment starts UNREVIEWED.
- **Testing:** validated on a synthetic edit with known answers
  (`tests/test_breakdown.py`) and on 4 real videos. The real videos exposed
  traps (piano-key textures, still slideshows, blank text cards), and each
  now has a fix and a regression fixture.
- **Validated on the Manus source video** (the owner's "Documentary Cinema"
  CapCut template, 52 s). It found the cuts, both RGB-split montages, the
  halftone, the leaks, the dissolves and the sound effects. That run is what
  drove band-excess sound detection and flow-based RGB split.
- **On-screen text (Oct 5, PR #9; opt-in with `--text` because it is slow):**
  `style_intel/typography.py` runs RapidOCR locally (PaddleOCR models on
  onnxruntime).
  - Each line of text gets its timing, position, size, colour and case
    (MEASURED).
  - Its in/out animation (type-on, slide, scale, tracking, fade, cut) and
    any RGB split or tear on the text itself are INFERRED.
  - The export's cover frame is labelled as such; the font family is
    NOT_MEASURED.
  - Tests: `tests/test_typography.py`.

**Channel operations (Oct 6, branch `channel-operations`; from the owner's
Rookcast research).** Status table and sources: `references/channel-operations.md`.
- **Profiles:** versioned, outside the repo (`scripts/channel.py`), pinned per
  project by hash.
- **Creative memory:** decisions with reasons; rules only by explicit
  promote from ≥ 2 videos (`scripts/creative_memory.py`).
- **Visible production graph:** `controller.py --graph`, with stale
  detection, pause and revise.
- **Provenance lineage**, a **publish package** with
  `containsSyntheticMedia` taken from provenance, and a **repetition guard**
  against YouTube's inauthentic-content policy.
- **Explicit NO_OP** Director events: restraint is recorded with its
  reasons.
- **YouTube publish:** dry run only. A real upload is BLOCKED until the owner
  sets up OAuth.

**Editorial intelligence (Sep 29; PR #5 started by the Hermes agent,
completed on branch `editorial-intelligence-completion`).** Exact status
tables are in `references/perception-and-rhythm.md` and
`references/generative-media.md`. In short:

- **Music map** (`style_intel/audio.py::temporal_map`). Every event is
  labelled MEASURED (onsets, energy) or INFERRED (beats, tempo, sections,
  phrases, BUILD/IMPACT/BREAKDOWN). A `measurements` table lists what is
  NOT_MEASURED and why: kick, snare, downbeat, meter, chorus and others.
  Thresholds are in `MUSIC_MAP_DEFAULTS`.
- **Director** (`scripts/director_brain.py::plan_edit`). Rule-based, and
  music events can become CUT, REVEAL, HOLD, ANTICIPATE, EMPHASIZE, MOTION,
  TRANSITION or J/L_CUT. A beat is never automatically a cut. Every
  tolerance is in `scripts/editing_config.py`. Transitions are chosen only
  from `allowed_transitions`, which a Style DNA fills with what the
  reference measurably used (`style_intel.shots.transition_vocabulary`,
  then `profile.choose_transitions`). Everything is a proposal: approved
  timelines are never overwritten. MOTION, TRANSITION and J/L are not
  rendered yet.
- **Model abstraction** (`scripts/model_provider.py`). `model_assisted` mode
  takes any command- or callable-based reasoning provider. Its proposals are
  validated, and rejected ones are listed.
- **Perception** (`scripts/perception.py`): the speech map (protected
  pauses, filler and repeat trim candidates), the visual map (cuts plus the
  transition vocabulary, and camera motion), and a rhythm review.
- **Generation** (`scripts/generation.py` + `generation_cli.py`). Image,
  music, SFX and voice jobs go through
  REQUESTED → QUOTED → COST_APPROVED → RIGHTS_APPROVED → READY → GENERATING
  → GENERATED → REGISTERED. Quotes and approvals are hash-bound, and gates
  that don't apply are recorded as not applicable. Video is DISABLED by a
  capability flag. No provider is configured: real generation is BLOCKED
  until the owner picks one.
- **Media semantics** (`scripts/media_semantics.py`, enforced in
  `evidence_links.py`). Generated media is never evidence, whatever it
  depicts.
- **Continuity bible** (`scripts/continuity_bible.py`). Explicit records for
  people, locations, objects and environments. An approved generated image
  becomes the entity's approved reference and is reused automatically by
  later requests.
- **CLIs:**
  - `scripts/director_pipeline.py` (music/speech/visual → review bundle);
  - `scripts/generation_cli.py` (one command per state transition).

**Verified on this PC (Sep 26):** `npm install` and `tsc --noEmit` pass.
`Proof-TitleCard` and `Proof-ArchiveVideo` render correctly. The grain tiles
were missing from the package, so they are now regenerated by
`project/scripts/make_grain.py` (seeded and deterministic).

## Next steps, in order

0. **Grow the VFX library to 100+ transitions.**
   - 40 recipes exist; 60+ more are needed. The library categories with one
     clip each (lens_flare, flicker, film_burn, weather) limit variety.
   - Convert and ingest the History Time Travel particles.
   - Add a sound library for the semantic SFX cues.
   - Register overlay-category and variant recipes. Each one must get a
     contact sheet that someone looks at
     (`project/scripts/transition_contact_sheet.mjs`).
0a. **Effect breakdown follow-ups.**
   - Add a sound-event classifier (e.g. PANNs or CLAP behind
     `model_provider`) for sound identity.
   - Let an optional vision-model review of the strips (via `model_provider`)
     move moments out of UNREVIEWED.
   - Downbeats via Beat This! (MIT); sections via allin1 (verify licence).
0b. **Make editorial proposals renderable and pick providers.**
   - Render the MOTION, TRANSITION and J/L proposals: native audio in
     `render_ffmpeg.py`, and TRANSITION recipes via the Remotion
     `TransitionStack`.
   - The owner chooses image, music, SFX and voice generators, and
     optionally a reasoning provider.
   - A vision model for shot scale, faces, gaze and action.
   - Source separation for drums and vocals, plus downbeat tracking.
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
