"""Fixed diagnostic labels only: never serialize errors, bodies, or user data."""
import httpx
from openai import APIConnectionError, APITimeoutError, OpenAIError
from pydantic import ValidationError


REASONS = frozenset({
    'quota_exhausted', 'rate_limit', 'authentication', 'permission', 'invalid_request',
    'provider_server_error', 'image_not_started', 'image_result_unknown', 'timeout', 'connection', 'response_schema_invalid',
    'response_incomplete', 'response_truncated', 'response_filtered', 'empty_response',
    'configuration', 'provider_error', 'unexpected_error',
})


SCHEMA_ERROR_TYPES = frozenset({
    'json_invalid', 'model_type', 'missing', 'literal_error', 'string_type',
    'string_too_short', 'string_too_long', 'extra_forbidden', 'value_error', 'other',
    'worry_message_blank', 'worry_too_many_questions',
})
SCHEMA_ERROR_FIELDS = frozenset({'action', 'message', 'root', 'other'})
SCHEMA_ERROR_CODES = frozenset(f'{kind}:{field}' for kind in SCHEMA_ERROR_TYPES for field in SCHEMA_ERROR_FIELDS)


def schema_failure_codes(error):
    """Fixed codes only; validation inputs, messages, contexts and unknown keys stay private."""
    if isinstance(error, ValidationError):
        codes = []
        for item in error.errors(include_input=False, include_context=False, include_url=False):
            kind = item['type'] if item['type'] in SCHEMA_ERROR_TYPES else 'other'
            loc = item['loc']
            field = 'root' if not loc else loc[0] if loc in (('action',), ('message',)) else 'other'
            codes.append(f'{kind}:{field}')
    else:
        value = getattr(error, 'schema_errors', None)
        codes = value.split(',') if isinstance(value, str) else []
    return ','.join(sorted(set(codes) & SCHEMA_ERROR_CODES)[:4]) or 'none'


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
