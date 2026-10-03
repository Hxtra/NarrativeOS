# Style Intelligence

The first general-purpose NarrativeOS system: give it a reference video in any
style (documentary, news, gaming, podcast clip, travel, short-form social) and
it measures the video's editing language as **Style DNA**. Then it turns that
into a **StyleProfile** the renderer uses. Documentary is one production
profile among many, not the identity of the system.

```bash
pip install -r style_intel/requirements.txt       # plus ffmpeg on PATH

python -m style_intel analyze reference.mp4 --out analysis/ref1
python -m style_intel profile analysis/ref1/style_dna.json --id ref1_style
```

`analyze` writes `style_dna.json`, `shots.json`, `shots_contact_sheet.jpg`
(one frame per sampled shot) and `report.md`. `profile` writes
`style_profile.json` and a typed
`templates/narrativeos-video-templates/project/src/styles/generated/<id>.ts`,
which the Remotion `STYLE_REGISTRY` loads automatically.

It takes local files. Your own exports and screen recordings are fine;
downloading someone else's video from YouTube is against YouTube's terms, and
doing so is your call. **It extracts the editing language, never the content.**
No frames, transcript text or audio are stored; only measurements and one
low-resolution frame per shot on the contact sheet, for your own review.

## What is measured, and how

| DNA field | Method | Drives in the StyleProfile |
|---|---|---|
| `editing.shot_duration_sec`, `cuts_per_minute`, `pacing` | Hard cuts from ffmpeg `scdet`, plus gradual transitions: colour histograms 0.5 s before vs. after each moment, each continuous high stretch = one transition | `pacing.targetShotSec`, `vfx.density`, title stagger |
| `editing.gradual_kinds` (light / dark / dissolve) | Brightness path through each gradual transition | Allows leak/burn, dip or crossfade recipes |
| `editing.flash_frames_per_minute`, `dips_to_black` | Per-frame luma (`signalstats`) | Allows `flash_cut`, `exposure_bump`, `dip_to_black` |
| `editing.beat_sync` | librosa beats vs cut times; one-sided binomial test against chance, p < 0.01 | `pacing.beatSync` |
| `visual.contrast`, `saturation`, `warmth`, `luma_mean`, `hue_concentration`, `dominant_hue_deg`, `bands.colour/tone` | Mid-shot frame statistics; toned B&W / duotone is its own band (`tinted_monochrome`) | `grade.filter` (duotone tinted to the measured hue) and shadow/highlight wash |
| `visual.grain` | Immerkaer noise estimator on a native-resolution centre crop, edges excluded so text and detail don't count | `grainOpacity` |
| `visual.camera_motion` | Zoom + pan fitted to ORB feature matches (ratio test + RANSAC); if fixed overlays win the fit, the leftover points are fitted again | `motion.weaveAmount`, allows `push_in_cut` |
| `audio.tempo_bpm`, `integrated_lufs`, `onsets_per_sec` | librosa, ffmpeg `ebur128` | Recorded for the future music-aware editor |
| `speech.words_per_minute`, `speech_coverage`, `first_speech_sec` | faster-whisper (`base`, CPU) | Recorded for narration pacing |
| `typography` | **Not measured yet**: needs an OCR engine | Defaults, listed in the profile's `unmeasured` |
| `judgement` (hook, tone) | **Not run yet**: needs a model pass, labelled as judgement | nothing |

Every band keeps its raw number beside it, and thresholds live at the top of
`dna.py`, so retuning a threshold never needs a re-analysis.

## Transitions are allowed only with evidence

A profile switches on a transition family only when the reference shows it:
- **dips** allow `dip_to_black`;
- **flash frames** allow `flash_cut` and `exposure_bump`;
- **light gradual transitions** allow leaks and burns;
- **plain gradual transitions** allow crossfades;
- **push-ins** allow `push_in_cut`.

Whip, glitch, RGB split, zoom punch and shake have no detector yet, so a
profile never enables them on its own. Cut rate alone is not evidence.

## Known limits

- Very slow dissolves (over ~1.5 s), and transitions between similar-looking shots, can be missed. A fast whip within one scene can read as a transition.
- A long burn whose middle is not fully blown out can be counted as two transitions.
- Look and motion are sampled from up to 60 shots.
- Camera motion needs texture; flat graphics and featureless shots stay static or unmeasured.
- Grain bands are provisionally calibrated.
- Typography and caption style are the biggest gap. OCR (e.g. PaddleOCR) is the next addition.

## Effect breakdown: every transition, effect and synced sound, with timestamps

```bash
python -m style_intel breakdown reference.mp4 --out analysis/ref1_breakdown [--no-speech] [--no-strips]
```

This answers the request usually handed to a multimodal model: "list every transition, effect and sound in this video with timestamps, and tell me how to recreate it". A Manus run of exactly that request later audited itself. Only metadata and cut points had been measured; every effect name, sound name and most timestamps were a model's unverifiable interpretation. Here every row comes from a detector that leaves numbers behind.

