#!/usr/bin/env python3
"""
run_pipeline.py — Orchestrator for the Flannan Isles video pipeline.

Stages:
  1. footage   — download Pexels/Pixabay footage (footage.py)
  2. timeline  — build timeline.json from script + footage (build_timeline.py)
  3. PAUSE     — HUMAN REVIEW GATE: inspect timeline.json before render
  4. render    — compile timeline to video (render.py)

This is the VidRush-style harness: each stage produces a versioned artifact,
the timeline is the source of truth, and render is a deterministic compiler.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\openclaw\Desktop\flannan_isles")
FOOTAGE_SCRIPT = PROJECT_ROOT / "footage.py"
TIMELINE_SCRIPT = PROJECT_ROOT / "build_timeline.py"
RENDER_SCRIPT = PROJECT_ROOT / "render.py"
TIMELINE_PATH = PROJECT_ROOT / "timeline.json"
ASSETS_PATH = PROJECT_ROOT / "assets.json"

PYTHON = r"C:\Users\openclaw\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"


def run_script(script_path: Path, label: str, timeout: int = 600) -> int:
    """Run a Python script and return its exit code."""
    print(f"\n{'=' * 60}")
    print(f"  STAGE: {label}")
    print(f"{'=' * 60}")
    print(f"  Script: {script_path.name}")

    r = subprocess.run(
        [PYTHON, str(script_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )

    if r.stdout:
        for line in r.stdout.strip().split("\n"):
            print(f"  │ {line}")
    if r.stderr:
        for line in r.stderr.strip().split("\n"):
            print(f"  │ ERR: {line}")

    if r.returncode != 0:
        print(f"\n  STAGE FAILED: {label} (rc={r.returncode})")
    else:
        print(f"\n  STAGE OK: {label}")

    return r.returncode


def print_timeline_summary(timeline_path: Path):
    """Print a human-readable summary of the timeline for review."""
    import json
    from pathlib import Path

    tl = json.loads(timeline_path.read_text())

    print(f"\n{'=' * 60}")
    print(f"  TIMELINE SUMMARY — FOR REVIEW")
    print(f"{'=' * 60}")
    print(f"  File: {timeline_path}")
    print(f"  Schema: {tl['schema_version']}")
    print(f"  Duration: {tl['total_duration_sec']:.1f}s "
          f"({tl['total_duration_sec']/60:.1f} min)")
    print(f"  Resolution: {tl['sequence']['width']}x{tl['sequence']['height']} @ {tl['sequence']['fps']}fps")
    print()

    for track in tl["tracks"]:
        kind = track["kind"]
        z = track.get("z", 0)
        items = track["items"]
        print(f"  TRACK: {track['id']} [{kind}] (z={z}, {len(items)} items)")

        for item in items:
            tid = item.get("id", "?")
            bid = item.get("beat_id", item.get("id", "?"))

            if kind in ("video",):
                if item.get("type") == "template":
                    print(f"    {tid:20s} template={item['template']:15s} "
                          f"[{item['timeline']['in_sec']:5.1f}s - {item['timeline']['out_sec']:5.1f}s] "
                          f"params={json.dumps(item.get('params', {}))}")
                elif item.get("asset_id"):
                    fa = next((a for a in tl.get("footage_assignments", [])
                               if a["asset_id"] == item["asset_id"]), {})
                    src = fa.get("path", "?")
                    src_name = Path(src).name if src else "?"
                    print(f"    {tid:20s} asset={item['asset_id']:12s} "
                          f"src={src_name:40s} "
                          f"[{item['timeline']['in_sec']:5.1f}s - {item['timeline']['out_sec']:5.1f}s] "
                          f"transition_in={item.get('transition_in', {}).get('type', 'hard')}")
                else:
                    print(f"    {tid:20s} [video item without asset]")

            elif kind == "audio":
                status = item.get("status", "?")
                if item.get("text"):
                    print(f"    {tid:20s} beat={bid:10s} "
                          f"[{item['timeline']['in_sec']:5.1f}s - {item['timeline']['out_sec']:5.1f}s] "
                          f"status={status} text=\"{item['text'][:50]}...\"")
                elif item.get("type") == "synthesized":
                    print(f"    {tid:20s} synthesis={item.get('synthesize', '?')} "
                          f"[{item['timeline']['in_sec']:5.1f}s - {item['timeline']['out_sec']:5.1f}s] "
                          f"gain={item.get('gain_db', 0)}dB")

            elif kind == "captions":
                # Captions are informational (rendered as part of overlay or drawtext)
                pass

        print()

    # Footage summary
    print(f"  === FOOTAGE ASSIGNMENTS ({len(tl.get('footage_assignments', []))} clips) ===")
    for a in tl.get("footage_assignments", []):
        fpath = Path(a["path"])
        print(f"    {a['beat_id']:8s} -> {fpath.name:45s} "
              f"[{a['timeline_in_sec']:5.1f}s - {a['timeline_out_sec']:5.1f}s] "
              f"({a['duration_sec']:.1f}s)")

    # Script summary
    print(f"\n  === SCRIPT ({len(tl.get('script', []))} beats) ===")
    total_words = 0
    for beat in tl.get("script", []):
        words = len(beat["text"].split())
        total_words += words
        print(f"    {beat['id']:8s} [{beat['timeline_in_sec']:5.1f}s - {beat['timeline_out_sec']:5.1f}s] "
              f"{words:2d}w  {beat['text'][:60]}...")
    print(f"  Total: {total_words} words, ~{total_words/140:.1f} min at 140 wpm")

    print(f"\n{'=' * 60}")
    print(f"  REVIEW CHECKLIST:")
    print(f"    [ ] Shot assignments match mood/context of each beat")
    print(f"    [ ] Caption text is accurate and readable")
    print(f"    [ ] Caption timing aligns with voiceover")
    print(f"    [ ] Transitions are appropriate (crossfade vs hard cut)")
    print(f"    [ ] Audio placement (voice + music ducking)")
    print(f"    [ ] No footage reused too frequently")
    print(f"    [ ] Total duration is correct for target")
    print(f"{'=' * 60}")


async def confirm_review() -> bool:
    """Pause for human review of the timeline. Returns True if approved."""
    print(f"\n{'=' * 60}")
    print(f"  REVIEW GATE")
    print(f"{'=' * 60}")
    print(f"\n  timeline.json has been written to:")
    print(f"    {TIMELINE_PATH}")
    print(f"\n  Please review the timeline above.")
    print(f"  Check shot assignments, captions, transitions, audio placement.")
    print(f"\n  When you're satisfied, type 'approve' to continue to render.")
    print(f"  To cancel, press Ctrl+C or type 'cancel'.")
    print()

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, input, "  Your decision: ")
        result = result.strip().lower()
        if result in ("approve", "yes", "y", "a"):
            print("\n  Approved — proceeding to render.")
            return True
        elif result in ("cancel", "no", "n", "c", "quit", "exit"):
            print("\n  Cancelled — timeline saved but not rendered.")
            return False
        else:
            print(f"\n  Unrecognized input '{result}'. Treating as cancelled.")
            return False
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return False


async def main():
    print("=" * 60)
    print("  FLANNAN ISLES — VIDEO PIPELINE")
    print("  VidRush/ViewMax-style harness")
    print("  Footage → Timeline (REVIEW) → Render")
    print("=" * 60)

    # Stage 1: Download footage
    rc = run_script(FOOTAGE_SCRIPT, "FOOTAGE", timeout=600)
    if rc != 0:
        print("\nFootage stage failed. Aborting.")
        return 1

    # Stage 2: Build timeline
    rc = run_script(TIMELINE_SCRIPT, "BUILD TIMELINE", timeout=120)
    if rc != 0:
        print("\nTimeline stage failed. Aborting.")
        return 1

    if not TIMELINE_PATH.exists():
        print(f"\nERROR: {TIMELINE_PATH} was not created.")
        return 1

    # Stage 3: Review gate
    print_timeline_summary(TIMELINE_PATH)
    approved = await confirm_review()
    if not approved:
        print("\nPipeline cancelled at review gate.")
        print(f"Timeline saved at: {TIMELINE_PATH}")
        return 0

    # Stage 4: Render
    rc = run_script(RENDER_SCRIPT, "RENDER", timeout=600)
    if rc != 0:
        print("\nRender stage failed.")
        return 1

    # Done
    print(f"\n{'=' * 60}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Output: {PROJECT_ROOT / 'flannan_isles_edit.mp4'}")
    print(f"  Timeline: {TIMELINE_PATH}")
    print(f"  Assets: {ASSETS_PATH}")
    print(f"  Render manifest: {PROJECT_ROOT / 'render_manifest.json'}")
    return 0


if __name__ == "__main__":
    asyncio.run(main())
