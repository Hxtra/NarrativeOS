---
name: narrativeos-voiceover
description: Make a realistic AI voiceover for a NarrativeOS video with Gemini TTS, using a working creator's method (many takes per line, best take picked, edited pauses, EQ). Use when a video needs narration and the owner has not recorded their own voice.
---

# Realistic AI voiceover (Gemini TTS)

Learned from a real creator, not invented: Isaac, "How I Actually Make AI Voice Sound Real" (YouTube, Oct 2026; 18 min).
The creator works in ElevenLabs and Premiere. NarrativeOS uses the same method with Gemini TTS and code.
Tool: `scripts/voiceover.py`. Key: `~/.narrativeos/gemini.key` (never print it).

## 1. What makes a voice sound human (the creator's four elements)
1. **Tone and speed change.** A flat tone throughout sounds robotic; excitement and calm must move.
2. **Pauses on important points.** Do not cut every pause for retention; pause where the message needs weight.
3. **Emphasis on key words.**
4. **A human-written script.** No TTS hides an AI-written script; write like a person talks.

## 2. Choose ONE voice and keep it
"Once you pick a voice, you're basically married to it." Audition, then keep the voice for the whole channel (brand). The creator
designs a custom voice so nobody else sounds the same. Never clone someone else's voice without permission.
`python scripts/voiceover.py audition --out DIR` renders the same line in 8 Gemini voices with measurements; a person chooses by
ear (the machine cannot hear).

## 3. Write the script for the voice
- One chunk per line: one or two sentences.
- `...` = hesitation, disappointment, a breath; `!` = excitement (use rarely in documentary).
- Numbers and years written as words ("eighteen twenty-three"), so the voice cannot misread them.
- End a line with `||` for an intentional pause after it (a beat: before a turn, after a reveal).
- The creator writes emphasis in CAPS for ElevenLabs. Not verified for Gemini yet: test before relying on it.

## 4. Generate a few sentences at a time, several takes each
"Each time you hit generate, the tone changes slightly... we're taking advantage of that." Generating line by line gives each
line its own tone and speed, like a real person; one long generation keeps the same pattern and sounds uncanny.
`python scripts/voiceover.py takes SCRIPT.txt --out DIR --voice NAME --n 3`

Gemini rules (MEASURED Oct 18):
- **The style cue must be SHORT and end with a colon** ("Narrate warmly, with quiet curiosity, like telling a friend a true
  story:"). A paragraph of direction is read aloud: a 22-word line came out 27 s long.
- Some models still speak the cue. Charon did once, and EVERY take from the fallback models did, from line 6 of the first test
  on. `pick` salvages such takes: speech-to-text finds the cue's last word ("story") and the take is cut in the gap after it.
- Free-tier quota is per model and PER DAY. On a 429 the tool falls back to the next TTS model with the same voice.
  - The first test exhausted all five TTS models after about 40 requests (8-voice audition twice, then 25 takes).
  - The reset came about 5.5 hours later.
  - Budget each day: audition once, use 2 takes per line, and keep the script under about 15 lines per day.
- Fallback models may sound slightly different from the main one. Listen for timbre jumps between lines.
- Gemini's Algieba reads at about 130 words a minute, slower than documentary pace (Fern 175). `assemble` caps the speed-up at
  1.12x, so plan scripts about 10 % shorter than the target length.

Cartesia (the owner's AVEN voice since Oct 19: "Ronald - Thinker", id `5ee9feff-1265-424a-9d7f-8e4d431a12c7`, model sonic-3):
- Add `--provider cartesia` to `audition` or `takes`. Key: `~/.narrativeos/cartesia.key`.
- Credits are paid, about one per character, and the owner has a small balance.
  - Every run prints its cost and stops unless `--spend` is given.
  - Ask the owner before spending. Use 1-2 takes per line, not 3.
- No style cue is sent, so nothing is read aloud before the script, and `pick` does not cut the start.
- MEASURED Oct 19 (one line): 11 words in 3.8 s, about 173 wpm, close to Fern's 175. No speed-up is needed, unlike Gemini Algieba.
- MEASURED Oct 19 (Eratosthenes, 21 lines):
  - Long lines come out fast: 200-250 wpm. The whole 306-word read took 94 s with the gaps.
  - `atempo` 0.92 gives a calmer read at no credit cost.
  - A `||` in the middle of a line was read aloud as "vertical bar". `chunks()` now splits there and never sends `|`.
- Names Cartesia may mispronounce (Syene, Eratosthenes) need a listen. Speech-to-text cannot judge pronunciation.

Measuring takes (fixed bugs, MEASURED):
- faster-whisper needs 16 kHz. TTS returns 24 kHz, and passing it unconverted made every timestamp 1.5x late and hurt recognition.
- The script spells numbers out ("ninety-seven percent") but speech-to-text writes digits ("97%"). Both sides are normalised to
  words before comparing; otherwise correct takes score as wrong.

## 5. Pick the best take per line
`python scripts/voiceover.py pick --out DIR --wpm 165` scores every take:
- heard correctly (speech-to-text match >= 0.85, no extra words);
- lively pitch (semitone spread);
- pace near the target;
- not clipped.

A person must listen and override picks in `picks.json`. The creator also splices the best parts of different takes inside one
sentence. That is manual for now.

## 6. Edit, speed and EQ
`python scripts/voiceover.py assemble --out DIR --wpm 165`:
- trim dead air and join takes with a natural gap (0.28 s), longer after `||` beats (0.7 s);
- change speed with pitch kept (ffmpeg atempo, limited to 0.9-1.12x);
- EQ chain: high-pass 80 Hz, cut boxiness around 300 Hz, slight presence at 4.5 kHz, gentle compression, loudness -16 LUFS.

Output: `vo.wav` plus `cues.json` (each line's start and end, for cutting the picture to the voice).

## 7. Disclosure and rights
- A generated voice is synthetic media. Record it as `media_class: generated` with `containsSyntheticMedia` in the publish package.
- YouTube allows AI voices on original content (creator's reading; check the current policy when publishing).
- The creator's bigger point: AI voice's real power is dubbing the same video into other languages (one track per language
  on YouTube). Not built yet.
