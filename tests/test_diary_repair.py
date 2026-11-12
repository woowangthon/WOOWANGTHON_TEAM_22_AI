"""Real engine/HTTP paths with scripted providers; never call external models."""
import logging

import pytest
from fastapi.testclient import TestClient

from engine import DiaryEngine, ProviderError
from models import DiaryCandidate, Message, Review, Sentence
from scripts.verify_integration import verify_diary
from server import create_app
from test_diary import FakeAdapter


def candidate(text, ids):
    return DiaryCandidate(sentences=[Sentence(text=text, source_ids=ids)])


def corrected_conversation():
    return [
        Message(role='assistant', text='오늘 무슨 일이 있었어?'),
        Message(role='child', text='친구랑 공원에서 공놀이 했어.'),
        Message(role='assistant', text='어떤 공을 썼어?'),
        Message(role='child', text='응'),
        Message(role='assistant', text='더 이야기해 줄래?'),
        Message(role='child', text='아니, 공원이 아니라 집이었어. 공놀이는 안 했고 블록을 쌓았어.'),
        Message(role='assistant', text='기분은 어땠어?'),
        Message(role='child', text='기분은 말하기 싫어.'),
        Message(role='assistant', text='더 남기고 싶은 이야기가 있어?'),
        Message(role='child', text='이제 그만할래. 일기로 만들어 줘.'),
    ]


def post_diary(adapter, messages):
    request = [m.model_dump() for m in messages]
    with TestClient(create_app(DiaryEngine(adapter))) as client:
        response = client.post('/api/diary', json={'messages': request})
    if response.status_code == 200:
        verify_diary(response.json(), request)
    return response


def test_review_rejection_repairs_corrected_facts_and_preserves_all_sources(caplog):
    messages = corrected_conversation()
    rejected = candidate('친구와 공원에서 공놀이를 했다.', [1])
    repaired = candidate('친구와 집에서 블록을 쌓았다.', [1, 5])
    adapter = FakeAdapter(rejected, Review(accepted=False), repaired, Review(accepted=True))
    with caplog.at_level(logging.INFO, logger='engine'):
        response = post_diary(adapter, messages)
    assert response.status_code == 200
    body = response.json()
    assert body['text'] == '친구와 집에서 블록을 쌓았다.'
    assert body['fallback'] is body['mock'] is False
    assert body['pages'] == [{'text': body['text'], 'source_ids': [1, 5], 'imageUrl': None}]
    assert body['requires_confirmation'] is True
    assert body['sources'] == [{'id': i, 'text': m.text} for i, m in enumerate(messages) if m.role == 'child']
    assert len(adapter.calls) == 4
    repair_payload = adapter.calls[2][0]
    assert 'previous_candidate' not in repair_payload
    assert repair_payload['sources'] == body['sources']
    assert repair_payload['conversation'] == [m.model_dump() for m in messages]
    assert 'outcome=review_rejected attempt=1' in caplog.text
    assert 'outcome=accepted attempt=2' in caplog.text
    assert all(m.text not in caplog.text for m in messages)


@pytest.mark.parametrize(('messages', 'draft', 'ids'), [
    ([Message(role='child', text='엄마랑 빵 만들었어.'),
      Message(role='child', text='맛은 좋았어.')], '엄마와 빵을 만들었다. 맛은 좋았다.', [0, 1]),
    ([Message(role='child', text='블록을 쌓았어.'),
      Message(role='assistant', text='무슨 색 블록이었어?'),
      Message(role='child', text='파란색')], '파란색 블록을 쌓았다.', [0, 2]),
    ([Message(role='assistant', text='공원에서 놀았지?'),
      Message(role='child', text='모르겠어.')], '모르겠어.', [1]),
    ([Message(role='child', text='공원에 안 갔어. 다음에 가고 싶어.')],
     '공원에 가지 않았다. 다음에 가고 싶다.', [0]),
])
def test_accepted_diary_keeps_short_answers_negation_and_wishes(messages, draft, ids):
    adapter = FakeAdapter(candidate(draft, ids), Review(accepted=True))
    body = post_diary(adapter, messages).json()
    assert body['text'] == draft
    assert body['fallback'] is False
    assert len(adapter.calls) == 2  # No repair on the normal path.
    assert adapter.calls[1][0]['candidate']['sentences'][0]['source_ids'] == ids


def test_repeated_rejection_keeps_exact_fallback_and_stops_after_one_repair(caplog):
    messages = corrected_conversation()
    adapter = FakeAdapter(candidate('즐거웠다.', [1]), Review(accepted=False),
                          candidate('슬펐다.', [5]), Review(accepted=False))
    body = post_diary(adapter, messages).json()
    assert body['fallback'] is True
    assert body['text'] == '\n'.join(m.text for m in messages if m.role == 'child')
    assert len(adapter.calls) == 4
    assert 'outcome=review_rejected attempt=2' in caplog.text


@pytest.mark.parametrize('ids', [[], [0], [999], [-1]])
def test_invalid_repaired_sources_never_reach_review_or_client(ids, caplog):
    messages = corrected_conversation()
    adapter = FakeAdapter(candidate('공놀이를 했다.', [1]), Review(accepted=False),
                          candidate('근거 없는 새 문장', ids))
    body = post_diary(adapter, messages).json()
    assert body['fallback'] is True
    assert '근거 없는 새 문장' not in body['text']
    assert len(adapter.calls) == 3
    assert 'outcome=source_validation_failed attempt=2' in caplog.text


@pytest.mark.parametrize('bad', [DiaryCandidate(sentences=[]), candidate(' ', [1]), candidate('가' * 501, [1])])
def test_invalid_candidate_is_distinguished_from_review_rejection(bad, caplog):
    adapter = FakeAdapter(bad)
    body = post_diary(adapter, corrected_conversation()).json()
    assert body['fallback'] is True
    assert len(adapter.calls) == 1
    assert 'outcome=candidate_validation_failed' in caplog.text
    assert 'review_rejected' not in caplog.text


@pytest.mark.parametrize(('answers', 'stage', 'attempt'), [
    ([], 'generation', 1),
    ([candidate('블록을 쌓았다.', [5])], 'review', 1),
    ([candidate('공놀이를 했다.', [1]), Review(accepted=False)], 'generation', 2),
    ([candidate('공놀이를 했다.', [1]), Review(accepted=False),
      candidate('블록을 쌓았다.', [5])], 'review', 2),
])
def test_provider_errors_remain_http_errors_without_retry_or_fallback(answers, stage, attempt, caplog):
    adapter = FakeAdapter(*answers, ProviderError('제공업체를 확인해 주세요.'))
    response = post_diary(adapter, corrected_conversation())
    assert response.status_code == 503
    assert response.json() == {'error': '제공업체를 확인해 주세요.'}
    assert len(adapter.calls) == len(answers) + 1
    assert f'outcome={stage}_failed attempt={attempt}' in caplog.text


def test_mock_never_calls_provider_or_repairs():
    adapter = FakeAdapter()
    body = DiaryEngine(adapter, mock=True).make_diary(corrected_conversation())
    assert body['fallback'] is body['mock'] is True
    assert adapter.calls == []
