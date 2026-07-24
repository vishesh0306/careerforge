import logging

import httpx

from app.services.job_search.common import JobSearchQuery, NormalizedListing

logger = logging.getLogger(__name__)

REMOTEOK_URL = "https://remoteok.com/api"
TIMEOUT_SECONDS = 15.0
_STOPWORDS = {"the", "and", "for", "with", "role", "job", "level"}


def _significant_words(text: str) -> list[str]:
    return [w for w in text.lower().split() if len(w) > 3 and w not in _STOPWORDS]


async def search(query: JobSearchQuery) -> list[NormalizedListing]:
    """RemoteOK's public API returns all listings with no server-side search — filter
    client-side by role keyword. Every listing here is inherently remote."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(REMOTEOK_URL, headers={"User-Agent": "CareerForge/1.0"})
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("RemoteOK search failed: %s", exc)
        return []

    role_words = _significant_words(query.role)
    listings: list[NormalizedListing] = []

    for item in data:
        if "id" not in item or "position" not in item:
            continue  # skip the leading legal-notice entry

        title = item.get("position", "")
        if role_words and not any(word in title.lower() for word in role_words):
            continue

        listings.append(
            NormalizedListing(
                source="remoteok",
                external_id=str(item["id"]),
                title=title,
                company=item.get("company"),
                jd_text=item.get("description"),
                url=item.get("url") or item.get("apply_url", ""),
                location=item.get("location") or "Remote",
            )
        )

    return listings
