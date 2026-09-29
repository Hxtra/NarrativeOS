import sys, hashlib
from pathlib import Path
import pytest
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import generation
from editorial_style import resolve_style, fingerprint


def test_video_disabled():
    # Video is a known kind that is explicitly switched off: the job is DISABLED and no transition can move it.
    job = generation.plan_request({'request_id': 'v', 'kind': 'video', 'purpose': 'test', 'enabled': True}, resolve_style({}), {})
    assert job['state'] == 'DISABLED' and job['capability']['enabled'] is False
    with pytest.raises(ValueError, match='disabled'):
        generation.attach_quote(job, {'version': 'v1', 'request_hash': 'x', 'provider': 'p', 'model': 'm', 'amount': 0,
                                      'currency': 'USD', 'basis': 'local_zero_cost', 'rights_terms': 'r'})


def test_adapter_verification_and_approval(tmp_path):
    assert callable(getattr(generation, 'execute_request', None))
    request = generation.plan_request({'request_id': 'i', 'kind': 'image', 'purpose': 'concept', 'visual_role': 'conceptual', 'width': 8, 'height': 8}, resolve_style({}), {})
    quote = {'version': 'v1', 'request_hash': request['request_hash'], 'provider': 'offline-fixture', 'model': 'fixture-v1', 'amount': 0, 'currency': 'USD', 'basis': 'local_zero_cost', 'rights_terms': 'engineering fixture only'}
    approval = {'quote_hash': fingerprint(quote), 'cost_approved': True, 'rights_approved': True}
    import cv2, numpy as np
    output = tmp_path / 'fixture.png'
    cv2.imwrite(str(output), np.zeros((8, 8, 3), dtype=np.uint8))
    supplied = {'path': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'provider': quote['provider'], 'model': quote['model'], 'request_hash': request['request_hash'], 'rights_terms': quote['rights_terms']}
    calls = []
    def adapter(req, q):
        calls.append(req)
        return supplied
    result = generation.execute_request(request, quote, approval, adapter)
    assert result['status'] == 'review_required' and result['byte_verified'] is True
    assert result['can_support_claim'] is False
    for changed in [{**approval, 'cost_approved': False}, {**approval, 'quote_hash': 'stale'}, {**approval, 'rights_approved': False}]:
        with pytest.raises(ValueError):
            generation.execute_request(request, quote, changed, adapter)
    assert len(calls) == 1
    supplied['sha256'] = 'fake'
    with pytest.raises(ValueError, match='bytes'):
        generation.execute_request(request, quote, approval, adapter)
