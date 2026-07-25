from app.core.errors import llm_error_response
from app.services.llm_client import LLMError, LLMQuotaExhaustedError


def test_llm_error_response_returns_503_for_quota_exhaustion():
    exc = LLMQuotaExhaustedError("All 2 configured Gemini API key(s) are currently rate-limited.")
    response = llm_error_response(exc, "ATS scoring")

    assert response.status_code == 503
    assert "ATS scoring is temporarily unavailable" in response.detail
    assert "rate-limited" in response.detail


def test_llm_error_response_returns_502_for_other_llm_errors():
    exc = LLMError("Gemini returned an empty text response")
    response = llm_error_response(exc, "ATS scoring")

    assert response.status_code == 502
    assert "ATS scoring failed" in response.detail
