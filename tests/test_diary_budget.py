"""Fake clocks and providers: no real models, sleeps of 100 seconds, or paid calls."""
import threading
import time
import re

import httpx
import pytest
from fastapi.testclient import TestClient

import server
import engine as engine_module
from engine import DiaryEngine, ProviderError
from models import DiaryCandidate, Message, Review, Sentence
from scripts.verify_integration import verify_diary
from server import create_app


MESSAGES = [Message(role='assistant', text='무슨 일이 있었어?'),
            Message(role='child', text='집에서 블록을 쌓았어.')]
DRAFT = DiaryCandidate(sentences=[Sentence(text='집에서 블록을 쌓았다.', source_ids=[1])])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TimedProvider:
    def __init__(self, clock, steps):
        self.clock = clock
        self.steps = list(steps)
        self.calls = []

    def parse(self, instruction, payload, schema, *, timeout=None):
        self.calls.append((self.clock(), timeout, schema))
        duration, answer = self.steps.pop(0)
        self.clock.now += duration
        if isinstance(answer, Exception):
            raise answer
        return answer


def run(steps):
    clock = Clock()
    adapter = TimedProvider(clock, steps)
    body = DiaryEngine(adapter, clock=clock).make_diary(MESSAGES)
    verify_diary(body, [m.model_dump() for m in MESSAGES])
    for start, timeout, _ in adapter.calls:
        assert 0 < timeout <= min(60, 1099 - start)
    return body, adapter


def test_slow_normal_diary_shares_budget_and_leaves_review_time():
    body, adapter = run([(45, DRAFT), (40, Review(accepted=True))])
    assert body['fallback'] is False
    assert body['text'] == '집에서 블록을 쌓았다.'
    assert [t for _, t, _ in adapter.calls] == [49.5, 54]


def test_four_calls_consume_one_budget_instead_of_four_timeouts():
    body, adapter = run([(20, DRAFT), (20, Review(accepted=False)),
                         (20, DRAFT), (20, Review(accepted=True))])
    assert body['fallback'] is False
    assert [t for _, t, _ in adapter.calls] == [49.5, 60, 29.5, 39]


@pytest.mark.parametrize('elapsed', [90, 98, 98.999])
def test_review_rejection_skips_repair_when_less_than_ten_seconds_remain(elapsed, caplog):
    body, adapter = run([(45, DRAFT), (elapsed - 45, Review(accepted=False))])
    assert body['fallback'] is True
    assert body['text'] == MESSAGES[1].text
    assert len(adapter.calls) == 2
    assert 'outcome=repair_skipped_budget' in caplog.text
    assert 'outcome=review_rejected' in caplog.text
    assert '_failed' not in caplog.text


def test_repair_may_start_at_exactly_ten_seconds_remaining():
    body, adapter = run([(40, DRAFT), (49, Review(accepted=False)),
                         (3, DRAFT), (3, Review(accepted=True))])
    assert body['fallback'] is False
    assert [t for _, t, _ in adapter.calls][-2:] == [5, 7]


@pytest.mark.parametrize('steps', [
    [(100, DRAFT)],
    [(45, DRAFT), (55, Review(accepted=True))],
    [(20, DRAFT), (20, Review(accepted=False)), (60, DRAFT)],
    [(20, DRAFT), (20, Review(accepted=False)), (20, DRAFT), (40, Review(accepted=True))],
])
def test_overdue_candidate_or_approval_is_discarded_without_more_calls(steps, caplog):
    # Deliberately ignores the provided timeout; post-call deadline still forbids reuse.
    body, adapter = run(steps)
    assert body['fallback'] is True
    assert body['text'] == MESSAGES[1].text
    assert len(adapter.calls) == len(steps)
    assert 'outcome=budget_exhausted' in caplog.text
    assert 'outcome=accepted' not in caplog.text


