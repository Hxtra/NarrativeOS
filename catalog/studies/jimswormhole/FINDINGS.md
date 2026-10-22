# jimswormhole: "Why does your year have twelve months when the moon gives you thirteen?" (owner's reference, Oct 22)

A 2:51 vertical (1080x1920, 30 fps) faceless documentary short. Study only: the video stays local; only these measurements
and observations are kept. Tools: `style_intel avsync` (layers), `style_intel motion`, Earshot 0.3.0 (timeline, realness,
critique against our Fern/Veritasium documentary profile and its own launch-film profile).
Labels: MEASURED (a tool's number), OBSERVED (looked at frames), INFERRED.

## Picture
- OBSERVED, the throughline object: a gold moon-dial with 13 markers on a deep-blue star map. It returns between every
  piece of evidence. Evidence in many forms:
  - a 1931 newspaper;
  - the Laussel Venus carving with its 13 notches;
  - Roman month lists;
  - the Book of Enoch;
  - portraits in gold medallions (Caesar, Augustus, Cotsworth, Eastman);
  - calendar grids;
  - Pope Gregory.
- OBSERVED, one continuous world: the star map is a single canvas the camera TRAVELS across between elements (1:12, 1:40),
  like AVEN's paper desk.
- OBSERVED, the signature transition, a moon ECLIPSE wipe: a dark disc with a glowing crescent rim sweeps across and the
  next scene appears behind it. At 0:48 the 13 glowing dots stay on screen THROUGH the eclipse and land on the star map:
  the theme object carries the cut.
- MEASURED (motion): 27 transitions in 171 s, about 9.5/min (Fern 9.7). 15 read as "dip to black" (median 11 frames); in
  fact they are the eclipse wipe (motion.py limit, see style_intel/README.md). 8 dissolves (17 frames), 3 hard cuts,
  1 wipe.
- MEASURED (motion), camera: 23 push-ins (median zoom x1.20 over 4.4 s) and 19 locked shots, mostly EASED (ease-in-out 12,
  ease-out 10). Fern's moves are 78 % constant-speed drifts, so this is a different signature. Animation on ones (smooth).
- OBSERVED, captions: word-by-word at the bottom, serif, key words in gold italic.

## Sound
- MEASURED (Earshot): narration in 97 % of the film; one music bed ("inspirational corporate", pizzicato strings: labels
  are hints); 123 BPM but no steady beat grid; real or pro-produced (p_real 0.95).
- MEASURED (Earshot), **a sound on nearly every transition:**
  - 60 % of picture changes have a salient hit within 100 ms; our Fern/Veritasium profile has 19-32 %;
  - 21 % land on a strong accent (>= 13 dB over the bed) within 1 frame, against 8 % by chance.
- MEASURED (Earshot) + OBSERVED (frames): the 3 loudest accents (1:12.1, 1:23.9, 1:40.7, about 26 dB over the bed) are
  whooshes on picture movement: the camera traveling up the star map (twice) and an eclipse wipe.
- MEASURED (avsync): the picture does not follow the music (no beat/bar lock, camera ignores the music). The weak relation
  has the picture 67 ms BEFORE the drum layer: effects placed on picture events, not visuals driven by music.
- MEASURED (Earshot): mastered quiet, -22.9 LUFS integrated, true peak -9.1 dBTP, little sub or air. This may be the download
  (platform processing), not the creator's master.

## For AVEN (INFERRED, owner to judge)
1. A theme-object transition (the eclipse) is AVEN's "light carries the cut", done as one recurring branded move.
2. One continuous world the camera travels across, with a whoosh on each journey, fits the paper desk.
3. This channel sounds its transitions far more than Fern (60 % vs about 25 %). It is a choice of style, not a rule. Fern's
   restraint is the other pole. The owner decides where AVEN sits.
