"""Supabase PostgreSQL access layer for CityPulse (psycopg 3).

Design rules (Phase 1):
- Credentials come exclusively from DATABASE_URL in .env — never from JS.
- Every query uses parameterized placeholders (%s); no string interpolation.
- Every helper returns (ok, payload_or_error) so routes can degrade to demo
  mode instead of raising on transient network problems.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings, load_env

logger = logging.getLogger("citypulse.database")

# ---------------------------------------------------------------- schema

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS civic_data (
    id            BIGSERIAL PRIMARY KEY,
    source_type   TEXT             NOT NULL,
    source_id     TEXT             NOT NULL,
    city          TEXT,
    location_name TEXT             NOT NULL,
    latitude      DOUBLE PRECISION NOT NULL,
    longitude     DOUBLE PRECISION NOT NULL,
    value         DOUBLE PRECISION,
    unit          TEXT,
    description   TEXT,
    severity      TEXT CHECK (severity IN ('low', 'moderate', 'high', 'critical')),
    recorded_at   TIMESTAMPTZ      NOT NULL DEFAULT now(),
    created_at    TIMESTAMPTZ      NOT NULL DEFAULT now()
);

-- Upgrade path for tables created before the city column existed.
ALTER TABLE civic_data ADD COLUMN IF NOT EXISTS city TEXT;

CREATE INDEX IF NOT EXISTS idx_civic_data_source_type  ON civic_data (source_type);
CREATE INDEX IF NOT EXISTS idx_civic_data_recorded_at  ON civic_data (recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_civic_data_location     ON civic_data (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_civic_data_severity     ON civic_data (source_type, severity);
CREATE INDEX IF NOT EXISTS idx_civic_data_source       ON civic_data (source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_civic_data_city         ON civic_data (city);
CREATE UNIQUE INDEX IF NOT EXISTS uq_civic_data_source ON civic_data (source_type, source_id);
"""

SEED_SQL = """
INSERT INTO civic_data
    (source_type, source_id, city, location_name, latitude, longitude,
     value, unit, description, severity, recorded_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now() - make_interval(mins => %s))
ON CONFLICT (source_type, source_id) DO UPDATE
SET city          = EXCLUDED.city,
    location_name = EXCLUDED.location_name,
    latitude      = EXCLUDED.latitude,
    longitude     = EXCLUDED.longitude,
    value         = EXCLUDED.value,
    unit          = EXCLUDED.unit,
    description   = EXCLUDED.description,
    severity      = EXCLUDED.severity;
"""


def _connect_kwargs() -> dict[str, Any]:
    """Build psycopg connection kwargs from DATABASE_URL."""
    load_env()
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL not configured (demo mode).")
    kwargs: dict[str, Any] = {"conninfo": url, "connect_timeout": 10}
    # Supabase direct connections require TLS.
    if "sslmode" not in url:
        kwargs["sslmode"] = "require"
    return kwargs


def get_connection():
    """Open a psycopg connection or raise RuntimeError with a short message."""
    try:
        import psycopg  # deferred import so demo mode needs no DB driver
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is not installed. Run: pip install -r requirements.txt"
        ) from exc

    try:
        return psycopg.connect(**_connect_kwargs())
    except Exception as exc:  # network down, wrong password, project paused...
        msg = str(exc).splitlines()[0][:200] if str(exc) else exc.__class__.__name__
        logger.warning("PostgreSQL connection failed: %s", msg)
        raise RuntimeError(f"PostgreSQL connection failed: {msg}") from exc


