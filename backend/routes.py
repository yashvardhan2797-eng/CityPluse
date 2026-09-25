"""HTTP routes for CityPulse (Phases 1-3).

Phase 1 endpoints are preserved unchanged in behavior; Phase 2/3 add data
ingestion status, normalized queries, analytics, and grounded AI summaries.
All endpoints are JSON under /api/*. The frontend never touches Supabase,
providers, or secrets directly — it calls these routes only.
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from backend.config import get_settings
from backend.database import (
    database_available,
    fetch_normalized_data,
    fetch_provider_status,
    fetch_records,
    fetch_severity_breakdown,
    get_last_refresh_seconds_ago,
)
from backend.demo_data import (
    build_demo_record,
    get_demo_cities,
    get_demo_summary,
    resolve_city,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ------------------------------------------------------------- helpers

def _data_mode() -> tuple[str, bool]:
    """Return (mode, db_ok): 'database' when Postgres answers, else 'demo'.

    Uses the short-TTL cached probe in database.database_available so a page
    load (several concurrent requests) costs one round trip instead of one
    connection per endpoint, while still recovering within seconds of an
    outage ending.
    """
    if not get_settings().database_url:
        return "demo", False
    ok = database_available()
    return ("database" if ok else "demo"), ok


# Canonical id->name resolver lives in demo_data (single source of truth);
# this alias keeps the historical call sites readable.
_city_display_name = resolve_city


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    """Parse a bounded integer query parameter (input validation)."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _bbox_arg() -> tuple[float, float, float, float] | None:
    """Parse bbox=minLon,minLat,maxLon,maxLat with sanity clamping."""
    raw = (request.args.get("bbox") or "").strip()
    if not raw:
        return None
    try:
        parts = [float(p) for p in raw.split(",")]
        if len(parts) != 4:
            return None
        min_lon, min_lat, max_lon, max_lat = parts
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            return None
        return min_lon, min_lat, max_lon, max_lat
    except ValueError:
        return None


def _demo_observations_payload(city: str | None):
    """Demo fallback payload for data/map endpoints (no DB configured)."""
    from backend.ingest import _fetch_demo  # noqa: PLC0415 — avoids import cycle at load

    city_key = city or "bengaluru"
    records = []
    for source_type in ("weather", "air_quality", "transit", "incident"):
        for obs in _fetch_demo(source_type, city_key):
            records.append({
                "source_type": obs.source_type,
                "source_id": obs.source_id,
                "provider": obs.provider,
                "metric": obs.metric,
                "city": obs.city,
                "location_name": obs.location_name,
                "latitude": obs.latitude,
                "longitude": obs.longitude,
                "value": obs.value,
                "unit": obs.unit,
                "description": obs.description,
                "severity": obs.severity,
                "recorded_at": obs.recorded_at.isoformat(),
                "created_at": obs.recorded_at.isoformat(),
                "metadata": {"is_synthetic": True, **obs.metadata},
            })
    return records


def _event_counts(city_raw: str) -> tuple[dict[str, int], int]:
    """Phase 3: event counts per status + the active total for KPI tiles."""
    from backend.events import ACTIVE_STATUSES, status_breakdown

    counts = status_breakdown(city_raw)
    return counts, sum(counts.get(status, 0) for status in ACTIVE_STATUSES)


def _query_records():
    """Shared query logic for /api/data and /api/map."""
    city_raw = (request.args.get("city") or "").strip() or None
    city = _city_display_name(city_raw) if city_raw else None
    source_type = (request.args.get("source_type") or "").strip() or None
    metric = (request.args.get("metric") or "").strip() or None
    hours = _int_arg("hours", 24, 1, 24 * 30)
    limit = _int_arg("limit", 300, 1, 1000)
    offset = _int_arg("offset", 0, 0, 10_000)
    bbox = _bbox_arg()
    return city, source_type, metric, hours, limit, offset, bbox


# -------------------------------------------------- Phase 1 endpoints

@api_bp.get("/health")
def health():
    """Liveness + data-mode + provider snapshot (no secrets)."""
    mode, db_ok = _data_mode()
    providers = None
    last_refresh = None
    if db_ok:
        ok, payload = fetch_provider_status()
        if ok:
            providers = [
                {
                    "source_type": p["source_type"],
                    "provider": p["provider"],
                    "mode": "synthetic" if p["is_synthetic"] else "live",
                    "last_success_at": p["last_success_at"],
                    "last_error": p["last_error"],
                }
                for p in payload
            ]
        seconds = get_last_refresh_seconds_ago()
        last_refresh = int(seconds) if seconds is not None else None
    return jsonify({
        "status": "ok",
        "mode": mode,
        "database_reachable": db_ok,
        "version": "0.2.0 (Phases 1-3)",
        "last_refresh_seconds_ago": last_refresh,
        "providers": providers,
    })


@api_bp.get("/cities")
def cities():
    """City list for the selector (demo list always available)."""
    mode, db_ok = _data_mode()
    return jsonify({
        "mode": mode,
        "database_reachable": db_ok,
        "cities": get_demo_cities(),
        "error": None,
    })


