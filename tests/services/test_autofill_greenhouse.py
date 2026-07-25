from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.resume import ContactInfo
from app.services.autofill.greenhouse import fill_greenhouse_form
from app.services.autofill.safe_page import SafeFormPage


def _mock_safe_page(found_labels: set) -> SafeFormPage:
    page = MagicMock()

    def get_by_label(label, **kwargs):
        locator = MagicMock()
        found = label in found_labels
        locator.count = AsyncMock(return_value=1 if found else 0)
        locator.fill = AsyncMock()
        locator.set_input_files = AsyncMock()
        return locator

    page.get_by_label.side_effect = get_by_label
    return SafeFormPage(page)


@pytest.mark.asyncio
async def test_fill_greenhouse_form_fills_found_fields_and_flags_missing():
    safe_page = _mock_safe_page({"First Name", "Last Name", "Email", "Resume"})
    contact = ContactInfo(name="Jane Doe", email="jane@example.com", phone="555-1234")

    filled = await fill_greenhouse_form(safe_page, contact, b"%PDF-fake-bytes", "resume.pdf")

    assert filled["First Name"] is True
    assert filled["Last Name"] is True
    assert filled["Email"] is True
    assert filled["Phone"] is False  # phone was provided but no matching field was found on the form
    assert filled["Resume"] is True


@pytest.mark.asyncio
async def test_fill_greenhouse_form_skips_empty_contact_fields_without_touching_the_page():
    safe_page = _mock_safe_page({"First Name", "Email", "Resume"})
    contact = ContactInfo(name="", email="jane@example.com", phone="")

    filled = await fill_greenhouse_form(safe_page, contact, b"%PDF", "resume.pdf")

    assert filled["First Name"] is False
    assert filled["Last Name"] is False
    assert filled["Email"] is True
    assert filled["Phone"] is False


@pytest.mark.asyncio
async def test_fill_greenhouse_form_falls_back_to_file_input_when_resume_has_no_label():
    page = MagicMock()

    def get_by_label(label, **kwargs):
        locator = MagicMock()
        found = label in {"First Name", "Last Name", "Email"}
        locator.count = AsyncMock(return_value=1 if found else 0)
        locator.fill = AsyncMock()
        return locator

    fallback_locator = MagicMock()
    fallback_locator.count = AsyncMock(return_value=1)
    fallback_locator.set_input_files = AsyncMock()
    raw_file_input_locator = MagicMock()
    raw_file_input_locator.first = fallback_locator

    page.get_by_label.side_effect = get_by_label
    page.locator.return_value = raw_file_input_locator

    safe_page = SafeFormPage(page)
    contact = ContactInfo(name="Jane Doe", email="jane@example.com")

    filled = await fill_greenhouse_form(safe_page, contact, b"%PDF", "resume.pdf")

    assert filled["Resume"] is True
    fallback_locator.set_input_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_fill_greenhouse_form_falls_back_when_label_resolves_to_a_non_input_wrapper():
    # Matches Greenhouse's real modern widget: "Resume" labels a wrapper <div>, not the <input>,
    # so set_input_files on it raises even though count() > 0 — must fall through, not give up.
    page = MagicMock()

    def get_by_label(label, **kwargs):
        locator = MagicMock()
        found = label in {"First Name", "Last Name", "Email"}
        locator.count = AsyncMock(return_value=1 if found else (1 if label == "Resume" else 0))
        locator.fill = AsyncMock()
        if label == "Resume":
            locator.set_input_files = AsyncMock(side_effect=Exception("Node is not an HTMLInputElement"))
        return locator

    fallback_locator = MagicMock()
    fallback_locator.count = AsyncMock(return_value=1)
    fallback_locator.set_input_files = AsyncMock()
    raw_file_input_locator = MagicMock()
    raw_file_input_locator.first = fallback_locator

    page.get_by_label.side_effect = get_by_label
    page.locator.return_value = raw_file_input_locator

    safe_page = SafeFormPage(page)
    contact = ContactInfo(name="Jane Doe", email="jane@example.com")

    filled = await fill_greenhouse_form(safe_page, contact, b"%PDF", "resume.pdf")

    assert filled["Resume"] is True
    fallback_locator.set_input_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_fill_greenhouse_form_survives_a_field_raising_and_flags_it_missed():
    page = MagicMock()

    def get_by_label(label, **kwargs):
        locator = MagicMock()
        if label == "Email":
            locator.count = AsyncMock(side_effect=RuntimeError("page closed"))
        else:
            locator.count = AsyncMock(return_value=0)
        locator.fill = AsyncMock()
        locator.set_input_files = AsyncMock()
        return locator

    page.get_by_label.side_effect = get_by_label
    no_fallback_locator = MagicMock()
    no_fallback_locator.count = AsyncMock(return_value=0)
    raw_file_input_locator = MagicMock()
    raw_file_input_locator.first = no_fallback_locator
    page.locator.return_value = raw_file_input_locator

    safe_page = SafeFormPage(page)
    contact = ContactInfo(name="Jane Doe", email="jane@example.com")

    filled = await fill_greenhouse_form(safe_page, contact, b"%PDF", "resume.pdf")

    assert filled["Email"] is False
