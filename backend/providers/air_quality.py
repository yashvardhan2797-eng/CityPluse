"""OpenAQ air-quality provider (v3 API, X-API-Key auth — docs.openaq.org).

Verified contract (official docs, 2026-09):
- Sign up at https://explore.openaq.org; key goes in the X-API-Key header.
- GET /v3/locations?coordinates={lat},{lon}&radius=25000&limit=25
    → {"results": [{"id": 8118, "name": ..., "coordinates": {...}, "sensors": [...]}]}
- GET /v3/locations/{id}/latest
    → {"results": [{"sensorsId": 23534, "value": 62.5,
                    "datetime": {"utc": "2026-09-24T11:30:00Z", ...}}]}
- Sensor names look like "pm25 µg/m³"; parameters carry name/units/displayName.
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

API_BASE = "https://api.openaq.org/v3"
TIMEOUT_SECONDS = 12
RADIUS_METERS = 25_000
MAX_LOCATIONS = 5

# parameter name (OpenAQ) → our metric name
PARAMETER_MAP = {
    "pm25": "pm25_ugm3",
    "pm10": "pm10_ugm3",
    "o3": "o3_ugm3",
    "no2": "no2_ugm3",
    "so2": "so2_ugm3",
    "co": "co_ugm3",
}


def _city_by_id(city_id: str):
    return next(c for c in DEMO_CITIES if c["id"] == city_id)


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Accept": "application/json"}


def _parse_utc(raw: str | None) -> datetime:
    if not raw:
        raise ProviderError("OpenAQ observation missing datetime.utc")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ProviderError(f"OpenAQ bad datetime {raw!r}") from exc


def classify_aq_severity(value: float) -> str:
    """Rough PM2.5-style classification (static thresholds, not anomaly detection)."""
    if value >= 150:
        return "critical"
    if value >= 55:
        return "high"
    if value >= 25:
        return "moderate"
    return "low"


def fetch_live(city_id: str, api_key: str) -> list[NormalizedObservation]:
    """Fetch latest readings for monitoring locations near a city centre."""
    if not api_key:
        raise ProviderError("OPENAQ_API_KEY is not configured")
    city = _city_by_id(city_id)
    session = requests.Session()
    session.headers.update(_headers(api_key))

    # Step 1: find nearby monitoring locations (documented geo search).
    try:
        loc_resp = session.get(
            f"{API_BASE}/locations",
            params={
                "coordinates": f"{city['lat']},{city['lon']}",
                "radius": RADIUS_METERS,
                "limit": MAX_LOCATIONS,
            },
            timeout=TIMEOUT_SECONDS,
        )
        loc_resp.raise_for_status()
        locations = loc_resp.json().get("results", [])
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"OpenAQ locations request failed: {exc}") from exc

    observations: list[NormalizedObservation] = []
    for loc in locations[:MAX_LOCATIONS]:
        loc_id = loc.get("id")
        loc_name = loc.get("name") or f"location-{loc_id}"
        coords = loc.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        if lat is None or lon is None:
            continue
        # sensorId → parameter name/units map for this location
        sensor_params = {
            s.get("id"): (s.get("parameter") or {}) for s in loc.get("sensors", [])
        }
        # Step 2: latest measurements for this location (documented endpoint).
        try:
            latest_resp = session.get(
                f"{API_BASE}/locations/{loc_id}/latest", timeout=TIMEOUT_SECONDS
            )
            latest_resp.raise_for_status()
            latest = latest_resp.json().get("results", [])
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"OpenAQ latest request failed for {loc_id}: {exc}") from exc

        for row in latest:
            param = sensor_params.get(row.get("sensorsId"), {})
            param_name = param.get("name")
            metric = PARAMETER_MAP.get(param_name)
            value = row.get("value")
            if metric is None or value is None:
                continue  # unmapped parameter / missing value: skip, never invent
            observed = _parse_utc((row.get("datetime") or {}).get("utc"))
            observations.append(
                NormalizedObservation(
                    source_type="air_quality",
                    provider="openaq",
                    source_id=make_source_id("openaq", loc_id, metric),
                    city=city["name"],
                    city_id=city_id,
                    location_name=str(loc_name),
                    latitude=float(lat),
                    longitude=float(lon),
                    metric=metric,
                    value=float(value),
                    unit=param.get("units") or "µg/m³",
                    severity=classify_aq_severity(float(value)),
                    description=f"Live air quality: {param.get('displayName') or param_name} = {value} at {loc_name}",
                    recorded_at=observed,
                    source_url=f"{API_BASE}/locations/{loc_id}/latest",
                    metadata={"openaq_location_id": loc_id, "sensors_id": row.get("sensorsId")},
                )
            )
    return observations


def fetch_demo(city_id: str, bucket=None) -> list[NormalizedObservation]:
    from backend.providers.demo_generators import demo_air_quality

    return demo_air_quality(city_id, bucket=bucket)
