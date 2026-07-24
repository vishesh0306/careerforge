import logging

import httpx

from app.core.config import settings
from app.services.job_search.common import JobSearchQuery, NormalizedListing

logger = logging.getLogger(__name__)

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search-v2"
JSEARCH_HOST = "jsearch.p.rapidapi.com"
TIMEOUT_SECONDS = 15.0
DEFAULT_COUNTRY = "in"  # India — matches this project's primary target user

_EMPLOYMENT_TYPE_MAP = {"full_time": "FULLTIME", "intern": "INTERN", "contract": "CONTRACTOR"}


async def search(query: JobSearchQuery) -> list[NormalizedListing]:
    if not settings.jsearch_rapidapi_key:
        logger.info("JSearch search skipped — JSEARCH_RAPIDAPI_KEY not configured.")
        return []

    search_query = query.role
    if query.location:
        search_query = f"{search_query} in {query.location}"

    params = {"query": search_query, "num_pages": "1", "country": DEFAULT_COUNTRY, "date_posted": "all"}
    if query.work_mode in ("wfh", "remote"):
        params["remote_jobs_only"] = "true"
    employment_type = _EMPLOYMENT_TYPE_MAP.get(query.job_type or "")
    if employment_type:
        params["employment_types"] = employment_type

    headers = {
        "X-RapidAPI-Key": settings.jsearch_rapidapi_key,
        "X-RapidAPI-Host": JSEARCH_HOST,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(JSEARCH_URL, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("JSearch search failed: %s", exc)
        return []

    listings: list[NormalizedListing] = []
    for item in data.get("data", {}).get("jobs", []):
        location_parts = [p for p in [item.get("job_city"), item.get("job_country")] if p]
        listings.append(
            NormalizedListing(
                source="jsearch",
                external_id=str(item.get("job_id")),
                title=item.get("job_title", ""),
                company=item.get("employer_name"),
                jd_text=item.get("job_description"),
                url=item.get("job_apply_link", ""),
                location=", ".join(location_parts) or None,
            )
        )

    return listings
