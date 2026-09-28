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
