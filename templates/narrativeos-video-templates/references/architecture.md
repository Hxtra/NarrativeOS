# Architecture

## Why a style-hub instead of per-template styling

Reverse-engineering two real purchased Envato/MotionElements `.aep` templates
(a "History Time Travel Slideshow" and an "Urban Slideshow") found the same
pattern in both, built by unrelated designers:

- **A numbered comp pipeline**, not a flat timeline: an "Edit" comp feeds a
  "Distortion"/effects comp feeds a "Final" comp. Cut, look, and composite
  are three separate passes.
- **A central hub layer for global parameters**, referenced everywhere via
  expressions — e.g. `comp("Color").layer("Color").effect("Bg Color")(...)`.
  Every color-bearing effect across the whole project routed through one
  "Color" comp, not graded per-layer.
- **Checkbox-driven toggles as opacity expressions**, not layer
  visibility: `if (effect("Leak On//Off")(...) == 1) 100 else 0`.
- **A shared organic-motion rig**: one Null object's position had
  `wiggle(30, slider, position[1])` applied via expression; other layers
  parented to that Null so the jitter propagated automatically. This is the
  direct real-world precedent for `useOrganicWeave()` /
  `project/src/motion/organicMotion.ts` — that file isn't a guess at what
  might look good, it's a code-equivalent of a confirmed real technique.
- **Every layer carries the same boilerplate property groups** (full
  Layer Styles: drop shadow, inner/outer glow, bevel/emboss, gradient/
  pattern fill; 3D extrusion/material/camera groups) whether used or not.
  This is an `.aep`-format fact, not a design choice — not directly
  relevant to the Remotion side, but relevant if NarrativeOS ever needs to
  *generate* `.aep` files rather than just parse them.
- **Real authored parameters are round numbers.** Decoding the binary
  `tduM`/`cdat` chunks as big-endian IEEE-754 doubles across both files:
  ~98-99.8% landed on clean values (100, 200, 90, 360, 10, 1000) — i.e.
  percentages, degrees, durations a human actually typed in. This is
  mentioned here because it's a sanity check worth reusing: if a future
  extraction pass on a new `.aep` produces mostly non-round floats, that's
  a signal the byte-offset assumptions are wrong, not that the template
  author used unusual values.

`StyleProfile` (`project/src/styles/StyleProfile.ts`) is deliberately built
as this project's equivalent of that central hub: one object holding grade,
typography, motion defaults, vignette/grain strength, and the allowed
transition set for a style. Every template reads from it; none hardcode
their own.

## Structure is part of style, not just surface (correction made mid-build)

The first version of this architecture only let `StyleProfile` change
colors, fonts, and motion amounts — every style rendered the exact same
composition, just recolored. That's a real gap: a genuine broadcast-graphic
convention and a centered classic title card aren't the same layout with
different paint, they put different things on screen in different places.

The fix: `StyleProfile.layouts: Record<templateId, layoutVariantName>`.
A template component defines its known layout variants as sibling
components and switches on `style.layouts?.[templateId] ?? 'default'`.
`title_card` has two real ones right now — `centered-classic` and
`corner-frame-broadcast` — proven to actually render differently (checked
by eye, not just typechecked).

**The rule going forward, and it's the same rule that already governs
`STYLE_REGISTRY` itself:** a new layout variant needs a defensible
structural basis before it gets added — a confirmed convention from the
`.aep` reverse-engineering, the case-library work once it has real depth,
or well-established generic design convention (like broadcast graphics
being asymmetric/corner-anchored, which `corner-frame-broadcast` is
grounded in). Do not add a `true_crime` layout variant because it feels
like true crime would look a certain way — that's the exact "illuminate
and guess" failure mode this whole project exists to avoid, just moved
from color values to layout structure. The infrastructure is ready the
moment real evidence exists; it should sit unused until then, the same way
`STYLE_REGISTRY` sat with one entry for most of this build.

## What's still unresolved from the `.aep` reverse-engineering

The `tdb4` chunk (124-byte fixed records, clearly structured, not yet
field-mapped) almost certainly holds real keyframe/easing data — the actual
bezier handle values a designer set on a keyframe. This would be the
highest-value thing to crack next if motion curves ever need to be
extracted from a real template rather than authored by hand, but it hasn't
been done yet. Two real files' worth of raw chunks are the starting point if
someone picks this up — don't start over from a fresh `.aep`.

## Why style-specific profiles (DW, true crime, mystery...) aren't populated yet

Populating `STYLE_REGISTRY` with a `dw_documentary` or `true_crime` profile
right now would mean guessing grade/typography/pacing numbers and dressing
them in a style name — exactly the "illuminate and guess" failure mode this
whole project is trying to avoid. Those profiles should be populated from
real evidence: either the case-library extraction work (real finished
videos, annotated cut-by-cut) or further `.aep` reverse-engineering on
style-specific purchased templates. Don't add a named style profile without
a cited source for its specific values.

## Shared primitives — what exists, so it isn't reimplemented per-template

- `project/src/motion/organicMotion.ts` — `useOrganicWeave()` (whole-frame
  jitter + exposure flicker, deterministic seeded hash, no `Math.random`)
  and `useWiggle()` (single-property wiggle, for anything narrower than
  the whole frame).
- `project/src/motion/FilmTexture.tsx` — `Grain`, `Vignette`, `Grade`.
  All three read every visual parameter from `StyleProfile`.
- `project/src/typography/Typography.tsx` — `SplitText` (per-character
  staggered reveal, in and optionally out), `Rule` (width-wipe divider),
  `Kicker`, `Caption`.

Determinism matters here the same way it mattered in the HyperFrames build
earlier in this project's history: every one of these uses a seeded hash
keyed on frame number, never `Math.random()`, `Date.now()`, or
`requestAnimationFrame` as a source of truth — so a render is frame-exact
and reproducible.