def test_expired_budget_returns_original_sources_without_any_provider_call(caplog):
    clock = Clock()
    adapter = TimedProvider(clock, [])
    body = DiaryEngine(adapter, clock=clock).make_diary(MESSAGES, deadline=clock())
    verify_diary(body, [m.model_dump() for m in MESSAGES])
    assert body['fallback'] is True
    assert adapter.calls == []
    assert 'budget_exhausted' in caplog.text


def test_actual_provider_failure_is_not_budget_fallback(caplog):
    clock = Clock()
    adapter = TimedProvider(clock, [(20, ProviderError('공급자 요청 실패'))])
    with pytest.raises(ProviderError):
        DiaryEngine(adapter, clock=clock).make_diary(MESSAGES)
    assert len(adapter.calls) == 1
    assert 'outcome=generation_failed' in caplog.text
    assert 'budget_exhausted' not in caplog.text


def test_http_watchdog_returns_before_blocking_provider_finishes(monkeypatch, caplog):
    monkeypatch.setattr(server, 'DIARY_REQUEST_BUDGET', .15)
    monkeypatch.setattr(server, 'DIARY_RESPONSE_RESERVE', .02)
    monkeypatch.setattr(engine_module, 'DIARY_RESPONSE_RESERVE', .02)
    release, finished = threading.Event(), threading.Event()
    calls = []

    class BlockingProvider:
        def parse(self, instruction, payload, schema, *, timeout=None):
            calls.append(timeout)
            try:
                release.wait(2)  # Cannot be interrupted by a timeout argument.
                return DRAFT
            finally:
                finished.set()

    try:
        with TestClient(create_app(DiaryEngine(BlockingProvider()))) as client:
            started = time.monotonic()
            response = client.post('/api/diary', json={'messages': [m.model_dump() for m in MESSAGES]})
            elapsed = time.monotonic() - started
            assert not release.is_set() and not finished.is_set()
            assert .1 <= elapsed < .8
            assert response.status_code == 200
            body = response.json()
            verify_diary(body, [m.model_dump() for m in MESSAGES])
            assert body['fallback'] is True and body['mock'] is False
    finally:
        release.set()
        assert finished.wait(2)
    assert len(calls) == 1  # Late generation must not start review after deadline.
    assert 'outcome=request_budget_exhausted' in caplog.text
    entries = [r.getMessage() for r in caplog.records if r.name in ('engine', 'server')]
    ids = {re.search(r'request_id=([0-9a-f]{32})', entry).group(1) for entry in entries}
    assert len(ids) == 1  # Watchdog, fallback and abandoned worker belong to one request.
    assert all(m.text not in caplog.text for m in MESSAGES)


@pytest.mark.parametrize('provider', ['groq', 'openai'])
def test_sdk_receives_budget_timeout_without_mutating_shared_client(provider, monkeypatch, caplog):
    from openai import OpenAI
    from providers import ProviderRouter

    monkeypatch.setenv('TEXT_PROVIDER', provider)
    calls = []

    def handler(request):
        calls.append(request.extensions['timeout'])
        raise httpx.ReadTimeout('PRIVATE-CHILD-TEXT-SECRET-KEY', request=request)

    router = ProviderRouter()
    client = OpenAI(api_key='private-test-key', max_retries=0, timeout=60,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    setattr(router, provider, client)
    try:
        with TestClient(create_app(DiaryEngine(router))) as api:
            response = api.post('/api/diary', json={'messages': [m.model_dump() for m in MESSAGES]})
        assert response.status_code == 503  # Provider timeout remains an error, never rejection.
        assert len(calls) == 1  # SDK retries stay disabled.
        assert all(0 < value <= 49.5 for value in calls[0].values())
        assert client.timeout == 60
        assert 'PRIVATE' not in response.text + caplog.text
        assert 'private-test-key' not in response.text + caplog.text
        assert 'outcome=generation_failed' in caplog.text
        assert 'review_rejected' not in caplog.text
    finally:
        client.close()
