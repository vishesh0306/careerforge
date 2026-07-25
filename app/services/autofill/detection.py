import re
from urllib.parse import urlparse

GREENHOUSE_HOST_PATTERN = re.compile(r"(^|\.)greenhouse\.io$", re.IGNORECASE)


def detect_ats_platform(url: str) -> str | None:
    """Returns the ATS platform key for a supported job listing URL, or None if unsupported."""
    host = urlparse(url).netloc.lower()
    if GREENHOUSE_HOST_PATTERN.search(host):
        return "greenhouse"
    return None
