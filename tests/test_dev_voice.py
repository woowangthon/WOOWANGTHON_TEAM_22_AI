"""개발 화면의 명시적 활성화·로컬 접근·제품 API 계약을 검증합니다."""
import pytest
from fastapi.testclient import TestClient
from engine import DiaryEngine
from server import create_app


def client_at(host='127.0.0.1'):
    return TestClient(create_app(DiaryEngine(mock=True)),client=(host,50000))


def test_demo_disabled_by_default(monkeypatch):
    monkeypatch.delenv('ENABLE_VOICE_DEMO',raising=False)
    with client_at() as client:
        assert client.get('/dev/voice').status_code==404
        assert client.get('/dev/voice/app.js').status_code==404


@pytest.mark.parametrize('host',['127.0.0.1','::1'])
def test_local_demo_and_assets(monkeypatch,host):
    monkeypatch.setenv('ENABLE_VOICE_DEMO','1')
    with client_at(host) as client:
        response=client.get('/dev/voice')
        assert response.status_code==200
        assert response.headers['cache-control']=='no-store'
        assert '마이크로 대화 시작' in response.text
        for name in ['app.js','core.mjs','illustration.mjs','style.css']:
            asset=client.get('/dev/voice/'+name)
            assert asset.status_code==200
            assert asset.headers['cache-control']=='no-store'
        assert client.get('/dev/voice/.env').status_code==404
        assert len(client.get('/openapi.json').json()['paths'])==9


def test_remote_demo_forbidden_but_api_unchanged(monkeypatch):
    monkeypatch.setenv('ENABLE_VOICE_DEMO','1')
    with client_at('203.0.113.1') as client:
        assert client.get('/dev/voice').status_code==403
        assert client.get('/dev/voice/app.js').status_code==403
        assert client.get('/api/status').status_code==200
