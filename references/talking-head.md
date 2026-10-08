# Talking-head core (Phase 2)

Raw talking-head takes in; a tight vertical (or 16:9) cut with word-by-word captions out.

```bash
python scripts/talking_head.py --project P --clips media/raw1.mp4 [media/raw2.mp4 ...] [--script script.txt] \
    [--aspect 9:16] [--platform reels] [--style documentary_general] [--out timeline_v3.json] [--force] [--approve-own-footage]
python scripts/compile_timeline.py --project P --preview
```

The result is an ordinary IR 3.0 timeline, so the Studio opens it, typed corrections edit it, and the compiler
renders it. `analysis/talking_head.json` records every decision with its reasons.

## Pipeline

1. **Transcribe.** faster-whisper (`base`, CPU, offline once cached) with word timings, cached per clip in
   `analysis/transcripts/`. A short prompt with hesitations nudges Whisper to write "um" and "uh" instead of
   silently dropping them.
2. **Lines.** Speech is split at pauses of 0.6 s or more and at every sentence end; retakes are usually per
   sentence. Lines made only of hesitation sounds are dropped.
3. **Takes.** Attempts at the same line are grouped.
   - With `--script`, each line is matched to a script sentence; lines that match none are dropped as off-script.
   - Without a script, lines are grouped by similarity; a false start is recognised as the beginning of a later
     attempt.
4. **Choice.** Each take is scored on:
   - completeness: of the script line, or "finished its sentence";
   - recognition confidence;
   - hesitations, stumbles and long internal pauses, each a penalty;
   - a small preference for the later take.
   The best take per line is kept. Dropped takes carry their reasons ("false start: a later take finishes the
   line", "less complete (50% vs 100%)", "an equally good later take was kept").
5. **Tight cut.**
   - Hesitation sounds and immediate word repeats are removed.
   - Silences over 0.35 s inside a take become jump cuts.
   - Every segment gets 0.08 s of padding before and 0.14 s after. The padding never reaches into a removed word.
   - Back-to-back segments of the same clip are merged, or split at the midpoint, so audio is never replayed.
   - Alternate segments punch in to 1.12×, so jump cuts read as deliberate.
6. **Firing moments** from what is said:

   | Moment | Detected from | Default move |
   |---|---|---|
   | HOOK | the first line | recorded |
   | NUMBER | digits, number words, % or $ (MEASURED) | caption emphasis + 1.2× punch-in on its segment |
   | LIST | ordinals: first, second, finally… (MEASURED) | caption emphasis + punch-in |
   | CONTRAST | "X or Y", "not X, it is Y", "not X but Y", "instead of" (INFERRED) | emphasis on both contrasted words |
   | QUESTION | a line ending in "?" as transcribed (MEASURED) | recorded |
   | CUE | "look at this", "track it", "right here"… (MEASURED) | recorded: acting on it needs frame awareness (Phase 3) |
   | NAME | capitalised mid-sentence (INFERRED) | recorded; lower third only for names given in `people` at 16:9 |

   Signatures (Phase 4) will replace these default moves with each style's own.
7. **Timeline.**
   - The main track uses the clips' own sound, with loudnorm at −14 LUFS.
   - A `kinetic_captions` graphic carries `"follow": "main"`. Its words carry their source moment
     (`asset_id`, `src_start`, `src_end`), and the compiler places them on the timeline at every render
     (`resolve_dynamic`). Captions therefore stay in sync after any Studio edit, and a removed take takes its words
     with it.
   - Without Remotion, plain burned-in caption lines are used, and the report says so.

## Kinetic captions (`kinetic_captions`)

- Works at 16:9, 9:16, 1:1 and 4:5, sized from the frame.
- 1–3 words per cell. A pause or a sentence end starts a new cell, and cells hold across short gaps so they don't
  flicker.
- The spoken word pops; words not yet spoken are dimmed. Emphasis words are 1.32× and use the highlight colour,
  which defaults to the style's text colour (no invented palette).
- It stays inside `safeArea`, which the compiler injects from `canvas.platform`.

## Platform safe zones

`canvas.platform` is one of `tiktok`, `reels`, `shorts` or `youtube`. The UI bands, as fractions of the frame:

| Platform | Top | Bottom | Left | Right |
|---|---|---|---|---|
| tiktok | 0.11 | 0.20 | 0.06 | 0.16 |
| reels | 0.10 | 0.20 | 0.06 | 0.14 |
| shorts | 0.10 | 0.18 | 0.06 | 0.14 |
| youtube | 0.05 | 0.08 | 0.05 | 0.05 |

Status: DOCUMENTED. The values are approximate, from the platforms' published safe-zone guides; check them against
a real screenshot before treating them as exact.

## Status

| Piece | Status |
|---|---|
| Lines, take grouping (with and without a script), choice with reasons, tight cut, segment joining | VALIDATED on exact word lists (`tests/test_talking_head.py`) |
| End to end | VALIDATED on real synthetic speech: a Windows-TTS raw take with a false start, an "um" and a twice-said sentence. Through Whisper it gives the right kept takes and reasons, a cut under 60% of the raw length, a NUMBER moment, a 9:16 render, and caption pixels measured inside the Reels safe area on every sample. |
| Captions staying in sync through edits (remove, slow down) | VALIDATED (`test_captions_follow_the_picture_through_any_edit`) |
| Whisper's punctuation | MEASURED as transcribed. In the demo, "And the best part?" came back with a full stop, so that QUESTION moment was not seen. |
| Real talking-head footage | NOT YET TESTED: no owner footage yet; the demo uses synthetic speech over a test pattern |
| Subject-aware reframing (9:16 from 16:9 footage) | NOT YET: centre crop. Phase 3 (face/subject tracking). |