@api_bp.get("/records")
def records():
    """Phase 1 records endpoint (kept for compatibility).

    Now backed by the same normalized civic_data table, enriched with
    provider/metric/metadata when available; falls back to demo data.
    """
    city_raw = (request.args.get("city") or "").strip() or None
    city = _city_display_name(city_raw) if city_raw else None
    mode, db_ok = _data_mode()

    if mode == "database":
        ok, payload = fetch_records(city=city)
        if ok and payload:
            return jsonify({"mode": "database", "city": city_raw, "records": payload})
        notice = (
            f"Database unavailable ({payload}); showing demo data."
            if not ok
            else f"No database records for '{city_raw or 'any city'}' yet; showing demo data."
        )
        return jsonify({
            "mode": "demo-fallback",
            "city": city_raw,
            "records": build_demo_record(city_raw or "bengaluru"),
            "notice": notice,
        })

    return jsonify({
        "mode": "demo",
        "city": city_raw or "bengaluru",
        "records": build_demo_record(city_raw or "bengaluru"),
        "notice": "Demo mode: synthetic data, not live civic information.",
    })


@api_bp.get("/summary")
def summary():
    """KPI summary derived from normalized observations (labeled by quality)."""
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    mode, db_ok = _data_mode()
    hours = _int_arg("hours", 24, 1, 168)

    if not db_ok:
        event_counts, active_events = _event_counts(city_raw)
        demo_summary = get_demo_summary(city_raw)
        demo_summary["active_events"] = active_events
        demo_summary["event_counts"] = event_counts
        return jsonify({
            "mode": mode,
            "city": city_raw,
            "database_reachable": db_ok,
            "summary": demo_summary,
            "notice": "Demo mode: synthetic KPI values, not live civic data.",
        })

    ok, rows = fetch_normalized_data(city=city, since_hours=hours, limit=1000)
    if not ok:
        event_counts, active_events = _event_counts(city_raw)
        demo_summary = get_demo_summary(city_raw)
        demo_summary["active_events"] = active_events
        demo_summary["event_counts"] = event_counts
        return jsonify({
            "mode": "demo-fallback",
            "city": city_raw,
            "database_reachable": db_ok,
            "summary": demo_summary,
            "notice": f"Database query failed ({rows}); showing demo KPIs.",
        })

    latest_by_metric: dict[str, dict] = {}
    synthetic_flags: list[bool] = []
    incidents_24h = 0
    for row in rows or []:
        metric = row.get("metric")
        if metric and metric not in latest_by_metric:
            latest_by_metric[metric] = row
        meta = row.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("is_synthetic"):
            synthetic_flags.append(True)
        if row.get("source_type") == "incident":
            incidents_24h += 1

    def _latest(metric: str) -> dict | None:
        row = latest_by_metric.get(metric)
        if not row:
            return None
        return {
            "value": row.get("value"),
            "unit": row.get("unit"),
            "recorded_at": row.get("recorded_at"),
            "location": row.get("location_name"),
            "synthetic": bool((row.get("metadata") or {}).get("is_synthetic")),
        }

    quality = "synthetic" if synthetic_flags and len(synthetic_flags) == len(rows or []) else (
        "mixed" if synthetic_flags else "live"
    )
    # Phase 3: operational event counts (open/acknowledged/in_progress).
    event_counts, active_events = _event_counts(city_raw)
    return jsonify({
        "mode": "database",
        "city": city_raw,
        "database_reachable": db_ok,
        "summary": {
            "temperature_c": _latest("temperature_c"),
            "humidity_pct": _latest("humidity_pct"),
            "precipitation_mm": _latest("precipitation_mm"),
            "pm25_ugm3": _latest("pm25_ugm3"),
            "transit_load_pct": _latest("load_factor_pct"),
            "transit_delay_min": _latest("delay_min"),
            "active_incidents": incidents_24h,
            "active_events": active_events,
            "event_counts": event_counts,
            "data_quality": quality,
            "window_hours": hours,
            "generated_at": rows[0]["recorded_at"] if rows else None,
        },
        "notice": None if rows else "No observations in the selected window yet.",
    })


@api_bp.get("/chart/severity")
def chart_severity():
    """Severity distribution for the dashboard chart."""
    city_raw = (request.args.get("city") or "").strip() or None
    city = _city_display_name(city_raw) if city_raw else None
    mode, db_ok = _data_mode()

    if mode == "database":
        ok, payload = fetch_severity_breakdown(city=city)
        if ok and sum(payload.values()) > 0:
            return jsonify({"mode": "database", "city": city_raw, "breakdown": payload})

    counts = {"low": 0, "moderate": 0, "high": 0, "critical": 0}
    for rec in build_demo_record(city_raw or "bengaluru"):
        counts[rec["severity"]] = counts.get(rec["severity"], 0) + 1
    return jsonify({
        "mode": "demo",
        "city": city_raw,
        "breakdown": counts,
        "notice": "Demo mode: synthetic severity distribution.",
    })


