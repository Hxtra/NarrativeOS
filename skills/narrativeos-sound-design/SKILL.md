---
name: narrativeos-sound-design
description: Design, source and mix a film's sound the way real documentary channels do: music picked by a person's ear, levels and silences measured from real mixes, real recorded effects tied to picture events, every file checked and rights-recorded. Use when a NarrativeOS film needs music, sound effects or a final mix.
---

# Sound design and mix

The owner's complaint that started this (Oct 17): "you are just slapping any random sound you find fit to it". Every sound
must have a job (a place, a change of world or state, a beat of the story), a time it lands on, and evidence for its level.

## 1. The rules, MEASURED in real mixes (Demucs stems, Oct 2026)
Source: Fern's "The Indian Genius Nobody Understands" and Veritasium's "The Absurd Engineering Behind the Internet".

| Rule | Measured |
|---|---|
| Music under almost the whole film | Fern 97 %, Veritasium 89 % |
| The voice sits well above the music while speaking | 24.7 dB (Fern), 23.1 dB (Veritasium) median voice-to-music gap |
| The music only dips a little under the voice | it comes up 2.9-3.5 dB in the gaps |
| A new library track per section, chosen by feeling | about one track every 2-2.5 min (Fern 13 in about 30 min; Veritasium 14 in 34 min). A 2-minute film gets about 2 cues |
| Silence is placed | Fern stops the music right before its darkest moment; Veritasium stops it where live sound is the point |
| Low hits mark a jump into a new world | 9 of 16 checked Fern booms land on such a cut; most other "effects" are inside the music |
| Foley is sparse and tells you where you are | cattle in an Indian street, rain in English cold, a heartbeat inside his mind |
| A bookend | Veritasium opens and closes on the same birdsong |
| A placed silence keeps the room | never digital zero: `sound_mix.py` fails a mix with dead air |

## 2. Plan from the picture
The film's renderer writes `events.json` (every cut and picture event with its time). For each section and event, write:
- the feeling;
- the sound's job;
- the time it lands on (often a spoken word: `scripts/word_times.py`).

Example: `NarrativeOS-Data/projects/aven/eratosthenes/SOUND_SOURCES.md`.

## 3. Music: the owner picks by ear
Claude cannot hear. Find 3-4 candidates per cue from title, genre and tags, send the links, and let the owner choose.
Then MEASURE the chosen track's energy curve (librosa RMS per second) and place it so its own events land on the
picture's.

Example (Eratosthenes): "An Unexpected Discovery" jumps 13 dB 4 s in. So it starts 4 s before the gold ring, and its
entrance lands as the ring begins around the Earth.

## 4. Sourcing (Pixabay)
**Licence:** Pixabay Content License. It is free, allows commercial use, needs no attribution and allows adaptation. It
forbids reselling the files unchanged on their own.

**Fetching:**
- Pixabay blocks command-line fetches of its pages (HTTP 403).
- Open a track's page in the owner's Chrome. Read the `cdn.pixabay.com/download/audio/...mp3` link from the page HTML, and
  check whether it says "Content ID Registered".
- The CDN file itself downloads fine with curl.
- Searching from inside a Pixabay tab works with `fetch('/sound-effects/search/<words>/')`. Space the requests about 2.5 s
  apart, or Cloudflare answers "Just a moment...".

**Content ID:** many tracks are registered. The upload may then get a claim, which is disputed with the Pixabay licence
certificate from the owner's own account (Claude never logs in). Record this in the rights file.

**Rights:** every file gets a record in the project's `media/rights.json`:
- source page and download URL;
- author and licence;
- Content ID status;
- sha256;
- used or rejected, with the reason.

## 5. Check every effect before using it
`python scripts/sfx_check.py DIR` measures:
- length;
- where the peak is (to line it up with the picture);
- low-end share;
- what PANNs hears.

MEASURED Oct 19: 2 of 18 Pixabay effects were not what their titles said. Reject those. Wind often gets weak labels, so the
owner checks it by ear.

## 6. Mix
Write a plan (JSON) and run `python scripts/sound_mix.py PLAN.json`:
- each music cue is levelled to 24 dB under the speaking voice and comes up 3.5 dB in the gaps;
- effects land with their peak on the planned time, at a level relative to the voice (a first setting for the owner's ear);
- the report gives the measured music-under-voice and gap levels, and fails on dead air.

Tests: `tests/test_sound_mix.py`. A film's plan generator is example code: `projects/aven/eratosthenes/film/mix.py`. Then
mux: `sh <lemo-opuscar>/core/render/mux.sh video.mp4 mix.wav out.mp4 24 2` (-14 LUFS, true peak -1.2).

## 7. Verify by measuring, then by the owner's ear
- Measure the key moments in the final file's audio: the opening, every world-jump, the placed silence (room tone, not
  -240 dB), the music's entrance.
- If two encodes write the same file, re-check that the final file has the newest mix.
- The owner listens last. Their ear overrides every number above.
