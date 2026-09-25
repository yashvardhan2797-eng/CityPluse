"""Deterministic synthetic data generators (demo mode).

Rules:
- Output is a pure function of (city, time bucket) → same bucket = same data
  (stable for dedup, screenshots, and demos). The bucket is embedded in the
  source_id so repeated ingestion builds a time series instead of overwriting.
- Every description starts with "Demo:" and is_synthetic=True is set so the
  observation can never be mistaken for a live reading.
- Values are plausible but NOT real; they intentionally avoid claiming to be
  observations from any actual city sensor.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from backend.demo_data import DEMO_CITIES
from backend.providers.base import NormalizedObservation, make_source_id


def _seed(*parts) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _pseudo(seed: int, low: float, high: float) -> float:
    """Deterministic pseudo-random float in [low, high]."""
    normalized = (seed % 100_000) / 100_000
    return round(low + (high - low) * normalized, 1)


def bucket_for(offset_hours: int = 0) -> datetime:
    """Current time floored to the hour, minus offset_hours (deterministic)."""
    now = datetime.now(timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    return base - timedelta(hours=offset_hours)


def current_bucket() -> datetime:
    """Current 5-minute bucket (used for 'now' observations)."""
    now = datetime.now(timezone.utc)
    return now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)


def _city(city_id: str):
    return next(c for c in DEMO_CITIES if c["id"] == city_id)


def _bucket_tag(bucket: datetime) -> str:
    return bucket.strftime("%Y%m%d%H")


def demo_weather(city_id: str, bucket: datetime | None = None) -> list[NormalizedObservation]:
    city = _city(city_id)
    bucket = bucket or current_bucket()
    hour = bucket.hour
    diurnal = (hour - 6) / 12.0
    specs = [
        ("temperature_c", "°C", 18 + 10 * diurnal, 4),
        ("humidity_pct", "%", max(20.0, 55 - 15 * diurnal), 8),
        ("precipitation_mm", "mm", 0.4, 1.2),
        ("wind_speed_kmh", "km/h", 9 + 4 * diurnal, 5),
    ]
    out: list[NormalizedObservation] = []
    for metric, unit, base, spread in specs:
        value = max(0.0, _pseudo(_seed(city_id, metric, bucket.hour, bucket.day), base - spread, base + spread))
        from backend.providers.weather import classify_weather_severity

        out.append(
            NormalizedObservation(
                source_type="weather",
                provider="demo",
                source_id=make_source_id("demo-weather", city_id, metric, _bucket_tag(bucket)),
                city=city["name"],
                city_id=city_id,
                location_name=f"{city['name']} (city-wide)",
                latitude=float(city["lat"]),
                longitude=float(city["lon"]),
                metric=metric,
                value=value,
                unit=unit,
                severity=classify_weather_severity(metric, value),
                description=f"Demo: simulated {metric} = {value} {unit}",
                recorded_at=bucket,
                source_url=None,
                metadata={"generator": "demo_weather", "bucket": bucket.isoformat()},
                is_synthetic=True,
            )
        )
    return out


def demo_air_quality(city_id: str, bucket: datetime | None = None) -> list[NormalizedObservation]:
    city = _city(city_id)
    bucket = bucket or current_bucket()
    pm25 = _pseudo(_seed(city_id, "pm25", bucket.hour // 3, bucket.day), 25, 140)
    pm10 = round(pm25 * 1.6, 1)
    o3 = _pseudo(_seed(city_id, "o3", bucket.hour // 3, bucket.day), 12, 70)

    def _aq_severity(v: float) -> str:
        if v >= 150:
            return "critical"
        if v >= 55:
            return "high"
        if v >= 25:
            return "moderate"
        return "low"

    out: list[NormalizedObservation] = []
    for metric, value in (("pm25_ugm3", pm25), ("pm10_ugm3", pm10), ("o3_ugm3", o3)):
        out.append(
            NormalizedObservation(
                source_type="air_quality",
                provider="demo",
                source_id=make_source_id("demo-aq", city_id, metric, _bucket_tag(bucket)),
                city=city["name"],
                city_id=city_id,
                location_name=f"{city['name']} (city-wide)",
                latitude=float(city["lat"]),
                longitude=float(city["lon"]),
                metric=metric,
                value=value,
                unit="µg/m³",
                severity=_aq_severity(value),
                description=f"Demo: simulated {metric} = {value} µg/m³",
                recorded_at=bucket,
                source_url=None,
                metadata={"generator": "demo_air_quality", "bucket": bucket.isoformat()},
                is_synthetic=True,
            )
        )
    return out


def demo_transit(city_id: str, bucket: datetime | None = None) -> list[NormalizedObservation]:
    city = _city(city_id)
    bucket = bucket or current_bucket()
    peak = 1.0 if bucket.hour in {8, 9, 18, 19} else 0.55
    load = min(115.0, _pseudo(_seed(city_id, "load", bucket.hour, bucket.day), 40, 75) * (0.8 + 0.4 * peak))
    delay = _pseudo(_seed(city_id, "delay", bucket.hour, bucket.day), 0, 7 if peak > 0.9 else 2.5)
    out: list[NormalizedObservation] = [
        NormalizedObservation(
            source_type="transit",
            provider="demo",
            source_id=make_source_id("demo-transit", city_id, "load", _bucket_tag(bucket)),
            city=city["name"],
            city_id=city_id,
            location_name=f"{city['name']} (network average)",
            latitude=float(city["lat"]),
            longitude=float(city["lon"]),
            metric="load_factor_pct",
            value=round(load, 1),
            unit="%",
            severity="high" if load >= 85 else ("moderate" if load >= 65 else "low"),
            description=f"Demo: simulated network load factor = {round(load, 1)}%",
            recorded_at=bucket,
            source_url=None,
            metadata={"generator": "demo_transit", "bucket": bucket.isoformat()},
            is_synthetic=True,
        ),
        NormalizedObservation(
            source_type="transit",
            provider="demo",
            source_id=make_source_id("demo-transit", city_id, "delay", _bucket_tag(bucket)),
            city=city["name"],
            city_id=city_id,
            location_name=f"{city['name']} (network average)",
            latitude=float(city["lat"]),
            longitude=float(city["lon"]),
            metric="delay_min",
            value=delay,
            unit="min",
            severity="high" if delay >= 5 else ("moderate" if delay >= 2 else "low"),
            description=f"Demo: simulated average delay = {delay} min",
            recorded_at=bucket,
            source_url=None,
            metadata={"generator": "demo_transit", "bucket": bucket.isoformat()},
            is_synthetic=True,
        ),
    ]
    return out


def demo_incidents(city_id: str, bucket: datetime | None = None) -> list[NormalizedObservation]:
    """0–3 synthetic incidents per hourly bucket, scattered around the centre."""
    city = _city(city_id)
    bucket = bucket or current_bucket()
    count = int(_pseudo(_seed(city_id, "inc-count", bucket.hour, bucket.day), 0, 3.99))
    categories = ("waterlogging", "signal fault", "road obstruction", "minor collision")
    out: list[NormalizedObservation] = []
    for i in range(count):
        category = categories[_seed(city_id, "cat", bucket.hour, bucket.day, i) % len(categories)]
        lat = float(city["lat"]) + _pseudo(_seed(city_id, "dlat", bucket.hour, bucket.day, i), -0.06, 0.06)
        lon = float(city["lon"]) + _pseudo(_seed(city_id, "dlon", bucket.hour, bucket.day, i), -0.06, 0.06)
        out.append(
            NormalizedObservation(
                source_type="incident",
                provider="demo",
                source_id=make_source_id("demo-inc", city_id, _bucket_tag(bucket), i),
                city=city["name"],
                city_id=city_id,
                location_name=f"{city['name']} area #{i + 1}",
                latitude=lat,
                longitude=lon,
                metric="incident_count",
                value=1,
                unit="count",
                severity="moderate",
                description=f"Demo: simulated {category} report",
                recorded_at=bucket,
                source_url=None,
                metadata={"generator": "demo_incidents", "category": category},
                is_synthetic=True,
            )
        )
    return out
