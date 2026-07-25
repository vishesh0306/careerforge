import json
import logging
from typing import Type, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-lite-latest"
DEFAULT_TIMEOUT_MS = 30_000
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
QUOTA_STATUS_CODES = {429}

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when every configured LLM backend has failed or returned an unusable response."""


class LLMQuotaExhaustedError(LLMError):
    """Raised specifically when every configured backend failed on a rate-limit/quota error — as
    opposed to some other kind of failure — so callers can surface a clearer, more actionable
    message than a generic 'the AI call failed'."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in RETRYABLE_STATUS_CODES
    return isinstance(exc, (TimeoutError, ConnectionError))


def _is_quota_error(exc: BaseException) -> bool:
    return isinstance(exc, errors.APIError) and exc.code in QUOTA_STATUS_CODES


def _retry_decorator():
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )


class _GeminiBackend:
    """Wraps a single Gemini API key. Retries transient failures (429/5xx/timeouts) internally;
    if retries exhaust, the underlying error is re-raised for LLMClient to decide whether to fall
    back to the next configured backend."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._timeout_ms = timeout_ms

    @_retry_decorator()
    def generate_text(self, prompt: str, temperature: float | None = None) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(timeout=self._timeout_ms),
                temperature=temperature,
            ),
        )
        if not response.text:
            raise LLMError("Gemini returned an empty text response")
        return response.text

    @_retry_decorator()
    def generate_structured(self, prompt: str, schema: Type[T], temperature: float | None = None) -> T:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                http_options=types.HttpOptions(timeout=self._timeout_ms),
                temperature=temperature,
            ),
        )
        if response.parsed is not None:
            return response.parsed
        if not response.text:
            raise LLMError("Gemini returned an empty structured response")
        try:
            return schema.model_validate(json.loads(response.text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(f"Gemini returned invalid structured output: {exc}") from exc


class LLMClient:
    """Single entry point for all Gemini calls. Feature code must go through this, never call the
    google-genai SDK directly.

    Holds an ordered chain of backends — a primary API key plus any configured fallback keys. A
    call that fails with a persistent rate-limit/quota error on one backend (after its own retries
    exhaust) is retried on the next backend in the chain, so one exhausted key degrades the app
    instead of breaking it. Only rate-limit/quota errors trigger fallback — any other failure (bad
    request, empty response) raises immediately, since it would very likely fail identically on
    every backend."""

    def __init__(self):
        api_keys = [key for key in (settings.gemini_api_key, settings.gemini_api_key_2) if key]
        self._backends = [_GeminiBackend(api_key=key) for key in api_keys]

    def generate_text(self, prompt: str, temperature: float | None = None) -> str:
        return self._call_with_fallback("generate_text", prompt, temperature=temperature)

    def generate_structured(self, prompt: str, schema: Type[T], temperature: float | None = None) -> T:
        return self._call_with_fallback("generate_structured", prompt, schema, temperature=temperature)

    def _call_with_fallback(self, method_name: str, *args, **kwargs):
        if not self._backends:
            raise LLMError("No Gemini API key is configured — set GEMINI_API_KEY to use this feature.")

        last_exc: BaseException | None = None
        for i, backend in enumerate(self._backends):
            try:
                return getattr(backend, method_name)(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                is_last_backend = i == len(self._backends) - 1
                if is_last_backend or not _is_quota_error(exc):
                    break
                logger.warning(
                    "LLM backend %d/%d hit a rate-limit/quota error, falling back to the next "
                    "configured key: %s",
                    i + 1,
                    len(self._backends),
                    exc,
                )

        if last_exc is not None and _is_quota_error(last_exc):
            raise LLMQuotaExhaustedError(
                f"All {len(self._backends)} configured Gemini API key(s) are currently "
                "rate-limited or out of quota. Wait for quota to reset, add another fallback key, "
                "or enable billing on an existing key."
            ) from last_exc
        raise last_exc


llm_client = LLMClient()
