"""Open-Meteo weather provider (free, keyless — documented at open-meteo.com/en/docs).

Contract (verified against official docs, 2026-09):
GET https://api.open-meteo.com/v1/forecast
    ?latitude=..&longitude=..
    &current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m
    &timezone=UTC
Response: {"current": {"time": "2026-09-24T12:00", "temperature_2m": 27.4, ...}}
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from backend.demo_data import DEMO_CITIES
from backend.providers.base import (
    NormalizedObservation,
    ProviderError,
    make_source_id,
)

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 10

# Metric definitions: name used in our model + severity thresholds (rough).
WEATHER_METRICS = (
    ("temperature_2m", "temperature_c", "°C", "temperature"),
    ("relative_humidity_2m", "humidity_pct", "%", "humidity"),
    ("precipitation", "precipitation_mm", "mm", "precipitation"),
    ("wind_speed_10m", "wind_speed_kmh", "km/h", "wind"),
)


def _city_by_id(city_id: str):
    return next(c for c in DEMO_CITIES if c["id"] == city_id)


def classify_weather_severity(metric: str, value: float) -> str:
    """Rough static thresholds — static classification, not anomaly detection."""
    if metric == "precipitation_mm":
        if value >= 7.6:
            return "critical"  # heavy rain
        if value >= 2.5:
            return "high"
        if value > 0:
            return "moderate"
        return "low"
    if metric == "temperature_c":
        if value >= 40 or value <= 2:
            return "critical"
        if value >= 36 or value <= 8:
            return "high"
        return "moderate"
    if metric == "wind_speed_kmh":
        if value >= 62:
            return "critical"
        if value >= 39:
            return "high"
        return "moderate"
    return "moderate"  # humidity


def fetch_live(city_id: str) -> list[NormalizedObservation]:
    """Fetch current weather for a city; raises ProviderError on failure."""
    city = _city_by_id(city_id)
    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "current": ",".join(m[0] for m in WEATHER_METRICS),
        "timezone": "UTC",
    }
    try:
        response = requests.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise ProviderError(f"Open-Meteo request failed: {exc}") from exc

    current = payload.get("current")
    if not isinstance(current, dict):
        raise ProviderError("Open-Meteo response missing 'current' object")

    # Open-Meteo 'current.time' is naive UTC ("2026-09-24T12:00").
    raw_time = current.get("time")
    try:
        recorded_at = datetime.fromisoformat(raw_time).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"Open-Meteo bad time format: {raw_time!r}") from exc

    observations: list[NormalizedObservation] = []
    for api_field, metric, unit, _kind in WEATHER_METRICS:
        value = current.get(api_field)
        if value is None:
            continue  # missing values are skipped, never invented
        observations.append(
            NormalizedObservation(
                source_type="weather",
                provider="open-meteo",
                source_id=make_source_id("open-meteo", city_id, metric),
                city=city["name"],
                city_id=city_id,
                location_name=f"{city['name']} (city-wide)",
                latitude=float(city["lat"]),
                longitude=float(city["lon"]),
                metric=metric,
                value=float(value),
                unit=unit,
                severity=classify_weather_severity(metric, float(value)),
                description=f"Live weather: {metric} = {value} {unit}",
                recorded_at=recorded_at,
                source_url=f"{API_URL}?latitude={city['lat']}&longitude={city['lon']}",
                metadata={"api_field": api_field, "timezone": "UTC"},
            )
        )
    return observations


def fetch_demo(city_id: str, bucket=None) -> list[NormalizedObservation]:
    """Deterministic synthetic weather (labeled) when live fetch is off/failed."""
    from backend.providers.demo_generators import demo_weather

    _city_by_id(city_id)  # validate the city id early
    return demo_weather(city_id, bucket=bucket)
