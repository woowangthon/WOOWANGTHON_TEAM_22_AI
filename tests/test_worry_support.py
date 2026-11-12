import pytest
from fastapi.testclient import TestClient

from engine import DiaryEngine, ProviderError
from providers import ProviderRouter
from server import create_app
from worry_support import WorryAction


class Adapter:
    def __init__(self, action='feelings', error=None):
        self.action = action
        self.error = error
        self.calls = []

    def parse(self, instruction, payload, schema, *, timeout):
        self.calls.append((payload, schema, timeout))
        if self.error:
            raise self.error
        return schema(action=self.action)


@pytest.mark.parametrize(('messages', 'status'), [
    ([], 'opening'),
    ([{'role': 'child', 'text': '엄마가 나를 때렸어.'}], 'needs_adult'),
    ([{'role': 'child', 'text': '죽고 싶어.'}], 'needs_adult'),
    ([{'role': 'child', 'text': '그만할래.'}], 'finished'),
])
def test_fixed_responses_do_not_call_model(messages, status):
    adapter = Adapter()
    with TestClient(create_app(DiaryEngine(adapter))) as client:
        response = client.post('/api/worry/chat', json={'messages': messages})
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.json()['status'] == status
    assert adapter.calls == []


@pytest.mark.parametrize(('action', 'error', 'status'), [
    ('feelings', None, 'reply'),
    ('needs_adult', None, 'needs_adult'),
    ('listen', ProviderError('private-provider-detail'), 'unavailable'),
])
def test_one_structured_call_selects_reviewed_response(monkeypatch, action, error, status):
    monkeypatch.setenv('WORRY_ENABLE_MODEL', '1')
    adapter = Adapter(action, error)
    messages = [{'role': 'child', 'text': '친구랑 다퉜어.'}]
    with TestClient(create_app(DiaryEngine(adapter))) as client:
        response = client.post('/api/worry/chat', json={'messages': messages})
    assert response.status_code == 200
    assert response.json()['status'] == status
    assert 'private-provider-detail' not in response.text
    assert adapter.calls == [({'conversation': messages}, WorryAction, 12)]


def test_rejects_last_assistant_and_private_metadata():
    with TestClient(create_app(DiaryEngine(Adapter()))) as client:
        for body in [
            {'messages': [{'role': 'assistant', 'text': '안녕.'}]},
            {'messages': [], 'guardian_id': 'not-for-ai'},
        ]:
            assert client.post('/api/worry/chat', json=body).status_code == 422


def test_external_model_is_off_by_default(monkeypatch):
    monkeypatch.delenv('WORRY_ENABLE_MODEL', raising=False)
    adapter = Adapter()
    with TestClient(create_app(DiaryEngine(adapter))) as client:
        response = client.post('/api/worry/chat', json={'messages': [{'role': 'child', 'text': '친구랑 다퉜어.'}]})
    assert response.json()['status'] == 'unavailable'
    assert adapter.calls == []


def test_render_factory_serves_worry_contract_without_external_model(monkeypatch):
    monkeypatch.setenv('WORRY_ENABLE_MODEL', '0')
    router = ProviderRouter(comic_image_attempts=1, cloudflare_http_attempts=1)

    def unexpected_model_call(*args, **kwargs):
        pytest.fail('Disabled worry endpoint must not call the provider')

    monkeypatch.setattr(router, 'parse', unexpected_model_call)
    with TestClient(create_app(DiaryEngine(adapter=router))) as client:
        opening = client.post('/api/worry/chat', json={'messages': []})
        assert opening.status_code == 200
        assert opening.json()['status'] == 'opening'
        assert opening.json()['mock'] is False
        assert opening.headers['Cache-Control'] == 'no-store'

        child_message = {'role': 'child', 'text': '친구랑 다퉜어.'}
        unavailable = client.post('/api/worry/chat', json={'messages': [child_message]})
        assert unavailable.status_code == 200
        assert unavailable.json()['status'] == 'unavailable'

        safe_adult = client.post('/api/worry/chat', json={
            'messages': [{'role': 'child', 'text': '엄마가 나를 때렸어.'}],
        })
        assert safe_adult.status_code == 200
        assert safe_adult.json()['status'] == 'needs_adult'

        too_many = client.post('/api/worry/chat', json={'messages': [child_message] * 25})
        too_long = client.post('/api/worry/chat', json={
            'messages': [{'role': 'child', 'text': '가' * 2000}] * 4 + [child_message],
        })
        for response in (too_many, too_long):
            assert response.status_code == 422
            assert response.json() == {'error': '메시지 형식과 글자 수를 확인해 주세요.'}
