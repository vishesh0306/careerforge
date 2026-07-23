from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors
from pydantic import BaseModel

from app.services.llm_client import LLMClient, LLMError


class Greeting(BaseModel):
    greeting: str


def _mock_response(text="hello", parsed=None):
    resp = MagicMock()
    resp.text = text
    resp.parsed = parsed
    return resp


def test_generate_text_retries_on_retryable_error_then_succeeds():
    client = LLMClient()
    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise errors.APIError(429, {"error": {"message": "rate limited"}})
        return _mock_response("real response")

    with patch.object(client._client.models, "generate_content", side_effect=side_effect) as mocked:
        result = client.generate_text("say hi")

    assert result == "real response"
    assert mocked.call_count == 3


def test_generate_text_does_not_retry_non_retryable_error():
    def side_effect(*args, **kwargs):
        raise errors.APIError(400, {"error": {"message": "bad request"}})

    client = LLMClient()
    with patch.object(client._client.models, "generate_content", side_effect=side_effect) as mocked:
        with pytest.raises(errors.APIError):
            client.generate_text("say hi")

    assert mocked.call_count == 1


def test_generate_text_raises_llm_error_on_empty_response():
    client = LLMClient()
    with patch.object(client._client.models, "generate_content", return_value=_mock_response(text="")):
        with pytest.raises(LLMError):
            client.generate_text("say hi")


def test_generate_structured_returns_validated_pydantic_instance():
    client = LLMClient()
    parsed_obj = Greeting(greeting="hi")
    with patch.object(
        client._client.models, "generate_content", return_value=_mock_response(text='{"greeting": "hi"}', parsed=parsed_obj)
    ):
        result = client.generate_structured("say hi", Greeting)

    assert isinstance(result, Greeting)
    assert result.greeting == "hi"


def test_generate_structured_falls_back_to_manual_parse_when_unparsed():
    client = LLMClient()
    with patch.object(
        client._client.models, "generate_content", return_value=_mock_response(text='{"greeting": "hi"}', parsed=None)
    ):
        result = client.generate_structured("say hi", Greeting)

    assert isinstance(result, Greeting)
    assert result.greeting == "hi"
