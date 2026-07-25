from fastapi import HTTPException

from app.services.llm_client import LLMError, LLMQuotaExhaustedError


def llm_error_response(exc: LLMError, action: str) -> HTTPException:
    """Converts an LLMError into the right HTTPException: 503 (temporarily unavailable, safe to
    retry later) when every configured AI backend is rate-limited/out of quota, 502 (the AI call
    itself failed for some other reason) otherwise."""
    if isinstance(exc, LLMQuotaExhaustedError):
        return HTTPException(status_code=503, detail=f"{action} is temporarily unavailable: {exc}")
    return HTTPException(status_code=502, detail=f"{action} failed: {exc}")