def test_connection() -> tuple[bool, str]:
    """Cheap SELECT 1 probe used by /api/health and DB-backed routes."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - degrade, don't crash the route
        return False, f"PostgreSQL error: {exc}"


# A TLS handshake to Supabase costs ~100ms+, and the dashboard issues several
# requests at once. Probing on every request was therefore both slow and
# heavy on the pooler, so connectivity is cached very briefly. Short TTL keeps
# the behaviour effectively live (a recovered database is picked up within
# seconds) while collapsing a burst of page-load requests into one probe.
_PROBE_CACHE: dict[str, tuple[float, bool]] = {}
_PROBE_TTL_SECONDS = 10.0
_PROBE_LOCK = threading.Lock()


def database_available(ttl: float = _PROBE_TTL_SECONDS) -> bool:
    """TTL-cached connectivity probe (falls back to ``test_connection``)."""
    import time

    settings = get_settings()
    url = settings.database_url
    if not url:
        return False

    now = time.monotonic()
    cached = _PROBE_CACHE.get(url)
    if cached and (now - cached[0]) < ttl:
        return cached[1]

    ok, _err = test_connection()
    with _PROBE_LOCK:
        _PROBE_CACHE[url] = (now, ok)
    return ok


def reset_connection_cache() -> None:
    """Force the next ``database_available`` call to re-probe (used by tests)."""
    _PROBE_CACHE.clear()


def ensure_schema() -> tuple[bool, str]:
    """Create the civic_data table and indexes if missing (idempotent).

    Called by scripts/setup_db.py and tests; never exposed over HTTP.
    """
    try:
        # NOTE: psycopg3 closes the connection when its `with` block exits,
        # so commit() must happen inside the block.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"Schema error: {exc}"


def seed_demo_records() -> tuple[bool, str]:
    """Insert/refresh clearly-labeled sample rows keyed by source_id.

    Severity is normalized to low/moderate/high/critical; descriptions are
    prefixed "Demo:" so nobody mistakes them for live data.
    """
    from backend.demo_data import DEMO_CITIES, build_demo_record

    city_names = {c["id"]: c["name"] for c in DEMO_CITIES}

    try:
        # NOTE: psycopg3 closes the connection when its `with` block exits,
        # so commit() must happen inside the block.
        with get_connection() as conn:
            with conn.cursor() as cur:
                for city_id in ("bengaluru", "mumbai", "delhi"):
                    city_name = city_names[city_id]
                    for offset, rec in enumerate(build_demo_record(city_id)):
                        severity = rec["severity"]
                        if severity == "unhealthy":
                            severity = "high"
                        cur.execute(
                            SEED_SQL,
                            (
                                rec["source_type"],
                                rec["source_id"],
                                city_name,
                                rec["location_name"],
                                rec["lat"],
                                rec["lon"],
                                rec["value"],
                                rec["unit"],
                                f"Demo: {rec['description']}" if not rec["description"].startswith("Demo:") else rec["description"],
                                severity,
                                6 * (offset + 1),
                            ),
                        )
            conn.commit()
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"Seed error: {exc}"


# ------------------------------------------------------------- queries

_COLUMNS = (
    "id, source_type, source_id, city, location_name, latitude, longitude, "
    "value, unit, description, severity, recorded_at, created_at"
)


def fetch_cities() -> tuple[bool, list[dict[str, Any]] | str]:
    """Distinct cities present in civic_data (DB mode); [] when empty."""
    sql = """
        SELECT location_name,
               AVG(latitude)  AS latitude,
               AVG(longitude) AS longitude
        FROM civic_data
        GROUP BY location_name
        ORDER BY location_name
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return True, [
            {"id": str(name).lower().replace(" ", "-").replace(",", ""),
             "name": name, "lat": float(lat), "lon": float(lon)}
            for name, lat, lon in rows
        ]
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_records(city: str | None = None, limit: int = 200) -> tuple[bool, list[dict[str, Any]] | str]:
    """Latest civic records, optionally filtered by city (parameterized)."""
    sql = f"""
        SELECT {_COLUMNS}
        FROM civic_data
        WHERE (%s::text IS NULL OR city ILIKE %s)
        ORDER BY recorded_at DESC
        LIMIT %s
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, city if city else None, limit))
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
        records = [_row_to_record(cols, row) for row in rows]
        return True, records
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_severity_breakdown(city: str | None = None) -> tuple[bool, dict[str, int] | str]:
    """Record count per severity bucket, optionally city-filtered."""
    sql = """
        SELECT severity, COUNT(*) AS n
        FROM civic_data
        WHERE (%s::text IS NULL OR city ILIKE %s)
        GROUP BY severity
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, city if city else None))
            rows = cur.fetchall()
        breakdown = {severity: 0 for severity in ("low", "moderate", "high", "critical")}
        for severity, n in rows:
            if severity in breakdown:
                breakdown[severity] = int(n)
        return True, breakdown
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def count_records(source_type: str | None = None) -> tuple[bool, int | str]:
    """Count records, optionally filtered by source_type."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            if source_type:
                cur.execute("SELECT COUNT(*) FROM civic_data WHERE source_type = %s", (source_type,))
            else:
                cur.execute("SELECT COUNT(*) FROM civic_data")
            row = cur.fetchone()
        return True, int(row[0])
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def _row_to_record(cols: list[str], row: tuple) -> dict[str, Any]:
    """Convert a DB row into a JSON-safe dict (datetimes to ISO strings)."""
    record = dict(zip(cols, row))
    for key in ("recorded_at", "created_at"):
        if record.get(key) is not None:
            record[key] = record[key].isoformat()
    return record


# ------------------------------------------------------------- Phase 2

UPSERT_OBSERVATION_SQL = """
INSERT INTO civic_data
    (source_type, source_id, provider, metric, city, location_name,
     latitude, longitude, value, unit, description, severity,
     recorded_at, source_url, metadata)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source_type, source_id) DO UPDATE
SET provider      = EXCLUDED.provider,
    metric        = EXCLUDED.metric,
    city          = EXCLUDED.city,
    location_name = EXCLUDED.location_name,
    latitude      = EXCLUDED.latitude,
    longitude     = EXCLUDED.longitude,
    value         = EXCLUDED.value,
    unit          = EXCLUDED.unit,
    description   = EXCLUDED.description,
    severity      = EXCLUDED.severity,
    recorded_at   = EXCLUDED.recorded_at,
    source_url    = EXCLUDED.source_url,
    metadata      = EXCLUDED.metadata
