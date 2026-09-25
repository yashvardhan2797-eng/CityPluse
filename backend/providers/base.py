"""Provider contracts and shared result types for CityPulse ingestion.

Separation of concerns:
- providers/*.py   → fetch + normalize a single source into NormalizedObservation
- ingest.py        → orchestration, validation, dedup/upsert, health tracking
- routes.py        → HTTP surface

Rules every provider must follow:
- Never fabricate "live" data: synthetic output must be deterministic per
  time bucket and flagged is_synthetic=True end-to-end.
- Validate coordinates, timestamps, values, and units before returning.
- Timeouts on every HTTP call; raise on unrecoverable errors and let the
  orchestrator record provider health.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("citypulse.providers")


class ProviderError(Exception):
    """Raised when a provider cannot fetch or parse its source."""


@dataclass
class NormalizedObservation:
    """A validated, normalized observation ready for persistence.

    This is the only shape providers may produce; ingest.py persists it.
    """

    source_type: str          # weather | air_quality | transit | incident
    provider: str             # open-meteo | openaq | gtfs-rt | city-open-data | demo
    source_id: str            # provider-unique id, e.g. "openaq-8118-pm25"
    city: str                 # canonical city name (DEMO_CITIES name)
    city_id: str              # canonical city id from demo_data.DEMO_CITIES
    location_name: str
    latitude: float
    longitude: float
    metric: str               # e.g. temperature_c, precipitation_mm, pm25_ugm3
    value: float | None
    unit: str
    severity: str             # low | moderate | high | critical
    description: str
    recorded_at: datetime     # UTC
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    is_synthetic: bool = False


def utc_now() -> datetime:
    """Timezone-aware UTC now (never naive)."""
    return datetime.now(timezone.utc)


def make_source_id(provider: str, *parts: Any) -> str:
    """Build a stable provider-unique source_id (used for dedup/upsert)."""
    return "-".join([provider, *[str(p) for p in parts]])


def validate_observation(obs: NormalizedObservation) -> None:
    """Raise ProviderError on invalid observations (defense in depth)."""
    if obs.source_type not in {"weather", "air_quality", "transit", "incident"}:
        raise ProviderError(f"invalid source_type: {obs.source_type!r}")
    if obs.severity not in {"low", "moderate", "high", "critical"}:
        raise ProviderError(f"invalid severity: {obs.severity!r}")
    if not (-90 <= obs.latitude <= 90):
        raise ProviderError(f"latitude out of range: {obs.latitude}")
    if not (-180 <= obs.longitude <= 180):
        raise ProviderError(f"longitude out of range: {obs.longitude}")
    if obs.recorded_at.tzinfo is None:
        raise ProviderError("recorded_at must be timezone-aware (UTC)")
    if not obs.source_id:
        raise ProviderError("source_id is required")
    if obs.is_synthetic and "Demo" not in obs.description[:20]:
        raise ProviderError("synthetic observations must be clearly labeled")
