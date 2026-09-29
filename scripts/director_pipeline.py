#!/usr/bin/env python3
"""Opt-in local measurements -> Director -> immutable review proposal bundle."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from director_brain import plan_edit
from editorial_style import resolve_style, production_directions
from event_graph import compile_graph, validate
from perception import rhythm_review, speech_map, visual_map


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def run(args) -> dict:
    # Reserve a new bundle; never overwrite a canonical or approved timeline.
    args.out.mkdir(parents=True, exist_ok=False)
    timeline = read(args.timeline)
    errors = validate({'base_timeline': timeline, 'events': []})
    if errors:
        raise ValueError(f'Invalid input timeline: {errors}')
    duration = max(float(s['end']) for s in timeline['shots'])
    narration = read(args.narration) if args.narration else {}
    alignment = read(args.alignment)
    speech = speech_map(alignment, narration, duration)
    if speech['status'] != 'measured':
        raise ValueError(f'Speech alignment unavailable: {speech.get("reason")}')
    from style_intel.audio import temporal_map
    music = temporal_map(args.music)
    visual = []
    manifest = read(args.visuals)
    for asset in manifest['assets']:
        path = Path(asset['path'])
        if not path.is_absolute():
            path = args.visuals.parent / path
        # Visual measurements are source-local, not a fabricated timeline mapping.
        visual.append(visual_map(path, asset['asset_id']))
    style = resolve_style(read(args.profile), read(args.dna) if args.dna else None)
    perception = {'schema_version': 1, 'music': music, 'speech': speech, 'visual': visual,
                  'timebases': {'music': 'timeline_zero; supply a pre-trimmed mix', 'speech': 'timeline', 'visual': 'source_local'}}
    director = None
    if args.director_provider:
        # Model-assisted: any reasoning model behind the provider interface; its proposals are validated like ours.
        director = {'mode': 'model_assisted', 'provider': read(args.director_provider)}
    graph = plan_edit(timeline, perception, style, director)
    graph['perception_artifact'] = 'perception.json'
    graph['visual_policy'] = 'Measurements retained for human review; no semantic visual decisions inferred.'
    proposal = compile_graph(graph)
    artifacts = {'perception.json': perception, 'editorial_style.json': style,
                 'rhythm_review.json': rhythm_review(proposal, music, visual),
                 'production_directions.json': production_directions(narration, alignment, style),
                 'event_graph.json': graph, 'timeline.proposed.json': proposal}
    sources = [args.timeline, args.music, args.alignment, args.visuals, args.profile]
    sources += [p for p in [args.narration, args.dna, args.director_provider] if p]
    report = {'status': 'review_required', 'production_ready': False, 'provider_calls': 0,
              'ai_video_enabled': False, 'director': graph['director'],
              'inputs': [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources],
              'artifacts': list(artifacts), 'events': len(graph['events']),
              'allowed_transitions': style['editing']['allowed_transitions'], 'allowed_transitions_source': style['editing'].get('allowed_transitions_source'),
              'limitations': ['Deterministic Director unless --director-provider is given; model proposals are validated and rejected ones are listed.', 'Visual evidence is measured, not semantic approval.',
                              'HOLD/ANTICIPATE are review markers; no invented camera movement.',
                              'J/L-cuts only when the style requests them and source audio is provable; native audio is not rendered yet. No speech retiming.', 'No render, rights approval or timeline promotion performed.']}
    artifacts['manifest.json'] = report
    # Serialize every artifact before publishing any successful result.
    encoded = {name: json.dumps(value, indent=2, allow_nan=False) + '\n' for name, value in artifacts.items()}
    for name, text in encoded.items():
        with (args.out / name).open('x', encoding='utf-8') as f:
            f.write(text)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ('timeline', 'music', 'alignment', 'visuals', 'profile', 'out'):
        ap.add_argument('--' + flag, type=Path, required=True)
    ap.add_argument('--narration', type=Path)
    ap.add_argument('--dna', type=Path)
    ap.add_argument('--director-provider', type=Path, help='reasoning provider config (model_provider.py); omit for the deterministic Director')
    args = ap.parse_args()
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({'status': result['status'], 'events': result['events'], 'out': str(args.out.resolve())}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
