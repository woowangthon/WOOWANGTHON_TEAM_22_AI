"""Render의 컷 생성 호출과 이미지 응답 계약을 합성 입력으로 검사합니다."""
from fastapi.testclient import TestClient
import pytest

from engine import DiaryEngine
from image_fixture import encoded_image
from server import create_app
from visual_story import text_hash


@pytest.mark.parametrize('generated', [True, False])
def test_deployed_panel_call_keeps_four_slots_and_response_shape(generated):
    image = 'data:image/png;base64,' + encoded_image() if generated else None
    calls = []

    class Adapter:
        image_provider = 'cloudflare'

        def generate_comic_panel(self, captions, index):
            calls.append((captions, index))
            return image

    text = '종이배를 접었다.'
    with TestClient(create_app(DiaryEngine(Adapter()))) as client:
        response = client.post('/api/visual-story/image', json={
            'diary_text': text, 'diary_hash': text_hash(text), 'source_ids': [0],
            'format': 'comic4', 'confirmed': True,
        })
    assert response.status_code == 200
    result = response.json()
    assert calls == [([text] * 4, 0)]
    assert result['status'] == ('generated' if generated else 'rejected')
    assert result['imageUrl'] == image
    assert result['error'] is None
    assert result['caption'] == text
