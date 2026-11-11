"""외부 과금 없이 실제 SDK/HTTP 요청 규격과 공급자별 키 분리를 검사합니다."""
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from image_fixture import encoded_image
from engine import DiaryEngine, GenerationError
from models import Review
from providers import ProviderRouter, cloudflare_prompt
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


@pytest.mark.parametrize('kind',['comic4','storybook'])
def test_cloudflare_plan_and_images_never_call_groq_or_openai(router,monkeypatch,kind):
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    def forbidden(*args,**kwargs):
        raise AssertionError('Cloudflare generation must not call a text or vision model')
    monkeypatch.setattr(router,'parse',forbidden)
    monkeypatch.setattr(router,'_review_image',forbidden)
    monkeypatch.setattr('comic_images.has_lettering', lambda data:False)
    calls=[]
    original_client=httpx.Client
    def handler(request):
        assert request.url.host=='api.cloudflare.com'
        assert request.headers['authorization']=='Bearer cf-test'
        body=json.loads(request.read())
        if 'messages' in body and isinstance(body['messages'][1]['content'],list):
            review_text = body['messages'][1]['content'][0]['text']
            evidence = json.loads(review_text.split(': ', 1)[1])
            assert evidence['captions'][evidence['scene']['index']]
            assert 'action_quote' not in evidence['scene'] and 'source_quote' not in evidence['scene']
            return httpx.Response(200,json={'success':True,'result':completion({**{name:True for name in ('objects','action','appearance','grounding','lettering','composition','character')},'object_counts':[1]})})
        if 'messages' in body:
            captions=json.loads(body['messages'][1]['content'])['captions']
            specs={'scenes':[{'index':i,'objects':[{'name':'blocks','source_quote':caption}],
                             'action':'The narrator stacks blocks.','mode':'actual'}
                            for i,caption in enumerate(captions)]}
            return httpx.Response(200,json={'success':True,'result':completion(specs)})
        assert len(body['prompt'])<=2048 and body['steps']==8
        if kind=='storybook':assert json.loads(body['prompt'].split('\n',1)[1])['selected_text']
        else:assert 'Main visible objects: blocks' in body['prompt']
        calls.append(body['prompt'])
        from PIL import Image
        import io
        stream=io.BytesIO();Image.new('RGB',(512,512),'white').save(stream,format='JPEG')
        return httpx.Response(200,json={'success':True,'result':{'image':base64.b64encode(stream.getvalue()).decode()}})
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original_client(
        **kw,transport=httpx.MockTransport(handler)))
    text='집에서 블록을 쌓았다. 탑이 무너졌다. 밑을 넓게 만들었다. 다시 쌓았다. 탑이 완성되었다. 기뻤다.'
    with TestClient(create_app(DiaryEngine(router))) as client:
        response=client.post('/api/visual-story',json={'diary_text':text,'format':kind,'confirmed':True})
        assert response.status_code==200
        plan=response.json()
        assert plan[kind]['planning_mode']=='deterministic'
        assert plan[kind]['notices']
        for scene in plan[kind]['scenes']:
            rendered=client.post('/api/visual-story/image',json={
                'diary_text':text,'diary_hash':plan['diary_hash'],
                'source_ids':scene['source_ids'],'format':kind,'confirmed':True})
            assert rendered.status_code==200
            result=rendered.json()
            assert result['status']=='generated'
            assert result['imageUrl'].startswith('data:image/jpeg;base64,')
            assert result['caption']==scene['caption']
            assert result['source_ids']==scene['source_ids']
            assert result['requires_confirmation'] is True
    assert len(calls)==4
    assert 'groq' not in router.__dict__ and 'openai' not in router.__dict__


def test_cloudflare_prompt_preserves_selected_source_when_context_is_too_long():
    selected='“공원은 아니고 집이야”라고 말했다. 블록을 쌓았다.'
    prompt=cloudflare_prompt({'format':'comic4','selected_text':selected,'diary_context':'긴 일기'*1500})
    source=json.loads(prompt.split('\n',1)[1])
    assert source=={'selected_text':selected}
    assert len(prompt)<=2048
    assert 'cream bean-shaped mascot' in prompt


def test_cloudflare_prompt_rejects_long_scene_without_truncation():
    with pytest.raises(GenerationError,match='입력 한도'):
        cloudflare_prompt({'selected_text':'가'*2048})


def test_cloudflare_failure_keeps_image_response_contract(router,monkeypatch):
    original_client=httpx.Client
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original_client(
        **kw,transport=httpx.MockTransport(lambda request:httpx.Response(429,json={'error':'private'}))))
    text='블록을 쌓았다.'
    with TestClient(create_app(DiaryEngine(router))) as client:
        response=client.post('/api/visual-story/image',json={
            'diary_text':text,'diary_hash':text_hash(text),'source_ids':[0],
            'format':'comic4','confirmed':True})
    assert response.status_code==200
    assert response.json()['status']=='failed'
    assert response.json()['imageUrl'] is None
    assert 'private' not in response.text


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
    with pytest.raises(GenerationError,match='응답 형식'):
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


@pytest.mark.parametrize('finish', ['length', 'content_filter'])
def test_incomplete_vision_is_failed_not_rejected(router, monkeypatch, finish):
    bind_groq(router, lambda request: httpx.Response(200, json=completion({'accepted': False}, finish)))
    monkeypatch.setattr(router, 'generate_reviewed_image', lambda *args: (
        'data:image/png;base64,' + encoded_image()
        if router._review_image('data:image/png;base64,' + encoded_image(), 'review', {}) else None))
    try:
        with TestClient(create_app(DiaryEngine(router))) as client:
            result = client.post('/api/visual-story/image', json={
                'diary_text': '블록을 쌓았다.', 'diary_hash': text_hash('블록을 쌓았다.'),
                'source_ids': [0], 'format': 'comic4', 'confirmed': True}).json()
        assert result['status'] == 'failed'
        assert result['imageUrl'] is None
        assert result['error']
    finally:
        router.groq.close()


@pytest.mark.parametrize('raw', [b'\xff\xd8\xff-truncated', b'\x89PNG\r\n\x1a\n-truncated'])
def test_signature_only_image_is_rejected_before_review(router, monkeypatch, raw):
    original_client = httpx.Client
    monkeypatch.setattr('providers.HTTPClient', lambda **kw: original_client(
        **kw, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'success': True, 'result': {'image': base64.b64encode(raw).decode()}}))))
    with pytest.raises(GenerationError, match='응답 형식'):
        router._cloudflare_image('test')


def test_empty_openai_vision_is_failure_not_rejection(router):
    router.vision_provider = 'openai'
    router.openai = OpenAI(api_key='test-only', max_retries=0, http_client=httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
            'id': 'resp_test', 'object': 'response', 'created_at': 0, 'model': 'test',
            'status': 'completed', 'output': []}))))
    try:
        with pytest.raises(GenerationError, match='비어'):
            router._review_image('data:image/png;base64,' + encoded_image(), 'review', {})
    finally:
        router.openai.close()


def test_openai_corrupt_image_fails_before_vision(router):
    router.image_provider = 'openai'
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'created': 0, 'data': [{'b64_json': 'broken-base64'}]})
    router.openai = OpenAI(api_key='test-only', max_retries=0, http_client=httpx.Client(
        transport=httpx.MockTransport(handler)))
    try:
        with pytest.raises(GenerationError, match='이미지 파일'):
            router.generate_reviewed_image('rules', {}, 'review')
        assert calls == ['/v1/images/generations']
    finally:
        router.openai.close()
