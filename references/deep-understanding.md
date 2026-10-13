# Deep understanding: watching a video well enough to remake it

Status: **PLAN** (Oct 13, 2026). Research notes and the design for the owner's request: "watch and understand the
video for real, not generic analysis or random OCR, well enough to remake the exact same thing." The first target
is the owner's reference `6cbda51b-...mp4` (76 s, 16:9, 1276x718, 29.97 fps).

## What "understood" has to mean

A description can sound right and still be wrong; the Manus breakdown and our own first alpine analysis both did
that. So the test of understanding here is **reproduction**: the video is understood when a project built only
from the analysis renders frames that match the reference, shot by shot, measured. This is analysis-by-synthesis,
the same loop recent inverse-graphics agents use (write a program, render it, compare with the target, revise):
4DCodeBench (arXiv 2610.03715) for dynamic scenes, VIGA (arXiv 2601.11109), and staged reconstruction with a
verifier in "Thinking in Blender" (arXiv 2606.02580). None of them targets edited video and motion graphics; that
is the part we build.

Every claim keeps its label: MEASURED (a tool computed it), OBSERVED (a model or a person saw it) or VERIFIED
(a re-render containing it matched the reference). Only VERIFIED is "understood".

## What the first look at this reference shows (OBSERVED, 60 sampled shots)

- Archive and news footage of one person, stock/3D renders, AI-looking illustrations.
- Layers: picture-in-picture insets, retro TV-set frames with footage on the screen, multi-panel collages,
  broadcast lower-thirds kept from the source (Bloomberg, CNBC).
- Text: 1-3 words at a time, centred, white, a small italic serif mixed with a bold sans ("has **enough**").
- Look: dark (luma 0.37), low saturation (0.28), grain, glow; a light-flare ending.
- MEASURED by Style DNA: 111 shots in 76 s (median 0.53 s), 16 flash frames, 0 dissolves, voice 207 words/min
  over 94 % of the runtime, cuts not on the beat (p = 0.42).
- Trap: faces are on screen most of the time, but the narrator never appears. Face share alone would call this a
  talking head; it needs an active-speaker check (lips moving with the voice).

## The pipeline

### 1. Cut list, frame-exact (MEASURED)
- Shot boundaries: TransNetV2 or AutoShot (AutoShot reports +1-4 F1 over TransNetV2, arXiv 2304.06116), checked
  against our scdet cuts; disagreements go to the watcher. Flash frames and dips are kept as their own events.
