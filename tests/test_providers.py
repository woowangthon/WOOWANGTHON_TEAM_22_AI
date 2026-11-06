"""외부 과금 없이 실제 SDK/HTTP 요청 규격과 공급자별 키 분리를 검사합니다."""
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from engine import DiaryEngine, GenerationError
from models import Review
from providers import ProviderRouter
from server import create_app
from visual_story import text_hash


@pytest.fixture
def router(monkeypatch):
    for name, value in {'TEXT_PROVIDER':'groq', 'STT_PROVIDER':'groq',
                        'IMAGE_PROVIDER':'cloudflare', 'VISION_PROVIDER':'groq',
                        'TTS_PROVIDER':'disabled', 'GROQ_API_KEY':'groq-test',
                        'CLOUDFLARE_ACCOUNT_ID':'a'*32, 'CLOUDFLARE_API_TOKEN':'cf-test'}.items():
        monkeypatch.setenv(name, value)
    return ProviderRouter()


def completion(content, finish='stop'):
    return {'id':'test', 'object':'chat.completion', 'created':0, 'model':'test',
            'choices':[{'index':0, 'finish_reason':finish,
                        'message':{'role':'assistant', 'content':json.dumps(content)}}]}


def bind_groq(router, handler):
    router.groq = OpenAI(api_key='groq-test', base_url='https://api.groq.com/openai/v1',
                         max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_text_schema_and_credentials(router):
    def handler(request):
        assert request.url.host == 'api.groq.com'
        assert request.headers['authorization'] == 'Bearer groq-test'
        body=json.loads(request.read())
        assert body['model']=='openai/gpt-oss-20b'
        assert body['response_format']['json_schema']['strict'] is True
        assert body['response_format']['json_schema']['schema']['additionalProperties'] is False
        return httpx.Response(200, json=completion({'accepted':True}))
    bind_groq(router,handler)
    try:
        assert router.parse('review',{'text':'test'},Review).accepted
    finally:
        router.groq.close()


@pytest.mark.parametrize('content,finish', [({'accepted':'invalid'},'stop'), ({'accepted':True},'length')])
def test_invalid_or_truncated_text_is_rejected(router,content,finish):
    bind_groq(router,lambda req:httpx.Response(200,json=completion(content,finish)))
    try:
        with pytest.raises(GenerationError):router.parse('review',{},Review)
    finally:router.groq.close()


@pytest.mark.parametrize('status,code,hint',[(401,'invalid_api_key','API 키'),
    (429,'credit_balance_exhausted','크레딧'),(429,'rate_limit_exceeded','한도'),
    (404,'model_not_found','모델')])
def test_errors_are_actionable_and_do_not_leak(router,status,code,hint):
    bind_groq(router,lambda req:httpx.Response(status,json={'error':{
        'message':'SECRET-KEY-AND-CHILD-TEXT','code':code,'type':'test'}}))
    try:
        with TestClient(create_app(DiaryEngine(router))) as client:
            response=client.post('/api/chat',json={'messages':[{'role':'child','text':'놀았어.'}]})
        assert response.status_code==503
        assert hint in response.json()['error']
        assert 'SECRET' not in response.text and 'groq-test' not in response.text
    finally:router.groq.close()


def test_groq_stt_uses_its_own_key_and_korean(router):
    def handler(request):
        assert request.url.path.endswith('/audio/transcriptions')
        assert request.headers['authorization']=='Bearer groq-test'
        body=request.read()
        assert b'whisper-large-v3-turbo' in body and b'recording.m4a' in body
        assert b'\r\nko\r\n' in body
        return httpx.Response(200,json={'text':'친구와 놀았어.'})
    bind_groq(router,handler)
    try:
        with TestClient(create_app(DiaryEngine(router))) as client:
            response=client.post('/api/transcribe',files={'file':('private-name.m4a',b'audio','audio/mp4')})
        assert response.status_code==200 and response.json()['requires_confirmation']
    finally:router.groq.close()


def test_disabled_tts_preserves_question_without_calls(router):
    with TestClient(create_app(DiaryEngine(router))) as client:
        result=client.post('/api/voice-chat',json={'messages':[]}).json()
        assert result['question']=='오늘은 무슨 일이 있었어?'
        assert result['audio_base64'] is None and '꺼져' in result['audio_error']
        assert client.post('/api/speech',json={'text':'안녕?'}).status_code==503
    assert 'openai' not in router.__dict__ and 'groq' not in router.__dict__


def test_status_uses_text_provider_key(router,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with TestClient(create_app(DiaryEngine(router))) as client:
        assert client.get('/api/status').json()['configured']
        monkeypatch.delenv('GROQ_API_KEY')
        assert not client.get('/api/status').json()['configured']


@pytest.mark.parametrize('accepted',[True,False])
def test_cloudflare_image_then_groq_vision(router,monkeypatch,accepted):
    calls=[]
    jpeg=base64.b64encode(b'\xff\xd8\xff-test-jpeg').decode()
    def groq_handler(request):
        body=json.loads(request.read());calls.append(body)
        if len(calls)==1:
            return httpx.Response(200,json=completion({'description':'Watercolor silhouette of a child playing ball. Blank background.'}))
        assert body['model']=='qwen/qwen3.8-27b'
        assert body['response_format']=={'type':'json_object'}
        assert body['messages'][1]['content'][1]['image_url']['url'].endswith(jpeg)
        return httpx.Response(200,json=completion({'accepted':accepted}))
    bind_groq(router,groq_handler)
    original_client=httpx.Client
    def cloudflare_handler(request):
        assert request.url.host=='api.cloudflare.com'
        assert request.url.path.endswith('/@cf/black-forest-labs/flux-1-schnell')
        assert request.headers['authorization']=='Bearer cf-test'
        body=json.loads(request.read())
        assert len(body['prompt'])<=2048 and body['steps']==4
        return httpx.Response(200,json={'success':True,'result':{'image':jpeg}})
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original_client(
        **kw,transport=httpx.MockTransport(cloudflare_handler)))
    try:
        with TestClient(create_app(DiaryEngine(router))) as client:
            response=client.post('/api/visual-story/image',json={
                'diary_text':'공놀이를 했다.', 'diary_hash':text_hash('공놀이를 했다.'),
                'source_ids':[0], 'format':'storybook','confirmed':True})
        assert response.status_code==200
        assert response.json()['status']==('generated' if accepted else 'rejected')
        assert bool(response.json()['imageUrl'])==accepted
        assert response.json()['caption']=='공놀이를 했다.'
        assert len(calls)==2
    finally:router.groq.close()


def test_missing_cloudflare_key_fails_before_any_network(router,monkeypatch):
    monkeypatch.delenv('CLOUDFLARE_API_TOKEN')
    with pytest.raises(GenerationError,match='CLOUDFLARE_API_TOKEN'):
        router.generate_reviewed_image('rules',{'text':'test'},'review')
    assert 'openai' not in router.__dict__


@pytest.mark.parametrize('status',[401,403,429,500])
def test_cloudflare_http_errors_are_safe(router,monkeypatch,status):
    original_client=httpx.Client
    def handler(request):
        return httpx.Response(status,json={'error':'SECRET-PROVIDER-DETAIL'})
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original_client(
        **kw,transport=httpx.MockTransport(handler)))
    with pytest.raises(GenerationError) as exc:
        router._cloudflare_image('test')
    assert 'SECRET' not in str(exc.value) and 'cf-test' not in str(exc.value)
    assert 'cloudflare' in str(exc.value)


def test_cloudflare_invalid_image_is_not_returned(router,monkeypatch):
    original_client=httpx.Client
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original_client(
        **kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,json={
            'success':True,'result':{'image':base64.b64encode(b'not an image').decode()}}))))
    with pytest.raises(GenerationError,match='이미지 형식'):
        router._cloudflare_image('test')


def test_openai_opt_in_sends_only_openai_key(router,monkeypatch):
    monkeypatch.setenv('TTS_PROVIDER','openai')
    live=ProviderRouter()
    def handler(request):
        assert request.url.host=='api.openai.com'
        assert request.headers['authorization']=='Bearer openai-test'
        return httpx.Response(200,content=b'ID3-test',headers={'content-type':'audio/mpeg'})
    live.openai=OpenAI(api_key='openai-test',max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:assert live.speech('안녕?')==b'ID3-test'
    finally:live.openai.close()