@api_bp.get("/settings")
def settings():
    """Non-secret runtime settings for the UI status panel."""
    s = get_settings()
    mode, db_ok = _data_mode()
    from backend.events import ALLOWED_TRANSITIONS, EVENT_SEVERITIES, EVENT_STATUSES

    return jsonify({
        "mode": mode,
        "database_reachable": db_ok,
        "supabase_configured": bool(s.supabase_url),
        "providers": {
            "weather": {"provider": "open-meteo", "configured": s.weather_enabled, "needs_key": False},
            "air_quality": {"provider": "openaq", "configured": bool(s.openaq_api_key), "needs_key": True},
            "transit": {"provider": "gtfs-rt", "configured": bool(s.transit_gtfs_rt_url), "needs_key": False},
            "incident": {"provider": "city-open-data", "configured": bool(s.incidents_socrata_url), "needs_key": False},
        },
        "ai_configured": bool(s.ai_provider and s.ai_api_key and s.ai_base_url),
        "realtime": {
            "enabled": s.realtime_enabled,
            "transport": "sse",
            "stream_path": "/api/events/stream",
            "heartbeat_seconds": s.sse_heartbeat_seconds,
        },
        "events": {
            "statuses": list(EVENT_STATUSES),
            "severities": list(EVENT_SEVERITIES),
            "transitions": {k: list(v) for k, v in ALLOWED_TRANSITIONS.items()},
            "stale_hours": s.event_stale_hours,
        },
        "simulation_enabled": s.simulation_enabled,
        "phase": 3,
    })


# -------------------------------------------------- Phase 2 endpoints

@api_bp.get("/data")
def data_endpoint():
    """Normalized records with filters: city, source_type, metric, hours, bbox, paging."""
    mode, db_ok = _data_mode()
    city, source_type, metric, hours, limit, offset, bbox = _query_records()

    if not db_ok:
        return jsonify({
            "mode": "demo",
            "records": _demo_observations_payload(city)[:limit],
            "pagination": {"limit": limit, "offset": offset, "total_estimate": None},
            "notice": "Demo mode: synthetic observations, not live data.",
        })

    ok, payload = fetch_normalized_data(
        source_type=source_type,
        city=city,
        metric=metric,
        since_hours=hours,
        bbox=bbox,
        limit=limit,
        offset=offset,
    )
    if not ok:
        return jsonify({"error": "query failed", "detail": str(payload)[:200]}), 503
    return jsonify({
        "mode": "database",
        "records": payload,
        "pagination": {"limit": limit, "offset": offset, "returned": len(payload)},
    })


@api_bp.get("/map")
def map_endpoint():
    """Geospatial records for map visualization (bbox filter supported)."""
    mode, db_ok = _data_mode()
    city, source_type, metric, hours, limit, offset, bbox = _query_records()
    limit = min(limit, 500)

    if not db_ok:
        records = [r for r in _demo_observations_payload(city) if r.get("latitude") is not None]
        return jsonify({"mode": "demo", "records": records[:limit]})

    ok, payload = fetch_normalized_data(
        source_type=source_type,
        city=city,
        metric=metric,
        since_hours=hours,
        bbox=bbox,
        limit=limit,
        offset=offset,
    )
    if not ok:
        return jsonify({"error": "query failed", "detail": str(payload)[:200]}), 503
    records = [r for r in payload if r.get("latitude") is not None]
    return jsonify({
        "mode": "database",
        "records": records,
        "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
    })


@api_bp.get("/sources")
def sources():
    """Provider health: availability, last success/attempt, errors."""
    mode, db_ok = _data_mode()
    s = get_settings()

    configured = {
        "weather": {"provider": "open-meteo", "configured": s.weather_enabled},
        "air_quality": {"provider": "openaq", "configured": bool(s.openaq_api_key)},
        "transit": {"provider": "gtfs-rt", "configured": bool(s.transit_gtfs_rt_url)},
        "incident": {"provider": "city-open-data", "configured": bool(s.incidents_socrata_url)},
    }
    status_rows = []
    if db_ok:
        ok, payload = fetch_provider_status()
        if ok:
            status_rows = payload

    merged = []
    for source_type, info in configured.items():
        row = next((r for r in status_rows if r["source_type"] == source_type), None)
        merged.append({
            "source_type": source_type,
            "provider": (row or {}).get("provider") or info["provider"],
            "configured": info["configured"],
            "mode": ("synthetic" if (row or {}).get("is_synthetic") else "live") if row else ("configured" if info["configured"] else "unconfigured"),
            "last_attempt_at": (row or {}).get("last_attempt_at"),
            "last_success_at": (row or {}).get("last_success_at"),
            "last_error": (row or {}).get("last_error"),
            "record_count_last": (row or {}).get("record_count_last", 0),
        })
    return jsonify({
        "mode": mode,
        "database_reachable": db_ok,
        "sources": merged,
        "last_refresh_seconds_ago": get_last_refresh_seconds_ago(),
        "note": "Sources fall back to clearly-labeled synthetic data when unavailable.",
    })


