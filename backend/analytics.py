"""Civic intelligence engine (Phase 3): explainable anomaly detection.

Method: robust z-score against a rolling baseline —
  baseline = median of prior observations in the window (excludes the point
  being evaluated), MAD = median absolute deviation of that baseline,
  robust_z = 0.6745 * (x - median) / MAD  (falls back to mean/stdev when MAD=0).

Design rules:
- Requires MIN_BASELINE_POINTS before producing any anomaly (no fabrication
  from sparse data).
- Deduplicated at the database level via UNIQUE (city, metric, observed_bucket),
  so re-running detection never repeats an alert for the same event.
- Every anomaly carries metric, observed value, baseline, deviation score,
  window, method, sample size, confidence, and explicit limitations.
- Thresholds are configurable via env (ANOMALY_Z_THRESHOLD etc.).
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone

from backend.config import get_settings
from backend.database import (
    fetch_metric_series,
    insert_anomaly_events,
    fetch_recent_anomalies,
)
from backend.demo_data import DEMO_CITIES

logger = logging.getLogger("citypulse.analytics")

# Metrics considered anomaly-relevant: (source_type, metric, direction hint)
WATCHED_METRICS: tuple[tuple[str, str], ...] = (
    ("weather", "precipitation_mm"),
    ("weather", "temperature_c"),
    ("weather", "wind_speed_kmh"),
    ("air_quality", "pm25_ugm3"),
    ("air_quality", "pm10_ugm3"),
    ("transit", "delay_min"),
    ("transit", "load_factor_pct"),
    ("incident", "incident_count"),
)

MIN_BASELINE_POINTS = 8      # observations required before any anomaly fires
MIN_HOURS_COVERAGE = 6       # series must span at least this many hours


def _thresholds() -> tuple[float, float]:
    s = get_settings()
    return s.anomaly_z_threshold, s.anomaly_severe_z_threshold


def _robust_stats(values: list[float]) -> dict:
    """Median/MAD baseline with mean/stdev fallback for zero-MAD series."""
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    if mad > 0:
        return {
            "method": "rolling_median_mad",
            "center": med,
            "scale": mad,
            "scale_note": f"MAD={mad:.2f}",
        }
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "method": "rolling_mean_stdev",
        "center": mean,
        "scale": stdev if stdev > 0 else max(1e-9, abs(mean) * 0.01),
        "scale_note": f"stdev={stdev:.2f} (MAD was 0)",
    }


def detect_metric_anomalies(
    series: list[dict],
    window_hours: int,
) -> list[dict]:
    """Detect anomalies in one metric series (chronological, hourly rows).

    series rows: {"bucket": iso_str, "avg_value": float, "n": int}
    Only the most recent point is tested against the baseline of its
    predecessors, which keeps the semantics simple and explainable:
    "is the latest hour unusual compared to recent history?"
    """
    z_thresh, severe_thresh = _thresholds()
    if len(series) < MIN_BASELINE_POINTS + 1:
        return []

    times = [row["bucket"] for row in series]
    span_hours = (
        datetime.fromisoformat(times[-1]) - datetime.fromisoformat(times[0])
    ).total_seconds() / 3600
    if span_hours < MIN_HOURS_COVERAGE:
        return []

    latest = series[-1]
    baseline_values = [row["avg_value"] for row in series[:-1] if row["avg_value"] is not None]
    if len(baseline_values) < MIN_BASELINE_POINTS:
        return []

    observed = latest["avg_value"]
    if observed is None:
        return []

    stats = _robust_stats(baseline_values)
    deviation = observed - stats["center"]
    robust_z = 0.6745 * deviation / stats["scale"]

    if abs(robust_z) < z_thresh:
        return []

    confidence = "low"
    limitations = (
        f"Baseline from {len(baseline_values)} hourly aggregates ({stats['scale_note']}); "
        "robust z-score flags unusual values but does not imply a cause. "
        f"Sample is short ({int(span_hours)}h), so rare-but-normal conditions can trigger alerts."
    )
    if abs(robust_z) >= severe_thresh and len(baseline_values) >= 2 * MIN_BASELINE_POINTS:
        confidence = "medium"

    return [
        {
            "bucket": latest["bucket"],
            "observed_value": round(observed, 2),
            "baseline_value": round(stats["center"], 2),
            "deviation": round(deviation, 2),
            "score": round(robust_z, 2),
            "method": stats["method"],
            "window_hours": window_hours,
            "sample_size": len(baseline_values),
            "confidence": confidence,
            "limitations": limitations,
        }
    ]


def run_anomaly_detection(city: str, window_hours: int = 72) -> dict:
    """Run detection across all watched metrics for one city.

    Returns {city, checked: [...], detected: n, insufficient_data: [...],
             anomalies: [...]} — anomalies are also persisted (deduped).
    """
    checked, insufficient, anomalies = [], [], []
    for source_type, metric in WATCHED_METRICS:
        ok, payload = fetch_metric_series(
            source_type=source_type, metric=metric, city=city, hours=window_hours
        )
        if not ok:
            insufficient.append({"source_type": source_type, "metric": metric, "reason": str(payload)})
            continue
        series = payload  # list of hourly aggregates (chronological)
        found = detect_metric_anomalies(series, window_hours)
        if not found:
            checked.append({"source_type": source_type, "metric": metric, "points": len(series)})
            if len(series) <= MIN_BASELINE_POINTS:
                insufficient.append({
                    "source_type": source_type,
                    "metric": metric,
                    "reason": f"only {len(series)} hourly points; need {MIN_BASELINE_POINTS + 1}+",
                })
            continue
        for anomaly in found:
            anomalies.append({
                "city": city,
                "source_type": source_type,
                "metric": metric,
                **anomaly,
            })

    stored = 0
    if anomalies:
        ok, payload = insert_anomaly_events(anomalies)
        stored = payload if ok else 0
        if not ok:
            logger.warning("anomaly persistence failed: %s", payload)

    return {
        "city": city,
        "window_hours": window_hours,
        "checked": checked,
        "insufficient_data": insufficient,
        "detected": len(anomalies),
        "new_events_stored": stored,
        "anomalies": anomalies,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Statistical flags only — an anomaly is not an explanation or a causal claim.",
    }


def get_recent_anomalies(city: str, limit: int = 20) -> list[dict]:
    ok, payload = fetch_recent_anomalies(city, limit)
    return payload if ok else []
