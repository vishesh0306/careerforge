from app.schemas.resume import ContactInfo
from app.services.autofill.safe_page import SafeFormPage


async def fill_greenhouse_form(
    safe_page: SafeFormPage, contact: ContactInfo, resume_pdf_bytes: bytes, resume_filename: str
) -> dict[str, bool]:
    filled: dict[str, bool] = {}

    name_parts = contact.name.split(maxsplit=1) if contact.name else []
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    text_fields = {
        "First Name": first_name,
        "Last Name": last_name,
        "Email": contact.email,
        "Phone": contact.phone,
    }

    for label, value in text_fields.items():
        if not value:
            filled[label] = False
            continue
        locator = safe_page.get_by_label(label, exact=False)
        try:
            if await locator.count() > 0:
                await locator.fill(value)
                filled[label] = True
            else:
                filled[label] = False
        except Exception:
            filled[label] = False

    resume_file = {"name": resume_filename, "mimeType": "application/pdf", "buffer": resume_pdf_bytes}
    filled["Resume"] = False

    # Greenhouse's modern upload widget associates "Resume" with a styled dropzone <div>, not the
    # underlying <input>, so this sometimes resolves to a non-input element and set_input_files
    # raises — that's expected here, not a real failure, so we fall through to the selector below.
    try:
        resume_locator = safe_page.get_by_label("Resume", exact=False)
        if await resume_locator.count() > 0:
            await resume_locator.set_input_files(resume_file)
            filled["Resume"] = True
    except Exception:
        pass

    if not filled["Resume"]:
        try:
            # Greenhouse's standard template always lists Resume before Cover Letter, so the
            # first file input on the page is the resume upload.
            fallback_locator = safe_page.locator('input[type="file"]').first
            if await fallback_locator.count() > 0:
                await fallback_locator.set_input_files(resume_file)
                filled["Resume"] = True
        except Exception:
            pass

    return filled