@api_bp.post("/refresh")
def refresh():
    """Trigger a manual ingestion run (rate-limited; optional shared token).

    Set REFRESH_TOKEN in .env to require header X-Refresh-Token: <token>.
    Left unset (local dev/demo), the endpoint is still rate-limited by
    INGEST_COOLDOWN_SECONDS and a Postgres advisory lock.
    """
    provided_token = request.headers.get("X-Refresh-Token", "")
    expected = (get_settings().refresh_token or "").strip()
    if expected and provided_token != expected:
        return jsonify({"error": "unauthorized: missing/invalid X-Refresh-Token"}), 401

    from backend.ingest import run_ingestion

    city_raw = (request.get_json(silent=True) or {}).get("city") or request.args.get("city")
    if city_raw:
        city_ids = [city_raw]
    else:
        city_ids = [c["id"] for c in get_demo_cities()]

    result = run_ingestion(city_ids=city_ids, respect_cooldown=True)
    status = 429 if result.get("skipped") and "cooldown" in str(result.get("reason", "")) else 200
    return jsonify(result), status


# -------------------------------------------------- Phase 3 endpoints

@api_bp.get("/analytics/anomalies")
def analytics_anomalies():
    """Detected anomalies with evidence; detection is explainable only."""
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)

    from backend.analytics import get_recent_anomalies, run_anomaly_detection

    if request.args.get("detect") == "1":
        report = run_anomaly_detection(city, window_hours)
        return jsonify({"mode": "database", **report})
    return jsonify({
        "mode": "database",
        "city": city_raw,
        "window_hours": window_hours,
        "anomalies": get_recent_anomalies(city, limit=20),
        "note": "Statistical flags only — not explanations or causal claims.",
    })


@api_bp.get("/analytics/correlations")
def analytics_correlations():
    """Possible associations between metrics (never causal claims)."""
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)

    from backend.correlations import run_correlation_analysis

    report = run_correlation_analysis(city, window_hours)
    return jsonify({"mode": "database", **report})


@api_bp.get("/ai/summary")
def ai_summary():
    """Grounded plain-language summary (AI when configured, deterministic fallback)."""
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)

    from backend.ai_summary import generate_summary

    report = generate_summary(city, window_hours)
    return jsonify({"mode": "database", **report})


@api_bp.post("/ai/ask")
def ai_ask():
    """Grounded civic companion: answers only from stored evidence.

    POST body: {"city": "bengaluru", "question": "...", "window_hours": 72}
    The question is treated as untrusted data; the answer cites evidence or
    explicitly says the data does not cover it.
    """
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    if len(question) > 500:
        return jsonify({"error": "question too long (max 500 chars)"}), 400
    city_raw = str(payload.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)

    from backend.companion import answer_question

    report = answer_question(city, question, window_hours)
    return jsonify({"mode": "database", **report})


# =====================================================================
# Phase 4 — alert center, historical replay, location comparison
# =====================================================================

_ALERT_SYNC_INTERVAL = 60  # seconds between evidence re-syncs per city
_alert_sync_last: dict[str, float] = {}


def _should_sync_alerts(city: str) -> bool:
    """Time-based throttle so polling cannot hammer the sync path."""
    import time

    now = time.monotonic()
    last = _alert_sync_last.get(city, 0.0)
    if now - last < _ALERT_SYNC_INTERVAL:
        return False
    _alert_sync_last[city] = now
    return True


def _alerts_mode() -> str:
    # Honest provenance: reflect what the alerts module actually used for its
    # most recent storage operation, not just whether Postgres answers reads.
    from backend import alerts as alerts_module

    return getattr(alerts_module, "last_storage_mode", "database")


@api_bp.get("/alerts")
def alerts_list():
    """Explainable, deduplicated alerts (informational, never official warnings)."""
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    status = (request.args.get("status") or "active").strip()
    if status not in ("active", "acknowledged", "dismissed", "all"):
        status = "active"
    limit = _int_arg("limit", 50, 1, 100)

    from backend import alerts as alerts_module

    # Sync-from-evidence is cheap and idempotent (dedup keys prevent repeats)
    # but touches anomaly_events + alert_instances on every call, so it is
    # throttled per city: the 60 s dashboard poll triggers at most one sync
    # per interval instead of one per concurrent panel request.
    if _should_sync_alerts(city) and _data_mode()[1]:
        try:
            alerts_module.sync_alerts(city, window_hours=24)
        except Exception:  # noqa: BLE001 — listing must survive sync problems
            pass
    report = alerts_module.list_alerts(city, status=status, limit=limit)
    return jsonify({"mode": _alerts_mode(), **report})


@api_bp.post("/alerts/<path:dedup_key>/acknowledge")
def alert_acknowledge(dedup_key: str):
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    from backend import alerts as alerts_module
    row = alerts_module.acknowledge_alert(city, dedup_key)
    if row is None:
        return jsonify({"error": "alert not found"}), 404
    return jsonify({"mode": _alerts_mode(), "alert": row})


@api_bp.post("/alerts/<path:dedup_key>/dismiss")
def alert_dismiss(dedup_key: str):
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    from backend import alerts as alerts_module
    row = alerts_module.dismiss_alert(city, dedup_key)
    if row is None:
        return jsonify({"error": "alert not found"}), 404
    return jsonify({"mode": _alerts_mode(), "alert": row})


