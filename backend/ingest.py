"""Ingestion orchestrator for CityPulse Phase 2.

Responsibilities (kept separate from providers and routes):
- Decide per source type whether to fetch live data or fall back to clearly
  labeled demo data (provider not configured / failed).
- Validate every observation before persistence (defense in depth).
- Upsert into civic_data keyed by (source_type, source_id) → no duplicates.
- Track provider health in provider_status + audit trail in ingestion_log.

Concurrency safety:
- A Postgres advisory lock prevents two ingestion runs at once (Flask debug
  mode spawns a helper process; the lock makes duplicate schedulers harmless
  across processes).
- POST /api/refresh is additionally rate-limited by INGEST_COOLDOWN_SECONDS.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.config import get_settings
from backend.database import (
    count_records,
    get_connection,
    log_ingestion,
    upsert_observations,
    upsert_provider_status,
)
from backend.providers import air_quality, incidents, transit, weather
from backend.providers.base import (
    NormalizedObservation,
    ProviderError,
    validate_observation,
)

logger = logging.getLogger("citypulse.ingest")

ADVISORY_LOCK_KEY = 918_273_645  # arbitrary app-specific lock id

SOURCE_TYPES = ("weather", "air_quality", "transit", "incident")


def _default_city_ids() -> list[str]:
    from backend.demo_data import DEMO_CITIES

    return [c["id"] for c in DEMO_CITIES]


def _refresh_cooldown_seconds() -> int:
    return max(30, int(get_settings().ingest_cooldown_seconds or 120))


def _is_live_configured(source_type: str, settings) -> bool:
    """Whether a real provider is configured for this source type."""
    if source_type == "weather":
        return settings.weather_enabled
    if source_type == "air_quality":
        return bool(settings.openaq_api_key)
    if source_type == "transit":
        return bool(settings.transit_gtfs_rt_url)
    if source_type == "incident":
        return bool(settings.incidents_socrata_url)
    return False


def _fetch_live(source_type: str, city_id: str, settings) -> list[NormalizedObservation]:
    if source_type == "weather":
        return weather.fetch_live(city_id)
    if source_type == "air_quality":
        return air_quality.fetch_live(city_id, settings.openaq_api_key)
    if source_type == "transit":
        return transit.fetch_live(city_id, settings.transit_gtfs_rt_url)
    if source_type == "incident":
        field_map = settings.incidents_field_map
        return incidents.fetch_live(
            city_id,
            settings.incidents_socrata_url or "",
            field_map,
        )
    raise ProviderError(f"unknown source_type {source_type}")


def _fetch_demo(source_type: str, city_id: str, bucket=None) -> list[NormalizedObservation]:
    """Synthetic observations for the current (or given) time bucket."""
    if source_type == "weather":
        return weather.fetch_demo(city_id, bucket=bucket)
    if source_type == "air_quality":
        return air_quality.fetch_demo(city_id, bucket=bucket)
    if source_type == "transit":
        return transit.fetch_demo(city_id, bucket=bucket)
    if source_type == "incident":
        return incidents.fetch_demo(city_id, bucket=bucket)
    raise ProviderError(f"unknown source_type {source_type}")


DEMO_HISTORY_HOURS = 48  # backfill window so analytics have usable series
DEMO_HISTORY_MIN_ROWS = 24  # only backfill when a source has almost no history


def _ensure_demo_history(source_type: str, city_ids: list[str]) -> int:
    """Backfill deterministic demo history for analytics (demo mode only).

    Demo generators are pure functions of (city, hour bucket), so backfilled
    rows exactly match what live polling would have produced — a coherent
    synthetic time series. Only runs when the source has < DEMO_HISTORY_MIN_ROWS.
    """
    ok, payload = count_records(source_type=source_type)
    if ok and isinstance(payload, int) and payload >= DEMO_HISTORY_MIN_ROWS:
        return 0

    from backend.providers.demo_generators import bucket_for

    backfilled = []
    for hours_ago in range(1, DEMO_HISTORY_HOURS + 1):
        bucket = bucket_for(offset_hours=hours_ago)
        for city_id in city_ids:
            backfilled.extend(_fetch_demo(source_type, city_id, bucket=bucket))
    stored = 0
    if backfilled:
        ok, payload = upsert_observations(backfilled)
        if ok:
            stored = payload
        else:
            logger.warning("demo history backfill failed for %s: %s", source_type, payload)
    logger.info("demo history backfill for %s: %d rows", source_type, stored)
    return stored


def _run_source(
    source_type: str, city_ids: list[str], settings
) -> dict:
    """Fetch + persist one source type across cities. Returns a status dict."""
    provider_name = {
        "weather": "open-meteo",
        "air_quality": "openaq",
        "transit": "gtfs-rt",
        "incident": "city-open-data",
    }.get(source_type, "demo")

    live_configured = _is_live_configured(source_type, settings)
    all_observations: list[NormalizedObservation] = []
    error: str | None = None
    mode = "demo"

    if live_configured:
        try:
            for city_id in city_ids:
                all_observations.extend(_fetch_live(source_type, city_id, settings))
            mode = "live"
            provider_name = all_observations[0].provider if all_observations else provider_name
        except ProviderError as exc:
            error = str(exc)
            logger.warning("%s live fetch failed (%s) — falling back to demo", source_type, error)
            all_observations = []

    if mode == "demo":
        for city_id in city_ids:
            all_observations.extend(_fetch_demo(source_type, city_id))
        # Give analytics a usable synthetic series on first run.
        _ensure_demo_history(source_type, city_ids)

    # Validate everything; drop invalid rows rather than persisting garbage.
    valid: list[NormalizedObservation] = []
    for obs in all_observations:
        try:
            validate_observation(obs)
            valid.append(obs)
        except ProviderError as exc:
            logger.warning("dropping invalid observation: %s", exc)

    stored = 0
    if valid:
        ok, payload = upsert_observations(valid)
        if ok:
            stored = payload
        else:
            error = error or str(payload)

    now = datetime.now(timezone.utc)
    upsert_provider_status(
        {
            "source_type": source_type,
            "provider": provider_name,
            "is_configured": live_configured,
            "is_synthetic": mode != "live",
            "last_attempt_at": now,
            "last_success_at": now if (mode == "live" or stored > 0) else None,
            "last_error": error,
            "record_count_last": stored,
        }
    )

    return {
        "source_type": source_type,
        "provider": provider_name,
        "mode": mode,
        "configured": live_configured,
        "records_stored": stored,
        "error": error,
    }


def run_ingestion(city_ids: list[str] | None = None, respect_cooldown: bool = True) -> dict:
    """Run all configured providers once. Returns a per-source status report."""
    settings = get_settings()
    city_ids = city_ids or _default_city_ids()

    # Cross-process guard (Flask debug reloader, double-clicked refresh...).
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            acquired = cur.fetchone()[0]
    if not acquired:
        return {"skipped": True, "reason": "another ingestion run is in progress"}

    try:
        # Cooldown against accidental API hammering.
        cooldown = _refresh_cooldown_seconds()
        if respect_cooldown:
            ok, seconds_since = _seconds_since_last_refresh()
            if ok and seconds_since is not None and seconds_since < cooldown:
                return {
                    "skipped": True,
                    "reason": (
                        f"cooldown: last refresh {int(seconds_since)}s ago "
                        f"(minimum {cooldown}s between refreshes)"
                    ),
                    "retry_after_seconds": int(cooldown - seconds_since),
                }

        results = []
        for source_type in SOURCE_TYPES:
            started = datetime.now(timezone.utc)
            try:
                result = _run_source(source_type, city_ids, settings)
            except Exception as exc:  # noqa: BLE001 — one source failing must not stop others
                logger.exception("ingestion failed for %s", source_type)
                result = {
                    "source_type": source_type,
                    "provider": "unknown",
                    "mode": "error",
                    "configured": False,
                    "records_stored": 0,
                    "error": str(exc)[:300],
                }
            log_ingestion(
                source_type,
                started,
                datetime.now(timezone.utc),
                result["mode"] != "error",
                result.get("records_stored", 0),
                result.get("error"),
            )
            results.append(result)
        return {"skipped": False, "sources": results, "ran_at": datetime.now(timezone.utc).isoformat()}
    finally:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
        except Exception:  # noqa: BLE001 — unlock failure must not mask results
            logger.exception("failed to release advisory lock")


def _seconds_since_last_refresh() -> tuple[bool, float | None]:
    """Read the newest ingestion_log.started_at (any source)."""
    from backend.database import get_last_refresh_seconds_ago

    return True, get_last_refresh_seconds_ago()