"""


def upsert_observations(observations) -> tuple[bool, int | str]:
    """Persist normalized observations; returns (ok, stored_count).

    Duplicate (source_type, source_id) rows are updated in place, so repeated
    ingestion never creates duplicates.
    """
    from backend.providers.base import ProviderError
    from backend.providers.base import validate_observation

    import psycopg  # lazy import keeps demo mode usable without the driver

    try:
        # Validate everything first (defense in depth), then batch-insert:
        # executemany pipelines the statements, which matters on remote
        # pooler connections where per-row round trips are slow.
        rows = []
        for obs in observations:
            validate_observation(obs)
            # Stamp synthetic-ness into metadata so every stored row
            # self-describes whether it is demo data.
            metadata = {**obs.metadata, "is_synthetic": obs.is_synthetic}
            rows.append(
                (
                    obs.source_type,
                    obs.source_id,
                    obs.provider,
                    obs.metric,
                    obs.city,
                    obs.location_name,
                    obs.latitude,
                    obs.longitude,
                    obs.value,
                    obs.unit,
                    obs.description,
                    obs.severity,
                    obs.recorded_at,
                    obs.source_url,
                    psycopg.types.json.Jsonb(metadata),
                )
            )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(UPSERT_OBSERVATION_SQL, rows)
            conn.commit()
        return True, len(rows)
    except ProviderError as exc:
        return False, f"validation failed: {exc}"
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


UPSERT_PROVIDER_STATUS_SQL = """
INSERT INTO provider_status
    (source_type, provider, is_configured, is_synthetic,
     last_attempt_at, last_success_at, last_error, record_count_last)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source_type) DO UPDATE
SET provider           = EXCLUDED.provider,
    is_configured      = EXCLUDED.is_configured,
    is_synthetic       = EXCLUDED.is_synthetic,
    last_attempt_at    = EXCLUDED.last_attempt_at,
    last_success_at    = EXCLUDED.last_success_at,
    last_error         = EXCLUDED.last_error,
    record_count_last  = EXCLUDED.record_count_last,
    updated_at         = now();
"""


def upsert_provider_status(status: dict[str, Any]) -> None:
    """Record per-source provider health (used by /api/sources)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    UPSERT_PROVIDER_STATUS_SQL,
                    (
                        status["source_type"],
                        status["provider"],
                        status["is_configured"],
                        status["is_synthetic"],
                        status.get("last_attempt_at"),
                        status.get("last_success_at"),
                        status.get("last_error"),
                        status.get("record_count_last", 0),
                    ),
                )
            conn.commit()
    except Exception:  # noqa: BLE001 — health tracking must never crash ingestion
        logger.exception("failed to update provider_status")


def log_ingestion(
    source_type: str,
    started_at: Any,
    finished_at: Any,
    ok: bool,
    records: int,
    error: str | None,
) -> None:
    """Append one row to the ingestion audit log."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ingestion_log (source_type, started_at, finished_at, ok, records, error) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (source_type, started_at, finished_at, ok, records, error),
                )
            conn.commit()
    except Exception:  # noqa: BLE001
        logger.exception("failed to write ingestion_log")


def get_last_refresh_seconds_ago() -> float | None:
    """Seconds since the most recent ingestion attempt (None if never)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT EXTRACT(EPOCH FROM (now() - MAX(started_at))) FROM ingestion_log")
            row = cur.fetchone()
            return float(row[0]) if row and row[0] is not None else None
    except Exception:  # noqa: BLE001
        return None


def fetch_provider_status() -> tuple[bool, list[dict[str, Any]] | str]:
    """Provider health rows for /api/sources."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_type, provider, is_configured, is_synthetic,
                       last_attempt_at, last_success_at, last_error,
                       record_count_last, updated_at
                FROM provider_status
                ORDER BY source_type
                """
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            for key in ("last_attempt_at", "last_success_at", "updated_at"):
                if record.get(key) is not None:
                    record[key] = record[key].isoformat()
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_normalized_data(
    source_type: str | None = None,
    city: str | None = None,
    metric: str | None = None,
    since_hours: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    is_synthetic: bool | None = None,
    limit: int = 500,
    offset: int = 0,
) -> tuple[bool, list[dict[str, Any]] | str]:
    """Query normalized records with filters (all parameterized)."""
    clauses: list[str] = []
    params: list[Any] = []
    if source_type:
        clauses.append("source_type = %s")
        params.append(source_type)
    if city:
        clauses.append("(city ILIKE %s OR %s::text IS NULL)")
        params.extend([city, city])
    if metric:
        clauses.append("metric = %s")
        params.append(metric)
    if since_hours:
        clauses.append("recorded_at >= now() - make_interval(hours => %s)")
        params.append(since_hours)
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        clauses.append("latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s")
        params.extend([min_lat, max_lat, min_lon, max_lon])
    if is_synthetic is not None:
        clauses.append("(metadata->>'is_synthetic')::boolean = %s")
        params.append(is_synthetic)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT " + _COLUMNS + ", provider, metric, source_url, metadata\n"
        "FROM civic_data\n"
        + where + "\n"
        "ORDER BY recorded_at DESC\n"
        "LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        return True, [_row_to_record(cols, row) for row in rows]
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_metric_series(
    source_type: str | None = None,
    metric: str | None = None,
    city: str | None = None,
    hours: int = 72,
) -> tuple[bool, list[dict[str, Any]] | str]:
    """Hourly aggregates (bucket, avg_value, n) for one metric, chronological.

    Buckets without observations are simply absent (missing data is never
    filled with zeros — callers must handle gaps explicitly).
    """
    sql = """
        SELECT date_trunc('hour', recorded_at) AS bucket,
               AVG(value)                       AS avg_value,
               COUNT(*)                         AS n
        FROM civic_data
        WHERE value IS NOT NULL
          AND (%s::text IS NULL OR source_type = %s)
          AND (%s::text IS NULL OR metric = %s)
          AND (%s::text IS NULL OR city = %s)
          AND recorded_at >= now() - make_interval(hours => %s)
        GROUP BY 1
        ORDER BY 1 ASC
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                sql,
                (source_type, source_type, metric, metric, city, city, hours),
            )
            rows = cur.fetchall()
        series = [
            {
                "bucket": bucket.isoformat() if hasattr(bucket, "isoformat") else str(bucket),
                "avg_value": float(avg) if avg is not None else None,
                "n": int(n),
            }
            for bucket, avg, n in rows
        ]
        return True, series
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_latest_by_metric(
    city: str | None = None, hours: int = 24, limit: int = 40
) -> list[dict[str, Any]]:
    """Most recent row per (source_type, metric) for the AI evidence block."""
    sql = """
        SELECT DISTINCT ON (source_type, metric)
               source_type, metric, value, unit, location_name,
               recorded_at, metadata
        FROM civic_data
        WHERE value IS NOT NULL
          AND (%s::text IS NULL OR city = %s)
          AND recorded_at >= now() - make_interval(hours => %s)
        ORDER BY source_type, metric, recorded_at DESC
        LIMIT %s
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, city, hours, limit))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            if record.get("recorded_at") is not None:
                record["recorded_at"] = record["recorded_at"].isoformat()
            out.append(record)
        return out
    except Exception:  # noqa: BLE001
        logger.exception("fetch_latest_by_metric failed")
        return []