- Each shot gets a dense strip (every frame for short shots, 6-10 fps for long ones), not the 1 fps a general
  video model samples by default (Gemini's default; fast edits inside one second are missed at that rate).

### 2. Watching, per shot (OBSERVED, structured)
A vision model fills a strict schema per shot, from the strip plus the transcript words in that shot:
- layers, back to front: base plate, insets (rectangle, frame, border), overlays (grain, leak, flare), text;
- for each layer: what it shows (subject, source type: interview, broadcast, stock, 3D render, AI image), and
  whether it moves (scale, position, rotation over the shot);
- transitions in and out, flashes, shakes, blur, RGB split;
- text: exact words, which words are serif or sans, and how each appears and leaves.

Watcher options (model-agnostic, through `scripts/model_provider.py`):
- **Gemini API** watches video with audio natively; custom `fps` and clip offsets in the `processing` object
  (static mode); 258 tokens a frame (66 at low resolution) plus 32 a second of audio. At 10 fps this video is
  about 200k tokens a pass. Needs an API key.
- **Claude in this session** viewing frame strips: no setup, uses session credits (about 110 strips).
- A local open model (Qwen-VL class) is not practical here: no GPU, a 4-core laptop CPU.

The watcher's output is a hypothesis. It is never the final answer on its own.

### 3. Measuring what the watcher claimed (MEASURED)
- **Source footage.** Distinctive frames (faces, logos, lower-thirds) go to reverse image search (Google Lens,
  Bing Visual Search), and broadcast clips get a text search ("Musk reacts to NYT's Tesla review", Bloomberg).
  When the original is found, everything about the shot becomes solvable exactly:
  - **geometry**: feature matching (ORB/SIFT + RANSAC homography) between the source frame and the reference
    frame gives the inset's exact scale, position and rotation, frame by frame, so keyframes are fitted, not
    guessed;
  - **colour**: source and reference pixel pairs give the grade directly (fit a 3D LUT by regression).
  Footage that cannot be found (AI images, custom 3D) is marked SUBSTITUTE, and its look is fitted from the
  reference frames alone.
- **Insets without a source:** track the inset's rectangle corners (edges + optical flow) for its transform.
- **Text:**
  - Words: OCR as one input, confirmed against the transcript and the watcher.
  - Font: candidate fonts (Google Fonts serif italics and heavy sans) are rendered at the measured size and
    compared with the glyph crops, render-and-compare, not a classifier (DeepFont-style recognisers are
    research code, arXiv 1507.03196).
  - Animation: opacity, blur, scale and offset of each word, per frame.
  - Timing: against the narrator's word times.
- **Look per shot:** grain amount and size, glow/bloom radius, vignette, chromatic aberration, all measured from
  the frames.
- **Audio:**
  - Separate voice, music and the rest with Demucs (fine on CPU for 76 s).
  - Identify the music by fingerprint (separation before fingerprinting helps peak-based matchers when music
    sits under speech).
  - SFX: onsets in the residual, classified (CLAP) or matched to our SFX library.
  - The voice: transcript with word times, plus pace and pauses.

### 4. Rebuilding: an editable project (VERIFIED by render)
The reconstruction is one JSON per video: shots, layers, keyframes, text, grade, audio. It compiles two ways:
- **A Kdenlive project (.kdenlive, MLT XML), rendered headless with `melt`.** Kdenlive's bundled MLT 7.37 on
  this PC has what this video needs: `qtblend`/`affine` (keyframed transform, opacity, blend modes),
  `avfilter.lut3d`, `frei0r.glow`/`softglow`, `frei0r.filmgrain`/`grain`, `frei0r.rgbsplit0r`, `vignette`,
  `frei0r.screen`, `qtext`/`kdenlivetitle`. The owner can open the result and keep editing by hand. Per-word
  animated typography beyond what Kdenlive titles can do is rendered by our Remotion templates as transparent
  clips and placed on a Kdenlive track. Notes:
  - Hand-generated .kdenlive files can fail to open without an error (Kdenlive forum, 24.12). So the first step
    is a golden file saved by this PC's Kdenlive, which we then mirror. Plain MLT XML always renders with
    `melt`.
  - Existing helpers (`mlt-python`, OTIO's MLT adapter, the `cli-anything-kdenlive` MCP) are references, not
    dependencies.
- **Our own compiler** (`compile_timeline.py`, IR 3.0), as today.

DaVinci Resolve is not needed for this. Kdenlive is installed, open-source and scriptable through its file
format. Resolve can import the same edit later through OTIO/FCPXML if the owner installs it.

### 5. The compare-and-fix loop (VERIFIED)
- **Per shot:** render, align by frame, then measure the difference:
  - frame similarity (SSIM, plus a perceptual metric);
  - text box overlap and glyph match;
  - colour ΔE;
  - cut-time error in frames;
  - audio onset error.
- **Worst shots first.** The watcher sees reference and render side by side and names the difference ("inset is
  8 % too small", "serif should be lighter"). The patch is applied and the shot re-rendered.
- **Stop rule:** each shot passes its thresholds, or it is labelled with what blocks it ("source footage not
  found", "font not identified").
- **Score:** the share of shots VERIFIED, and per-shot similarity. Unlike the compare loop's single number, this
  says which shot fails and why, in frames.

## Limits, stated plainly
- "Exactly the same" needs the same footage, fonts and music. Where those cannot be found, the remake is close,
  not exact, and each such shot says so.
- This reference is someone else's edit built on broadcast footage (Bloomberg, CNBC, WSJ). A frame-exact remake
  is for study and benchmarking on this PC. It is not for publishing. What carries over to the owner's videos is
  the reconstructed method: the layer recipes, text system, look and pacing. The reference's footage, words and
  transcript never enter the repo (CLAUDE.md).
- Cost: the watcher pass and the fix loop cost model tokens. Measuring first, and sending only the uncertain
  shots to the watcher, keeps that down.

## Sources
- 4DCodeBench, agents on inverse graphics of dynamic scenes: https://arxiv.org/html/2610.03715v1
- VIGA, vision-as-inverse-graphics agent: https://arxiv.org/pdf/2601.11109
- Thinking in Blender, staged executable inverse graphics: https://arxiv.org/html/2606.02580
- AutoShot shot boundary detection: https://arxiv.org/pdf/2304.06116
- Gemini video understanding (fps, offsets, tokens): https://ai.google.dev/gemini-api/docs/video-understanding
- Generative Omnimatte, video layer decomposition: https://arxiv.org/html/2411.16683v2
- DeepFont: https://arxiv.org/pdf/1507.03196
- Kdenlive/MLT generation: https://discuss.kde.org/t/issue-with-python-generated-kdenlive-project-won-t-open/30729 ,
  https://pypi.org/project/mlt-xml/ , https://pypi.org/project/otio-mlt-adapter/0.2.0 ,
  https://mail.kde.org/pipermail/kdenlive/2025-August/011683.html
- Source separation before audio fingerprinting: https://repositori.upf.edu/items/ca89891c-f07a-4488-90b3-762aae96a53a
- Timeline-Bench (agents editing raw footage to a final cut): https://arxiv.org/abs/2609.35143
