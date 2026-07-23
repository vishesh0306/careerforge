import json
import logging
from typing import Type, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TIMEOUT_MS = 30_000
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when a Gemini call fails after retries or returns an unusable response."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_STATUS_CODES
    return isinstance(exc, (TimeoutError, ConnectionError))


def _retry_decorator():
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )


class LLMClient:
    """Single entry point for all Gemini calls. Feature code must go through this,
    never call the google-genai SDK directly."""

    def __init__(self, model: str = DEFAULT_MODEL, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = model
        self._timeout_ms = timeout_ms

    @_retry_decorator()
    def generate_text(self, prompt: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=self._timeout_ms)
                ),
            )
        except Exception as exc:
            logger.warning("Gemini generate_text call failed: %s", exc)
            raise

        if not response.text:
            raise LLMError("Gemini returned an empty text response")
        return response.text

    @_retry_decorator()
    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        """Generate JSON constrained to a Pydantic schema and return a validated instance."""
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    http_options=types.HttpOptions(timeout=self._timeout_ms),
                ),
            )
        except Exception as exc:
            logger.warning("Gemini generate_structured call failed: %s", exc)
            raise

        if response.parsed is not None:
            return response.parsed

        if not response.text:
            raise LLMError("Gemini returned an empty structured response")
        try:
            return schema.model_validate(json.loads(response.text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(f"Gemini returned invalid structured output: {exc}") from exc


llm_client = LLMClient()
