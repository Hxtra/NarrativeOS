"""CLI: python -m style_intel analyze <video> --out <dir> | profile <style_dna.json> --id <style_id> | breakdown <video> --out <dir>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import breakdown as breakdown_mod
from . import dna as dna_mod
from . import profile as profile_mod


def report(dna: dict) -> str:
    ed, look, snd, sp = dna["editing"], dna["visual"], dna["audio"], dna["speech"]
    sd = ed["shot_duration_sec"]
    lines = [
        f"# Style DNA: {dna['source']['file']}",
        "",
        f"- **Length:** {dna['source']['duration_sec']:.1f} s, {dna['source']['width']}x{dna['source']['height']} @ {dna['source']['fps'] or '?'} fps",
        f"- **Pacing:** {ed['pacing']}. {ed['shot_count']} shots, median {sd['median']} s (p10 {sd['p10']} s, p90 {sd['p90']} s), {ed['cuts_per_minute']} cuts/min",
        f"- **Flashes / dips:** {ed['flash_frames_per_minute']} flash frames/min, {ed['dips_to_black']} dips to black",
        f"- **Look:** {look['bands']['colour']}, {look['bands']['tone']}, {look['bands']['contrast']} contrast, {look['bands']['grain']} grain{', letterboxed' if look['bands']['letterboxed'] else ''}",
        f"- **Camera:** mostly {look['camera_motion']['dominant']} {look['camera_motion']['fractions']}",
    ]
    if snd.get("status") == "measured":
        bs = snd["cut_sync_to_beats"]
        sync = "not enough cuts to test" if bs["synced"] is None else f"{'yes' if bs['synced'] else 'no'} ({bs['on_event_fraction']} of cuts on a beat vs {bs['chance_fraction']} by chance)"
        lines.append(f"- **Audio:** {snd['tempo_bpm']} BPM, {snd['integrated_lufs']} LUFS. Cuts follow the beat: {sync}")
    else:
        lines.append(f"- **Audio:** {snd.get('status')}")
    if sp.get("status") == "measured" and sp.get("has_speech"):
        lines.append(f"- **Speech:** {sp['words_per_minute']} words/min, speech covers {sp['speech_coverage']:.0%} of the runtime, first words at {sp['first_speech_sec']} s")
    else:
        lines.append(f"- **Speech:** {sp.get('reason') or ('none detected' if sp.get('has_speech') is False else sp.get('status'))}")
    lines += ["", "**Not measured:** typography (no OCR yet), judgement traits (hook, tone).", "", "**Limitations:**", *[f"- {x}" for x in dna["limitations"]], ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m style_intel", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="measure a reference video into style_dna.json")
    a.add_argument("video", type=Path)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--no-speech", action="store_true", help="skip the Whisper speech pass")
    a.add_argument("--cut-threshold", type=float, default=10.0, help="ffmpeg scdet threshold (lower = more cuts)")
    p = sub.add_parser("profile", help="turn style_dna.json into a StyleProfile the renderer loads")
    p.add_argument("dna", type=Path)
    p.add_argument("--id", required=True)
    p.add_argument("--label")
    b = sub.add_parser("breakdown", help="timestamped list of every transition, effect and synced sound, with evidence and recipes")
    b.add_argument("video", type=Path)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--cut-threshold", type=float, default=10.0)
    b.add_argument("--no-strips", action="store_true", help="skip the per-moment review strips")
    b.add_argument("--no-speech", action="store_true", help="skip the Whisper pass that flags sounds overlapping speech")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "breakdown":
        if not args.video.is_file():
            print(f"no such file: {args.video}", file=sys.stderr)
            return 1
        result = breakdown_mod.analyze(args.video.resolve(), args.out, cut_threshold=args.cut_threshold, strips=not args.no_strips, with_speech=not args.no_speech)
        print(breakdown_mod.report(result))
        return 0

    if args.cmd == "analyze":
        if not args.video.is_file():
            print(f"no such file: {args.video}", file=sys.stderr)
            return 1
        result = dna_mod.analyze(args.video.resolve(), args.out, with_speech=not args.no_speech, threshold=args.cut_threshold)
        text = report(result)
        (args.out / "report.md").write_text(text, encoding="utf-8")
        print(text)
        return 0

    dna = json.loads(args.dna.read_text(encoding="utf-8"))
    prof = profile_mod.build(dna, args.id, args.label)
    (args.dna.parent / "style_profile.json").write_text(json.dumps(prof, indent=2) + "\n", encoding="utf-8")
    ts = profile_mod.write_ts(prof)
    print(f"wrote {ts}")
    print(json.dumps({k: prof[k] for k in ("id", "grade", "pacing", "vfx", "grainOpacity", "unmeasured")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
