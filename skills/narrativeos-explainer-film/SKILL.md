---
name: narrativeos-explainer-film
description: Build a faceless, story-driven explainer film (Fern storytelling + Veritasium-style explanation) from a sourced script - physical 3D scenes and ink-on-paper diagrams rendered with code, every shot landing on a spoken word, cuts carried by one throughline object. Use when the owner wants a new channel video built, or a scene animated, in the AVEN style or a similar one.
---

# Explainer film from a script

First built for the owner's channel AVEN:
- the 60 s test "The Glass That Lit the Sea" (Oct 18);
- "The Man Who Measured the Earth With a Shadow" (Oct 19, 1:52).

The channel's look and measured style live outside the repo, as a channel profile:
- `NarrativeOS-Data/analysis/aven_refs/AVEN_STYLE.md`;
- `MOTION_NOTES.md`, `SOUND_NOTES.md`.

This skill is the method.

## Order of work (never skip ahead)
1. **Script with a fact table.**
   - Every line is traced to a source.
   - Uncertain things are worded as uncertain ("it was said", "one ancient source says", "by several likely readings"). The
     owner rejected stating an interpretation as fact.
   - Numbers are written as words for the voice.
   - Keep `SCRIPT.md` with the table, and note what was left out and why.
   - About 300 words is about 2 minutes at about 173 wpm.
2. **Owner rewrites and approves** the script. Then the voice: skill `narrativeos-voiceover`. Paid credits are only spent
   after approval.
3. **Word times** of the final voice: `python scripts/word_times.py vo.wav words.json --prompt "<rare names>"`.
4. **Plan before building: `CONTINUITY.md`.** One row per shot:
   - the line and the word it lands on;
   - the medium and the shot's single job;
   - what carries the cut out (shape, light or motion).

   One throughline object runs through every shot (a light, a shadow), as in the InGenius trailer.
5. **Build the scenes** (below). Render stills, then a contact sheet: `python scripts/contact_sheet.py stills DIR OUT.jpg`.
   LOOK at it, fix, repeat. A film is not done until its frames have been looked at.
6. **Render**, then sound (skill `narrativeos-sound-design`), then mux. Then a strip of the final file
   (`contact_sheet.py video`) and loudness.

## Rhythm, MEASURED in the references
- Fern cuts about 9.7 times a minute.
- 78 % of Fern's camera moves are constant-speed drifts (median push 6 % over 3.8 s). Use linear camera moves, not eased
  flourishes.
- A picture event lands ON the word it illustrates. Shots switch on nouns in a list ("a stick, a shadow, and a well": one
  cut per noun).
- Opening: give the picture and air about 2 s before the first word.

## Building with code (Lemo-Opuscar + three.js)
**Tool:** `NarrativeOS-Data/tools/lemo-opuscar` (MIT). A film is a folder with `index.html` and `main.js` that exposes
`window.DUR`, `window.render(t)` (a pure function of t), `window.EV` (events for the sound) and `window.READY`.

**Environment:** `PLAYWRIGHT_CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe"`, `LEMO_ANGLE=d3d11`.

**Commands:**
- `node core/render/still.mjs FILM 1 5 9 ... --out FILM/stills/passN`. Render at the FULL size: a smaller `--size` crops the
  page to its top-left corner (MEASURED).
- `node core/render/events.mjs FILM`, which writes `events.json`.
- `node core/render/video.mjs FILM --fps 24 --workers 2 --out FILM/out/video.mp4`. MEASURED: 2,694 frames in 464 s.
- `sh core/render/mux.sh video.mp4 mix.wav out.mp4 24 2`, which adds grain and sets -14 LUFS.

**Patterns** (`NarrativeOS-Data/projects/aven/eratosthenes/film/main.js` is the worked example):
- **Timing from words:** a `T` map of film times looked up from `words.json`, plus `PRE`. Shots are `[name, start, end]`
  built from cues and words, never typed seconds.
- **Paper desk home base:**
  - one sheet of paper on a wooden desk, with a soft warm key light, a focus band (DOF) and grain;
  - every diagram is ink drawn INTO the paper at pen speed (`writeOn`, `wobble`, `inkInto`);
  - the camera is a slow push toward the part being drawn.
- **Real-light 3D scenes:** where shadows ARE the story (the well, the stick, the bending board), use a real directional sun
  with soft shadow maps. Real physics is more convincing than painted shadows: the bent board's shadow really shrinks.
- **Maps from real coordinates:** an equirectangular projection of real lat/lon points. It is still hand-drawn in style.
- **Honest diagrams:** a tiny true angle (7.2 degrees) is drawn larger WITH the label "(drawn larger)", then shrinks to its
  true size when the maths needs it.
- **Place and date tags:** small paper tags, bottom-left (Fern's grammar).
- **Cuts:**
  - a shape match (the globe's circle becomes the well's circle);
  - a light bloom (the sun carries the cut);
  - a same-framing match cut (Syene's stick with no shadow, then Alexandria's stick with one: only the difference changes).

## Look (owner-approved for AVEN, Oct 18)
- Rich physical 3D, not flat vector ("lacks detail, like CorelDRAW 2016" was rejected).
- Soft warm even light. Not hard shadows, heavy particles or darkness ("crime doc ... not our style" was rejected).
- Paper median brightness about 167. Letterbox 2.39.

## Mistakes already made (check for them)
| Symptom | Cause | Fix |
|---|---|---|
| A quarter of every still | stills rendered at a smaller --size | render full size, scale in the contact sheet |
| Sand inside a well instead of water | the ground plane covered the hole | a ring-shaped ground with a real hole |
| The key shadow invisible | the sun put the shadow behind the object, from the camera's view | choose the sun's azimuth so the shadow falls across the frame |
| A short true shadow hidden | the object's base disc was wider than the shadow | shrink the base |
| 2 s of blank paper | the shot started long before its first drawing | something must be on screen from the first frame (a source tag, a sketch) |
| A scene too dark | low fill on a dark backdrop | a lighter backdrop, hemisphere fill about 0.75 |
