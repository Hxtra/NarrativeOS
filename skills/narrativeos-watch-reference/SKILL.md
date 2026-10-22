---
name: narrativeos-watch-reference
description: Study a reference video or tutorial the way an editor does (experience first, then go back to the moments that land, then find why), with a multimodal watcher proposing and NarrativeOS measurements deciding. Use when the owner gives a video to learn from, copy a feeling from, or analyse "to the last detail".
---

# Watching a reference like a person

**The owner's rule (Oct 19):** watching a video, turning it into text, then imagining a new video from that text is "totally
the wrong way". A description loses what made the moment work. In Fern's arrow shot, for example, it loses the narrator
pausing as the arrow flies, the music, and where the sound lands, all placed on purpose by the editors.

The spec is the real moment. The words are only an index into it.

## 1. Watch in the human order (never hand the watcher a checklist)
A checklist makes the watcher find only what we expected. A person:
1. experiences the video;
2. goes back to the moments that got to them, until they can explain them;
3. finds what makes this video itself;
4. works out what the team intended;
5. admits what they can't pin down.

Prompt: `prompts/watch_like_human.md`. Paste it into Gemini with the link and a 3-5 minute section; long videos get
shallow answers.

`prompts/detail_lookup.md` is a checklist. Use it only later, to look up one detail of a moment that has already been found.

## 2. The watcher proposes; measurements decide
MEASURED Oct 19: the Gemini app watched Veritasium's "The Absurd Engineering Behind the Internet" with both prompts.

| Layer | Gemini's answer | Checked against our measurements |
|---|---|---|
| Story and meaning | topic times within about 20 s of the transcript; sound reading of the film's themes | **useful** |
| How it watched | "frame stepping at 24 fps, audio looped" | false: the app samples about 1 fps |
| Picture | "archival illustration" opening | wrong: a live-action re-enactment |
| Pace | "60 cuts per minute" | wrong: about 9 |
| Music | "cuts out entirely" at 7:31; "dips" at the 25:00 notebook | wrong: the bed is flat at 7:31, and the music RISES about 10 dB at 25:00 |
| Precision | "-18 dB duck", "90 BPM", "large-diaphragm condenser" | invented |

So use a watcher to POINT at moments and to read meaning. Every claim about timing, sound or cuts is checked with:
- `python -m style_intel departments VIDEO --out DIR`: stems, music identity, every sound event by family, ducking, picture sync;
- `style_intel/motion.py` (in the departments run): every cut, transition, camera move and drawing rate, at full frame rate;
- `python -m style_intel soundtags`: what each second sounds like (PANNs; Claude cannot hear);
- `python -m style_intel avsync VIDEO --auto-crop`: whether the picture follows the sound, with what delay, and WHICH part of the
  picture follows WHICH sound.
  - Use it when the owner says "everything is synced". On the TB-303 clip the whole frame looked unsynced, but the rings followed
    the bass on the same frame and the sparkle followed the hi-hats.

Write each claim down as MEASURED, OBSERVED (looked at frames), INFERRED or the watcher's PROPOSAL.

**Use both sync views (MEASURED Oct 22, jimswormhole):**
- `avsync` asks whether the PICTURE follows the music (brightness, regions, camera).
- Earshot's `timeline --video` asks whether SOUNDS land on picture events.

On that film, avsync found almost nothing: transitions darken the frame, and the picture ignores the beat. Earshot found a
salient sound under 60 % of the transitions. The frames confirmed whooshes on the eclipse wipes and the camera journeys.
Either tool alone would have told half the story.

## 3. The owner's feeling is the label
The owner feels what lands, and no model does that reliably. When they mark a moment ("this hit me"), extract exactly
that window:
- the clip;
- the Demucs stems;
- frames at the full frame rate;
- a sync map of what happens, to 0.1 s: the voice stops, the picture moves, the sound lands, the music moves.

Where the owner and the watcher disagree, the owner is right.

## 4. Keep the moment, not the description
A studied moment is kept as evidence plus measurements, with a short name. Rebuilds are compared against the real moment
(stems, levels, frames), never against the description of it. Reference footage stays local and study-only; only
measurements enter the repo (CLAUDE.md rights rules).

## 5. Tutorials
For a tutorial, the watcher may take the whole video with its sound. Take the frames where the tutor shows values (1080p,
via the owner's Chrome) and the transcript. Methods come from real editors, never invented (CLAUDE.md, "Learn from real
editors").