INSERT_ANOMALY_SQL = """
INSERT INTO anomaly_events
    (city, source_type, metric, observed_bucket, observed_value,
     baseline_value, deviation_score, method, window_hours,
     sample_size, confidence, limitations)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (city, metric, observed_bucket) DO NOTHING;
"""


def insert_anomaly_events(events: list[dict[str, Any]]) -> tuple[bool, int | str]:
    """Persist anomaly events (deduped by city+metric+bucket)."""
    try:
        rows = [
            (
                event["city"],
                event["source_type"],
                event["metric"],
                event["bucket"],
                event.get("observed_value"),
                event.get("baseline_value"),
                event.get("score"),
                event.get("method", "rolling_median_mad"),
                event.get("window_hours"),
                event.get("sample_size"),
                event.get("confidence", "low"),
                event.get("limitations"),
            )
            for event in events
        ]
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(INSERT_ANOMALY_SQL, rows)
            conn.commit()
        return True, len(rows)
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_recent_anomalies(city: str, limit: int = 20) -> tuple[bool, list[dict[str, Any]] | str]:
    """Latest anomaly events for a city (newest first)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT city, source_type, metric, observed_bucket, observed_value,
                       baseline_value, deviation_score, method, window_hours,
                       sample_size, confidence, limitations, created_at
                FROM anomaly_events
                WHERE city = %s
                ORDER BY observed_bucket DESC
                LIMIT %s
                """,
                (city, limit),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            for key in ("observed_bucket", "created_at"):
                if record.get(key) is not None:
                    record[key] = record[key].isoformat()
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


# =====================================================================
# Phase 3 — civic event lifecycle + simulation runs
#
# Conventions match the rest of this module:
# - every statement is parameterized (%s placeholders);
# - every helper returns (ok, payload_or_error) so callers can degrade to a
#   clearly-labeled demo store instead of raising on transient DB problems;
# - column names in dynamic SET clauses come only from EVENT_UPDATABLE_COLUMNS
#   (an allow-list defined in code), never from request input, so building the
#   statement cannot be used for SQL injection.
# =====================================================================

EVENT_COLUMNS = (
    "id, event_ref, external_key, city, city_id, source_type, category, title, "
    "description, severity, status, latitude, longitude, location_name, "
    "reported_at, acknowledged_at, resolved_at, closed_at, acknowledged_by, "
    "resolved_by, resolution_note, evidence, tags, is_simulated, "
    "simulation_run_id, revision, created_at, updated_at"
)

# Allow-list for dynamic UPDATE statements (never taken from user input).
EVENT_UPDATABLE_COLUMNS = frozenset({
    "external_key", "city", "city_id", "source_type", "category", "title",
    "description", "severity", "status", "latitude", "longitude",
    "location_name", "reported_at", "acknowledged_at", "resolved_at",
    "closed_at", "acknowledged_by", "resolved_by", "resolution_note",
    "evidence", "tags", "is_simulated", "simulation_run_id", "revision",
})

EVENT_TIMESTAMP_COLUMNS = (
    "reported_at", "acknowledged_at", "resolved_at", "closed_at",
    "created_at", "updated_at",
)