@api_bp.get("/alerts/rules")
def alert_rules():
    """Configured threshold rules (read-only view; seeded from env/db)."""
    from backend import alerts as alerts_module
    return jsonify({"mode": _alerts_mode(), "rules": alerts_module.list_rules()})


@api_bp.get("/analytics/health")
def health_score_view():
    """Explainable city health score + per-metric contributions (graph dashboard)."""
    from backend.health_score import compute_health_score

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    hours = _int_arg("hours", 24, 6, 24 * 30)
    return jsonify(compute_health_score(city, hours=hours))


@api_bp.get("/analytics/health/trend")
def health_trend_view():
    """Daily health scores for the trend chart (stored data only)."""
    from backend.health_score import get_health_trend

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    days = _int_arg("days", 7, 1, 30)
    return jsonify(get_health_trend(city, days=days))


@api_bp.get("/analytics/severity-series")
def severity_series_view():
    """Per-bucket severity counts (stacked area/bar) — single grouped query."""
    from backend.database import fetch_severity_time_series

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    hours = _int_arg("hours", 72, 6, 24 * 30)
    bucket_size = (request.args.get("bucket") or "hour").strip()
    if bucket_size not in ("hour", "day"):
        bucket_size = "hour"  # normalize; never echo arbitrary input
    ok, rows = fetch_severity_time_series(city, hours=hours, bucket_size=bucket_size)
    if not ok:
        return jsonify({"mode": "demo", "city": city, "hours": hours, "bucket": bucket_size,
                        "series": [], "error": rows}), 503
    return jsonify({"mode": "database", "city": city, "hours": hours, "bucket": bucket_size,
                    "series": rows})


@api_bp.get("/history")
def history_view():
    """Historical replay: hourly per-metric averages from stored records only.

    Never fabricates coverage: hours without observations are absent, and the
    response states the actual coverage window per metric.
    """
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    hours = _int_arg("hours", 168, 6, 24 * 30)
    metrics_raw = (request.args.get("metrics") or "").strip()
    metrics = [m.strip() for m in metrics_raw.split(",") if m.strip()][:6] or None

    from backend.database import fetch_history_buckets

    ok, buckets = fetch_history_buckets(city, hours=hours, metrics=metrics)
    if not ok:
        if _data_mode()[1]:
            return jsonify({"error": "history query failed"}), 503
        buckets = []  # demo fallback handled below

    # Coverage summary so the UI can disclose gaps honestly.
    coverage: dict[str, dict] = {}
    for row in buckets or []:
        entry = coverage.setdefault(
            row["metric"], {"points": 0, "first_bucket": row["bucket"], "last_bucket": row["bucket"]}
        )
        entry["points"] += 1
        entry["last_bucket"] = row["bucket"]

    return jsonify({
        "mode": "database" if ok else "demo",
        "city": city_raw,
        "hours": hours,
        "buckets": buckets or [],
        "coverage": {
            metric: {
                **info,
                "note": f"{info['points']} hourly points; gaps mean no observations existed",
            }
            for metric, info in coverage.items()
        },
        "note": "Historical view reads stored records only; nothing is interpolated or back-filled.",
    })


@api_bp.get("/analytics/locations")
def analytics_locations():
    """Location comparison over a matching window, with coverage disclosure."""
    city_raw = (request.args.get("city") or "bengaluru").strip()
    city = _city_display_name(city_raw)
    hours = _int_arg("hours", 24, 6, 24 * 14)
    metrics_raw = (request.args.get("metrics") or "").strip()
    metrics = [m.strip() for m in metrics_raw.split(",") if m.strip()][:6] or None

    from backend.database import fetch_location_comparison

    ok, rows = fetch_location_comparison(city, hours=hours, metrics=metrics)
    if not ok:
        if _data_mode()[1]:
            return jsonify({"error": "comparison query failed"}), 503
        rows = []

    # Group per location with coverage disclosure; ordering is alphabetical —
    # no ranking is implied by presentation order.
    locations: dict[str, dict] = {}
    for row in rows or []:
        entry = locations.setdefault(row["location_name"], {
            "location": row["location_name"],
            "metrics": {},
            "observations": 0,
            "hours_covered": 0,
            "includes_synthetic": False,
        })
        entry["metrics"][row["metric"]] = {
            "avg_value": row["avg_value"],
            "observations": row["observations"],
        }
        entry["observations"] += row["observations"]
        entry["hours_covered"] = max(entry["hours_covered"], row["hours_covered"])
        entry["includes_synthetic"] = entry["includes_synthetic"] or bool(row.get("has_synthetic"))

    return jsonify({
        "mode": "database" if ok else "demo",
        "city": city_raw,
        "hours": hours,
        "locations": sorted(locations.values(), key=lambda e: e["location"]),
        "note": (
            "Comparisons describe available observations only. Locations differ in "
            "sensor coverage and sample size; differences may reflect coverage, not "
            "conditions. No ranking is implied."
        ),
    })


