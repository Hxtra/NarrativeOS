#!/usr/bin/env python3
"""
build_timeline.py — Research + script + footage → timeline.json

This is the DECISION LAYER. It takes the script, the available footage,
and produces a complete timeline specification. render.py never sees
the script or footage — it only reads this JSON.

Output: flannan_isles/timeline.json
        flannan_isles/timeline.v1.json  (versioned copy)

The pipeline PAUSES after writing timeline.json so a human can review
shot assignments, caption timing, transitions, and audio placement
before render spends time compiling.
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(r"C:\Users\openclaw\Desktop\flannan_isles")
DL_DIR = PROJECT_ROOT / "footage"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
ASSETS_PATH = PROJECT_ROOT / "assets.json"

# Fixed script for Flannan Isles — atmospheric documentary tone
# Each entry: (text, approximate_duration_seconds, caption_style)
SCRIPT = [
    {
        "id": "beat_01",
        "text": "In 1900, three lighthouse keepers vanished from the Flannan Isles.",
        "duration_sec": 7.0,
        "caption": "In 1900, three lighthouse keepers\nvanished from the Flannan Isles.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_02",
        "text": "A remote archipelago in the Outer Hebrides of Scotland.",
        "duration_sec": 6.0,
        "caption": "A remote archipelago\nin the Outer Hebrides of Scotland.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_03",
        "text": "The lighthouse stood on Eilean Mòr — the largest of the group.",
        "duration_sec": 6.0,
        "caption": "The lighthouse stood on Eilean Mòr —\nthe largest of the group.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_04",
        "text": "On December 15th, a passing ship noticed the light was dark.",
        "duration_sec": 7.0,
        "caption": "On December 15th, a passing ship\nnoticed the light was dark.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_05",
        "text": "No flag was flying. No supplies had been landed for weeks.",
        "duration_sec": 6.0,
        "caption": "No flag was flying.\nNo supplies had been landed for weeks.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_06",
        "text": "When a relief vessel finally arrived on December 26th, the lighthouse was silent.",
        "duration_sec": 8.0,
        "caption": "When a relief vessel finally arrived\non December 26th, the lighthouse was silent.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_07",
        "text": "The door was unlocked. The beds were unmade. A meal sat half-eaten on the table.",
        "duration_sec": 8.0,
        "caption": "The door was unlocked.\nThe beds were unmade.\nA meal sat half-eaten on the table.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_08",
        "text": "But the three keepers — James Ducat, Thomas Marshall, and Donald MacArthur — were gone.",
        "duration_sec": 8.0,
        "caption": "But the three keepers —\nJames Ducat, Thomas Marshall,\nand Donald MacArthur — were gone.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_09",
        "text": "The lighthouse log recorded a violent storm on the 12th and 13th of December.",
        "duration_sec": 7.0,
        "caption": "The lighthouse log recorded\na violent storm on the 12th and 13th of December.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_10",
        "text": "The entries grew increasingly frantic. Then, on the 14th, the final entry read:",
        "duration_sec": 8.0,
        "caption": "The entries grew increasingly frantic.\nThen, on the 14th,\nthe final entry read:",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_11",
        "text": '"Storm ended, sea calm. God is over all."',
        "duration_sec": 5.0,
        "caption": '"Storm ended, sea calm.\nGod is over all."',
        "caption_style": "quote",
    },
    {
        "id": "beat_12",
        "text": "But there was no storm recorded by weather stations on the mainland.",
        "duration_sec": 7.0,
        "caption": "But there was no storm recorded\nby weather stations on the mainland.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_13",
        "text": "No ship reported bad weather in the area that week.",
        "duration_sec": 5.0,
        "caption": "No ship reported bad weather\nin the area that week.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_14",
        "text": "Some say the keepers disappeared during a real storm — one never recorded.",
        "duration_sec": 8.0,
        "caption": "Some say the keepers disappeared\nduring a real storm —\none never recorded.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_15",
        "text": "Others believe a fight broke out between them.",
        "duration_sec": 5.0,
        "caption": "Others believe a fight\nbroke out between them.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_16",
        "text": "A popular theory claims one keeper went mad and killed the others.",
        "duration_sec": 7.0,
        "caption": "A popular theory claims one keeper\ngo mad and killed the others.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_17",
        "text": "The logbook tells a darker story: entries about cursing, prayers, and a final supper.",
        "duration_sec": 8.0,
        "caption": "The logbook tells a darker story:\nentries about cursing, prayers,\nand a final supper.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_18",
        "text": "But the log was never found. Only fragments survive.",
        "duration_sec": 5.0,
        "caption": "But the log was never found.\nOnly fragments survive.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_19",
        "text": "Whatever happened on that remote rock, the sea kept its secret.",
        "duration_sec": 7.0,
        "caption": "Whatever happened on that remote rock,\nthe sea kept its secret.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_20",
        "text": "The Flannan Isles lighthouse was automated in 1971. No keeper has lived there since.",
        "duration_sec": 7.0,
        "caption": "The Flannan Isles lighthouse was automated\nin 1971. No keeper has lived there since.",
        "caption_style": "lower_third",
    },
    {
        "id": "beat_21",
        "text": "To this day, the disappearance remains one of Britain's most enduring mysteries.",
        "duration_sec": 7.0,
        "caption": "To this day, the disappearance remains\none of Britain's most enduring mysteries.",
        "caption_style": "lower_third",
    },
]


def load_assets() -> list[dict]:
    """Load asset manifest."""
    if ASSETS_PATH.exists():
        return json.loads(ASSETS_PATH.read_text()).get("assets", [])
    return []


def list_footage() -> list[dict]:
    """List downloaded footage files with probe data."""
    assets = load_assets()
    footage = []
    for a in assets:
        if a.get("provider") == "pexels" and a.get("local_path"):
            footage.append({
                "asset_id": a["asset_id"],
                "path": a["local_path"],
                "width": a.get("probe", {}).get("width", 0),
                "height": a.get("probe", {}).get("height", 0),
                "duration_sec": a.get("probe", {}).get("duration_sec", 0),
                "fps": a.get("probe", {}).get("fps", "0/1"),
                "codec": a.get("probe", {}).get("codec", ""),
                "file_size_mb": round(a.get("file_size", 0) / (1024 * 1024), 2),
                "sha256": a.get("sha256", ""),
                "query": a.get("query", ""),
            })
    return footage


def assign_footage_to_beats(script: list[dict], footage: list[dict]) -> list[dict]:
    """
    Assign footage clips to script beats.
    Strategy: round-robin across available footage, matching mood queries.
    Each beat gets one clip, trimmed to the beat's duration + 1s buffer.
    """
    if not footage:
        print("WARNING: No footage available. Timeline will have empty video tracks.")
        return []

    assignments = []
    total_beats = len(script)

    # Group footage by approximate mood (heuristic from query)
    mood_map = {
        "storm": [],
        "waves": [],
        "lighthouse": [],
        "fog": [],
        "cliffs": [],
        "room": [],
        "clock": [],
        "ocean": [],
        "default": [],
    }

    for f in footage:
        q = f.get("query", "").lower()
        if "storm" in q:
            mood_map["storm"].append(f)
        elif "wave" in q:
            mood_map["waves"].append(f)
        elif "lighthouse" in q:
            mood_map["lighthouse"].append(f)
        elif "fog" in q or "mist" in q:
            mood_map["fog"].append(f)
        elif "cliff" in q or "coast" in q:
            mood_map["cliffs"].append(f)
        elif "room" in q:
            mood_map["room"].append(f)
        elif "clock" in q:
            mood_map["clock"].append(f)
        elif "ocean" in q:
            mood_map["ocean"].append(f)
        else:
            mood_map["default"].append(f)

    # For each beat, pick the best matching footage
    for i, beat in enumerate(script):
        beat_id = beat["id"]
        dur = beat["duration_sec"]

        # Pick a mood based on beat content
        text_lower = beat["text"].lower()
        if "storm" in text_lower:
            pool = mood_map["storm"] or mood_map["waves"] or mood_map["default"]
        elif "lighthouse" in text_lower or "light" in text_lower:
            pool = mood_map["lighthouse"] or mood_map["default"]
        elif "sea" in text_lower or "ocean" in text_lower or "wave" in text_lower:
            pool = mood_map["waves"] or mood_map["ocean"] or mood_map["storm"] or mood_map["default"]
        elif "rock" in text_lower or "remote" in text_lower or "isle" in text_lower:
            pool = mood_map["cliffs"] or mood_map["default"]
        elif "log" in text_lower or "book" in text_lower or "entry" in text_lower:
            pool = mood_map["room"] or mood_map["clock"] or mood_map["default"]
        elif "fog" in text_lower or "mist" in text_lower:
            pool = mood_map["fog"] or mood_map["default"]
        elif "clock" in text_lower:
            pool = mood_map["clock"] or mood_map["default"]
        else:
            # Default: rotate through all footage
            pool = mood_map["default"] or footage

        if not pool:
            pool = footage

        # Pick from pool, round-robin by beat index
        pick = pool[i % len(pool)]

        # Determine trim: use full clip duration or beat duration, whichever is less
        clip_dur = pick.get("duration_sec", 0)
        trim_dur = min(dur + 1.0, clip_dur) if clip_dur > 0 else dur
        trim_start = 0.0

        assignments.append({
            "beat_id": beat_id,
            "asset_id": pick["asset_id"],
            "path": pick["path"],
            "source_in_sec": trim_start,
            "source_out_sec": trim_start + trim_dur,
            "timeline_in_sec": 0.0,  # filled in after assembly order
            "duration_sec": trim_dur,
            "mood": pick.get("query", ""),
        })

    return assignments


def build_timeline() -> dict:
    """Build the complete timeline specification."""
    script = SCRIPT
    footage = list_footage()

    print(f"=== build_timeline.py ===")
    print(f"  Script: {len(script)} beats, "
          f"{sum(b['duration_sec'] for b in script):.1f}s total narration")
    print(f"  Footage: {len(footage)} clips available")

    if not footage:
        print("  WARNING: No footage — timeline will be incomplete")

    # Assign footage to beats
    assignments = assign_footage_to_beats(script, footage)

    # Compute timeline positions
    current_time = 0.0
    for i, (beat, assign) in enumerate(zip(script, assignments)):
        assign["timeline_in_sec"] = current_time
        assign["timeline_out_sec"] = current_time + assign["duration_sec"]
        beat["timeline_in_sec"] = current_time
        beat["timeline_out_sec"] = current_time + beat["duration_sec"]
        current_time += beat["duration_sec"]

    total_duration = current_time

    # Build tracks
    # Track 1: Main video (B-roll footage)
    video_items = []
    for i, assign in enumerate(assignments):
        video_items.append({
            "id": f"shot_{i+1:02d}",
            "beat_id": assign["beat_id"],
            "asset_id": assign["asset_id"],
            "source": {
                "in_sec": assign["source_in_sec"],
                "out_sec": assign["source_out_sec"],
            },
            "timeline": {
                "in_sec": assign["timeline_in_sec"],
                "out_sec": assign["timeline_out_sec"],
            },
            "transform": {
                "fit": "cover",
                "anchor": "center",
            },
            "transition_in": {
                "type": "crossfade",
                "duration_sec": 0.5,
            },
            "transition_out": {
                "type": "crossfade",
                "duration_sec": 0.5,
            },
            "rationale": f"Footage for {assign['beat_id']}: {assign.get('mood','')}",
            "provenance": {
                "provider": "pexels",
                "asset_id": assign["asset_id"],
                "rights_state": "approved",
            },
        })

    # Track 2: Overlay (lower-thirds, title card, outro)
    overlay_items = []

    # Title card at start
    overlay_items.append({
        "id": "title_card",
        "type": "template",
        "template": "title_card",
        "params": {
            "title": "The Flannan Isles",
            "subtitle": "Three Keepers — One Unsolved Mystery",
        },
        "timeline": {
            "in_sec": 0.0,
            "out_sec": 3.0,
        },
        "transition_in": {"type": "fade_in", "duration_sec": 0.5},
        "transition_out": {"type": "fade_out", "duration_sec": 0.5},
    })

    # Lower-thirds for each beat
    for i, beat in enumerate(script):
        if beat.get("caption"):
            overlay_items.append({
                "id": f"lowerthird_{i+1:02d}",
                "type": "template",
                "template": "lower_third",
                "params": {
                    "text": beat["caption"],
                    "style": beat.get("caption_style", "lower_third"),
                },
                "timeline": {
                    "in_sec": beat["timeline_in_sec"] + 0.3,
                    "out_sec": beat["timeline_out_sec"],
                },
                "transition_in": {"type": "fade_in", "duration_sec": 0.2},
                "transition_out": {"type": "fade_out", "duration_sec": 0.2},
            })

    # Outro card at end
    overlay_items.append({
        "id": "outro_card",
        "type": "template",
        "template": "title_card",
        "params": {
            "title": "The sea keeps its secrets.",
            "subtitle": "The Flannan Isles, 1900",
        },
        "timeline": {
            "in_sec": total_duration,
            "out_sec": total_duration + 4.0,
        },
        "transition_in": {"type": "fade_in", "duration_sec": 0.5},
        "transition_out": {"type": "fade_out", "duration_sec": 0.5},
    })

    # Track 3: Captions (text overlay track — separate from lower-thirds for styling control)
    caption_items = []
    for i, beat in enumerate(script):
        if beat.get("caption"):
            caption_items.append({
                "id": f"caption_{i+1:02d}",
                "beat_id": beat["id"],
                "text": beat["caption"],
                "style": beat.get("caption_style", "lower_third"),
                "timeline": {
                    "in_sec": beat["timeline_in_sec"] + 0.3,
                    "out_sec": beat["timeline_out_sec"],
                },
            })

    # Track 4: Voice audio (narration — to be filled by TTS in run_pipeline.py)
    voice_items = []
    for i, beat in enumerate(script):
        voice_items.append({
            "id": f"voice_{i+1:02d}",
            "beat_id": beat["id"],
            "text": beat["text"],
            "timeline": {
                "in_sec": beat["timeline_in_sec"],
                "out_sec": beat["timeline_out_sec"],
            },
            "provider": "openai_tts",
            "model": "tts-1-hd",
            "voice": "onyx",
            "status": "pending",  # TTS not synthesized yet
        })

    # Track 5: Music (dark drone — synthesized)
    music_items = [{
        "id": "music_bed",
        "type": "synthesized",
        "synthesize": "dark_drone",
        "timeline": {
            "in_sec": 0.0,
            "out_sec": total_duration + 4.0,
        },
        "gain_db": -18.0,
        "ducking": {
            "sidechain": "voice_track",
            "threshold_db": -30,
            "ratio": 5,
            "attack_ms": 20,
            "release_ms": 250,
        },
        "status": "pending",
    }]

    # Assemble timeline
    timeline = {
        "schema_version": "flannan.timeline/v1.0",
        "project_id": "flannan_isles_20260905",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sequence": {
            "width": 1280,
            "height": 720,
            "fps": 24,
            "duration_sec": total_duration + 7.0,  # + title (3s) + outro (4s)
        },
        "tracks": [
            {
                "id": "v_main",
                "kind": "video",
                "z": 10,
                "items": video_items,
            },
            {
                "id": "v_overlay",
                "kind": "video",
                "z": 20,
                "items": overlay_items,
            },
            {
                "id": "v_captions",
                "kind": "video",
                "z": 30,
                "items": caption_items,
            },
            {
                "id": "a_voice",
                "kind": "audio",
                "z": 10,
                "items": voice_items,
            },
            {
                "id": "a_music",
                "kind": "audio",
                "z": 5,
                "items": music_items,
            },
        ],
        "script": script,
        "footage_assignments": assignments,
        "total_narration_sec": sum(b["duration_sec"] for b in script),
        "total_duration_sec": total_duration + 7.0,
        "assets_used": [
            {
                "asset_id": a["asset_id"],
                "path": a["path"],
                "query": a.get("query", ""),
                "duration_sec": a.get("duration_sec", 0),
                "file_size_mb": a.get("file_size_mb", 0),
            }
            for a in footage
        ],
    }

    return timeline


def main():
    timeline = build_timeline()

    # Write timeline.json (review copy)
    timeline_path = PROJECT_ROOT / "timeline.json"
    timeline_path.write_text(json.dumps(timeline, indent=2))
    print(f"\n  Written: {timeline_path}")
    print(f"  Duration: {timeline['total_duration_sec']:.1f}s "
          f"({timeline['total_duration_sec']/60:.1f} min)")
    print(f"  Tracks: {len(timeline['tracks'])}")
    print(f"  Video items: {len(timeline['tracks'][0]['items'])}")
    print(f"  Overlay items: {len(timeline['tracks'][1]['items'])}")
    print(f"  Caption items: {len(timeline['tracks'][2]['items'])}")
    print(f"  Voice items: {len(timeline['tracks'][3]['items'])}")
    print(f"  Music items: {len(timeline['tracks'][4]['items'])}")

    # Write versioned copy
    vpath = PROJECT_ROOT / "timeline.v1.json"
    vpath.write_text(json.dumps(timeline, indent=2))
    print(f"  Versioned: {vpath}")

    # Print summary of footage used
    print(f"\n  === FOOTAGE ASSIGNMENTS ===")
    for a in timeline["footage_assignments"]:
        print(f"    {a['beat_id']:8s} -> {Path(a['path']).name:45s} "
              f"[{a['timeline_in_sec']:5.1f}s - {a['timeline_out_sec']:5.1f}s] "
              f"({a['duration_sec']:.1f}s)")

    print(f"\n  === TIMELINE READY FOR REVIEW ===")
    print(f"  Open: {timeline_path}")
    print(f"  Check: shot assignments, caption timing, transitions, audio placement")
    print(f"  Then run: python render.py  (after approving timeline)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
