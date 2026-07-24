import asyncio
import hashlib
import json
import logging

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import JobListing
from app.services.job_search import adzuna, arbeitnow, jsearch, remoteok
from app.services.job_search.common import JobSearchQuery, NormalizedListing

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600
CACHE_KEY_PREFIX = "job_search_cache:"

SOURCES = [adzuna, arbeitnow, jsearch, remoteok]


def _cache_key(query: JobSearchQuery) -> str:
    canonical = "|".join(
        [
            query.role.strip().lower(),
            (query.location or "").strip().lower(),
            (query.job_type or "").strip().lower(),
            (query.work_mode or "").strip().lower(),
            str(query.experience_years or ""),
        ]
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


async def _fetch_all_sources(query: JobSearchQuery) -> list[NormalizedListing]:
    results = await asyncio.gather(*(source.search(query) for source in SOURCES), return_exceptions=True)

    listings: list[NormalizedListing] = []
    for source_module, result in zip(SOURCES, results):
        if isinstance(result, Exception):
            logger.warning("%s search raised an unexpected error: %s", source_module.__name__, result)
            continue
        listings.extend(result)
    return listings


def _upsert_and_resolve_ids(listings: list[NormalizedListing]) -> list[int]:
    if not listings:
        return []

    session = SessionLocal()
    try:
        for listing in listings:
            stmt = (
                pg_insert(JobListing)
                .values(
                    source=listing.source,
                    external_id=listing.external_id,
                    title=listing.title,
                    company=listing.company,
                    jd_text=listing.jd_text,
                    url=listing.url,
                    location=listing.location,
                )
                .on_conflict_do_nothing(index_elements=["source", "external_id"])
            )
            try:
                # Each insert runs in its own SAVEPOINT — one malformed listing
                # (e.g. an oversized field from a source) must not abort the
                # whole batch and crash the search run.
                with session.begin_nested():
                    session.execute(stmt)
            except Exception as exc:
                logger.warning(
                    "Skipping listing %s/%s — insert failed: %s", listing.source, listing.external_id, exc
                )
        session.commit()

        keys = [(listing.source, listing.external_id) for listing in listings]
        rows = (
            session.query(JobListing.id)
            .filter(tuple_(JobListing.source, JobListing.external_id).in_(keys))
            .all()
        )
        return [row.id for row in rows]
    finally:
        session.close()


async def get_or_fetch_listing_ids(query: JobSearchQuery) -> list[int]:
    """Returns job_listings.id values matching this query — served from cache when an
    identical query ran within the last hour, otherwise fetched live from all sources."""
    key = _cache_key(query)
    redis_client = AsyncRedis.from_url(settings.redis_url)
    try:
        cached = await redis_client.get(key)
        if cached is not None:
            logger.info("Job search cache hit for key %s", key)
            return json.loads(cached)

        listings = await _fetch_all_sources(query)
        listing_ids = _upsert_and_resolve_ids(listings)

        await redis_client.set(key, json.dumps(listing_ids), ex=CACHE_TTL_SECONDS)
        return listing_ids
    finally:
        await redis_client.aclose()
