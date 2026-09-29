import sys, json
from pathlib import Path
import pytest
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from director_brain import plan_edit
from event_graph import validate, compile_graph
from controller import validator


def timeline():
    return {'status': 'approved', 'approved': True, 'delivery_ready': True, 'review': {'approved': True}, 'shots': [
        {'shot_id': 'A', 'asset_id': 'a', 'start': 0, 'end': 2, 'media_type': 'image', 'status': 'approved', 'approved': True},
        {'shot_id': 'B', 'asset_id': 'b', 'start': 2, 'end': 4, 'media_type': 'image', 'status': 'approved'}]}


def graph():
    return plan_edit(timeline(), {'music': {'status': 'measured', 'events': [{'event_id': 'M', 'type': 'ONSET', 'start': 2.1, 'confidence': .8}]}}, {'editing': {'rhythm_mode': 'phrase_aware'}})


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1])
def test_invalid_graph_timing_rejected(value):
    g = graph(); g['events'][0]['timing']['start'] = value
    assert validate(g)
    with pytest.raises(ValueError): compile_graph(g)


@pytest.mark.parametrize('change', [{'left_shot_id': 'missing'}, {'to': 5}, {'right_shot_id': 'A'}, {'from': 1}, {'to': float('nan')}])
def test_invalid_boundary_rejected(change):
    g = graph(); g['events'][0]['boundary'].update(change)
    assert validate(g)
    with pytest.raises(ValueError): compile_graph(g)


def test_approval_cannot_survive_compile():
    result = compile_graph(graph())
    assert result.get('approved') is not True and result.get('delivery_ready') is not True
    assert all(s.get('approved') is not True for s in result['shots'])


def test_blocked_evidence_and_model_metadata_not_consumed():
    g = graph()
    evidence = {'music': {'status': 'blocked', 'events': [{'event_id': 'M', 'type': 'ONSET', 'start': 2.1, 'confidence': .8}]}}
    assert plan_edit(timeline(), evidence, g['style'])['events'] == []
    with pytest.raises(ValueError, match='deterministic'):
        plan_edit(timeline(), evidence, g['style'], {'mode': 'model', 'model': 'imaginary'})


@pytest.mark.parametrize('stage,name', [('TIMELINE', 'timeline.json'), ('TIMELINE_IR', 'timeline_ir.json')])
def test_controller_nested_review_required_cannot_pass(tmp_path, stage, name):
    data = timeline(); data['status'] = 'passed'; data['review'] = {'required': True, 'approved': False}
    (tmp_path / name).write_text(json.dumps(data))
    assert validator(tmp_path, stage)[0] is False
