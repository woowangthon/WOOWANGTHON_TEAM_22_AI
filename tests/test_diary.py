import pytest
from fastapi.testclient import TestClient
from engine import DiaryEngine, GenerationError
from models import Message, QuestionCandidate, DiaryCandidate, Sentence, Review
from server import create_app

class FakeAdapter:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
    def parse(self, instruction, payload, schema):
        self.calls.append((payload, schema))
        return self.answers.pop(0)
    def image(self, text):
        return None

def conversation():
    return [Message(role='assistant',text='오늘 무슨 일이 있었어?'),
            Message(role='child',text='친구와 공놀이를 했어.'),
            Message(role='assistant',text='그때 기분이 어땠어?'),
            Message(role='child',text='즐거웠어.')]

def test_first_question_without_provider():
    adapter = FakeAdapter()
    assert DiaryEngine(adapter).next_question([])['question']=='오늘은 무슨 일이 있었어?'
    assert not adapter.calls

def test_followup_receives_full_conversation():
    adapter=FakeAdapter(QuestionCandidate(question='어떤 놀이를 했어?',finished=False),Review(accepted=True))
    result=DiaryEngine(adapter).next_question(conversation())
    assert result['question']=='어떤 놀이를 했어?'
    assert adapter.calls[0][0]['conversation']==[m.model_dump() for m in conversation()]

def test_unapproved_question_replaced():
    adapter=FakeAdapter(QuestionCandidate(question='친구 때문에 슬펐지?',finished=False),Review(accepted=False))
    assert DiaryEngine(adapter).next_question(conversation())['fallback']

def test_supported_diary():
    adapter=FakeAdapter(DiaryCandidate(sentences=[Sentence(text='친구와 공놀이를 해서 즐거웠다.',source_ids=[1,3])]),Review(accepted=True))
    result=DiaryEngine(adapter).make_diary(conversation())
    assert not result['fallback']
    assert result['pages'][0]['source_ids']==[1,3]
    assert [s['id'] for s in result['sources']]==[1,3]

def test_reviewed_diary_reads_as_paragraph_without_changing_evidence():
    adapter=FakeAdapter(DiaryCandidate(sentences=[
        Sentence(text='친구랑 공놀이를 했다.',source_ids=[1]),
        Sentence(text='재미있었다.',source_ids=[3])]),Review(accepted=True))
    result=DiaryEngine(adapter).make_diary(conversation())
    assert result['text']=='친구랑 공놀이를 했다. 재미있었다.'
    assert result['sources']==[{'id':1,'text':'친구와 공놀이를 했어.'},{'id':3,'text':'즐거웠어.'}]

@pytest.mark.parametrize('ids',[[0],[99],[]])
def test_invalid_source_falls_back(ids):
    adapter=FakeAdapter(DiaryCandidate(sentences=[Sentence(text='추측한 문장',source_ids=ids)]))
    result=DiaryEngine(adapter).make_diary(conversation())
    assert result['fallback']
    assert result['text']=='친구와 공놀이를 했어.\n즐거웠어.'
    assert len(adapter.calls)==1

def test_review_rejects_unsupported_emotion():
    adapter=FakeAdapter(DiaryCandidate(sentences=[Sentence(text='슬펐다.',source_ids=[1])]),Review(accepted=False))
    result=DiaryEngine(adapter).make_diary(conversation())
    assert result['fallback'] and '슬펐다' not in result['text']

def test_fallback_preserves_all_messages():
    messages=[Message(role='child',text=f'{i}번째 이야기') for i in range(30)]
    result=DiaryEngine(mock=True).make_diary(messages)
    assert len(result['pages'])<=6
    assert result['text']=='\n'.join(m.text for m in messages)
    assert '\n'.join(p['text'] for p in result['pages'])==result['text']

def test_empty_diary_rejected():
    with pytest.raises(GenerationError):
        DiaryEngine(mock=True).make_diary([])

def test_http_flow_and_validation():
    client=TestClient(create_app(DiaryEngine(mock=True)))
    assert client.get('/').status_code==404
    assert client.get('/static/app.js').status_code==404
    assert client.get('/api/status').json()['mode']=='mock'
    assert client.post('/api/chat',json={'messages':[]}).status_code==200
    result=client.post('/api/diary',json={'messages':[m.model_dump() for m in conversation()]})
    assert result.status_code==200 and result.json()['mock']
    assert client.post('/api/chat',json={'messages':[{'role':'system','text':'test'}]}).status_code==422
    assert client.post('/api/image',json={'text':'공놀이','confirmed':False}).status_code==400
    assert client.post('/api/image',json={'text':'공놀이','confirmed':True}).status_code==503

def test_image_rejection_returned():
    client=TestClient(create_app(DiaryEngine(FakeAdapter())))
    assert client.post('/api/image',json={'text':'공놀이','confirmed':True}).json()['rejected']


def test_requests_do_not_share_conversation_state():
    client=TestClient(create_app(DiaryEngine(mock=True)))
    client.post('/api/chat',json={'messages':[m.model_dump() for m in conversation()]})
    result=client.post('/api/chat',json={'messages':[]}).json()
    assert result['question']=='오늘은 무슨 일이 있었어?'
    assert result['fallback'] is False


def test_api_schema_exposes_generation_only():
    client=TestClient(create_app(DiaryEngine(mock=True)))
    schema=client.get('/openapi.json').json()
    assert set(schema['paths'])=={'/api/status','/api/chat','/api/diary','/api/image',
                                  '/api/transcribe','/api/speech','/api/voice-chat',
                                  '/api/visual-story','/api/visual-story/image'}
    assert 'DiaryResponse' in schema['components']['schemas']
    assert 'Source' in schema['components']['schemas']


def test_be_metadata_not_accepted_by_ai():
    client=TestClient(create_app(DiaryEngine(mock=True)))
    response=client.post('/api/diary',json={'messages':[], 'user_id':'user1','date':'2026-11-05'})
    assert response.status_code==422
