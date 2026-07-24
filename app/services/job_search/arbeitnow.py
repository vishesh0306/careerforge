import logging

import httpx

from app.services.job_search.common import JobSearchQuery, NormalizedListing

logger = logging.getLogger(__name__)

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
TIMEOUT_SECONDS = 15.0
_STOPWORDS = {"the", "and", "for", "with", "role", "job", "level"}


def _significant_words(text: str) -> list[str]:
    return [w for w in text.lower().split() if len(w) > 3 and w not in _STOPWORDS]


async def search(query: JobSearchQuery) -> list[NormalizedListing]:
    """Arbeitnow's public API returns all listings with no server-side text search —
    filter client-side by role keyword, and by remote flag when work_mode is wfh/remote."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(ARBEITNOW_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("Arbeitnow search failed: %s", exc)
        return []

    role_words = _significant_words(query.role)
    want_remote_only = (query.work_mode or "").lower() in ("wfh", "remote")
    listings: list[NormalizedListing] = []

    for item in data.get("data", []):
        title = item.get("title", "")
        if role_words and not any(word in title.lower() for word in role_words):
            continue
        if want_remote_only and not item.get("remote"):
            continue

        listings.append(
            NormalizedListing(
                source="arbeitnow",
                external_id=item.get("slug", item.get("url", title)),
                title=title,
                company=item.get("company_name"),
                jd_text=item.get("description"),
                url=item.get("url", ""),
                location="Remote" if item.get("remote") else item.get("location"),
            )
        )

    return listings
