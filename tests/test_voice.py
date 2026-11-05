"""실제 마이크·API 키 없이 음성 연결 규격과 실패 처리를 검사합니다."""
import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from engine import DiaryEngine
from models import QuestionCandidate, Review
from server import create_app
from voice import MAX_AUDIO_BYTES


class AudioAdapter:
    def __init__(self, transcript='친구와 놀았어.', speech_ok=True, question_ok=True):
        self.calls = []
        self.transcript = transcript
        self.speech_ok = speech_ok
        self.question_ok = question_ok
        self.client = OpenAI(api_key='test-only', max_retries=0,
                             http_client=httpx.Client(transport=httpx.MockTransport(self.handle)))

    def parse(self, instruction, payload, schema):
        if schema is Review:
            return Review(accepted=self.question_ok)
        return QuestionCandidate(question='어떤 놀이를 했어?',finished=False)

    def handle(self, request):
        body = request.read()
        self.calls.append((request.url.path, body))
        if request.url.path.endswith('/transcriptions'):
            return httpx.Response(200,json={'text':self.transcript})
        if request.url.path.endswith('/speech'):
            if not self.speech_ok:
                return httpx.Response(429,json={'error':{'message':'test-private-provider-message','type':'rate_limit'}})
            return httpx.Response(200,content=b'ID3-fake-test-audio',headers={'content-type':'audio/mpeg'})
        raise AssertionError('예상하지 못한 제공자 호출')


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv('STT_MODEL','gpt-transcribe')
    monkeypatch.setenv('TTS_MODEL','gpt-4o-mini-tts')
    monkeypatch.setenv('TTS_VOICE','coral')
    adapter=AudioAdapter()
    with TestClient(create_app(DiaryEngine(adapter))) as client:
        yield SimpleNamespace(client=client,adapter=adapter)
    adapter.client.close()


def upload(client, data=b'fake-audio', name='recording.webm', mime='audio/webm'):
    return client.post('/api/transcribe',files={'file':(name,data,mime)})


def test_transcription_is_confirmation_draft(api):
    result=upload(api.client,name='private-child-name.webm',mime='audio/webm;codecs=opus')
    assert result.status_code==200
    assert result.json()=={'text':'친구와 놀았어.','requires_confirmation':True,'mock':False}
    path,body=api.adapter.calls[0]
    assert path.endswith('/transcriptions')
    assert b'gpt-transcribe' in body and b'recording.webm' in body
    assert b'private-child-name' not in body
    assert len(api.adapter.calls)==1  # 전사만으로 질문이나 일기를 만들지 않습니다.


@pytest.mark.parametrize('name,mime,status',[
    ('clip.exe','audio/webm',415),('clip.webm','text/html',415),
    ('clip.m4a','audio/mp4',200),('clip.webm','application/octet-stream',200)])
def test_upload_types(api,name,mime,status):
    assert upload(api.client,name=name,mime=mime).status_code==status
    if status!=200:
        assert not api.adapter.calls


def test_empty_upload_does_not_call_provider(api):
    assert upload(api.client,data=b'').status_code==400
    assert not api.adapter.calls


def test_large_upload_does_not_call_provider(api):
    assert upload(api.client,data=b'x'*(MAX_AUDIO_BYTES+1)).status_code==413
    assert not api.adapter.calls


@pytest.mark.parametrize('text',['', '  ', '가'*2001])
def test_unusable_transcript_not_committed(api,text):
    api.adapter.transcript=text
    result=upload(api.client)
    assert result.status_code==503
    assert len(api.adapter.calls)==1


def test_speech_binary_and_no_store(api):
    result=api.client.post('/api/speech',json={'text':'오늘은 무슨 일이 있었어?'})
    assert result.status_code==200
    assert result.content==b'ID3-fake-test-audio'
    assert result.headers['content-type']=='audio/mpeg'
    assert result.headers['cache-control']=='no-store'
    body=json.loads(api.adapter.calls[0][1])
    assert body['input']=='오늘은 무슨 일이 있었어?'
    assert body['response_format']=='mp3' and body['voice']=='coral'


@pytest.mark.parametrize('text',['', '  ', '가'*1001])
def test_speech_invalid_input(api,text):
    assert api.client.post('/api/speech',json={'text':text}).status_code==422
    assert not api.adapter.calls


def test_voice_chat_starts_and_returns_audio(api):
    response=api.client.post('/api/voice-chat',json={'messages':[]})
    assert response.status_code==200
    result=response.json()
    assert result['question']=='오늘은 무슨 일이 있었어?'
    assert base64.b64decode(result['audio_base64'])==b'ID3-fake-test-audio'
    assert result['audio_mime_type']=='audio/mpeg' and result['audio_error'] is None
    assert result['fallback'] is False


def test_rejected_question_is_not_spoken(api):
    api.adapter.question_ok=False
    result=api.client.post('/api/voice-chat',json={'messages':[{'role':'child','text':'공놀이 했어.'}]}).json()
    assert result['fallback'] is True
    assert json.loads(api.adapter.calls[0][1])['input']=='더 들려주고 싶은 이야기가 있어?'


def test_tts_failure_preserves_question(api):
    api.adapter.speech_ok=False
    result=api.client.post('/api/voice-chat',json={'messages':[]})
    assert result.status_code==200
    body=result.json()
    assert body['question']=='오늘은 무슨 일이 있었어?'
    assert body['audio_base64'] is None and body['audio_error']
    assert 'test-private-provider-message' not in result.text
    assert len(api.adapter.calls)==1


def test_separate_speech_failure_is_sanitized(api):
    api.adapter.speech_ok=False
    result=api.client.post('/api/speech',json={'text':'안녕?'})
    assert result.status_code==502
    assert 'test-private-provider-message' not in result.text


def test_mock_never_fakes_transcription_or_audio():
    with TestClient(create_app(DiaryEngine(mock=True))) as client:
        assert upload(client).status_code==503
        assert client.post('/api/speech',json={'text':'안녕?'}).status_code==503
        reply=client.post('/api/voice-chat',json={'messages':[]}).json()
        assert reply['mock'] and reply['audio_base64'] is None and reply['audio_error']
