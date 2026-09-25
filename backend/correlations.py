"""Civic intelligence engine (Phase 3): correlation analysis.

Compares pairs of metrics over aligned hourly aggregates for one city.
Rules baked in:
- Both series must have enough overlapping, valid points (MIN_OVERLAP_POINTS)
  before any coefficient is reported — otherwise "insufficient data".
- Pearson (linear) AND Spearman (rank/monotonic) are computed; both are
  reported with sample size, time window, and city scope.
- Outliers beyond 3 robust-z are excluded before Pearson (Spearman is
  naturally rank-based).
- Output language is strictly associational: "moves together / opposite".
  Nothing here may be presented as causation.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from backend.database import fetch_metric_series

MIN_OVERLAP_POINTS = 12          # aligned hourly points required per pair
OUTLIER_ROBUST_Z = 3.0           # excluded from Pearson only

# Compatible metric pairs (same city, aligned hours). Kept explicit so we
# never compare unrelated units by accident.
METRIC_PAIRS: tuple[tuple[str, str], ...] = (
    ("pm25_ugm3", "temperature_c"),
    ("pm25_ugm3", "humidity_pct"),
    ("pm25_ugm3", "precipitation_mm"),
    ("pm25_ugm3", "wind_speed_kmh"),
    ("delay_min", "precipitation_mm"),
    ("delay_min", "load_factor_pct"),
    ("incident_count", "precipitation_mm"),
)

METRIC_UNITS = {
    "pm25_ugm3": "µg/m³",
    "pm10_ugm3": "µg/m³",
    "o3_ugm3": "µg/m³",
    "temperature_c": "°C",
    "humidity_pct": "%",
    "precipitation_mm": "mm",
    "wind_speed_kmh": "km/h",
    "delay_min": "min",
    "load_factor_pct": "%",
    "incident_count": "count",
}


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient (returns 0.0 when undefined)."""
    n = len(x)
    mean_x, mean_y = statistics.fmean(x), statistics.fmean(y)
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    var_x = sum((a - mean_x) ** 2 for a in x)
    var_y = sum((b - mean_y) ** 2 for b in y)
    denom = math.sqrt(var_x * var_y)
    return cov / denom if denom > 0 else 0.0


def _spearman(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation (average ranks for ties; 0.0 when undefined)."""

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                result[order[k]] = avg_rank
            i = j + 1
        return result

    return _pearson(ranks(x), ranks(y))


def _exclude_outliers(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop rows where either side is a robust-z outlier (>= OUTLIER_ROBUST_Z)."""
    def filter_side(pairs: list[tuple[float, float]], idx: int) -> list[tuple[float, float]]:
        values = [p[idx] for p in pairs]
        med = statistics.median(values)
        mad = statistics.median([abs(v - med) for v in values])
        if mad == 0:
            return pairs
        kept = [
            p for p in pairs
            if abs(0.6745 * (p[idx] - med) / mad) < OUTLIER_ROBUST_Z
        ]
        # Keep at least the minimum sample even if aggressive filtering bites.
        return kept if len(kept) >= MIN_OVERLAP_POINTS else pairs

    return filter_side(filter_side(points, 0), 1)


def _interpret(r: float) -> str:
    """Associational wording only — never causal."""
    strength = (
        "very weak" if abs(r) < 0.2
        else "weak" if abs(r) < 0.4
        else "moderate" if abs(r) < 0.7
        else "strong"
    )
    direction = "move together" if r > 0 else "move in opposite directions"
    return f"{strength} association: the two metrics tend to {direction}"


def analyze_pair(city: str, metric_a: str, metric_b: str, window_hours: int) -> dict:
    """Analyze one metric pair; never raises — reports insufficiency instead."""
    empty = {
        "city": city,
        "metric_a": metric_a,
        "metric_b": metric_b,
        "window_hours": window_hours,
        "status": "insufficient_data",
    }
    ok_a, series_a = fetch_metric_series(metric=metric_a, city=city, hours=window_hours)
    ok_b, series_b = fetch_metric_series(metric=metric_b, city=city, hours=window_hours)
    if not (ok_a and ok_b):
        return {**empty, "reason": "database query failed"}

    by_bucket = {row["bucket"]: row["avg_value"] for row in series_b}
    aligned: list[tuple[float, float]] = []
    for row in series_a:
        value_b = by_bucket.get(row["bucket"])
        if row["avg_value"] is not None and value_b is not None:
            aligned.append((float(row["avg_value"]), float(value_b)))

    if len(aligned) < MIN_OVERLAP_POINTS:
        return {
            **empty,
            "overlap_points": len(aligned),
            "reason": f"only {len(aligned)} aligned hourly points; need {MIN_OVERLAP_POINTS}+",
        }

    filtered = _exclude_outliers(aligned)
    xs = [p[0] for p in filtered]
    ys = [p[1] for p in filtered]
    pearson = _pearson(xs, ys)
    spearman = _spearman(xs, ys)

    return {
        "city": city,
        "metric_a": metric_a,
        "metric_b": metric_b,
        "unit_a": METRIC_UNITS.get(metric_a, ""),
        "unit_b": METRIC_UNITS.get(metric_b, ""),
        "window_hours": window_hours,
        "sample_size": len(filtered),
        "outliers_excluded": len(aligned) - len(filtered),
        "pearson_r": round(pearson, 3),
        "spearman_rho": round(spearman, 3),
        "interpretation": _interpret(pearson),
        "time_scope": f"last {window_hours}h, hourly averages",
        "geographic_scope": f"{city} (city-wide aggregates)",
        "status": "ok",
        "limitations": (
            "Association only — this does NOT show that one metric causes the other. "
            "Possible confounders (time of day, season, events) are not controlled for. "
            "Short windows and city-wide averages can over- or under-state real relationships."
        ),
    }


# Small TTL cache: correlation analysis fans out to 2 queries per pair, which
# is slow over remote pooler connections; results within an hour bucket are
# effectively identical, so caching is safe and keeps the API responsive.
_CACHE: dict[tuple[str, int, str], tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 600.0


def run_correlation_analysis(city: str, window_hours: int = 72) -> dict:
    """Analyze all compatible metric pairs for a city (cached 10 min)."""
    import time

    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    key = (city, window_hours, hour_bucket)
    now_ts = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now_ts - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    results = [analyze_pair(city, a, b, window_hours) for a, b in METRIC_PAIRS]
    usable = [r for r in results if r["status"] == "ok"]
    insufficient = [r for r in results if r["status"] != "ok"]
    report = {
        "city": city,
        "window_hours": window_hours,
        "pairs_analyzed": len(usable),
        "insufficient_pairs": len(insufficient),
        "correlations": usable,
        "insufficient_details": insufficient,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "All findings are possible associations, not causal conclusions.",
    }
    _CACHE[key] = (now_ts, report)
    return report
