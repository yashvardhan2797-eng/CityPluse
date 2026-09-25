"""City resilience intelligence (Phase 9).

An explainable, configurable resilience indicator that EXTENDS the existing
city health score (health_score.py) rather than replacing it. Where health
answers "how bad are conditions right now?", resilience answers "how well is
the city holding up over a longer window".

Components (each 0-100, each fully documented):
- stress           — reuses compute_health_score over the window (environmental
                     and operational stress from the SAME penalty model);
- anomaly_burden   — frequency and severity of detected anomalies per day;
- recovery         — mean resolution time of civic events that were resolved
                     (from the existing event lifecycle's resolved_at stamps);
- data_coverage    — share of expected hourly metric observations actually
                     present (gaps counted as gaps, never zero-filled).

The overall score is a weighted mean of the AVAILABLE components; weights are
printed in the response and renormalized when a component has no data. Every
number cites its inputs. This is a prototype indicator — it is NOT a
scientifically validated index, and the response says so.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.database import fetch_history_buckets, fetch_recent_anomalies

# Component weights — configurable via env in a future phase; documented here.
COMPONENT_WEIGHTS = {
    "stress": 0.30,
    "anomaly_burden": 0.25,
    "recovery": 0.25,
    "data_coverage": 0.20,
}

# Anomaly-burden scoring: each detected anomaly per day costs ANOMALY_PENALTY
# points from 100, capped at ANOMALY_PENALTY_CAP. Severity (|robust z| >= 5)
# counts double. Constants are planning heuristics, not calibrated research.
ANOMALY_PENALTY = 10.0
ANOMALY_PENALTY_CAP = 60.0
SEVERE_DEVIATION_Z = 5.0

# Recovery scoring: resolution within RECOVERY_TARGET_HOURS scores full marks;
# each additional hour costs RECOVERY_PENALTY_PER_HOUR, floor at the floor value.
RECOVERY_TARGET_HOURS = 2.0
RECOVERY_PENALTY_PER_HOUR = 10.0
RECOVERY_FLOOR = 20.0

# Expected metrics for coverage: the health model's scored set + weather context.
EXPECTED_METRICS = ("pm25_ugm3", "pm10_ugm3", "o3_ugm3", "delay_min", "incident_count",
                    "precipitation_mm", "temperature_c", "wind_speed_kmh")

DISCLAIMER = (
    "Prototype indicator — computed from this platform's own data with documented "
    "heuristics. It is NOT a scientifically validated resilience index."
)


def _stress_component(city: str, hours: int) -> dict:
    from backend.health_score import compute_health_score
    health = compute_health_score(city, hours=hours)
    return {
        "value": health["score"],
        "weight": COMPONENT_WEIGHTS["stress"],
        "status": "ok" if health.get("contributions") else "no_data",
        "inputs": {
            "health_score": health["score"],
            "health_category": health["category"],
            "penalty_contributions": len(health.get("contributions", [])),
        },
        "formula": "city health score over the same window (existing penalty model)",
        "note": "Lower stress = higher score; reuses the health model verbatim for consistency.",
    }


def _anomaly_component(city: str, days: int) -> dict:
    ok, rows = fetch_recent_anomalies(city, limit=300)
    if not ok:
        return {"value": None, "weight": COMPONENT_WEIGHTS["anomaly_burden"], "status": "unavailable",
                "formula": f"100 - min({ANOMALY_PENALTY_CAP:g}, per_day * {ANOMALY_PENALTY:g})",
                "note": f"anomaly history unavailable: {rows}"}
    by_day: dict[str, dict] = {}
    for r in rows or []:
        day = str(r.get("observed_bucket") or "")[:10]
        if not day:
            continue
        entry = by_day.setdefault(day, {"count": 0, "severe": 0})
        entry["count"] += 1
        try:
            if abs(float(r.get("deviation_score") or 0)) >= SEVERE_DEVIATION_Z:
                entry["severe"] += 1
        except (TypeError, ValueError):
            pass
    if not by_day:
        return {"value": 100.0, "weight": COMPONENT_WEIGHTS["anomaly_burden"], "status": "ok",
                "inputs": {"anomaly_days": 0, "per_day_average": 0.0},
                "formula": "no anomalies in retained history — full marks (sample window disclosed)",
                "note": "Retention is limited to recent events; absence of anomalies is not proof of none."}
    span_days = max(1, len(by_day))
    total = sum(e["count"] for e in by_day.values())
    per_day = total / span_days
    weighted = sum(e["count"] + e["severe"] for e in by_day.values()) / span_days
    penalty = min(ANOMALY_PENALTY_CAP, weighted * ANOMALY_PENALTY)
    return {
        "value": round(100.0 - penalty, 1),
        "weight": COMPONENT_WEIGHTS["anomaly_burden"],
        "status": "ok",
        "inputs": {
            "per_day_average": round(per_day, 2),
            "severity_weighted_per_day": round(weighted, 2),
            "days_with_anomalies": len(by_day),
            "retained_anomalies": total,
        },
        "formula": f"100 - min({ANOMALY_PENALTY_CAP:g}, severity_weighted_per_day * {ANOMALY_PENALTY:g}); severe (|z|>={SEVERE_DEVIATION_Z:g}) counts double",
    }


def _recovery_component(city: str) -> dict:
    from backend.events import list_events
    try:
        listing = list_events(city=city, statuses=("resolved",), include_simulated=False, limit=100)
        events = listing.get("events", []) if isinstance(listing, dict) else []
    except Exception:  # noqa: BLE001
        return {"value": None, "weight": COMPONENT_WEIGHTS["recovery"], "status": "unavailable",
                "formula": f"100 - max(0, mean_resolution_h - {RECOVERY_TARGET_HOURS:g}) * {RECOVERY_PENALTY_PER_HOUR:g}, floor {RECOVERY_FLOOR:g}",
                "note": "event history unavailable"}
    durations: list[float] = []
    for ev in events:
        rep, res = ev.get("reported_at"), ev.get("resolved_at")
        if not rep or not res:
            continue
        try:
            delta_h = (
                datetime.fromisoformat(str(res).replace("Z", "+00:00"))
                - datetime.fromisoformat(str(rep).replace("Z", "+00:00"))
            ).total_seconds() / 3600
            if delta_h >= 0:
                durations.append(delta_h)
        except ValueError:
            continue
    if not durations:
        return {"value": None, "weight": COMPONENT_WEIGHTS["recovery"], "status": "no_data",
                "formula": f"100 - max(0, mean_resolution_h - {RECOVERY_TARGET_HOURS:g}) * {RECOVERY_PENALTY_PER_HOUR:g}, floor {RECOVERY_FLOOR:g}",
                "note": "no resolved events with both reported_at and resolved_at in history"}
    mean_h = sum(durations) / len(durations)
    penalty = max(0.0, mean_h - RECOVERY_TARGET_HOURS) * RECOVERY_PENALTY_PER_HOUR
    return {
        "value": round(max(RECOVERY_FLOOR, 100.0 - penalty), 1),
        "weight": COMPONENT_WEIGHTS["recovery"],
        "status": "ok",
        "inputs": {
            "resolved_events_considered": len(durations),
            "mean_resolution_hours": round(mean_h, 2),
            "fastest_h": round(min(durations), 2),
            "slowest_h": round(max(durations), 2),
        },
        "formula": f"100 - max(0, mean_resolution_h - {RECOVERY_TARGET_HOURS:g}) * {RECOVERY_PENALTY_PER_HOUR:g}, floor {RECOVERY_FLOOR:g}",
    }


def _coverage_component(city: str, hours: int) -> dict:
    ok, rows = fetch_history_buckets(city, hours=hours, metrics=None)
    if not ok:
        return {"value": None, "weight": COMPONENT_WEIGHTS["data_coverage"], "status": "unavailable",
                "formula": "covered (metric,hour) pairs / expected pairs",
                "note": f"history unavailable: {rows}"}
    pairs = {(str(r["bucket"])[:13], r["metric"]) for r in rows or []}
    expected_hours = max(1, hours)
    expected = expected_hours * len(EXPECTED_METRICS)
    covered = len(pairs)
    pct = min(100.0, covered / expected * 100.0)
    per_metric: dict[str, int] = {}
    for _, metric in pairs:
        per_metric[metric] = per_metric.get(metric, 0) + 1
    return {
        "value": round(pct, 1),
        "weight": COMPONENT_WEIGHTS["data_coverage"],
        "status": "ok" if covered else "no_data",
        "inputs": {
            "covered_metric_hours": covered,
            "expected_metric_hours": expected,
            "hours_requested": hours,
            "per_metric_hours": dict(sorted(per_metric.items(), key=lambda kv: -kv[1])),
        },
        "formula": f"min(100, covered ({covered}) / expected ({expected}) * 100) over {len(EXPECTED_METRICS)} expected metrics",
        "note": "Missing hours count as missing — never zero-filled.",
    }


def compute_resilience(city: str, hours: int = 168) -> dict:
    """Assemble the component scores and the weighted overall indicator."""
    days = max(1, round(hours / 24))
    components = {
        "stress": _stress_component(city, hours),
        "anomaly_burden": _anomaly_component(city, days),
        "recovery": _recovery_component(city),
        "data_coverage": _coverage_component(city, hours),
    }
    total_weight = sum(c["weight"] for c in components.values() if c["value"] is not None)
    score = None
    if total_weight > 0:
        score = round(
            sum((c["value"] or 0) * c["weight"] for c in components.values() if c["value"] is not None)
            / total_weight,
            1,
        )
    category = None
    if score is not None:
        category = ("strong" if score >= 75 else "moderate" if score >= 55
                    else "strained" if score >= 35 else "weakened")
    return {
        "city": city,
        "window_hours": hours,
        "resilience_score": score,
        "category": category,
        "components": components,
        "weights_used": {k: v["weight"] for k, v in components.items()},
        "weight_renormalization": (
            f"components without data ({', '.join(k for k, v in components.items() if v['value'] is None) or 'none'}) "
            "are excluded and remaining weights renormalized"
        ),
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Extends the city health score with anomaly burden, recovery, and coverage — all explainable components.",
    }


def get_resilience_trend(city: str, days: int = 14) -> dict:
    """Daily resilience proxy: health trend joined with per-day anomaly counts."""
    from backend.health_score import get_health_trend
    health = get_health_trend(city, days=days)
    ok, rows = fetch_recent_anomalies(city, limit=300)
    by_day: dict[str, int] = {}
    if ok:
        for r in rows or []:
            day = str(r.get("observed_bucket") or "")[:10]
            if day:
                by_day[day] = by_day.get(day, 0) + 1
    trend = [
        {**point, "anomalies": by_day.get(point["day"], 0)}
        for point in health.get("trend", [])
    ]
    return {
        "city": city,
        "days": days,
        "trend": trend,
        "note": "Daily health score (same penalty model) plus stored anomaly counts per day; days without data are absent.",
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