# Error handlers live at app level in app_factory.py.


# =====================================================================
# Phase 3 — civic event lifecycle, real-time stream, simulation
#
# The REST endpoints below stay the primary interface (they work with or
# without the stream); /api/events/stream is an additive push channel so the
# dashboard reflects operator actions and drills immediately.
# =====================================================================

def _event_error(exc: Exception):
    """Map a domain error onto a consistent JSON error response."""
    code = getattr(exc, "code", "invalid_event")
    status = int(getattr(exc, "status", 400))
    return jsonify({"error": str(exc), "code": code}), status


def _csv_arg(name: str, allowed: tuple[str, ...]) -> tuple[str, ...] | None:
    """Parse a comma-separated query parameter, keeping only allowed values."""
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    values = tuple(v.strip().lower() for v in raw.split(",") if v.strip())
    kept = tuple(v for v in values if v in allowed)
    return kept or None


def _bool_arg(name: str, default: bool) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@api_bp.get("/events")
def events_list():
    """List civic events (filters: city, status, severity, source_type, window)."""
    from backend.events import EVENT_SEVERITIES, EVENT_STATUSES, EventError, list_events

    try:
        payload = list_events(
            city=(request.args.get("city") or "").strip() or None,
            statuses=_csv_arg("status", EVENT_STATUSES),
            severities=_csv_arg("severity", EVENT_SEVERITIES),
            source_type=(request.args.get("source_type") or "").strip() or None,
            include_simulated=_bool_arg("include_simulated", True),
            limit=_int_arg("limit", 100, 1, 500),
            offset=_int_arg("offset", 0, 0, 10_000),
        )
    except EventError as exc:
        return _event_error(exc)
    return jsonify(payload)


@api_bp.post("/events")
def events_create():
    """Create a civic event (operator report or ingested incident)."""
    from backend.events import EventError, create_event, storage_mode

    body = request.get_json(silent=True) or {}
    try:
        event = create_event(
            body,
            actor=(request.headers.get("X-Actor") or body.get("actor") or "operator"),
            external_key=body.get("external_key"),
        )
    except EventError as exc:
        return _event_error(exc)
    mode = storage_mode()
    return jsonify({
        "mode": mode,
        "persisted": mode == "database",
        "event": event,
    }), 201 if event.get("created") else 200


@api_bp.get("/events/<event_ref>")
def events_detail(event_ref: str):
    """One event plus its full lifecycle audit trail."""
    from backend.events import get_event

    payload = get_event(event_ref)
    if payload is None:
        return jsonify({"error": "event not found", "code": "not_found"}), 404
    return jsonify(payload)


@api_bp.patch("/events/<event_ref>")
def events_update(event_ref: str):
    """Update descriptive fields (status changes go through /transition)."""
    from backend.events import EventError, storage_mode, update_event

    body = request.get_json(silent=True) or {}
    try:
        event = update_event(
            event_ref,
            body,
            actor=(request.headers.get("X-Actor") or body.get("actor") or "operator"),
            expected_revision=body.get("expected_revision"),
        )
    except EventError as exc:
        return _event_error(exc)
    mode = storage_mode()
    return jsonify({"mode": mode, "persisted": mode == "database", "event": event})


def _apply_transition(event_ref: str, action: str, body: dict):
    """Shared handler body for the transition + shortcut endpoints."""
    from backend.events import EventError, storage_mode, transition_event

    try:
        event = transition_event(
            event_ref,
            action,
            actor=(request.headers.get("X-Actor") or body.get("actor") or "operator"),
            note=body.get("note") or body.get("resolution_note"),
        )
    except EventError as exc:
        return _event_error(exc)
    mode = storage_mode()
    return jsonify({"mode": mode, "persisted": mode == "database", "event": event})


@api_bp.post("/events/<event_ref>/transition")
def events_transition(event_ref: str):
    """Apply a lifecycle action: acknowledge | start | resolve | close | reopen."""
    body = request.get_json(silent=True) or {}
    return _apply_transition(event_ref, str(body.get("action") or ""), body)


@api_bp.post("/events/<event_ref>/acknowledge")
def events_acknowledge(event_ref: str):
    """Convenience shortcut: acknowledge an open event."""
    return _apply_transition(event_ref, "acknowledge", request.get_json(silent=True) or {})


@api_bp.post("/events/<event_ref>/resolve")
def events_resolve(event_ref: str):
    """Convenience shortcut: resolve an active event (optional note)."""
    return _apply_transition(event_ref, "resolve", request.get_json(silent=True) or {})


@api_bp.post("/events/<event_ref>/close")
def events_close(event_ref: str):
    """Convenience shortcut: close an event (terminal state)."""
    return _apply_transition(event_ref, "close", request.get_json(silent=True) or {})



# --------------------------------------------------- real-time (SSE)

