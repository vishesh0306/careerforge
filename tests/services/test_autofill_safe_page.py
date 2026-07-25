from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.autofill.safe_page import SafeFormPage, SafeLocator

# The whole point of these wrappers is that a submit/apply action is structurally impossible
# through them — not just avoided by convention. If any of these names ever appear on either
# class, the guarantee is broken.
SUBMIT_CAPABLE_METHODS = {"click", "press", "dispatch_event", "evaluate", "evaluate_handle", "tap", "check"}


def test_safe_form_page_exposes_no_submit_capable_methods():
    exposed = {name for name in dir(SafeFormPage) if not name.startswith("_")}
    assert SUBMIT_CAPABLE_METHODS.isdisjoint(exposed)


def test_safe_locator_exposes_no_submit_capable_methods():
    exposed = {name for name in dir(SafeLocator) if not name.startswith("_")}
    assert SUBMIT_CAPABLE_METHODS.isdisjoint(exposed)


@pytest.mark.asyncio
async def test_safe_form_page_get_by_label_delegates_fill_to_underlying_locator():
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.fill = AsyncMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_page.get_by_label.return_value = mock_locator

    safe_page = SafeFormPage(mock_page)
    locator = safe_page.get_by_label("Email")

    assert await locator.count() == 1
    await locator.fill("test@example.com")

    mock_locator.fill.assert_awaited_once_with("test@example.com")


@pytest.mark.asyncio
async def test_safe_locator_first_delegates_to_underlying_locator_first():
    mock_page = MagicMock()
    mock_raw_locator = MagicMock()
    mock_first_locator = MagicMock()
    mock_first_locator.count = AsyncMock(return_value=1)
    mock_raw_locator.first = mock_first_locator
    mock_page.locator.return_value = mock_raw_locator

    safe_page = SafeFormPage(mock_page)
    first = safe_page.locator('input[type="file"]').first

    assert await first.count() == 1


@pytest.mark.asyncio
async def test_safe_form_page_goto_and_screenshot_delegate_to_underlying_page():
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"fake-png-bytes")

    safe_page = SafeFormPage(mock_page)
    await safe_page.goto("https://example.com", wait_until="domcontentloaded")
    screenshot = await safe_page.screenshot(full_page=True)

    mock_page.goto.assert_awaited_once_with("https://example.com", wait_until="domcontentloaded")
    assert screenshot == b"fake-png-bytes"
