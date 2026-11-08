"""BE-facing invariants and mixed per-scene outcomes, without external calls."""
from fastapi.testclient import TestClient
from engine import DiaryEngine, ProviderError
from models import DiaryCandidate, Sentence, Review
from server import create_app
from scripts.verify_integration import verify_diary
from visual_story import text_hash


class DiaryAdapter:
    def parse(self, instruction, payload, schema):
        if schema is Review:
            return Review(accepted=True)
        return DiaryCandidate(sentences=[Sentence(text='블록을 쌓았다.', source_ids=[1])])


def test_real_path_diary_contract_with_stubbed_provider():
    messages = [{'role': 'assistant', 'text': '무슨 일이 있었어?'},
                {'role': 'child', 'text': '블록을 쌓았어.'}]
    with TestClient(create_app(DiaryEngine(DiaryAdapter()))) as client:
        response = client.post('/api/diary', json={'messages': messages})
    assert response.status_code == 200
    verify_diary(response.json(), messages)
    assert response.json()['mock'] is False
    assert response.json()['fallback'] is False


def test_mixed_scene_outcomes_preserve_previous_success():
    class Adapter:
        def generate_reviewed_image(self, instruction, payload, review):
            if payload['selected_text'] == '책을 펼쳤다.':
                raise ProviderError('test provider unavailable')
            if payload['selected_text'] == '책을 덮었다.':
                return None
            return 'data:image/png;base64,fixture'
    text = '공을 굴렸다. 책을 펼쳤다. 책을 덮었다. 블록을 쌓았다.'
    with TestClient(create_app(DiaryEngine(Adapter()))) as client:
        results = [client.post('/api/visual-story/image', json={
            'diary_text': text, 'diary_hash': text_hash(text), 'source_ids': [i],
            'format': 'comic4', 'confirmed': True}).json() for i in range(4)]
    assert [r['status'] for r in results] == ['generated', 'failed', 'rejected', 'generated']
    assert results[0]['imageUrl'] == results[3]['imageUrl'] == 'data:image/png;base64,fixture'
    assert results[1]['imageUrl'] is results[2]['imageUrl'] is None
    assert len({r['scene_key'] for r in results}) == 4


def test_provider_failure_is_not_reported_as_diary_fallback():
    class Adapter:
        def parse(self, *args):
            raise ProviderError('test quota exceeded')
    with TestClient(create_app(DiaryEngine(Adapter()))) as client:
        response = client.post('/api/diary', json={'messages': [{'role': 'child', 'text': '블록을 쌓았다.'}]})
    assert response.status_code == 503
    assert set(response.json()) == {'error'}


def test_explicit_finish_does_not_call_provider_even_when_unavailable():
    class Unavailable:
        def parse(self, *args):
            raise AssertionError('Explicit finish should not call a model')
    for mock in (True, False):
        with TestClient(create_app(DiaryEngine(Unavailable(), mock=mock))) as client:
            body = client.post('/api/chat', json={'messages': [
                {'role': 'child', 'text': '이제 그만할래. 일기로 만들어 줘.'}]}).json()
        assert body['finished'] is True
        assert body['fallback'] is False
        assert body['mock'] is mock
        assert '?' not in body['question']


def test_negated_or_quoted_finish_is_not_treated_as_stop():
    from models import QuestionCandidate
    class Adapter:
        def parse(self, instruction, payload, schema):
            return Review(accepted=True) if schema is Review else QuestionCandidate(question='더 이야기해 줄래?', finished=False)
    with TestClient(create_app(DiaryEngine(Adapter()))) as client:
        for text in ('그만하고 싶지 않아.', '친구가 그만할래라고 했어.', '그만할래? 아니 계속할래.'):
            body = client.post('/api/chat', json={'messages': [{'role': 'child', 'text': text}]}).json()
            assert body['finished'] is False


def test_sixty_messages_keep_original_indices_and_at_most_six_pages():
    messages = [{'role': 'assistant' if i % 2 == 0 else 'child', 'text': f'{i}번째 이야기'} for i in range(60)]
    with TestClient(create_app(DiaryEngine(mock=True))) as client:
        response = client.post('/api/diary', json={'messages': messages})
    assert response.status_code == 200
    body = response.json()
    verify_diary(body, messages)
    assert len(body['pages']) == 6
    assert [s['id'] for s in body['sources']] == list(range(1, 60, 2))
    assert body['text'] == '\n'.join(m['text'] for m in messages if m['role'] == 'child')


def test_twenty_generated_sentences_are_all_preserved():
    class Adapter:
        def parse(self, instruction, payload, schema):
            if schema is Review:
                return Review(accepted=True)
            return DiaryCandidate(sentences=[Sentence(text=f'{i}번째 일을 했다.', source_ids=[i]) for i in range(20)])
    messages = [{'role': 'child', 'text': f'{i}번째 일을 했어.'} for i in range(20)]
    with TestClient(create_app(DiaryEngine(Adapter()))) as client:
        response = client.post('/api/diary', json={'messages': messages})
    verify_diary(response.json(), messages)
    assert len(response.json()['pages']) <= 6
    assert response.json()['text'] == ' '.join(f'{i}번째 일을 했다.' for i in range(20))


def test_conversation_total_limit_is_not_silently_truncated():
    with TestClient(create_app(DiaryEngine(mock=True))) as client:
        body = {'messages': [{'role': 'child', 'text': '가' * 2000} for _ in range(10)]}
        valid = client.post('/api/diary', json=body)
        assert valid.status_code == 200
        verify_diary(valid.json(), body['messages'])
        body['messages'].append({'role': 'child', 'text': '나'})
        invalid = client.post('/api/diary', json=body)
        assert invalid.status_code == 503
        assert set(invalid.json()) == {'error'}