def _jsonb(value: Any) -> Any:
    """Wrap a Python value for a JSONB column.

    psycopg 3 adapts plain lists to Postgres ARRAY types by default, which does
    not match a JSONB column, so evidence/tags must be wrapped explicitly.
    """
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:  # pragma: no cover - driver missing in demo mode
        raise RuntimeError(
            "psycopg is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return Jsonb(value if value is not None else [])


def _row_to_event(row: tuple, cols: list[str]) -> dict[str, Any]:
    """Convert a civic_events row into a JSON-safe dict (datetimes to ISO)."""
    record = dict(zip(cols, row))
    for key in EVENT_TIMESTAMP_COLUMNS:
        if record.get(key) is not None:
            record[key] = record[key].isoformat()
    for key in ("evidence", "tags"):
        if record.get(key) is None:
            record[key] = []
    return record


def insert_civic_event(fields: dict[str, Any]) -> tuple[bool, dict[str, Any] | str]:
    """Insert one civic event.

    Returns ``(True, {"event": row, "inserted": bool})``. When ``external_key``
    is supplied and already stored, the existing row is returned with
    ``inserted=False`` (idempotent ingestion — re-ingesting a feed item can
    never create a duplicate event).
    """
    columns = [
        "event_ref", "external_key", "city", "city_id", "source_type",
        "category", "title", "description", "severity", "status",
        "latitude", "longitude", "location_name", "reported_at",
        "acknowledged_at", "resolved_at", "closed_at", "acknowledged_by",
        "resolved_by", "resolution_note", "evidence", "tags",
        "is_simulated", "simulation_run_id", "revision",
    ]
    values = [
        _jsonb(fields.get(name)) if name in ("evidence", "tags") else fields.get(name)
        for name in columns
    ]
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"""
        INSERT INTO civic_events ({", ".join(columns)})
        VALUES ({placeholders}, now(), now())
        ON CONFLICT (external_key) DO NOTHING
        RETURNING {EVENT_COLUMNS}
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, values)
                row = cur.fetchone()
                inserted = row is not None
                if not inserted:
                    # Conflict on external_key: return the stored event instead.
                    cur.execute(
                        f"SELECT {EVENT_COLUMNS} FROM civic_events WHERE external_key = %s",
                        (fields.get("external_key"),),
                    )
                    row = cur.fetchone()
                cols = [d[0] for d in cur.description]
            conn.commit()
        if row is None:  # pragma: no cover - conflict without a matching row
            return False, "conflicting event row could not be reloaded"
        return True, {"event": _row_to_event(row, cols), "inserted": inserted}
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_civic_event(event_ref: str) -> tuple[bool, dict[str, Any] | None | str]:
    """Load one event by its public event_ref (None when absent)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {EVENT_COLUMNS} FROM civic_events WHERE event_ref = %s",
                (event_ref,),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
        return True, (_row_to_event(row, cols) if row else None)
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_civic_events(
    city: str | None = None,
    statuses: tuple[str, ...] | None = None,
    severities: tuple[str, ...] | None = None,
    source_type: str | None = None,
    include_simulated: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> tuple[bool, list[dict[str, Any]] | str]:
    """List events newest-first, with active statuses ordered first."""
    sql = f"""
        SELECT {EVENT_COLUMNS}
        FROM civic_events
        WHERE (%s::text IS NULL OR city ILIKE %s)
          AND (%s::text[] IS NULL OR status = ANY(%s))
          AND (%s::text[] IS NULL OR severity = ANY(%s))
          AND (%s::text IS NULL OR source_type = %s)
          AND (%s::boolean OR is_simulated = FALSE)
        ORDER BY
            CASE status
                WHEN 'open' THEN 0
                WHEN 'acknowledged' THEN 1
                WHEN 'in_progress' THEN 2
                WHEN 'resolved' THEN 3
                ELSE 4
            END,
            reported_at DESC
        LIMIT %s OFFSET %s
    """
    params = (
        city, city if city else None,
        list(statuses) if statuses else None, list(statuses) if statuses else None,
        list(severities) if severities else None, list(severities) if severities else None,
        source_type, source_type,
        include_simulated,
        limit, offset,
    )
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        return True, [_row_to_event(row, cols) for row in rows]
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def update_civic_event(
    event_ref: str,
    fields: dict[str, Any],
    expected_revision: int | None = None,
) -> tuple[bool, dict[str, Any] | None | str]:
    """Apply an allow-listed field update and return the updated row.

    ``expected_revision`` enables optimistic concurrency: when it does not match
    the stored revision the update is rejected (None) so two operators cannot
    silently overwrite each other's work.
    """
    unknown = set(fields) - EVENT_UPDATABLE_COLUMNS
    if unknown:
        return False, f"columns not updatable: {sorted(unknown)}"
    if not fields:
        return True, None
    assigns = ", ".join(f"{name} = %s" for name in fields)
    params: list[Any] = [
        _jsonb(value) if name in ("evidence", "tags") else value
        for name, value in fields.items()
    ]
    guard = ""
    if expected_revision is not None:
        guard = " AND revision = %s"
        params.append(expected_revision)
    sql = f"""
        UPDATE civic_events
        SET {assigns}, updated_at = now(), revision = revision + 1
        WHERE event_ref = %s{guard}
        RETURNING {EVENT_COLUMNS}
    """
    params.append(event_ref)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                cols = [d[0] for d in cur.description]
            conn.commit()
        return True, (_row_to_event(row, cols) if row else None)
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def append_event_timeline(
    event_id: int,
    action: str,
    from_status: str | None,
    to_status: str | None,
    actor: str | None,
    note: str | None,
) -> tuple[bool, str]:
    """Append one entry to the append-only lifecycle audit trail."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO civic_event_timeline
                        (event_id, action, from_status, to_status, actor, note)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (event_id, action, from_status, to_status, actor, note),
                )
            conn.commit()
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_event_timeline(event_id: int, limit: int = 50) -> tuple[bool, list[dict[str, Any]] | str]:
    """Lifecycle history for one event (oldest first)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT action, from_status, to_status, actor, note, at
                FROM civic_event_timeline
                WHERE event_id = %s
                ORDER BY at ASC, id ASC
                LIMIT %s
                """,
                (event_id, limit),
            )
            rows = cur.fetchall()
        return True, [
            {
                "action": action,
                "from_status": from_status,
                "to_status": to_status,
                "actor": actor,
                "note": note,
                "at": at.isoformat() if at else None,
            }
            for action, from_status, to_status, actor, note, at in rows
        ]
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def count_civic_events(
    city: str | None = None,
    active_only: bool = True,
    include_simulated: bool = True,
) -> tuple[bool, int | str]:
    """Count events; active = open | acknowledged | in_progress."""
    active_filter = (
        "AND status IN ('open', 'acknowledged', 'in_progress')" if active_only else ""
    )
    sim_filter = "" if include_simulated else "AND is_simulated = FALSE"
    sql = f"""
        SELECT COUNT(*) FROM civic_events
        WHERE (%s::text IS NULL OR city ILIKE %s)
        {active_filter}
        {sim_filter}
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, city if city else None))
            row = cur.fetchone()
        return True, int(row[0])
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def count_civic_events_by_status(city: str | None = None) -> tuple[bool, dict[str, int] | str]:
    """Event counts grouped by status (used by /api/summary and /api/events)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) FROM civic_events
                WHERE (%s::text IS NULL OR city ILIKE %s)
                GROUP BY status
                """,
                (city, city if city else None),
            )
            rows = cur.fetchall()
        return True, {str(status): int(total) for status, total in rows}
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def civic_events_version(city: str | None = None) -> tuple[bool, int | str]:
    """Change token for event data (max updated_at in ms, mixed with the count).

    Used by the SSE stream and its polling fallback so clients can tell whether
    their cached state is current without re-fetching every event.
    """
    sql = """
        SELECT COALESCE(EXTRACT(EPOCH FROM MAX(updated_at)) * 1000, 0)::bigint,
               COUNT(*)
        FROM civic_events
        WHERE (%s::text IS NULL OR city ILIKE %s)
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, city if city else None))
            max_ms, count = cur.fetchone()
        return True, int(max_ms or 0) * 1000 + int(count)
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def insert_simulation_run(fields: dict[str, Any]) -> tuple[bool, str]:
    """Record the start of a simulation run (idempotent on run_ref)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO simulation_runs
                        (run_ref, scenario_id, scenario_name, city, city_id,
                         status, actor, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_ref) DO NOTHING
                    """,
                    (
                        fields.get("run_ref"),
                        fields.get("scenario_id"),
                        fields.get("scenario_name"),
                        fields.get("city"),
                        fields.get("city_id"),
                        fields.get("status", "running"),
                        fields.get("actor"),
                        fields.get("notes"),
                    ),
                )
            conn.commit()
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def update_simulation_run(run_ref: str, fields: dict[str, Any]) -> tuple[bool, str]:
    """Update simulation run counters/status (allow-listed columns only)."""
    allowed = {"status", "events_created", "observations_written", "finished_at", "notes"}
    unknown = set(fields) - allowed
    if unknown:
        return False, f"columns not updatable: {sorted(unknown)}"
    if not fields:
        return True, ""
    assigns = ", ".join(f"{name} = %s" for name in fields)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE simulation_runs SET {assigns} WHERE run_ref = %s",
                    [*fields.values(), run_ref],
                )
            conn.commit()
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_simulation_run_events(run_ref: str) -> tuple[bool, list[dict[str, Any]] | str]:
    """Events produced by one simulation run (newest first)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {EVENT_COLUMNS} FROM civic_events
                WHERE simulation_run_id = %s
                ORDER BY reported_at DESC
                """,
                (run_ref,),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        return True, [_row_to_event(row, cols) for row in rows]
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_simulation_runs(limit: int = 20) -> tuple[bool, list[dict[str, Any]] | str]:
    """Recent simulation runs (newest first)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_ref, scenario_id, scenario_name, city, city_id, status,
                       started_at, finished_at, events_created,
                       observations_written, actor, notes
                FROM simulation_runs
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            for key in ("started_at", "finished_at"):
                if record.get(key) is not None:
                    record[key] = record[key].isoformat()
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


