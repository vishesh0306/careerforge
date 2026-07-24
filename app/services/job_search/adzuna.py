import logging

import httpx

from app.core.config import settings
from app.services.job_search.common import JobSearchQuery, NormalizedListing

logger = logging.getLogger(__name__)

ADZUNA_URL_TEMPLATE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
TIMEOUT_SECONDS = 15.0
DEFAULT_COUNTRY = "in"  # India — matches this project's primary target user
RESULTS_PER_PAGE = 20


async def search(query: JobSearchQuery) -> list[NormalizedListing]:
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        logger.info("Adzuna search skipped — ADZUNA_APP_ID/ADZUNA_APP_KEY not configured.")
        return []

    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": RESULTS_PER_PAGE,
        "what": query.role,
        "content-type": "application/json",
    }
    if query.location:
        params["where"] = query.location
    if query.job_type == "full_time":
        params["full_time"] = 1
    elif query.job_type == "contract":
        params["contract"] = 1

    url = ADZUNA_URL_TEMPLATE.format(country=DEFAULT_COUNTRY)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("Adzuna search failed: %s", exc)
        return []

    listings: list[NormalizedListing] = []
    for item in data.get("results", []):
        listings.append(
            NormalizedListing(
                source="adzuna",
                external_id=str(item.get("id")),
                title=item.get("title", ""),
                company=(item.get("company") or {}).get("display_name"),
                jd_text=item.get("description"),
                url=item.get("redirect_url", ""),
                location=(item.get("location") or {}).get("display_name"),
            )
        )

    return listings
