# Signatures (Phase 4)

A Signature is a saved editing style: what one reference edit does, *when* it does it, and the pipeline that
recreates it on new footage. The idea comes from the owner's Forseth / Pocket Creative research ("save the DNA of
a video style, a different pipeline per DNA"). The difference is that NarrativeOS measures a style instead of
asking a model to describe it.

## Where Signatures live

- **Location:** `~/NarrativeOS-Signatures/<id>/`, or the folder in `NARRATIVEOS_SIGNATURES`. This is outside the
  repo, like channel profiles and the VFX library.
- **Folder contents:**
  - `signature.json` — the current version.
  - `versions/vNNN.json` — every earlier version.
  - `reference/` — the Style DNA, the breakdown, the transcript and the measured StyleProfile.
  - `verify/` — the recreations.
  - `notes.jsonl` — corrections made while the Signature was in use.
- **Reference footage** is analysed only. It is never used in an edit, and the reference itself is not copied in.
  Only its name, its sha256 and its measurements are kept.
- **The measured StyleProfile** goes into `reference/style_profile.json` and nowhere else. Registering it as a
  renderer style in `src/styles/generated/` is a separate decision for the owner.

## Studying a reference

```
python scripts/signature.py study REFERENCE.mp4 --id my_style --label "..." [--text] [--no-verify]
```

A study takes these steps:

1. **Measure the reference:**
   - Style DNA (`style_intel.dna`): pacing, shot lengths, the transition vocabulary and colour.
   - The effect breakdown (`style_intel.breakdown`): every visual moment, its measured layers and the closest
     registered recipe.
   - On-screen text, with `--text`.
   - The transcript (faster-whisper) and its firing moments: NUMBER, CONTRAST, LIST, QUESTION, CUE, NAME and HOOK,
     plus LINE_START.
2. **Discover moves** (`discover_moves`). Each visual moment that does something is paired with the speech moment
   it lands on, within 0.4 s. "Does something" means a non-hard-cut recipe, or a zoom without a cut, which counts
   as a punch-in. An effect becomes a move that **fires on** a trigger only when both of these hold:
   - **support** ≥ 2: it landed on that trigger at least twice;
   - **precision** ≥ 0.5: it landed on at least half of that trigger's occurrences.

   Any other effect is kept as **UNCLASSIFIED**, with the places it was seen, so a coincidence never becomes a
   rule.
3. **Measure the pipeline:**
   - the kind of edit (a talking head when speech covers ≥ 35% of the reference);
   - the aspect ratio;
   - how tight it cuts: the longest pause kept inside a line, which becomes `max_gap_in_run_sec`;
   - how hard it punches in;
   - its caption treatment, from the measured text: position, words per line, case and size.
4. **Verify each transition move by recreation.** The move's recipe is rendered between two synthetic shots, and
   the recreation goes through the same breakdown. Its measured effects are then compared with the reference
   moments' effects (Jaccard similarity of effect types):
   - **verified** at ≥ 0.6;
   - **approximate** above 0;
   - **failed** at 0, or when the recreation does not render.

A new Signature is **experimental**. Every move starts as a **draft**, with its evidence: times, what was said, and
review strips.

## Applying a Signature

```
python scripts/signature.py apply ID --project P --clips media/raw.mp4 [--script s.txt]
```

`apply` runs the Signature's pipeline (so far `talking_head`) with its own cut settings and caption treatment, and
replaces the built-in moves with the Signature's moves:

- **A transition move** goes on the cut at its moment. If the reference cut there and the new cut does not, the
  segment is cut just before the moment's first word: in the pause, at most 0.12 s early. The new piece takes the
  other framing so the cut reads. A moment within 0.5 s of a segment edge is **skipped and reported**, never forced.
- **Rejected and UNCLASSIFIED moves** never fire.
- **Rules** are applied last, as constraints (see below).
- **The measured face wins over captions.** A Signature's caption position never covers the measured face; the
  conflict is recorded in `frame.caption_conflict`.
- **Pinning:** the project is pinned to the exact version in `signature_pin.json`. The Studio shows the pin, and
  says when the library has moved on.

## Learning, slowly

- **Notes.** A correction typed in the Studio on a pinned project is kept as a note on the Signature, alongside the
  channel's creative memory. Notes are evidence, not rules.
- **Rules.** `promote-rule` turns notes into a rule only when they come from **at least two projects**: one video's
  taste is not yet a style. A rule is a constraint on the built timeline:
  - `avoid`: recipes it must not use;
  - `max_transitions_per_minute`;
  - `captions`: parameter overrides.
- **Lifecycle:** experimental → **proven** needs two shipped, **approved** edits (`ship --approved`). A Signature
  can also be pending, rejected (it then cannot be applied) or archived.
- **Versions:** every change is a new version. A study never overwrites an existing Signature.

## Status

| Piece | Status |
|---|---|
| Move discovery, support/precision, UNCLASSIFIED for coincidences, firing (use a cut, make a cut, skip at an edge), rules, face-over-captions, versions, lifecycle gates, Studio pin and notes | VALIDATED (`tests/test_signature.py`, exact) |
| Known-answer reference → study → recreation → apply | VALIDATED (`test_a_style_is_learned_from_a_reference_verified_by_recreation_and_applied_to_a_new_take`). A TTS take is cut with a flash_cut before every number and nowhere else. The study finds exactly one move, "flash cut on number" (support 3/3, precision 1.0), and verifies it by recreation (similarity 1.0). Applied to a different take, it fires on all three numbers there and nowhere else. |
| Caption style from measured text | IMPLEMENTED; NOT VALIDATED on a real reference |
| Documentary-kind Signatures | IMPLEMENTED as study output only; `apply` refuses them until the documentary pipeline can take moves |
| A real reference | NOT YET: the owner supplies the first one |

## What the known-answer experiment fixed

The first run of the experiment did **not** recover the known style. Each cause was a measurement error, fixed at
its source and now covered by a test:

- **Word timing** (`talking_head.transcribe`). Decoding the whole take, Whisper put the word after a pause *before*
  the pause: "three" at 0.60 s, where the audio has it at 1.48 s. So moments sat far from their cuts. Words now take
  their times from a phrase-by-phrase decode between measured pauses; see `references/talking-head.md`.
- **Mid-sentence pauses** (`lines_of`). With correct timing, "I posted (0.9 s) three videos a week." split into two
  lines, and "I posted" was dropped as an earlier attempt of "Then I posted". A pause now ends a line only when the
  speaker starts over after it, or when it is longer than 2 s.
- **A flash read as a whip pan** (`style_intel/breakdown.py`). A white wash lowers measured sharpness with the
  square of contrast, so a whip/blur must now also hold with contrast divided out.
- **A still after a fade read as a frame hold.** The brightness change no longer counts as motion.
- **A white flash over warm footage read as a cool light leak.** A leak's tint is now measured after removing what
  white light does to that shot's colour.
- **"The cheap one" read as a NUMBER.** "one" after a determiner, or before "of", is a pronoun.

What a study cannot know yet:

- **Sound identity** (which whoosh) and **typography font** are NOT_MEASURED by the breakdown.
- **The trigger is INFERRED from co-occurrence, not intent.** The evidence strips are there so a person can confirm
  it.
