import json, subprocess, sys
from pathlib import Path
from test_perception_rhythm import click_audio, base_timeline
ROOT = Path(__file__).parents[1]


def inputs(path):
    path.mkdir(exist_ok=True)
    def save(name, data):
        p = path / name; p.write_text(json.dumps(data)); return p
    tl = base_timeline(); tl['status'] = 'approved'
    save('timeline.json', tl)
    save('profile.json', {'editorial_intent': {'editing': {'rhythm_mode': 'phrase_aware'}}})
    save('alignment.json', {'status': 'passed', 'captions': [{'start': 0, 'end': 8, 'text': 'Engineering timing fixture, not real speech'}]})
    save('visuals.json', {'assets': []})
    click_audio(path / 'click.wav', duration=8)
    return [sys.executable, str(ROOT / 'scripts/director_pipeline.py'), '--timeline', str(path / 'timeline.json'), '--music', str(path / 'click.wav'), '--alignment', str(path / 'alignment.json'), '--visuals', str(path / 'visuals.json'), '--profile', str(path / 'profile.json'), '--out', str(path / 'proposal')]


def test_cli_measures_to_review_proposal_without_touching_approved_input(tmp_path):
    cmd = inputs(tmp_path)
    before = (tmp_path / 'timeline.json').read_bytes()
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    out = tmp_path / 'proposal'
    perception = json.loads((out / 'perception.json').read_text())
    assert perception['music']['status'] == 'measured'
    graph = json.loads((out / 'event_graph.json').read_text())
    assert graph['events'] and graph['director']['model'] is None
    proposal = json.loads((out / 'timeline.proposed.json').read_text())
    assert proposal['review'] == {'required': True, 'approved': False, 'reason': 'Perception edits require timeline, asset and listening review.'}
    assert (tmp_path / 'timeline.json').read_bytes() == before
    review = json.loads((out / 'rhythm_review.json').read_text())
    assert review['status'] == 'review_required' and isinstance(review['warnings'], list)
    manifest = (out / 'manifest.json').read_text()
    assert 'JEV' not in manifest and 'Deterministic Director unless --director-provider' in manifest
    snapshot = (out / 'timeline.proposed.json').read_bytes()
    assert subprocess.run(cmd, capture_output=True).returncode != 0
    assert (out / 'timeline.proposed.json').read_bytes() == snapshot


def test_cli_malformed_alignment_fails_closed(tmp_path):
    cmd = inputs(tmp_path)
    (tmp_path / 'alignment.json').write_text(json.dumps({'status': 'passed', 'captions': [{'end': 1}]}))
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert not (tmp_path / 'proposal/timeline.proposed.json').exists()


def test_build_timeline_refuses_overwrite(tmp_path):
    (tmp_path / 'timeline.json').write_text('{"status":"approved"}')
    (tmp_path / 'shot_specs.json').write_text('{"shots":[]}')
    (tmp_path / 'approved_assets.json').write_text('{"assets":[]}')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_timeline.py'), '--project', str(tmp_path)], capture_output=True)
    assert result.returncode != 0
    assert json.loads((tmp_path / 'timeline.json').read_text())['status'] == 'approved'
