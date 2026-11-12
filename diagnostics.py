"""Fixed diagnostic labels only: never serialize errors, bodies, or user data."""
import httpx
from openai import APIConnectionError, APITimeoutError, OpenAIError
from pydantic import ValidationError


REASONS = frozenset({
    'quota_exhausted', 'rate_limit', 'authentication', 'permission', 'invalid_request',
    'provider_server_error', 'image_result_unknown', 'timeout', 'connection', 'response_schema_invalid',
    'response_incomplete', 'response_truncated', 'response_filtered', 'empty_response',
    'configuration', 'provider_error', 'unexpected_error',
})


def failure_details(error):
    """Allowlist categories/status only; unrecognized provider codes are never emitted."""
    status = getattr(error, 'status_code', None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    reason = getattr(error, 'reason', None)
    if not isinstance(reason, str) or reason not in REASONS:
        body = getattr(error, 'body', None)
        detail = body.get('error', body) if isinstance(body, dict) else {}
        code = detail.get('code') if isinstance(detail, dict) else None
        if code in ('credit_balance_exhausted', 'insufficient_quota', 'billing_hard_limit_reached'):
            reason = 'quota_exhausted'
        elif status == 429:
            reason = 'rate_limit'
        elif status == 401:
            reason = 'authentication'
        elif status in (403, 404):
            reason = 'permission'
        elif status == 400:
            reason = 'invalid_request'
        elif status is not None and status >= 500:
            reason = 'provider_server_error'
        elif isinstance(error, (APITimeoutError, httpx.TimeoutException, TimeoutError)):
            reason = 'timeout'
        elif isinstance(error, (APIConnectionError, httpx.RequestError)):
            reason = 'connection'
        elif isinstance(error, ValidationError):
            reason = 'response_schema_invalid'
        elif isinstance(error, OpenAIError) or status is not None:
            reason = 'provider_error'
        else:
            reason = 'unexpected_error'
    provider = getattr(error, 'provider', None)
    provider = provider if provider in ('groq', 'openai', 'cloudflare') else 'unknown'
    return reason, status, provider
