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
python tools/vfx_ingest.py ingest ~/Downloads/overlays \
  --source-url "https://..." --license "..." --rights-status verified

# 2. Look at every contact sheet, then confirm (optionally re-categorise).
python tools/vfx_ingest.py list
python tools/vfx_ingest.py confirm vfx_dust_mono_001 --category graphic_elements

# 3. Expose the library to Remotion (junction on Windows, symlink elsewhere).
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
| `analysis.peak_frame` / `peak_time_sec` | Argmax of per-frame mean luma (`signalstats` YAVG) | `OverlayLayer` places the clip so this frame lands on the cut |
| `analysis.background_luma_p10` | Median of the per-frame 10th-percentile luma | A black background means the clip was built for Screen or Add |
| `analysis.recommended_blend` | Background, mean luma and alpha | Default blend mode |
| `tone` | Mean chroma of the brightest quarter of frames | Selecting warm or cool leaks; the opposite tone is hue-rotated 180° |
| `technical.*` | `media-library/tools/probe_asset.py` (ffprobe) | fps, size, codec, alpha, audio |

## Rights

- `rights_status: verified` means the recorded licence permits use in the owner's productions. For example, the MotionElements purchases.
- `rights_status: unknown` means the source hasn't been recorded yet. The clip is fine for local experiments but not for release.
- `redistributable` is always `false` unless the licence explicitly allows re-sharing.

## Current library (owner's machine, 2026-09-26)

These are the 5 clips from the purchased *Urban Slideshow* template (MotionElements item 15839870):

| id | original | notes |
|---|---|---|
| `vfx_light_leak_warm_001` | Rainbow_3.mp4 | Bright warm leak, 25 fps, peak 0.72 s |
| `vfx_light_leak_warm_002` | Leak.mov | Dim deep-red glow, broad peak at 10.2 s |
| `vfx_dust_mono_003` | noise.mov | Sparse specks |
| `vfx_graphic_elements_mono_001` | Dot_01.mov | HUD dot-matrix bars |
| `vfx_graphic_elements_mono_002` | Element_05.mov | HUD brackets, crosshairs, red X marks |

**Not yet ingested:**
- The *History Time Travel* particle overlays. They ship as PNG image sequences, so they need converting to a video with alpha (ProRes 4444 or VP9 alpha) first.
- Its `Distortion_Power_Zoom_03.mp3` transition sound. The engine's SFX cues are semantic and wait for a sound library.
- The owner's 43 downloaded overlay clips, which are still on their phone.

## Tests

```bash
python -m pytest tests   # synthetic clips with known peaks, from tools/make_test_overlays.py
```
