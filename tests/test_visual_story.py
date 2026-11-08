"""그림책·4컷의 원문 보존, 컷 수, 부분 실패, SDK 연결 규격을 검사합니다."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from image_fixture import encoded_image
from engine import DiaryEngine, GenerationError
from server import create_app
from visual_models import ScenePlan, SceneGroup
from visual_story import VisualStoryService, text_hash

DIARY = '공원에 갔다. 친구를 만났다. 공놀이를 했다. 즐거웠다. 집에 왔다.'


class FakeAdapter:
    def __init__(self, groups=None, fail=False):
        self.groups = groups
        self.fail = fail
        self.calls = []

    def parse(self, instruction, payload, schema):
        self.calls.append(payload)
        if self.fail:
            raise GenerationError('test')
        return ScenePlan(scenes=[SceneGroup(source_ids=ids) for ids in self.groups])


@pytest.fixture
def mock_api():
    with TestClient(create_app(DiaryEngine(mock=True))) as client:
        yield client


def plan(client, text=DIARY, **kwargs):
    return client.post('/api/visual-story', json={'diary_text':text,'confirmed':True,**kwargs})


def test_both_formats_preserve_original(mock_api):
    result = plan(mock_api).json()
    assert len(result['comic4']['scenes']) == 4
    assert result['comic4']['layout'] == 'grid_2x2'
    assert result['storybook']['layout'] == 'pages'
    for kind in ['storybook','comic4']:
        scenes = result[kind]['scenes']
        assert [sid for scene in scenes for sid in scene['source_ids']] == list(range(5))
        for scene in scenes:
            assert scene['caption'] == '\n'.join(result['sources'][sid]['text'] for sid in scene['source_ids'])
            assert scene['imageUrl'] is None
    assert result['mock']


@pytest.mark.parametrize('count',[1,2,3])
def test_short_input_reuses_scene_without_new_events(mock_api,count):
    text='\n'.join(f'{i}번째 문장' for i in range(count))
    result=plan(mock_api,text).json()
    scenes=result['comic4']['scenes']
    assert len(scenes)==4
    assert len(result['storybook']['scenes'])==count
    for scene in scenes[count:]:
        assert scene['repeated']
        assert scene['caption']==scenes[count-1]['caption']
        assert scene['reuse_scene_id']==scenes[count-1]['scene_id']


@pytest.mark.parametrize('groups',[
    [[0],[1],[2],[3]],                  # 원문 누락
    [[0],[1],[2],[3,4,5]],              # 없는 근거
    [[0],[2],[1],[3,4]],                # 순서 변경
    [[0],[1],[2],[2,3,4]],              # 중복
    [[0],[],[1],[2,3,4]],               # 빈 장면
])
def test_invalid_plan_falls_back(groups):
    with TestClient(create_app(DiaryEngine(FakeAdapter(groups)))) as client:
        result=plan(client,format='comic4').json()
    assert result['comic4']['planning_mode']=='fallback'
    assert [sid for scene in result['comic4']['scenes'] for sid in scene['source_ids']]==list(range(5))


def test_model_groups_used_without_generated_caption():
    adapter=FakeAdapter([[0],[1,2],[3],[4]])
    with TestClient(create_app(DiaryEngine(adapter))) as client:
        result=plan(client,format='comic4').json()
    assert result['storybook'] is None
    assert result['comic4']['planning_mode']=='model'
    assert result['comic4']['scenes'][1]['caption']=='친구를 만났다.\n공놀이를 했다.'
    assert adapter.calls[0]['target_count']==4


def test_model_error_preserves_all_diary():
    with TestClient(create_app(DiaryEngine(FakeAdapter(fail=True)))) as client:
        result=plan(client,format='comic4').json()
    assert result['comic4']['planning_mode']=='fallback'
    assert len(result['sources'])==5


@pytest.mark.parametrize('body,status',[
    ({'diary_text':DIARY},400),
    ({'diary_text':'  ','confirmed':True},422),
    ({'diary_text':'가'*6001,'confirmed':True},422),
    ({'diary_text':DIARY,'confirmed':True,'format':'comic8'},422),
    ({'diary_text':DIARY,'confirmed':True,'storybook_pages':7},422),
    ({'diary_text':'\n'.join(['문장']*81),'confirmed':True},422),
])
def test_request_limits(mock_api,body,status):
    assert mock_api.post('/api/visual-story',json=body).status_code==status


def image_body(text=DIARY,ids=None):
    return {'diary_text':text,'diary_hash':text_hash(text),'source_ids':ids or [0],
            'format':'comic4','confirmed':True}


@pytest.mark.parametrize('ids',[[-1],[999],[1,0],[0,0],[0,2]])
def test_bad_image_sources_rejected(mock_api,ids):
    assert mock_api.post('/api/visual-story/image',json=image_body(ids=ids)).status_code==422


def test_edited_diary_hash_conflict(mock_api):
    body=image_body();body['diary_text']='새로 수정한 일기'
    assert mock_api.post('/api/visual-story/image',json=body).status_code==409


def test_image_requires_confirmation(mock_api):
    body=image_body();body['confirmed']=False
    assert mock_api.post('/api/visual-story/image',json=body).status_code==400


def test_mock_image_explicitly_has_no_picture(mock_api):
    result=mock_api.post('/api/visual-story/image',json=image_body()).json()
    assert result['status']=='mock' and result['imageUrl'] is None
    assert result['caption']=='공원에 갔다.'


def test_image_failure_is_scoped_to_scene(monkeypatch):
    def fail(*args):
        raise GenerationError('private-provider-detail')
    monkeypatch.setattr(VisualStoryService,'_generate_image',fail)
    with TestClient(create_app(DiaryEngine(FakeAdapter()))) as client:
        response=client.post('/api/visual-story/image',json=image_body())
    assert response.status_code==200
    result=response.json()
    assert result['status']=='failed' and result['caption']=='공원에 갔다.'
    assert result['error'] and 'private-provider-detail' not in response.text


@pytest.mark.parametrize('accepted,status',[(True,'generated'),(False,'rejected')])
def test_real_sdk_request_shapes_with_fake_network(monkeypatch,accepted,status):
    calls=[]
    monkeypatch.setenv('IMAGE_MODEL','gpt-image-1.5')
    monkeypatch.setenv('TEXT_MODEL','gpt-4.1-mini')
    def handler(request):
        body=json.loads(request.read());calls.append((request.url.path,body))
        if request.url.path.endswith('/images/generations'):
            return httpx.Response(200,json={'created':0,'data':[{'b64_json':encoded_image()}]})
        return httpx.Response(200,json={
            'id':'resp_test','object':'response','created_at':0,'model':'gpt-4.1-mini',
            'status':'completed','output':[{'id':'msg_test','type':'message','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':json.dumps({'accepted':accepted}),'annotations':[]}]}]})
    adapter=FakeAdapter()
    adapter.client=OpenAI(api_key='test-only',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        with TestClient(create_app(DiaryEngine(adapter))) as client:
            response=client.post('/api/visual-story/image',json=image_body())
        assert response.status_code==200
        result=response.json()
        assert result['status']==status
        assert bool(result['imageUrl'])==accepted
        assert calls[0][1]['output_format']=='png'
        assert calls[0][1]['model']=='gpt-image-1.5'
        assert '단일 컷' in calls[0][1]['prompt']
        assert calls[1][1]['store'] is False
        assert calls[1][1]['input'][1]['content'][1]['type']=='input_image'
    finally:
        adapter.client.close()


def test_scene_key_distinguishes_formats(mock_api):
    body=image_body()
    comic=mock_api.post('/api/visual-story/image',json=body).json()
    body['format']='storybook'
    book=mock_api.post('/api/visual-story/image',json=body).json()
    assert comic['scene_key']!=book['scene_key']