# =====================================================================
# Phase 4 — alert center, historical replay, location comparison
# =====================================================================


def upsert_alert_instance(payload: dict[str, Any]) -> tuple[bool, bool | str]:
    """Insert or update one alert by dedup_key.

    Returns (ok, created_flag). Acknowledgement/dismissal is preserved on
    re-sync because the ON CONFLICT clause never touches those columns.

    created/updated is decided by ``created_at = updated_at``: both default to
    the same transaction timestamp on INSERT, while an UPDATE always stamps
    ``updated_at`` with a later transaction. (The previous ``xmax = 0``
    heuristic was unreliable — an updated row version can also report
    xmax = 0 when the update is the row's first version in the page cache.)
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_instances (
                    dedup_key, city, source_type, metric, severity, title, summary,
                    evidence, observed_value, baseline_value, location_name,
                    detected_at, is_synthetic
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dedup_key) DO UPDATE SET
                    summary        = EXCLUDED.summary,
                    observed_value = EXCLUDED.observed_value,
                    baseline_value = EXCLUDED.baseline_value,
                    evidence       = EXCLUDED.evidence,
                    updated_at     = now()
                RETURNING created_at = updated_at AS created
                """,
                (
                    payload["dedup_key"],
                    payload.get("city"),
                    payload.get("source_type"),
                    payload.get("metric"),
                    payload.get("severity") or "low",
                    payload.get("title") or "Civic alert",
                    payload.get("summary") or "",
                    _jsonb(payload.get("evidence") or {}),
                    payload.get("observed_value"),
                    payload.get("baseline_value"),
                    payload.get("location_name"),
                    payload.get("detected_at") or datetime.now(timezone.utc),
                    bool(payload.get("is_synthetic")),
                ),
            )
            row = cur.fetchone()
            conn.commit()
        return True, bool(row[0]) if row else False
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_alert_instances(
    city: str,
    status: str = "active",
    limit: int = 50,
) -> tuple[bool, list[dict[str, Any]] | str]:
    """Alerts for a city: active, acknowledged, dismissed, or all."""
    if status not in ("active", "acknowledged", "dismissed", "all"):
        status = "active"
    conditions = {
        "active": "AND dismissed_at IS NULL AND acknowledged_at IS NULL",
        "acknowledged": "AND acknowledged_at IS NOT NULL AND dismissed_at IS NULL",
        "dismissed": "AND dismissed_at IS NOT NULL",
        "all": "",
    }
    sql = f"""
        SELECT dedup_key, city, source_type, metric, severity, title, summary,
               evidence, observed_value, baseline_value, location_name,
               detected_at, acknowledged_at, acknowledged_by, dismissed_at,
               is_synthetic
        FROM alert_instances
        WHERE city = %s {conditions[status]}
        ORDER BY detected_at DESC
        LIMIT %s
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, max(1, min(limit, 100))))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            for key in ("detected_at", "acknowledged_at", "dismissed_at"):
                if record.get(key) is not None and hasattr(record[key], "isoformat"):
                    record[key] = record[key].isoformat()
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def update_alert_instance(
    dedup_key: str,
    acknowledged: bool = False,
    dismissed: bool = False,
    by: str = "dashboard",
) -> tuple[bool, dict[str, Any] | str]:
    """Acknowledge or dismiss an alert (never overwrites a later action)."""
    try:
        sets = ["updated_at = now()"]
        params: list[Any] = []
        if acknowledged:
            sets.append("acknowledged_at = COALESCE(acknowledged_at, now())")
            sets.append("acknowledged_by = COALESCE(acknowledged_by, %s)")
            params.append(by)
        if dismissed:
            sets.append("dismissed_at = COALESCE(dismissed_at, now())")
        params.append(dedup_key)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alert_instances SET {sets}
                WHERE dedup_key = %s
                RETURNING dedup_key, acknowledged_at, dismissed_at
                """.replace("{sets}", ", ".join(sets)),
                tuple(params),
            )
            row = cur.fetchone()
            conn.commit()
        if not row:
            return False, "alert not found"
        return True, {
            "dedup_key": row[0],
            "acknowledged_at": row[1].isoformat() if row[1] else None,
            "dismissed_at": row[2].isoformat() if row[2] else None,
        }
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_alert_rules() -> tuple[bool, list[dict[str, Any]] | str]:
    """Configurable alert rules."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, city, metric, operator, threshold_value,
                       window_hours, enabled, label
                FROM alert_rules
                ORDER BY id ASC
                """
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        return True, [dict(zip(cols, row)) for row in rows]
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def upsert_alert_rule(rule: dict[str, Any]) -> tuple[bool, bool | str]:
    """Insert a rule if new (or refresh enabled flag); returns (ok, created)."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_rules (city, metric, operator, threshold_value,
                                         window_hours, enabled, label)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (city, metric, operator, threshold_value)
                    DO UPDATE SET enabled = EXCLUDED.enabled
                RETURNING (xmax = 0) AS created
                """,
                (
                    rule.get("city"),
                    rule["metric"],
                    rule.get("operator") or ">",
                    float(rule["threshold_value"]),
                    int(rule.get("window_hours") or 24),
                    bool(rule.get("enabled", True)),
                    rule.get("label"),
                ),
            )
            row = cur.fetchone()
            conn.commit()
        return True, bool(row[0]) if row else False
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_history_buckets(
    city: str,
    hours: int = 168,
    metrics: list[str] | None = None,
) -> tuple[bool, list[dict[str, Any]] | str]:
    """Hourly avg per metric over the window (historical replay charts).

    Missing hours are simply absent — callers render gaps, never zeros.
    """
    sql = """
        SELECT date_trunc('hour', recorded_at) AS bucket,
               metric,
               AVG(value) AS avg_value,
               COUNT(*)   AS n
        FROM civic_data
        WHERE value IS NOT NULL
          AND city = %s
          AND metric IS NOT NULL
          AND recorded_at >= now() - make_interval(hours => %s)
          AND (%s::text[] IS NULL OR metric = ANY(%s))
        GROUP BY 1, 2
        ORDER BY 1 ASC, 2 ASC
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, hours, metrics, metrics))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            if record.get("bucket") is not None and hasattr(record["bucket"], "isoformat"):
                record["bucket"] = record["bucket"].isoformat()
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_location_comparison(
    city: str,
    hours: int = 24,
    metrics: list[str] | None = None,
    limit_locations: int = 12,
) -> tuple[bool, list[dict[str, Any]] | str]:
    """Per-location metric averages over a matching window.

    Coverage fields (observations, distinct hours, last seen) are returned so
    the UI can disclose sample-size differences; no rankings are implied.
    """
    sql = """
        SELECT location_name,
               metric,
               AVG(value)                    AS avg_value,
               COUNT(*)                      AS observations,
               COUNT(DISTINCT date_trunc('hour', recorded_at)) AS hours_covered,
               MAX(recorded_at)              AS last_observed_at,
               BOOL_OR((metadata->>'is_synthetic')::boolean)   AS has_synthetic
        FROM civic_data
        WHERE value IS NOT NULL
          AND city = %s
          AND location_name IS NOT NULL
          AND metric IS NOT NULL
          AND recorded_at >= now() - make_interval(hours => %s)
          AND (%s::text[] IS NULL OR metric = ANY(%s))
        GROUP BY location_name, metric
        ORDER BY location_name, metric
        LIMIT %s
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, hours, metrics, metrics, max(1, min(limit_locations * 8, 200))))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            for key in ("last_observed_at",):
                if record.get(key) is not None and hasattr(record[key], "isoformat"):
                    record[key] = record[key].isoformat()
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"


