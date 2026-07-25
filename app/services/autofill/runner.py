import base64

from playwright.async_api import async_playwright

from app.schemas.resume import ContactInfo
from app.services.autofill.detection import detect_ats_platform
from app.services.autofill.greenhouse import fill_greenhouse_form
from app.services.autofill.safe_page import SafeFormPage

PLATFORM_FILLERS = {
    "greenhouse": fill_greenhouse_form,
}


class UnsupportedATSPlatformError(Exception):
    """Raised when a listing URL doesn't match any ATS platform this feature can fill."""


async def run_autofill_draft(
    url: str, contact: ContactInfo, resume_pdf_bytes: bytes, resume_filename: str
) -> dict:
    platform = detect_ats_platform(url)
    if platform is None or platform not in PLATFORM_FILLERS:
        raise UnsupportedATSPlatformError(f"No supported ATS platform detected for URL: {url}")

    filler = PLATFORM_FILLERS[platform]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            safe_page = SafeFormPage(page)
            await safe_page.goto(url, wait_until="domcontentloaded")
            filled_fields = await filler(safe_page, contact, resume_pdf_bytes, resume_filename)
            screenshot_bytes = await safe_page.screenshot(full_page=True)
        finally:
            await browser.close()

    return {
        "ats_platform": platform,
        "filled_fields": filled_fields,
        "screenshot_base64": base64.b64encode(screenshot_bytes).decode("ascii"),
    }
