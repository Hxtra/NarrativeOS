# Licensed assets — not included

This skill's code (`media_reveal` template) references two files that are
NOT shipped here, because they're paid assets from a purchased
MotionElements/Envato template ("Urban Slideshow"):

- `Leak.mov` — light-leak overlay, no alpha channel, composite via
  `mix-blend-mode: screen`
- `noise.mov` — grain/noise overlay loop, same compositing method

**If you own this template:** drop your own licensed copies of these two
files into this folder, keeping these exact filenames. The code checks for
their presence at render time; it does not bundle them.

**If you don't own this template:** `media_reveal`'s `leakOverlaySrc` /
`noiseOverlaySrc` params are optional — omit them and the template renders
without the overlay compositing (verified in testing: the template degrades
cleanly, it doesn't error).

This boundary is deliberate: NarrativeOS's code is redistributable, your
purchased template assets are your own responsibility, and nothing here
quietly bakes someone else's commercial asset into a shared skill.
