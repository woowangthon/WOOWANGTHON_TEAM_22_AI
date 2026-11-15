"""SDK 응답 검증 실패의 고정 진단 코드만 전달합니다."""
import httpx
import pytest
from openai import OpenAI

from engine import ProviderError
from providers import ProviderRouter
from worry_support import WorryAction


@pytest.mark.parametrize('content,code', [
    ('{', 'json_invalid:root'),
    ('{"action":"listen"}', 'missing:message'),
    ('{"action":"listen","message":"  "}', 'worry_message_blank:root'),
    ('{"action":"private-action","message":"private-message"}', 'literal_error:action'),
    ('{"action":"listen","message":"test","private-key":"private-value"}', 'extra_forbidden:other'),
])
def test_sdk_schema_failures_keep_only_fixed_codes(monkeypatch, content, code):
    monkeypatch.setenv('TEXT_PROVIDER', 'groq')
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={
            'id': 'synthetic', 'object': 'chat.completion', 'created': 0, 'model': 'synthetic',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': content}}],
        })

    router = ProviderRouter()
    with OpenAI(api_key='synthetic-key', base_url='https://provider.invalid/v1', max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as sdk:
        router.__dict__['groq'] = sdk
        with pytest.raises(ProviderError) as caught:
            router.parse('synthetic instruction', {'conversation': []}, WorryAction, timeout=12)
    assert len(calls) == 1
    assert caught.value.schema_errors == code
    assert caught.value.reason == 'response_schema_invalid'
    assert 'private' not in str(caught.value) + caught.value.schema_errors