**Output:**
- `breakdown.json`: moments, each with its events, evidence, closest recipe, measured layer stack and sound.
- `breakdown.md`: the guide as a table.
- `strips/<moment>.jpg`: 5 frames around each moment (−6, −2, 0, +2, +6) for review.

Every moment starts as `review: UNREVIEWED`.

| Event | Basis | How it is detected |
|---|---|---|
| hard cut, flash frame, dip to black | MEASURED | `shots.py` (scdet; luma path) |
| gradual transition (dissolve / light / dark) | INFERRED | `shots.py` histogram distance |
| frame hold | MEASURED | Identical consecutive frames right after motion **in the same shot**. A still image after a cut is a still shot, not a hold; one repeat is pulldown. |
| RGB split | MEASURED | Phase correlation of the red channel against the blue one; reported as px on a 1080p frame |
| zoom | MEASURED | Similarity transform fitted to ORB matches between consecutive frames, ≥ 2 %/frame |
| whip pan | INFERRED | One-axis motion blur (gradient anisotropy) plus a sharpness collapse plus real travel (≥ 10 % of the frame). Direction comes from global motion and matches `whip_pan` layers (`left` = picture moves left). |
| blur | INFERRED | Sharpness far below the shot's median, no direction, on a textured frame |
| glitch tear | INFERRED | Horizontal bands displaced by different amounts. A band only counts if shifting it by the measured amount explains the change; periodic textures such as piano keys fake shifts one period apart. |
| halftone | INFERRED | A 2-D lattice in the whitened spectrum (two directions plus their sum or difference), made of separate dots (dots found ÷ cells expected). Dot grids 5–32 px pass; photos, piano footage and a rendered keyboard do not. |
| light leak / exposure bloom | INFERRED | Brighter than the picture on **both** sides, for 5–75 frames, not cut in and out. A colour shift makes it a leak (warm/cool, brightest side); none makes it a bloom. |
| sound at a moment | onset and peak MEASURED, class INFERRED | Loudest RMS peak within −0.5/+0.35 s, standing ≥ 10 dB above the floor and the level before. The class comes from the envelope and spectrum: **click** (≤ 120 ms), **impact** (fast attack, low-heavy, long decay), **whoosh** (slow attack, flat noise across ≥ 1 kHz), **hit**, or unclassified. A **riser** is a ≥ 8 dB straight-line climb lasting ≥ 1 s into the moment. |
| speech overlap | INFERRED | faster-whisper segment times (no text kept). A sound inside speech is flagged "may be the voice". |

**NOT_MEASURED, never guessed:**
- typography (no OCR yet);
- speed ramps;
- what made a sound ("bird", "water", "shutter");
- music vs. SFX (no source separation);
- which plugin or AE effect made a look.

The "equivalent techniques" section of the report is reference material, not a finding.

**Moments to recipes.** Events within 0.3 s form one moment, the same shape as a TransitionStack (a cut plus layers). Long events (a hold, a slow leak) join a moment without stretching it. Each moment gets:
- the closest **registered** recipe (e.g. RGB split → `rgb_split_hit`, whip → `whip_pan_<dir>`, zoom into a cut → `whip_zoom`);
- a layer stack with the measured parameters (the `rgb_split` px, the `stutter` hold frames, the leak tone).

Every threshold is in `breakdown.BREAKDOWN_DEFAULTS`.

**Validated against:**
- `tests/test_breakdown.py`: a synthetic edit with every effect and sound placed at a known time. All are found, with no extras. Measured parameters match what was applied (RGB offset 36 px, zoom 1.34×, 6 held frames). Sounds are classified as click, whoosh, impact and riser.
- Regression fixtures for the traps real footage exposed: a rendered keyboard texture, and a slideshow of stills.
- Real videos, checked against the review strips:
  - two AI-image slideshows (only their hard cuts);
  - a piano lesson (only its 8 cuts, after the keyboard trap was fixed);
  - a handheld phone clip (nothing).
- **Not yet run:** the real edit the Manus analysis was made from (`1001964947.mp4`, 52 s, 1024×576); it isn't on this PC.

**Limits:**
- Effects not listed above are not detected, including masks and wipes, shape transitions, displacement other than horizontal bands, and camera shake.
- In a music bed or under narration, the loudest peak near a cut may be a note or a word: check the speech flag and listen.
- An effect laid over a cut into a very different shot can be hidden by the cut's own change.

## Tests

`tests/test_style_intel.py` builds synthetic videos with known answers:
- exact cut times;
- cuts on vs. off a 120 BPM click track;
- warm vs. cool colour;
- a zoom into a real photo;
- flash frames and a dip to black;
- a dissolve, a fade through white and a fade through black, each detected and classified.

It checks the DNA recovers each of them, that profiles only enable transitions with evidence, and that the generated TypeScript loads.

No styles have been generated yet. `src/styles/generated/` stays empty until a reference is chosen.