@api_bp.get("/events/stream")
def events_stream():
    """Server-Sent Events stream of civic-event changes.

    Chosen over WebSockets/Flask-SocketIO because it needs no async worker and
    no new dependency, streams through the Vite dev proxy unchanged, and the
    REST endpoints above remain the primary interface. A client that cannot use
    SSE falls back to GET /api/events/poll (same notification ids, so the two
    transports can be used together without duplicated alerts).
    """
    from backend.events import list_events

    settings_obj = get_settings()
    if not settings_obj.realtime_enabled:
        return jsonify({
            "error": "real-time stream disabled (REALTIME_ENABLED=0)",
            "fallback": "/api/events/poll",
        }), 503

    from backend.realtime import format_sse, get_bus, stream

    city = (request.args.get("city") or "").strip() or None
    include_simulated = _bool_arg("include_simulated", True)
    snapshot = list_events(city=city, include_simulated=include_simulated, limit=200)

    subscriber_id, channel = get_bus().subscribe()
    heartbeat = max(2, int(settings_obj.sse_heartbeat_seconds or 20))
    max_seconds = max(30, int(settings_obj.sse_max_stream_seconds or 1800))

    def generate():
        # First frame carries a full snapshot so a (re)connecting client is
        # consistent immediately instead of waiting for the next change.
        yield format_sse({
            "type": "stream.ready",
            "transport": "sse",
            "mode": snapshot["mode"],
            "persisted": snapshot["persisted"],
            "version": snapshot["version"],
            "city": city,
            "count": snapshot["count"],
            "events": snapshot["events"],
        }, event="stream.ready")
        yield from stream(subscriber_id, channel,
                          heartbeat_seconds=heartbeat, max_seconds=max_seconds)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"   # disable proxy buffering
    response.headers["Connection"] = "keep-alive"
    return response


@api_bp.get("/events/poll")
def events_poll():
    """Polling fallback for the stream: notifications after ``since``.

    Returns the same envelopes (with the same ``notification_id`` values) that
    the SSE stream emits, plus a fresh event list whenever the data version
    changed, so the client never has to guess whether it is up to date.
    """
    from backend.events import list_events

    since = _int_arg("since", 0, 0, 2**31 - 1)
    city = (request.args.get("city") or "").strip() or None
    include_simulated = _bool_arg("include_simulated", True)

    from backend.realtime import get_bus

    bus = get_bus()
    notifications = bus.since(since)
    payload = list_events(city=city, include_simulated=include_simulated, limit=200)
    resync = _bool_arg("resync", True)
    return jsonify({
        "mode": payload["mode"],
        "persisted": payload["persisted"],
        "transport": "poll",
        "notifications": notifications,
        "last_notification_id": bus.last_notification_id,
        "version": payload["version"],
        "resynced": resync,
        "events": payload["events"] if resync else [],
        "count": payload["count"] if resync else 0,
    })


@api_bp.get("/realtime/status")
def realtime_status():
    """Real-time transport diagnostics (no secrets, no event payloads)."""
    from backend.realtime import get_bus

    settings_obj = get_settings()
    return jsonify({
        "enabled": settings_obj.realtime_enabled,
        "transport": "sse",
        "stream_path": "/api/events/stream",
        "poll_path": "/api/events/poll",
        "heartbeat_seconds": settings_obj.sse_heartbeat_seconds,
        **get_bus().stats(),
    })





# ------------------------------------------------------- simulation drills

def _bool_body(body: dict, key: str, default: bool) -> bool:
    if key not in body:
        return default
    return bool(body[key])


@api_bp.get("/simulation/scenarios")
def simulation_scenarios():
    """Scenario catalogue for the dashboard's drill controls."""
    from backend.simulation import list_scenarios_public

    s = get_settings()
    return jsonify({
        "enabled": s.simulation_enabled,
        "scenarios": list_scenarios_public(),
        "note": "Drills are clearly labelled synthetic; they never overwrite live observations.",
    })


@api_bp.post("/simulation/run")
def simulation_run():
    """Start a scenario drill: labeled observation + civic event + audit trail."""
    from backend.events import EventError
    from backend.simulation import run_scenario

    s = get_settings()
    if not s.simulation_enabled:
        return jsonify({
            "error": "simulation disabled (set SIMULATION_ENABLED=1 to enable)",
            "code": "simulation_disabled",
        }), 503

    body = request.get_json(silent=True) or {}
    scenario_id = str(body.get("scenario_id") or body.get("scenario") or "").strip()
    city_raw = str(body.get("city") or body.get("city_id") or "").strip() or "bengaluru"
    if not scenario_id:
        return jsonify({
            "error": "scenario_id is required",
            "code": "validation_error",
        }), 400

    try:
        payload = run_scenario(
            scenario_id,
            city_raw,
            actor=(request.headers.get("X-Actor") or body.get("actor") or "operator"),
            write_observation=_bool_body(body, "write_observation", True),
            note=body.get("note"),
        )
    except EventError as exc:
        return _event_error(exc)
    return jsonify(payload), 201


@api_bp.get("/simulation/runs")
def simulation_runs():
    """Recent simulation runs with their current event status."""
    from backend.simulation import list_runs

    return jsonify(list_runs(limit=_int_arg("limit", 20, 1, 100)))


