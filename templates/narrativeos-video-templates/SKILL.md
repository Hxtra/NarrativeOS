---
name: narrativeos-video-templates
description: Renders documentary video segments (title cards, chapter breaks, credits rolls, subscribe CTAs, and more as they're added) from a registry of pre-built Remotion components, driven by a style profile and a params object — not generated from scratch per video. Use this whenever NarrativeOS needs to render a motion-design segment for a documentary video, whenever the user asks to add a new template to the library, or whenever the user asks about the template registry, style profiles, or how a specific template's parameters work. Always consult this skill before writing new motion-design/Remotion code for NarrativeOS — check the registry first, since a template may already exist for what's being asked.
---

# NarrativeOS Video Templates

A registry of reusable Remotion components for documentary-style video segments. The point of this skill is that NarrativeOS's render stage should **look up a template by name and fill in parameters** — never ask an LLM to write new motion-design code per video. That only works if the registry is checked first and extended deliberately, so **always read this file's current template manifest before assuming a template doesn't exist or writing a new one from scratch.**

## Architecture, in one paragraph

Every template is a React component that takes exactly two props: `style: StyleProfile` and `params: <TemplateSpecificParams>`. It never hardcodes a color, font, grain amount, or jitter amount — those all come from the `StyleProfile` (`project/src/styles/StyleProfile.ts`), which is the single hub every template reads from. This mirrors a real pattern found by reverse-engineering two purchased Envato/MotionElements `.aep` templates: both routed every color-bearing effect through one central "Color" comp via expressions, rather than grading each layer independently. `StyleProfile` is the code-equivalent of that hub. Templates are registered by calling `registerTemplate()` once at module load, and resolved at render time with `resolveTemplate(id)` — see `project/src/registry/registry.ts`.

**Style is structure, not just palette.** `StyleProfile.layouts` (a `Record<templateId, layoutVariantName>`) lets a style select a genuinely different composition for a given template, not just different colors on the same one. `title_card` currently has two real layouts: `centered-classic` (symmetric, corner brackets) and `corner-frame-broadcast` (asymmetric, bottom-left anchored, vertical accent rule, standard broadcast-graphic convention). See `references/architecture.md` for why this exists and the rule for adding more variants — every new layout needs a defensible structural basis, not a guess at what a specific genre "feels like."

## When to use this skill

- Rendering any documentary video segment for NarrativeOS — check `## Template manifest` below for what already exists before writing anything.
- Adding a new template to the library — follow `## How to add a new template` exactly; do not build a one-off component outside the registry.
- Anything involving `StyleProfile`, the shared motion/typography/texture primitives, or how a specific template's params work — read `references/architecture.md` for the full technical detail before making changes.
- The user mentions Envato-level documentary quality, motion design templates, "pick and fill the placeholder," or asks what templates are available.

## Template manifest (current)

| id | pack | what it is | params |
|---|---|---|---|
| `title_card` | core | Main title / show-open | `{kicker?, headline, sub?}` |
| `chapter_break` | core | Chapter/section interstitial (RESET/BUILD beat — slower, heavier motion than title_card, not a re-skin) | `{eyebrow, title}` |
| `credits_roll` | core | Scrolling end credits | `{title, rows: {role, name}[], scrollSpeedPxPerSec?}` |
| `subscribe_cta` | core | Subscribe/CTA end card | `{channelName, ctaLine?}` |
| `media_reveal` | archive | Media slot (photo/video) + text slot, with real licensed overlay compositing (light leak, grain) — see `media-library/` and `project/public/licensed/*/README.md` before using the overlay params | `{mediaSrc, mediaType, kenBurns?, kicker?, caption?, leakOverlaySrc?, noiseOverlaySrc?}` |
| `speaker_lower_third` | speaker | Speaker ID, with a genuinely distinct returning-speaker variant (smaller tag, no role, no bar-wipe) — not a faster replay of the first-appearance animation | `{name, role?, isReturning?}` |
| `location_stamp` | speaker | Location/date super — top-left anchored, deliberately distinct position and scale from `speaker_lower_third` so both can be on screen at once | `{location?, date?}` |
| `interview_frame` | speaker | Frame/set treatment for interview footage — consistent border/vignette/grade across disparate real sources, handles aspect-ratio mismatch by pillarboxing/letterboxing rather than cropping or stretching | `{mediaSrc, mediaType, sourceAspectRatio?}` |
| `archive_video` | archive | Normalizes heterogeneous real sources: aspect ratio, grade/grain/vignette, real on-screen attribution, explicit source-fps surfacing (probed, never guessed), explicit audio policy (preserve/mute/duck/replace — safe default is mute), and an enforced watermark-state guard that refuses to render unsafe combinations. See `references/archive-video-hardening.md` for what's verified vs. still deferred (frame rate itself needs no correction — Remotion syncs by real time already, confirmed from their own docs; audio-only normalization and watermark removal are explicitly not implemented, only made explicit) | `{mediaSrc, mediaType, sourceAspectRatio?, kenBurns?, attribution?, technicalProfile?, audioPolicy?, watermarkPolicy?, flickerAmount?, showTechnicalDebug?}` |
| `double_exposure_portrait` | archive | Primary portrait + secondary contextual image, composited via the `useDoubleExposure` primitive — proven with two distinct real Media Library records (NASA astronaut portrait + NASA/Hubble deep field), each with its own independent attribution line | `{primaryMediaSrc, primaryMediaType, secondaryMediaSrc, secondaryMediaType, doubleExposure?, kenBurns?, primaryAttribution?, secondaryAttribution?}` |

**Primitives vs. editorial treatments — the actual architectural split, keep protecting it:**
```
Primitives (return styles only, never render anything themselves)
├── useKenBurns        — motion/kenBurns.ts
├── containFit         — motion/mediaFit.ts
├── useDoubleExposure   — motion/doubleExposure.ts
├── Grade/Vignette/Grain — motion/FilmTexture.tsx
└── formatAttribution   — motion/attribution.ts

Editorial treatments (compose primitives, own layout/registration)
├── archive_video
├── double_exposure_portrait
├── media_reveal
└── interview_frame

StyleProfile decides how those primitives behave — a future
style-specific profile changes grade/motion/layout without any
editorial treatment's code changing.
```
Three primitives now have a real track record of being extracted mid-build
once a second consumer needed them (`useKenBurns`, `containFit`,
`ArchiveAttribution`, `useArchiveFlicker`) — each checked for regression
before being trusted. **The verification method matters, and got refined
mid-build:** an initial refactor check showed a false-positive diff
(mean ~2.5/255) attributed to Remotion's bundle cache; clearing
`node_modules/.remotion` made it go away that one time. A second,
unrelated refactor produced the *identical* diff magnitude even with that
cache cleared beforehand — meaning the cache explanation was too narrow.
The actual cause: this environment's headless Chromium has small (~1%
average pixel value) cross-process image scaling/decoding nondeterminism,
unrelated to code logic. **The reliable check is same-session
self-consistency** — render the current code twice in immediate
succession and diff those (always 0 in every test run here) — combined
with direct logical comparison of old vs. new code (same math, same
random seed strings). A before/after diff captured across two separate
`npx remotion still` invocations is not a reliable regression signal in
this environment; don't trust it alone.

