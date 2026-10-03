# VFX library

Footage overlays (light leaks, film burns, dust, flares, HUD elements) that the
transition engine in `project/src/vfx/` composites over cuts.

**The clips never go in this repo.** The repo is public, and free or purchased
overlays usually allow use in videos but not re-uploading the files. Clips
live in a local library folder. The repo holds only the code, the schema and
the tooling.

```
<library>/                         $NARRATIVEOS_VFX_LIBRARY, default ~/NarrativeOS-VFX-Library
  light_leak/vfx_light_leak_warm_001.mp4
  dust/vfx_dust_mono_001.mov
  ...
  metadata/<id>.json               one record per clip (schema/vfx_asset.schema.json)
  contact_sheets/<id>.jpg          4x2 frames, for review
  vfx_catalog.json                 all records; what Remotion reads
```

## Workflow

```bash
# 1. Ingest a folder of downloads (copies, never moves; dedupes by sha256).
#    With per-file source records, rights come from the record whose sha256 matches:
python tools/vfx_ingest.py ingest ~/Downloads/overlays --provenance ~/Downloads/overlays/metadata
#    Without them, state the source for the whole folder:
python tools/vfx_ingest.py ingest ~/Downloads/overlays \
  --source-url "https://..." --license "..." --rights-status verified

# 2. Look at every contact sheet, then confirm (optionally re-categorise or fix the blend),
#    or reject with a reason. Rejected clips stay on record and are never used.
python tools/vfx_ingest.py list
python tools/vfx_ingest.py confirm vfx_dust_mono_001 --category graphic_elements
python tools/vfx_ingest.py confirm vfx_scratches_mono_001 --blend multiply --reason "white film gate"
python tools/vfx_ingest.py reject vfx_weather_cool_001 --reason "green screen; needs keying"

# 3. Before release, print the on-screen credits the clips you used require.
python tools/vfx_ingest.py credits vfx_light_leak_cool_001 vfx_dust_mono_002

# After changing the analysis code, re-measure; review decisions are kept.
python tools/vfx_ingest.py reanalyze

# 4. Expose the library to Remotion (junction on Windows, symlink elsewhere).
python ../project/scripts/link_vfx_library.py
```

Recipes only use **confirmed** clips. The category that ingest assigns is a
guess made from the measurements. During testing it called HUD graphics
"dust", so a person or Claude has to look at the contact sheet before a clip
is confirmed.

## What ingest measures

All measurements come from ffmpeg. Nothing is inferred from the filename.

| Field | How | Used for |
|---|---|---|
| `analysis.peak_frame` / `peak_time_sec` | Argmax of per-frame mean luma (`signalstats` YAVG), searched at least `peak_search_margin_frames` (0.5 s, less on short clips) from either edge | `OverlayLayer` places the clip so this frame lands on the cut. The margin exists because a clip ending on a white frame put its "peak" on the last frame, so the overlay ended exactly at the cut and showed nothing |
| `analysis.background_luma_p10` | Median of the per-frame 10th-percentile luma | A black background means the clip was built for Screen or Add |
| `analysis.recommended_blend` | Background, mean luma and alpha | Default blend mode |
| `tone` | Mean chroma of the brightest quarter of frames | Selecting warm or cool leaks; the opposite tone is hue-rotated 180° |
| `technical.*` | `media-library/tools/probe_asset.py` (ffprobe) | fps, size, codec, alpha, audio |

## Rights

- `rights_status: verified` means the recorded licence permits use in the owner's productions. For example, the MotionElements purchases.
- `rights_status: unknown` means the source hasn't been recorded yet. The clip is fine for local experiments but not for release.
- `redistributable` is always `false` unless the licence explicitly allows re-sharing.
- With `--provenance`, each clip is matched to its source record **by sha256 checksum, never by filename**. A record makes rights `verified` only when it names a licence and states that commercial use is allowed. The licence URL, attribution text, share-alike flag and redistribution terms are copied into the clip's `rights` block.
- `attribution_required: true` clips (CC BY) need an on-screen or end credit in any video that uses them. `credits` prints the lines.
- Pixabay-licensed clips may be used inside larger works but never redistributed on their own, which is one more reason the library stays outside the public repo.