@api_bp.get("/simulation/runs/<run_ref>")
def simulation_run_detail(run_ref: str):
    """One simulation run plus the events it produced."""
    from backend.simulation import run_detail

    payload = run_detail(run_ref)
    if payload is None:
        return jsonify({"error": "simulation run not found", "code": "not_found"}), 404
    return jsonify(payload)


@api_bp.post("/simulation/runs/<run_ref>/advance")
def simulation_advance(run_ref: str):
    """Walk a drill's incident through the lifecycle (acknowledge/resolve/close)."""
    from backend.events import EventError
    from backend.simulation import advance_run

    body = request.get_json(silent=True) or {}
    action = str(body.get("action") or "acknowledge").strip().lower()
    try:
        payload = advance_run(
            run_ref,
            action,
            actor=(request.headers.get("X-Actor") or body.get("actor") or "operator"),
            note=body.get("note"),
        )
    except EventError as exc:
        return _event_error(exc)
    return jsonify(payload)


@api_bp.post("/simulation/runs/<run_ref>/reset")
def simulation_reset(run_ref: str):
    """End a drill: close its simulated events (never delete them)."""
    from backend.events import EventError
    from backend.simulation import reset_run

    body = request.get_json(silent=True) or {}
    try:
        payload = reset_run(
            run_ref,
            actor=(request.headers.get("X-Actor") or body.get("actor") or "operator"),
        )
    except EventError as exc:
        return _event_error(exc)
    return jsonify(payload)


# =====================================================================
# Phase 9 — urban intelligence: impact engine, cross-domain graph,
# resilience, digital twin, scenario lab, operations copilot.
#
# Conventions match the existing file: bounded int args, canonical city
# resolution, allowlisted enums, 400 on bad input, 503 on DB failure.
# =====================================================================

@api_bp.get("/analytics/impact")
def analytics_impact():
    """Anomaly → impact → advisory interventions (with simulated compare)."""
    from backend.impact import build_impact_brief

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)
    metric = (request.args.get("metric") or "").strip() or None
    return jsonify(build_impact_brief(city, metric=metric, window_hours=window_hours))


@api_bp.get("/analytics/cross-domain")
def analytics_cross_domain():
    """Association graph: co-occurrence, correlation, co-location + evidence."""
    from backend.cross_domain import build_cross_domain_graph

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)
    report = build_cross_domain_graph(city, window_hours=window_hours)
    return jsonify({"mode": "database", **report})


@api_bp.get("/analytics/resilience")
def analytics_resilience():
    """Explainable resilience indicator (components + weights + formulas)."""
    from backend.resilience import compute_resilience

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    hours = _int_arg("hours", 168, 24, 720)
    return jsonify(compute_resilience(city, hours=hours))


@api_bp.get("/analytics/resilience/trend")
def analytics_resilience_trend():
    """Daily resilience proxy: health trend + anomaly counts per day."""
    from backend.resilience import get_resilience_trend

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    days = _int_arg("days", 14, 1, 30)
    return jsonify(get_resilience_trend(city, days=days))


@api_bp.get("/twin")
def twin_view():
    """Zone-level urban digital twin state (map layers + per-zone detail)."""
    from backend.twin import build_twin

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    hours = _int_arg("hours", 24, 6, 168)
    report = build_twin(city, hours=hours)
    status = 503 if report.get("status") == "unavailable" else 200
    return jsonify(report), status


@api_bp.get("/twin/impact")
def twin_impact():
    """Impact brief for one zone's nearest flagged anomaly (from the twin)."""
    from backend.impact import build_impact_brief

    city = _city_display_name((request.args.get("city") or "bengaluru").strip())
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)
    metric = (request.args.get("metric") or "").strip() or None
    brief = build_impact_brief(city, metric=metric, window_hours=window_hours)
    return jsonify(brief)


@api_bp.get("/scenario-lab/models")
def scenario_models():
    """Scenario Lab catalog: models, documented params and ranges."""
    from backend.scenario_lab import list_models

    return jsonify({"models": list_models(),
                    "note": "All models are transparent, labeled simulations over real baselines."})


@api_bp.post("/scenario-lab/run")
def scenario_run():
    """Run a scenario model; 400 on unknown model / invalid parameters."""
    from backend.scenario_lab import ScenarioParamError, run_model

    body = request.get_json(silent=True) or {}
    city = _city_display_name(str(body.get("city") or "bengaluru").strip())
    model_id = str(body.get("model") or "").strip()
    if not model_id:
        return jsonify({"error": "model is required"}), 400
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    try:
        result = run_model(city, model_id, params)
    except ScenarioParamError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"mode": "database", **result})


@api_bp.post("/copilot/ask")
def copilot_ask():
    """Operations Copilot: validated read-only tools + grounded answer."""
    from backend.copilot import answer as copilot_answer

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    if len(question) > 500:
        return jsonify({"error": "question too long (max 500 chars)"}), 400
    city = _city_display_name(str(payload.get("city") or "bengaluru").strip())
    window_hours = _int_arg("window_hours", 72, 12, 24 * 14)
    return jsonify(copilot_answer(city, question, window_hours))