**Shared motion primitives** (use these, don't reimplement per-template):
`project/src/motion/kenBurns.ts` (`useKenBurns`) and
`project/src/motion/mediaFit.ts` (`containFit`) — both were originally
inlined inside one template each (`media_reveal`, `interview_frame`
respectively) and were extracted once a second template needed the same
logic. Both refactors were verified pixel-identical before/after
(`mean diff: 0.0`) before being trusted — that's the bar for any future
extraction too, not just a typecheck pass.

**Layering multiple templates in one frame:** use `MultiLayerPlayer` (`project/src/TemplatePlayer.tsx`), not `TemplatePlayer` — it takes a `layers: LayerSpec[]` array and stacks them. This is how `interview_frame` + `location_stamp` + `speaker_lower_third` actually coexist on screen (see `Proof-InterviewCombined` in `Root.tsx`). A real render will almost always need this, not a single template in isolation.

## Transitions & VFX (`project/src/vfx/`, library in `vfx-library/`)

A transition is **data**: a cut type plus a stack of layers, registered by
name in `vfx/recipes.ts`. New transitions are new combinations, not new code.
Check `listTransitions()` before writing any transition or effect code.

- **Cut types:** `hard`, `crossfade`, `soft_wipe`, `halftone`.
- **Media layers** modify the shots: `zoom_punch`, `whip_pan` (A and B travel as one strip), `directional_blur`, `blur`, `rgb_split`, `glitch_slices`, `shake`, `flicker`, `stutter`, `desaturate`.
- **Overlay layers** composite on top: `overlay` (a real footage clip from the VFX library), `flash`, `dip`, `film_burn` (procedural).
- **SFX cues** (`whoosh`, `impact`, `shutter`, `glitch_tick`...) are semantic. They play only when `sfxSources` maps them to files, which is waiting on a sound library.
- **`OverlayLayer`** is the one component for every footage overlay. It uses a Screen/Add/Overlay blend, stays muted, and applies the style tint. It is **peak-aligned**: the clip's brightest frame, measured at ingest, lands on the cut. This has been verified on real clips with `scripts/verify_peak_alignment.mjs`, including a 25 fps clip on the 30 fps timeline. `MediaReveal` uses it too; that refactor was verified pixel-identical in a same-session A/B.
- Overlay layers select clips **by category, preferred tone and preferred blend, never by filename** (`{category: 'scratches', blend: 'screen'}` picks scratches that read on dark pictures). A layer's own `blend` overrides the clip's (CRT static uses `normal` for a short burst). They only use confirmed library clips. If none exists, they render their procedural `fallback`, so every recipe renders out of the box. When the requested tone is the opposite of the clip's (warm↔cool), the clip is hue-rotated 180°.
- **Grade the shots, not the stack.** Leaks, burns and RGB fringes sit above the grade, the same as in an editor.
- Each recipe carries an editorial `meaning`, and each `StyleProfile.vfx.allowedTransitions` lists what that style may use. Most cuts should stay `hard_cut`.

**40 recipes (all rendered and reviewed on contact sheets):**

| intensity | recipes |
|---|---|
| clean | `hard_cut`, `crossfade_soft`, `dip_to_black` |
| subtle | `dip_to_white`, `blur_dissolve`, `push_in_cut`, `exposure_bump`, `memory_fade`, `archive_flicker_cut`, `soft_wipe_left`, `soft_wipe_up`, `archive_scratch_cut`, `dust_drift_dissolve`, `snowfall_passage` |
| medium | `flash_cut`, `light_leak_warm`, `light_leak_cool`, `leak_crossfade`, `rgb_split_hit`, `stutter_cut`, `halftone_reveal`, `lens_flare_sweep`, `particle_shimmer_reveal`, `projector_flicker_cut`, `film_damage_dip` |
| bold | `leak_flash_combo`, `film_burn_passage`, `film_burn_procedural`, `whip_zoom`, `whip_pan_left`, `whip_pan_right`, `whip_pan_up`, `impact_cut`, `shake_impact`, `glitch_cut`, `glitch_reveal`, `digital_tear`, `glitch_overlay_cut`, `vhs_static_cut`, `leak_whip` |

**QA:**
- `node scripts/transition_contact_sheet.mjs [--style id] [--only substr]` writes 8 frames per recipe to `out/contact-sheets/`. Look at them; a typecheck is not enough.
- `node scripts/verify_peak_alignment.mjs --recipe light_leak_warm --asset <id>` checks where the clip's brightest frame lands relative to the cut.

**Growing to 100+:**
- Ingest more clips; overlay recipes pick them up automatically, by category. Library categories: light_leak, film_burn, flash, lens_flare, dust, grain, scratches, glitch, smoke, bokeh, particles, texture, graphic_elements, weather, flicker, crt.
- Register variants: new layer stacks, parameters, or directions.
- Each new recipe needs a contact sheet that someone has looked at.

## Media Library (M2 — see `media-library/README.md`)

Four assets now exist: two byte-backed verified NASA photos, one
metadata-only Wikimedia photo (bytes blocked, see below), and one
Internet Archive video whose rights and availability are fully verified
but whose bytes couldn't be pulled into *this* sandbox specifically (see
`tools/internet_archive_adapter.py` and `media-library/README.md`'s
Internet Archive section — the reason is precise: this sandbox's
`bash_tool` network egress explicitly refuses `archive.org`, confirmed
via the proxy's own `x-deny-reason: host_not_allowed`, not any defect in
the source or the adapter). NASA's documented search API separately
returned HTTP 400 on every tested query shape. Read `media-library/README.md`
in full before building another adapter — it defines the ingestion
pipeline (fetch → verify rights → auto-tag → store), the source risk
tiers (NASA/Wikimedia/Internet Archive are all tractable on rights;
Internet Archive specifically needs per-item checking, never a blanket
source-level policy — the adapter enforces this by refusing to advance
an item past `CANDIDATE` without its own explicit `licenseurl`), and the
three-way fallback policy (exact match / category match / no silent
substitution) that the original design was missing.