## Current library (owner's machine)

### Urban Slideshow (ingested 2026-09-26)

These are the 5 clips from the purchased *Urban Slideshow* template (MotionElements item 15839870):

| id | original | notes |
|---|---|---|
| `vfx_light_leak_warm_001` | Rainbow_3.mp4 | Bright warm leak, 25 fps, peak 0.72 s |
| `vfx_light_leak_warm_002` | Leak.mov | Dim deep-red glow, broad peak at 10.2 s |
| `vfx_dust_mono_003` | noise.mov | Sparse specks |
| `vfx_graphic_elements_mono_001` | Dot_01.mov | HUD dot-matrix bars |
| `vfx_graphic_elements_mono_002` | Element_05.mov | HUD brackets, crosshairs, red X marks |

### The owner's 43 overlay downloads (ingested 2026-10-03)

All 43 checksums matched their source records: 38 Pixabay-licensed and 5 CC BY 3.0 (Wikimedia Commons). Every contact sheet was looked at. **30 were confirmed and 13 rejected.** The downloader's category labels were used as hints only, and 5 of them were wrong.

The library now holds **35 confirmed clips** (these 30 plus the 5 above):

| category | n | ids (`vfx_` prefix omitted) |
|---|---|---|
| light_leak | 6 | light_leak_cool_001, light_leak_neutral_001, light_leak_warm_001…004 |
| scratches | 6 | scratches_mono_001…005, scratches_warm_001 |
| dust | 4 | dust_mono_001…004 |
| particles | 4 | particles_mono_001…003, particles_warm_001 |
| texture | 4 | texture_mono_003, texture_warm_004…006 |
| crt | 3 | crt_cool_001, crt_mono_001, crt_mono_002 (full-frame static: recipes use `normal` blend for a short burst) |
| glitch | 2 | glitch_cool_001, glitch_cool_003 |
| graphic_elements | 2 | graphic_elements_mono_001, graphic_elements_mono_002 |
| film_burn | 1 | film_burn_warm_001 (was labelled a light leak) |
| flicker | 1 | flicker_mono_001 (white projector gate) |
| lens_flare | 1 | lens_flare_cool_001 |
| weather | 1 | weather_mono_002 (snow) |

**Re-categorised in review:**
- CRT → scratches (`scratches_mono_004`);
- grain → scratches (`scratches_mono_005`);
- light leak → film burn (`film_burn_warm_001`);
- light leak → texture (a full-frame red wash, `texture_warm_006`);
- texture → dust (`dust_mono_004`).

**Blend override:** `scratches_mono_001` is a white film gate with dark scratches, so its blend changed from screen to multiply.

**Credits owed (CC BY 3.0):** `light_leak_cool_001`, `light_leak_neutral_001`, `light_leak_warm_003` and `light_leak_warm_004` (Wikimedia "Light Leaks … FREE FOOTAGE"). Run `credits` for the exact lines.

**Rejected (kept on record, never resolved by recipes):**

| reason | ids |
|---|---|
| Green or blue screen: needs chroma keying, which `OverlayLayer` does not do | glitch_cool_002, texture_cool_001, weather_cool_001 |
| Live-action footage, not an overlay (the methane-sensor clip matched the word "leaks") | light_leak_mono_001, texture_mono_001, texture_warm_001, texture_warm_002, weather_mono_001 |
| Full-frame backgrounds | glitch_warm_001, particles_warm_002, texture_warm_003 |
| Full-frame inserts: candidates for future insert templates | crt_warm_001 ("NO SIGNAL" card), grain_warm_001 (film-leader countdown) |

**Not yet ingested:**
- The *History Time Travel* particle overlays. They ship as PNG image sequences, so they need converting to a video with alpha (ProRes 4444 or VP9 alpha) first.
- Its `Distortion_Power_Zoom_03.mp3` transition sound. The engine's SFX cues are semantic and wait for a sound library.

## Tests

```bash
python -m pytest tests   # synthetic clips with known peaks, from tools/make_test_overlays.py
```
