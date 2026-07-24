import logging

import httpx

from app.core.config import settings
from app.services.job_search.common import JobSearchQuery, NormalizedListing, normalize_job_type

logger = logging.getLogger(__name__)

ADZUNA_URL_TEMPLATE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
TIMEOUT_SECONDS = 15.0
DEFAULT_COUNTRY = "in"  # India — matches this project's primary target user
RESULTS_PER_PAGE = 20


async def search(query: JobSearchQuery) -> list[NormalizedListing]:
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        logger.info("Adzuna search skipped — ADZUNA_APP_ID/ADZUNA_APP_KEY not configured.")
        return []

    # title_only restricts matching to the job title, not the full description —
    # without it, a search for "Backend Developer" also matches MERN/Node/Golang
    # postings whose description happens to mention backend work.
    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": RESULTS_PER_PAGE,
        "what": query.role,
        "title_only": query.role,
        "content-type": "application/json",
    }
    if query.location:
        params["where"] = query.location

    job_type = normalize_job_type(query.job_type)
    if job_type in ("fulltime", "permanent"):
        params["full_time"] = 1
    elif job_type == "contract":
        params["contract"] = 1
    elif job_type in ("intern", "internship"):
        params["what_or"] = "intern internship"

    # Exclude senior-level postings by title when the candidate is early-career —
    # otherwise a search for "Backend Developer" at 1 YOE still surfaces roles
    # explicitly requiring 5-10+ years, which are not a realistic match.
    if query.experience_years is not None and query.experience_years <= 2:
        params["what_exclude"] = "senior lead principal staff architect"

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