Everything else in the brief (lower thirds, archive/parallax treatment, evidence cards, transitions, quote cards, audio-reactive) is **not yet built** — see `references/roadmap.md` for the full remaining list, organized by pack, so the next session picks up from here instead of re-deriving the list.

Style profiles registered: `documentary_general` (centered-classic title layout), `documentary_broadcast_grid` (corner-frame-broadcast title layout — proves the layout-branching mechanism works, not a claim about any specific documentary genre), and `premium_documentary` (the streaming-documentary / "Netflix doc" feel, named generically — `minimal-sans` title layout in Inter, colour grade, minimal VFX density; status `DOCUMENTED`, built from the owner's reference analysis in section 42 of the master handoff, not yet checked against real references). Every profile now has a `vfx` block (density, allowed transitions, overlay opacity scale, tint). Style-specific profiles actually named for a genre (DW, true crime, mystery, educational...) — both their surface values AND their structural layouts — should be populated from real evidence (the case-library work / `.aep` reverse-engineering), not guessed — see `references/architecture.md` for why.

## How to render a template right now

```bash
cd project
npx remotion still <CompositionId> out.png --frame=<N> \
  --browser-executable=<path-to-chromium>
```

Or programmatically, the actual "pick and fill" call:
```tsx
import {resolveTemplate} from './registry/registry';
import {getStyle} from './styles/StyleProfile';
const def = resolveTemplate('title_card');
const style = getStyle('documentary_general');
// <def.component style={style} params={{headline: '...'}} />
```

## How to add a new template

1. Check the manifest above first — don't duplicate.
2. Create `project/src/templates/<Name>.tsx`. Define a `<Name>Params` interface.
3. The component signature must be `({style, params}: {style: StyleProfile; params: <Name>Params}) => JSX`.
4. Pull texture/typography/motion from the shared primitives (`project/src/motion/FilmTexture.tsx`, `project/src/typography/Typography.tsx`, `project/src/motion/organicMotion.ts`) — do not reimplement grain, vignette, grade, or jitter per-template.
5. Call `registerTemplate<Name Params>({id, label, pack, durationInFrames, component, defaultParams})` at module scope.
6. Import the file for its side effect in `project/src/TemplatePlayer.tsx`.
7. Add a `<Composition>` entry in `project/src/Root.tsx` with non-default params, and render a still to actually verify it — a template isn't done until a rendered frame has been looked at, not just typechecked.
8. Update the manifest table in this file.

Read `references/architecture.md` before adding a template that needs something the shared primitives don't yet cover (a new transition type, a new texture) — extend the shared primitive, don't fork it per-template.

## Known constraints

- Remotion composition IDs may only contain `a-z A-Z 0-9 -` (no underscores) — template `id` values (used as registry keys, not composition IDs) can use underscores, but any `<Composition id=...>` in `Root.tsx` cannot.
- Grain tiles (`project/public/grain/grain0-7.png`, read by `FilmTexture.tsx`) are generated by `python project/scripts/make_grain.py` (seeded, deterministic). Without them the grain layer 404s silently and renders nothing.
- Fonts are vendored locally (`project/public/fonts/`) and loaded via `delayRender`, not Google Fonts — this environment has no reliable path to fonts.googleapis.com at render time in some sandboxes; keep it this way for portability.
- Chromium must be pointed at explicitly via `--browser-executable` in sandboxed environments where the default download is blocked (`HYPERFRAMES_BROWSER_PATH`-style issue, same root cause, different tool).
