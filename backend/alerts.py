"""CityPulse alert center (Phase 4): explainable, deduplicated alerts.

Principles (matching the rest of CityPulse):
- Alerts are ALWAYS derived from verified evidence already stored by the
  analytics engine (anomaly_events) or from an explicitly configured
  threshold rule evaluated against stored observations. Nothing is invented.
- Deduplication is enforced at the database level via UNIQUE (dedup_key);
  anomaly-derived alerts use the anomaly's natural key, rule alerts use a
  per-city/rule/hour-bucket key. Re-running the sync can never create a
  second alert for the same event.
- Alerts are informational civic observations — clearly labeled as such —
  never official emergency warnings, and never a claim of danger.
- Thresholds are configurable via the alert_rules table (optionally seeded
  from ALERT_RULES_JSON env for convenience) and readable via the API.
- Storage degrades safely: when PostgreSQL is unreachable the module keeps
  an in-process demo store so the alert center remains demonstrable.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
from datetime import datetime, timedelta, timezone

from backend import database as db
from backend.demo_data import resolve_city

logger = logging.getLogger("citypulse.alerts")

ACTIVE_ALERT_LIMIT = 50          # bounded payloads
DISMISS_IS_FINAL = True          # dismissed alerts stay dismissed

# --------------------------------------------------------------- demo store
# In-process fallback so the alert center works without PostgreSQL (tests,
# offline demos). Keys mirror the DB schema; labeled synthetic.
_demo_alerts: list[dict] = []
_demo_rules: list[dict] = []


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _demo_store(city: str) -> list[dict]:
    global _demo_alerts
    if _demo_alerts:
        return _demo_alerts
    now = _utc_now()
    _demo_alerts = [
        {
            "dedup_key": "demo:pm25_ugm3",
            "city": city or "Bengaluru",
            "source_type": "air_quality",
            "metric": "pm25_ugm3",
            "severity": "moderate",
            "title": "PM2.5 above configured threshold",
            "summary": "Latest PM2.5 117.7 µg/m³ exceeded the configured threshold of 100 µg/m³ "
                       "(synthetic demo observation; informational only).",
            "evidence": {
                "kind": "threshold_rule",
                "metric": "pm25_ugm3",
                "threshold": 100.0,
                "window_hours": 24,
                "observations_considered": 12,
            },
            "observed_value": 117.7,
            "baseline_value": None,
            "location_name": f"{city or 'Bengaluru'} (city-wide)",
            "detected_at": (now - timedelta(minutes=8)).isoformat(),
            "is_synthetic": True,
            "acknowledged_at": None,
            "dismissed_at": None,
        },
        {
            "dedup_key": "demo:precipitation_mm",
            "city": city or "Bengaluru",
            "source_type": "weather",
            "metric": "precipitation_mm",
            "severity": "low",
            "title": "Rainfall spike vs recent baseline",
            "summary": "Hourly precipitation 4.1 mm vs rolling baseline 0.6 mm — unusual vs "
                       "recent history, not explained (synthetic demo data).",
            "evidence": {
                "kind": "anomaly",
                "method": "rolling_median_mad",
                "deviation_score": 4.2,
                "window_hours": 24,
                "sample_size": 18,
            },
            "observed_value": 4.1,
            "baseline_value": 0.6,
            "location_name": f"{city or 'Bengaluru'} (city-wide)",
            "detected_at": (now - timedelta(minutes=25)).isoformat(),
            "is_synthetic": True,
            "acknowledged_at": None,
            "dismissed_at": None,
        },
    ]
    return _demo_alerts


def _demo_rules(city: str) -> list[dict]:
    global _demo_rules
    if _demo_rules:
        return _demo_rules
    _demo_rules = [
        {"id": 1, "city": None, "metric": "pm25_ugm3", "operator": ">",
         "threshold_value": 100.0, "window_hours": 24, "enabled": True, "label": "PM2.5 > 100"},
        {"id": 2, "city": None, "metric": "delay_min", "operator": ">",
         "threshold_value": 15.0, "window_hours": 24, "enabled": True, "label": "Transit delay > 15 min"},
    ]
    return _demo_rules


# --------------------------------------------------------------- rule seeding
def _rules_from_env() -> list[dict]:
    """Optional ALERT_RULES_JSON env seed, e.g.
    [{"metric":"pm25_ugm3","operator":">","threshold_value":100}]"""
    raw = (os.getenv("ALERT_RULES_JSON") or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        return [r for r in parsed if isinstance(r, dict)]
    except json.JSONDecodeError:
        logger.warning("ALERT_RULES_JSON is not valid JSON; ignoring")
        return []


def _coerce_rule(rule: dict) -> dict | None:
    metric = (rule.get("metric") or "").strip()
    operator = (rule.get("operator") or ">").strip()
    threshold = rule.get("threshold_value")
    if not metric or operator not in (">", "<", ">=") or threshold is None:
        return None
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return None
    return {
        "city": (rule.get("city") or "").strip() or None,
        "metric": metric,
        "operator": operator,
        "threshold_value": threshold,
        "window_hours": int(rule.get("window_hours") or 24),
        "enabled": bool(rule.get("enabled", True)),
        "label": (rule.get("label") or "").strip() or None,
    }


def sync_alerts(city: str, window_hours: int = 24) -> dict:
    """Rebuild open alerts from stored evidence (idempotent, deduplicated).

    Sources, in priority order:
      1. anomaly_events rows in the window (each becomes one alert, keyed by
         the anomaly's natural key so re-runs cannot duplicate).
      2. enabled alert_rules evaluated against the latest stored observations.
    Returns a report; never raises on storage failure (logs and continues).
    """
    city_display = _city_display(city)
    now = _utc_now()
    created = 0
    updated = 0

    ok, rows = db.fetch_recent_anomalies(city_display, limit=ACTIVE_ALERT_LIMIT)
    if ok:
        for row in rows:
            bucket = row.get("observed_bucket")
            key = f"anomaly:{row.get('city')}:{row.get('metric')}:{bucket}"
            payload = {
                "dedup_key": key,
                "city": row.get("city") or city_display,
                "source_type": row.get("source_type"),
                "metric": row.get("metric"),
                "severity": _severity_from_score(row.get("deviation_score")),
                "title": f"{_metric_label(row.get('metric'))} unusual vs recent baseline",
                "summary": _anomaly_summary(row),
                "evidence": {
                    "kind": "anomaly",
                    "method": row.get("method"),
                    "deviation_score": row.get("deviation_score"),
                    "window_hours": row.get("window_hours"),
                    "sample_size": row.get("sample_size"),
                    "confidence": row.get("confidence"),
                    "limitations": row.get("limitations") or (
                        "Statistical flag derived from anomaly_events; it does not "
                        "explain a cause and is not an official warning."
                    ),
                },
                "observed_value": row.get("observed_value"),
                "baseline_value": row.get("baseline_value"),
                "location_name": f"{row.get('city') or city_display} (city-wide)",
                "detected_at": _iso(bucket) or now.isoformat(),
                # anomaly_events does not record provenance; the dashboard's
                # global live/simulated labeling still applies to the metric.
                "is_synthetic": False,
            }
            changed = _upsert_alert(payload)
            created += 1 if changed == "created" else 0
            updated += 1 if changed == "updated" else 0

    rules = _load_rules()
    for rule in rules:
        if rule.get("enabled") is False:
            continue
        rule_city = rule.get("city")
        if rule_city and rule_city.lower() not in (city_display.lower(), city.lower()):
            continue
        hits = _evaluate_rule(rule, city_display, window_hours)
        if not hits:
            continue
        for hit in hits[:5]:  # bound rule-derived alerts per sync
            hour_bucket = hit["recorded_at"].replace(minute=0, second=0, microsecond=0)
            key = f"rule:{rule['metric']}:{rule['operator']}{rule['threshold_value']:g}:{hour_bucket.isoformat()}"
            payload = {
                "dedup_key": key,
                "city": city_display,
                "source_type": hit.get("source_type"),
                "metric": rule["metric"],
                "severity": _severity_from_rule(rule, hit["value"]),
                "title": f"{_metric_label(rule['metric'])} crossed configured threshold",
                "summary": _rule_summary(rule, hit),
                "evidence": {
                    "kind": "threshold_rule",
                    "rule_id": rule.get("id"),
                    "label": rule.get("label"),
                    "threshold": rule["threshold_value"],
                    "operator": rule["operator"],
                    "window_hours": rule.get("window_hours") or window_hours,
                    "observations_considered": hit.get("observations_considered"),
                    "limitations": "Informational threshold crossing on city-wide "
                                   "observations; not an official emergency warning.",
                },
                "observed_value": hit["value"],
                "baseline_value": None,
                "location_name": hit.get("location_name") or f"{city_display} (city-wide)",
                "detected_at": _iso(hit["recorded_at"]) or now.isoformat(),
                "is_synthetic": bool(hit.get("is_synthetic")),
            }
            changed = _upsert_alert(payload)
            created += 1 if changed == "created" else 0
            updated += 1 if changed == "updated" else 0

    return {
        "city": city_display,
        "created": created,
        "updated": updated,
        "synced_at": now.isoformat(),
    }


_city_display = resolve_city  # canonical resolver from demo_data (no duplicate mapper)


def _load_rules() -> list[dict]:
    ok, rows = db.fetch_alert_rules()
    if ok:
        seeded = False
        for raw in _rules_from_env():
            rule = _coerce_rule(raw)
            if not rule:
                continue
            changed = db.upsert_alert_rule(rule)
            seeded = seeded or changed
        return rows
    # demo fallback rules
    return _demo_rules("")


# --------------------------------------------------------------- rule evaluation
def _evaluate_rule(rule: dict, city_display: str, window_hours: int) -> list[dict]:
    """Evaluate one rule against stored observations; returns matching rows."""
    metric = rule["metric"]
    ok, series = db.fetch_metric_series(
        city=city_display,
        metric=metric,
        hours=min(rule.get("window_hours") or window_hours, 24 * 7),
    )
    if not ok or not series:
        return []
    # Consider only recent observations (last bucket per location to avoid
    # alerting repeatedly on the same stale reading).
    latest_by_location: dict[str, dict] = {}
    for row in series:
        loc = row.get("location_name") or "city-wide"
        latest_by_location[loc] = row
    hits: list[dict] = []
    observations_considered = len(series)
    for row in latest_by_location.values():
        value = row.get("value")
        if value is None:
            continue  # never treat missing as zero
        threshold = rule["threshold_value"]
        crossed = (
            (rule["operator"] == ">" and value > threshold)
            or (rule["operator"] == "<" and value < threshold)
            or (rule["operator"] == ">=" and value >= threshold)
        )
        if crossed:
            row = dict(row)
            row["observations_considered"] = observations_considered
            hits.append(row)
    return hits


def _severity_from_score(score: float | None) -> str:
    if score is None:
        return "low"
    if score >= 8:
        return "critical"
    if score >= 6:
        return "high"
    if score >= 4:
        return "moderate"
    return "low"


def _severity_from_rule(rule: dict, value: float) -> str:
    if rule["operator"] in (">", ">="):
        ratio = value / rule["threshold_value"] if rule["threshold_value"] else 1.0
        if ratio >= 2:
            return "high"
        if ratio >= 1.5:
            return "moderate"
        return "low"
    return "low"


def _anomaly_summary(row: dict) -> str:
    metric_label = _metric_label(row.get("metric"))
    observed = row.get("observed_value")
    baseline = row.get("baseline_value")
    score = row.get("deviation_score")
    fmt = lambda v: "n/a" if v is None else f"{v:g}"  # noqa: E731
    return (
        f"{metric_label} read {fmt(observed)} vs a rolling baseline of {fmt(baseline)} "
        f"({row.get('method') or 'robust z-score'}; score {fmt(score)} over a "
        f"{row.get('window_hours') or '?'}h window, n={row.get('sample_size') or '?'}). "
        "Unusual vs recent history — not an explanation, and not an official warning."
    )


def _rule_summary(rule: dict, hit: dict) -> str:
    fmt = lambda v: f"{v:g}"  # noqa: E731
    synthetic = " (synthetic demo observation)" if hit.get("is_synthetic") else ""
    return (
        f"Latest {fmt(hit['value'])} {rule['operator']} threshold {fmt(rule['threshold_value'])}"
        f"{synthetic} — informational threshold crossing from configured rule "
        f"'{rule.get('label') or rule['metric']}', not an official emergency warning."
    )


def _metric_label(metric: str | None) -> str:
    if not metric:
        return "Metric"
    label = metric.replace("_", " ")
    return label[0].upper() + label[1:]


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# --------------------------------------------------------------- storage
# Provenance of the most recent alert storage operation ("database" or
# "demo-fallback"). Routes surface this so the UI can never label a
# demo-store write as live database data.
last_storage_mode: str = "database"


def _upsert_alert(payload: dict) -> str:
    global last_storage_mode
    # db.upsert_alert_instance returns (ok, created_flag): True => fresh INSERT.
    ok, created = db.upsert_alert_instance(payload)
    if ok:
        last_storage_mode = "database"
        return "created" if created else "updated"
    last_storage_mode = "demo-fallback"
    _upsert_demo(payload)
    return "created"


def _upsert_demo(payload: dict) -> None:
    store = _demo_store(payload.get("city") or "")
    for existing in store:
        if existing["dedup_key"] == payload["dedup_key"]:
            keep_ack = existing.get("acknowledged_at")
            keep_dismiss = existing.get("dismissed_at")
            existing.update(payload)
            existing["acknowledged_at"] = keep_ack or existing.get("acknowledged_at")
            existing["dismissed_at"] = keep_dismiss or existing.get("dismissed_at")
            return
    store.append(payload)


def list_alerts(
    city: str,
    status: str = "active",
    limit: int = 50,
) -> dict:
    """List alerts (active / acknowledged / dismissed / all) for a city."""
    global last_storage_mode
    city_display = _city_display(city)
    ok, rows = db.fetch_alert_instances(city_display, status=status, limit=max(1, min(limit, 100)))
    if ok:
        last_storage_mode = "database"
        return {"city": city_display, "status": status, "alerts": rows}
    last_storage_mode = "demo-fallback"
    store = _demo_store(city_display)
    now = _utc_now()
    out = []
    for a in store:
        if a.get("city") != city_display:
            continue
        if status == "active" and (a.get("dismissed_at") or a.get("acknowledged_at")):
            continue
        if status == "acknowledged" and not a.get("acknowledged_at"):
            continue
        if status == "dismissed" and not a.get("dismissed_at"):
            continue
        age = (now - datetime.fromisoformat(a["detected_at"])).total_seconds()
        if status == "active" and age > 7 * 86400:
            continue  # stale demo alerts fade away
        out.append(a)
    return {"city": city_display, "status": status, "alerts": out[:limit]}


def acknowledge_alert(city: str, dedup_key: str, by: str = "dashboard") -> dict | None:
    global last_storage_mode
    ok, row = db.update_alert_instance(dedup_key, acknowledged=True, by=by)
    if ok:
        last_storage_mode = "database"
        return row
    last_storage_mode = "demo-fallback"
    for existing in _demo_store(city):
        if existing["dedup_key"] == dedup_key:
            existing["acknowledged_at"] = _utc_now().isoformat()
            existing["acknowledged_by"] = by
            return existing
    return None


def dismiss_alert(city: str, dedup_key: str) -> dict | None:
    global last_storage_mode
    ok, row = db.update_alert_instance(dedup_key, dismissed=True)
    if ok:
        last_storage_mode = "database"
        return row
    last_storage_mode = "demo-fallback"
    for existing in _demo_store(city):
        if existing["dedup_key"] == dedup_key:
            existing["dismissed_at"] = _utc_now().isoformat()
            return existing
    return None


def list_rules() -> list[dict]:
    global last_storage_mode
    ok, rows = db.fetch_alert_rules()
    if ok:
        last_storage_mode = "database"
        return rows
    last_storage_mode = "demo-fallback"
    return _demo_rules("")
