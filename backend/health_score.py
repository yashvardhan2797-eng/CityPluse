"""City health scoring: transparent penalty model over documented guidelines.

Each watched metric contributes a capped, linear penalty when its recent
average crosses a documented guideline. Score, category, and per-metric
contributions are returned so the UI can show WHY a score is what it is.
Metrics without data contribute no penalty but are disclosed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.database import fetch_history_buckets

PENALTY_RULES = {
    "pm25_ugm3": {"limit": 35, "max_penalty": 30, "label": "PM2.5"},
    "pm10_ugm3": {"limit": 50, "max_penalty": 20, "label": "PM10"},
    "o3_ugm3": {"limit": 100, "max_penalty": 15, "label": "Ozone"},
    "delay_min": {"limit": 5, "max_penalty": 15, "label": "Transit delay"},
    "incident_count": {"limit": 3, "max_penalty": 20, "label": "Incidents"},
}
SCORED_METRICS = tuple(PENALTY_RULES)
_RECENT_POINTS = 6

COVERAGE_NOTE = "no qualifying observations in window — no penalty, not proof of good"


def _metric_windows(city: str, hours: int) -> dict[str, list[dict]]:
    """One DB call grouped by metric (rows chronological per metric)."""
    ok, buckets = fetch_history_buckets(city=city, hours=hours, metrics=None)
    if not ok:
        return {}
    series: dict[str, list[dict]] = {}
    for row in buckets:
        series.setdefault(row["metric"], []).append(row)
    return series


def _penalty(metric: str, value: float) -> float:
    rule = PENALTY_RULES[metric]
    over = value - rule["limit"]
    if over <= 0:
        return 0.0
    return min(rule["max_penalty"], over / rule["limit"] * rule["max_penalty"])


def _category(score: float) -> str:
    return ("good" if score >= 80 else "moderate" if score >= 60 else "poor" if score >= 40 else "critical")


def compute_health_score(city: str, hours: int = 24) -> dict:
    """Penalty-based score over the last `hours`; every contribution explained."""
    series_by_metric = _metric_windows(city, hours)
    score = 100.0
    contributions: list[dict] = []
    coverage: dict[str, dict] = {m: {"points": 0, "note": COVERAGE_NOTE} for m in SCORED_METRICS}
    for metric in SCORED_METRICS:
        rows = series_by_metric.get(metric) or []
        values = [r["avg_value"] for r in rows if r.get("avg_value") is not None][-_RECENT_POINTS:]
        if not values:
            continue
        latest = values[-1]
        pen = _penalty(metric, latest)
        score -= pen
        rule = PENALTY_RULES[metric]
        coverage[metric] = {"points": len(values), "note": "recent hourly averages"}
        contributions.append({
            "metric": metric,
            "label": rule["label"],
            "latest": round(latest, 2),
            "points_averaged": len(values),
            "penalty": round(pen, 2),
            "limit": rule["limit"],
            "status": "penalty" if pen > 0 else "within guideline",
        })
    score = max(0.0, round(score, 1))
    return {
        "city": city,
        "score": score,
        "category": _category(score),
        "contributions": contributions,
        "coverage": coverage,
        "window_hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Transparent penalty model over documented guidelines; metrics without "
            "data contribute no penalty but are disclosed. Not an official index."
        ),
    }


def get_health_trend(city: str, days: int = 7) -> dict:
    """Daily health scores for the last `days` days, from stored hourly data.

    Reuses the exact same penalty model per day (per-metric daily average of
    hourly averages). Days without data are absent — gaps stay gaps.
    """
    series_by_metric = _metric_windows(city, days * 24)
    by_day: dict[str, dict[str, list[float]]] = {}
    for metric, rows in series_by_metric.items():
        for row in rows:
            day = str(row["bucket"])[:10]
            by_day.setdefault(day, {}).setdefault(metric, []).append(row["avg_value"])

    trend: list[dict] = []
    for day in sorted(by_day):
        metric_values = {
            m: vals[-_RECENT_POINTS:]
            for m, vals in by_day[day].items()
            if any(v is not None for v in vals)
        }
        score = 100.0
        scored_any = False
        for metric in SCORED_METRICS:
            vals = [v for v in metric_values.get(metric, []) if v is not None]
            if not vals:
                continue
            scored_any = True
            score -= _penalty(metric, vals[-1])
        if scored_any:
            trend.append({"day": day, "score": round(max(0.0, score), 1), "n_points": len(by_day[day])})

    return {
        "city": city,
        "days": days,
        "trend": trend,
        "note": (
            "Daily scores recompute the same penalty model on stored hourly data; "
            "days without observations are absent (gaps shown, never filled)."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
