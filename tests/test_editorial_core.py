import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from narration_plan import validate as validate_narration
from visual_coverage import validate as validate_coverage
from event_graph import validate as validate_graph, compile_graph
from retime_timeline import retime


def test_narration_allows_explicit_silence_and_natural_audio():
    plan={"segments":[
        {"segment_id":"N1","type":"NARRATION","text":"A discovery was made.","timing":{"target_start":0,"target_end":3}},
        {"segment_id":"N2","type":"SILENCE","reason":"let footage breathe","timing":{"target_start":3,"target_end":5}},
        {"segment_id":"N3","type":"NATURAL_AUDIO","source_ref":"asset_door","timing":{"target_start":5,"target_end":8}}
    ]}
    assert validate_narration(plan)==[]


def test_narration_rejects_missing_silence_reason():
    plan={"segments":[{"segment_id":"N1","type":"SILENCE","timing":{"target_start":0,"target_end":2}}]}
    assert {"segment_id":"N1","error":"SILENCE requires reason"} in validate_narration(plan)


def test_contextual_coverage_forbids_literal_matching():
    plan={"coverage_id":"VC1","beat_id":"B1","viewer_objective":"show the world","mode":"CONTEXTUAL","literal_word_matching":True}
    assert validate_coverage(plan)


def test_event_graph_compiles_coordinated_consequences():
    graph={"schema_version":"1.0","events":[{"event_id":"EV1","type":"REVEAL","purpose":"show evidence","timing":{"start":0,"duration":4},"affected_objects":["SHOT_1"],"visual":[{"operation":"video_enter","asset_id":"asset_verified"}],"audio":[{"operation":"duck_music","amount_db":-4}],"constraints":["evidence_passed"]}]}
    assert validate_graph(graph)==[]
    ir=compile_graph(graph)
    assert ir["shots"][0]["asset_id"]=="asset_verified"
    assert ir["audio_events"][0]["event_id"]=="EV1"


def test_ripple_retime_moves_downstream_objects_and_records_history():
    data={"shots":[
        {"shot_id":"SHOT_1","start":0,"end":5},
        {"shot_id":"SHOT_2","start":5,"end":10}],
        "audio_events":[{"event_id":"A1","start":5,"end":7}],
        "caption_events":[{"id":"C1","start":5,"end":6}],
        "markers":[{"id":"M1","start":10}]
    }
    out=retime(data,"SHOT_1",8)
    assert out["shots"][1]["start"]==8
    assert out["shots"][1]["end"]==13
    assert out["audio_events"][0]["start"]==8
    assert out["caption_events"][0]["end"]==9
    assert out["markers"][0]["start"]==13
    assert out["retiming_history"][0]["delta"]==3