def fetch_severity_time_series(
    city: str,
    hours: int = 72,
    bucket_size: str = "hour",
) -> tuple[bool, list[dict[str, Any]] | str]:
    """Observation counts per severity per time bucket (DB-side aggregation).

    One grouped query — no Python-side counting. Buckets with no rows are
    absent, so charts show gaps rather than fabricated zeros. bucket_size is
    validated against an allowlist and values are passed as bind parameters.
    """
    if bucket_size not in ("hour", "day"):
        bucket_size = "hour"
    sql = """
        SELECT date_trunc(%(part)s, recorded_at) AS bucket,
               severity,
               COUNT(*) AS count
        FROM civic_data
        WHERE city = %(city)s
          AND recorded_at >= now() - make_interval(hours => %(hours)s)
          AND severity IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1 ASC, 2 ASC
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"part": bucket_size, "city": city, "hours": hours})
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            if record.get("bucket") is not None and hasattr(record["bucket"], "isoformat"):
                record["bucket"] = record["bucket"].isoformat()
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"



# =====================================================================
# Phase 9 — impact engine / cross-domain helpers
# =====================================================================

def fetch_anomalies_with_footprints(city: str, limit: int = 50) -> tuple[bool, list[dict[str, Any]] | str]:
    """Stored anomaly flags enriched with mean observed coordinates.

    Footprints join anomaly_events to civic_data on (city, metric, hour
    bucket); the mean of geolocated observations becomes the anomaly's
    approximate location. Anomalies without geolocated rows are returned
    with coordinates=None — the UI must skip, never guess, those.
    """
    sql = """
        SELECT a.city, a.source_type, a.metric, a.observed_bucket, a.observed_value,
               a.baseline_value, a.deviation_score, a.method, a.window_hours,
               a.sample_size, a.confidence, a.limitations, a.created_at,
               AVG(c.latitude)  AS latitude,
               AVG(c.longitude) AS longitude,
               COUNT(c.id)      AS footprint_points
        FROM anomaly_events a
        LEFT JOIN civic_data c
               ON c.city = a.city
              AND c.metric = a.metric
              AND date_trunc('hour', c.recorded_at) = a.observed_bucket
              AND c.latitude IS NOT NULL
        WHERE a.city = %s
        GROUP BY a.id
        ORDER BY a.observed_bucket DESC
        LIMIT %s
    """
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (city, max(1, min(int(limit), 100))))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            record = dict(zip(cols, row))
            for key in ("observed_bucket", "created_at"):
                if record.get(key) is not None and hasattr(record[key], "isoformat"):
                    record[key] = record[key].isoformat()
            for key in ("latitude", "longitude"):
                if record.get(key) is not None:
                    record[key] = float(record[key])
            record["footprint_points"] = int(record.get("footprint_points") or 0)
            out.append(record)
        return True, out
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"PostgreSQL error: {exc}"
