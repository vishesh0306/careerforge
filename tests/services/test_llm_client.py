from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors
from pydantic import BaseModel

from app.services.llm_client import LLMClient, LLMError, LLMQuotaExhaustedError, _GeminiBackend


class Greeting(BaseModel):
    greeting: str


def _mock_response(text="hello", parsed=None):
    resp = MagicMock()
    resp.text = text
    resp.parsed = parsed
    return resp


def _quota_error():
    return errors.APIError(429, {"error": {"message": "quota exhausted"}})


# --- _GeminiBackend: retry behavior for a single API key ---


def test_generate_text_retries_on_retryable_error_then_succeeds():
    backend = _GeminiBackend(api_key="fake-key")
    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise errors.APIError(429, {"error": {"message": "rate limited"}})
        return _mock_response("real response")

    with patch.object(backend._client.models, "generate_content", side_effect=side_effect) as mocked:
        result = backend.generate_text("say hi")

    assert result == "real response"
    assert mocked.call_count == 3


def test_generate_text_does_not_retry_non_retryable_error():
    def side_effect(*args, **kwargs):
        raise errors.APIError(400, {"error": {"message": "bad request"}})

    backend = _GeminiBackend(api_key="fake-key")
    with patch.object(backend._client.models, "generate_content", side_effect=side_effect) as mocked:
        with pytest.raises(errors.APIError):
            backend.generate_text("say hi")

    assert mocked.call_count == 1


def test_generate_text_raises_llm_error_on_empty_response():
    backend = _GeminiBackend(api_key="fake-key")
    with patch.object(backend._client.models, "generate_content", return_value=_mock_response(text="")):
        with pytest.raises(LLMError):
            backend.generate_text("say hi")


def test_generate_structured_returns_validated_pydantic_instance():
    backend = _GeminiBackend(api_key="fake-key")
    parsed_obj = Greeting(greeting="hi")
    with patch.object(
        backend._client.models,
        "generate_content",
        return_value=_mock_response(text='{"greeting": "hi"}', parsed=parsed_obj),
    ):
        result = backend.generate_structured("say hi", Greeting)

    assert isinstance(result, Greeting)
    assert result.greeting == "hi"


def test_generate_structured_falls_back_to_manual_parse_when_unparsed():
    backend = _GeminiBackend(api_key="fake-key")
    with patch.object(
        backend._client.models,
        "generate_content",
        return_value=_mock_response(text='{"greeting": "hi"}', parsed=None),
    ):
        result = backend.generate_structured("say hi", Greeting)

    assert isinstance(result, Greeting)
    assert result.greeting == "hi"


# --- LLMClient: fallback orchestration across backends ---


class _FakeBackend:
    def __init__(self, text_result=None, text_error=None):
        self._text_result = text_result
        self._text_error = text_error
        self.calls = 0

    def generate_text(self, prompt, temperature=None):
        self.calls += 1
        if self._text_error:
            raise self._text_error
        return self._text_result


def _client_with_backends(*backends) -> LLMClient:
    client = LLMClient.__new__(LLMClient)
    client._backends = list(backends)
    return client


def test_llm_client_succeeds_immediately_without_trying_fallback():
    backend_1 = _FakeBackend(text_result="first try works")
    backend_2 = _FakeBackend(text_result="should not be reached")
    client = _client_with_backends(backend_1, backend_2)

    result = client.generate_text("hi")

    assert result == "first try works"
    assert backend_2.calls == 0


def test_llm_client_falls_back_to_next_backend_on_quota_error():
    backend_1 = _FakeBackend(text_error=_quota_error())
    backend_2 = _FakeBackend(text_result="from backend 2")
    client = _client_with_backends(backend_1, backend_2)

    result = client.generate_text("hi")

    assert result == "from backend 2"
    assert backend_1.calls == 1
    assert backend_2.calls == 1


def test_llm_client_raises_quota_exhausted_when_every_backend_exhausted():
    backend_1 = _FakeBackend(text_error=_quota_error())
    backend_2 = _FakeBackend(text_error=_quota_error())
    client = _client_with_backends(backend_1, backend_2)

    with pytest.raises(LLMQuotaExhaustedError):
        client.generate_text("hi")


def test_llm_client_does_not_fall_back_on_a_non_quota_error():
    backend_1 = _FakeBackend(text_error=LLMError("Gemini returned an empty text response"))
    backend_2 = _FakeBackend(text_result="should not be reached")
    client = _client_with_backends(backend_1, backend_2)

    with pytest.raises(LLMError) as exc_info:
        client.generate_text("hi")

    assert backend_2.calls == 0
    assert not isinstance(exc_info.value, LLMQuotaExhaustedError)


def test_llm_client_with_single_backend_raises_quota_exhausted_not_raw_sdk_error():
    # Previously a persistent 429 with only one key leaked the raw google.genai APIError, so
    # callers had to catch broad Exception instead of the app's own LLMError. Wrapping it even in
    # the single-backend case means `except LLMError` is now sufficient everywhere.
    backend_1 = _FakeBackend(text_error=_quota_error())
    client = _client_with_backends(backend_1)

    with pytest.raises(LLMQuotaExhaustedError):
        client.generate_text("hi")
