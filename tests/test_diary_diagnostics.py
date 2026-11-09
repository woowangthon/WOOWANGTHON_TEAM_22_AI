"""Safe stage diagnostics through real SDK/HTTP paths with an in-memory transport."""
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from diagnostics import failure_details
from engine import DiaryEngine, ProviderError
from providers import ProviderRouter
from server import create_app
from test_providers import bind_groq, completion


PRIVATE = 'PRIVATE-CHILD-TEXT-API-KEY'
REQUEST = {'messages': [{'role': 'assistant', 'text': '무슨 일이 있었어?'},
                        {'role': 'child', 'text': PRIVATE}]}
DRAFT = {'sentences': [{'text': '다듬은 초안', 'source_ids': [1]}]}


def install(monkeypatch, handler):
    monkeypatch.setenv('TEXT_PROVIDER', 'groq')
    router = ProviderRouter()
    bind_groq(router, handler)
    return router


def response(kind, request):
    if kind in ('timeout', 'connection'):
        cls = httpx.ReadTimeout if kind == 'timeout' else httpx.ConnectError
        raise cls(PRIVATE, request=request)
    if kind in ('rate_limit', 'quota_exhausted', 'authentication', 'invalid_request', 'provider_server_error'):
        status = {'rate_limit': 429, 'quota_exhausted': 429, 'authentication': 401,
                  'invalid_request': 400, 'provider_server_error': 503}[kind]
        return httpx.Response(status, json={'error': {'message': PRIVATE,
            'code': 'insufficient_quota' if kind == 'quota_exhausted' else PRIVATE}})
    body = completion({'accepted': True})
    if kind == 'response_schema_invalid':
        body['choices'][0]['message']['content'] = PRIVATE  # Invalid JSON.
    elif kind == 'wrong_schema':
        body['choices'][0]['message']['content'] = '{"unexpected": "' + PRIVATE + '"}'
    elif kind == 'empty_response':
        body['choices'][0]['message']['content'] = None
    elif kind in ('response_truncated', 'response_filtered'):
        body['choices'][0]['finish_reason'] = 'length' if kind == 'response_truncated' else 'content_filter'
    elif kind == 'response_incomplete':
        body['choices'] = []
    return httpx.Response(200, json=body)


@pytest.mark.parametrize('stage,attempt,prefix', [
    ('generation', 1, []),
    ('review', 1, [DRAFT]),
    ('review', 2, [DRAFT, {'accepted': False}, DRAFT]),
])
@pytest.mark.parametrize('kind', [
    'rate_limit', 'quota_exhausted', 'authentication', 'invalid_request', 'provider_server_error',
    'timeout', 'connection', 'response_schema_invalid', 'wrong_schema', 'empty_response',
    'response_truncated', 'response_filtered', 'response_incomplete',
])
def test_failures_are_classified_at_correct_stage_without_raw_data(
        monkeypatch, caplog, stage, attempt, prefix, kind):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) <= len(prefix):
            return httpx.Response(200, json=completion(prefix[len(calls) - 1]))
        return response(kind, request)

    router = install(monkeypatch, handler)
    try:
        with TestClient(create_app(DiaryEngine(router))) as client:
            result = client.post('/api/diary', json=REQUEST, headers={'X-Request-ID': PRIVATE})
        assert result.status_code == 503
        assert set(result.json()) == {'error'}  # No error metadata added to the BE JSON.
        assert len(calls) == len(prefix) + 1  # Never retry a provider/format failure.
        failures = [r.getMessage() for r in caplog.records if f'outcome={stage}_failed' in r.getMessage()]
        assert len(failures) == 1
        reason = 'response_schema_invalid' if kind == 'wrong_schema' else kind
        assert f'attempt={attempt}' in failures[0]
        assert f'reason={reason}' in failures[0]
        assert 'provider=groq' in failures[0]
        assert re.search(r'request_id=[0-9a-f]{32}\b', failures[0])
        if kind in ('rate_limit', 'quota_exhausted'):
            assert 'status=429' in failures[0]
        assert PRIVATE not in caplog.text + result.text
        assert 'groq-test' not in caplog.text + result.text
        assert '다듬은 초안' not in caplog.text
    finally:
        router.groq.close()


def test_rejected_then_failed_review_and_new_generation_have_distinct_request_ids(monkeypatch, caplog):
    steps = iter([DRAFT, {'accepted': False}, DRAFT, None, None])

    def handler(request):
        item = next(steps)
        return httpx.Response(200, json=completion(item)) if item is not None else response('rate_limit', request)

    router = install(monkeypatch, handler)
    try:
        with TestClient(create_app(DiaryEngine(router))) as client:
            first = client.post('/api/diary', json=REQUEST)
            second = client.post('/api/diary', json=REQUEST)
        assert first.status_code == second.status_code == 503
        entries = [r.getMessage() for r in caplog.records if r.name == 'engine']
        assert len(entries) == 3
        assert 'review_rejected attempt=1' in entries[0]
        assert 'review_failed attempt=2' in entries[1]
        assert 'generation_failed attempt=1' in entries[2]
        ids = [re.search(r'request_id=([0-9a-f]{32})', entry).group(1) for entry in entries]
        assert ids[0] == ids[1] != ids[2]
        assert 'reason=rate_limit' in entries[1] and 'reason=rate_limit' in entries[2]
        assert PRIVATE not in caplog.text
    finally:
        router.groq.close()


def test_untrusted_exception_metadata_is_never_logged_verbatim():
    error = ProviderError(PRIVATE, reason=PRIVATE, status_code=PRIVATE, provider=PRIVATE)
    assert failure_details(error) == ('unexpected_error', None, 'unknown')
    error.reason = ['not', 'hashable']
    assert failure_details(error) == ('unexpected_error', None, 'unknown')
