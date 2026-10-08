# Frame awareness (Phase 3)

The pictures are measured with local MediaPipe models, so edits can follow the subject:
- reframing 16:9 to 9:16 around the speaker;
- placing captions away from the face;
- putting text behind the person;
- marking what a finger points at.

## Models

`python scripts/vision_models.py fetch` downloads three Google MediaPipe models (Apache-2.0) into
`~/NarrativeOS-Models` (or `NARRATIVEOS_MODELS`), outside the repo:

| Model | File | Size | Used for |
|---|---|---|---|
| face_detector | blaze_face_short_range.tflite | 0.2 MB | faces |
| hand_landmarker | hand_landmarker.task | 7.8 MB | index fingertip and wrist per hand |
| selfie_segmenter | selfie_segmenter.tflite | 0.2 MB | person mask: subject box, mattes |

Each file's sha256 is recorded on first download and checked on every use; a changed file is refused.

MediaPipe 1.1 is installed with `--no-deps` because it asks for `opencv-contrib-python`, which would collide with
the installed `opencv-python-headless` (both ship `cv2`). The tasks used here don't need it.

## Analysis (`scripts/frame_awareness.py`)

Frames are sampled at 6 fps at 384 px wide and cached per clip. Each sample is MEASURED:
- faces (normalised boxes and scores);
- hands (index fingertip, wrist);
- the person box from the segmentation mask;
- a 6×4 empty-space grid (1 means empty), from the person mask and edge clutter.

The face model squashes its input to a square, so it runs on a square crop around the person found by segmentation
(sliding squares when there is none). On a wide frame it otherwise misses faces it finds at 0.92 confidence on a
square.

## Reframing: a camera operator, not a centre crop

`camera_keys()` gives keyframes `[t, cx, cy]`, the crop centre in normalised source coordinates.
- **Hold:** the camera stays still while the subject stays inside a deadzone (12% of the crop width).
- **Lead:** when the subject leaves it, the camera eases (smoothstep) to where the subject *will be* 0.5 s later,
  starting 0.2 s early. We edit offline, so the whole track is known.
- **Clamp:** the crop never leaves the frame.

A main-track shot carries the keys as `"reframe": {"keys": [[source_time, cx, cy], ...]}`. The keys are in source
time, so trims and speed changes keep them right. The compiler turns them into a per-frame `crop` expression on the
cover-fitted picture. Replacing a shot's footage drops its keys.

## Text behind the subject

A graphic with `"behind_subject": true` is composited, then the person is put back on top. The compiler renders the
main picture under the graphic with the same picture chain, segments that exact picture into a matte, and overlays
the picture through the matte (`alphamerge`). The matte is aligned pixel for pixel and cached in `renders/mattes/`.

## In the talking-head pass

When the models are present, `talking_head.py` adds three things:
- **Reframing:** camera keys on every segment whose footage shape differs from the target.
- **Caption position:** taken from the measured face. Captions go upper when the face sits in the lower part of the
  output frame.
- **Spoken cues** ("look at this", "track it", …): an `anchor_marker` graphic follows the measured index fingertip
  for 3 s after the cue. Without a hand in view it reports "no hand seen" instead of guessing.

Anchors and caption words are resolved by the compiler at render time (`resolve_dynamic`). They go through the
crop's position at that moment, so they stay on the finger and in sync after edits.

## Status

| Piece | Status |
|---|---|
| Camera path rules (hold through jitter, lead a move, stay in frame), point mapping through the crop, anchor resolution | VALIDATED (`tests/test_frame_awareness.py`, exact) |
| Reframing on a real face | VALIDATED on the public-domain NASA portrait moving across a 16:9 frame: the centre crop loses the face in most samples, while subject-follow keeps it in every sample, centred (±0.1) whenever she is still |
| Text behind the subject | VALIDATED: with the person measured by segmentation, a word crossing her is hidden exactly where she is and drawn everywhere else (mean difference < 8 grey levels in both regions) |
| Talking-head demo | Speech take + moving portrait: the face was found in 133/133 samples, all 5 segments were reframed, captions placed low (face at 0.29), and the frames were reviewed |
| Fingertip anchors | IMPLEMENTED; the hand model runs on every sample. NOT VALIDATED on real hands: no footage with a pointing hand yet |
| Real owner footage | NOT YET TESTED |
